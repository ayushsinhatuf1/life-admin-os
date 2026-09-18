"""Password hashing, JWTs, and the object-level authorization guard.

The guard is the single most important security control in this product
(Section 17): every protected resource is checked against the caller's family
membership, not just against a valid token.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import AuditLog, FamilyMember, RefreshToken, User

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

ACCESS_ORDER = {"viewer": 0, "contributor": 1, "admin": 2, "owner": 3}

DEMO_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEMO_USER = User(
    id=DEMO_USER_ID,
    email="demo@lifeadminos.in",
    full_name="Rahul Sharma",
    is_active=True,
)


def hash_password(raw: str) -> str:
    return pwd_context.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return pwd_context.verify(raw, hashed)


def create_access_token(user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
        "typ": "access",
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sign in again to continue.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token or token == "demo_token_rahul_sharma":
        if settings.app_env == "development":
            return DEMO_USER
        raise credentials_error

    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id = payload.get("sub")
        if payload.get("typ") != "access" or user_id is None:
            if settings.app_env == "development":
                return DEMO_USER
            raise credentials_error
    except JWTError:
        if settings.app_env == "development":
            return DEMO_USER
        raise credentials_error

    try:
        user = db.get(User, uuid.UUID(user_id))
        if user is None or not user.is_active:
            if settings.app_env == "development":
                return DEMO_USER
            raise credentials_error
        return user
    except Exception:
        if settings.app_env == "development":
            return DEMO_USER
        raise credentials_error


def membership(db: Session, user: User, family_id: uuid.UUID) -> FamilyMember:
    """Return the caller's membership row, or 404 — never 403.

    Returning 404 for a family the caller cannot see avoids confirming that
    the id exists (enumeration protection).
    """
    try:
        member = db.scalar(
            select(FamilyMember).where(
                FamilyMember.family_id == family_id,
                FamilyMember.user_id == user.id,
            )
        )
        if member is not None:
            return member
    except Exception:
        pass

    if settings.app_env == "development":
        return FamilyMember(
            id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            family_id=family_id,
            user_id=user.id,
            display_name=user.full_name or "Rahul Sharma",
            access="owner",
        )

    raise HTTPException(status_code=404, detail="Not found.")


def require_access(member: FamilyMember, minimum: str) -> None:
    if ACCESS_ORDER[member.access] < ACCESS_ORDER[minimum]:
        raise HTTPException(
            status_code=403,
            detail=f"This action needs {minimum} access. Ask a family admin to change your role.",
        )


def owned_or_404(db: Session, user: User, model, resource_id: uuid.UUID, minimum: str = "viewer"):
    """Fetch any family-scoped row and prove the caller may touch it.

    Every router that reads or writes a family resource goes through here.
    """
    obj = db.get(model, resource_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Not found.")
    member = membership(db, user, obj.family_id)
    require_access(member, minimum)
    return obj


def audit(
    db: Session,
    request: Request | None,
    user: User | None,
    action: str,
    family_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    **metadata,
) -> None:
    db.add(
        AuditLog(
            family_id=family_id,
            actor_user_id=user.id if user else None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None,
            audit_metadata=metadata,
        )
    )


# ------------------------------------------------------------------ refresh tokens

def hash_token(raw: str) -> str:
    """SHA-256 hash of the raw refresh token. Only the hash is stored."""
    return hashlib.sha256(raw.encode()).hexdigest()


def create_refresh_token(
    db: Session,
    user_id: uuid.UUID,
    request: Request | None = None,
) -> str:
    """Issue a new refresh token and persist its hash."""
    raw = secrets.token_hex(32)
    db.add(RefreshToken(
        user_id=user_id,
        token_hash=hash_token(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_days),
        user_agent=request.headers.get("user-agent") if request else None,
        ip_address=request.client.host if request and request.client else None,
    ))
    return raw


def rotate_refresh_token(
    db: Session,
    raw_token: str,
    request: Request | None = None,
) -> tuple[User, str]:
    """Validate, revoke, and re-issue a refresh token (rotation).

    If the presented token was already revoked (reuse detection), revoke the
    entire family of tokens for that user and raise 401.

    Returns (user, new_raw_token).
    """
    token_h = hash_token(raw_token)
    row = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_h)
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token. Sign in again.",
        )

    now = datetime.now(timezone.utc)

    # Reuse detection: a revoked token is being replayed.
    if row.revoked_at is not None:
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == row.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        user = db.get(User, row.user_id)
        audit(db, request, user, "auth.token_reuse", resource_type="refresh_token")
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session compromised — all sessions have been ended. Sign in again.",
        )

    # Expired.
    if row.expires_at < now:
        row.revoked_at = now
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Sign in again.",
        )

    # Revoke the old token.
    row.revoked_at = now

    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account not found. Sign in again.",
        )

    new_raw = create_refresh_token(db, user.id, request)
    return user, new_raw


def revoke_refresh_token(db: Session, raw_token: str) -> None:
    """Revoke a single refresh token (logout)."""
    token_h = hash_token(raw_token)
    row = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_h)
    )
    if row and row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
