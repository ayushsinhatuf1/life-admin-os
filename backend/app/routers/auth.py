from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Consent, Family, FamilyMember, User
from app.security import (
    audit,
    create_access_token,
    create_refresh_token,
    current_user,
    hash_password,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_password,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class ConsentItem(BaseModel):
    purpose: str
    granted: bool


class SignUp(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    family_name: str | None = None
    consents: list[ConsentItem] | None = None
    notice_version: str = "2026-09-v1"


class Login(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    family_id: uuid.UUID


class RefreshIn(BaseModel):
    refresh_token: str


class RefreshOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class LogoutIn(BaseModel):
    refresh_token: str


@router.post("/register", response_model=TokenOut, status_code=201)
def register(payload: SignUp, request: Request, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(status_code=409, detail="That email is already registered.")
    if len(payload.password) < 12:
        raise HTTPException(status_code=422, detail="Use at least 12 characters.")

    user = User(email=payload.email, full_name=payload.full_name,
                password_hash=hash_password(payload.password))
    db.add(user)
    db.flush()

    # Capture DPDP versioned consents (Section 18)
    consent_map = {c.purpose: c.granted for c in (payload.consents or [])}
    for purpose in ["service_delivery", "ai_processing", "email_reminders"]:
        is_granted = consent_map.get(purpose, True)
        db.add(
            Consent(
                user_id=user.id,
                purpose=purpose,
                granted=is_granted,
                notice_version=payload.notice_version,
            )
        )

    family = Family(name=payload.family_name or f"{payload.full_name}'s family",
                    owner_user_id=user.id)
    db.add(family)
    db.flush()
    db.add(FamilyMember(family_id=family.id, user_id=user.id,
                        display_name=payload.full_name,
                        relationship_label="self", access="owner"))
    audit(db, request, user, "user.register", family_id=family.id)

    refresh = create_refresh_token(db, user.id, request)
    db.commit()
    return TokenOut(
        access_token=create_access_token(user.id),
        refresh_token=refresh,
        family_id=family.id,
    )


@router.post("/login", response_model=TokenOut)
def login(payload: Login, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    member = db.scalar(select(FamilyMember).where(FamilyMember.user_id == user.id))
    audit(db, request, user, "user.login", family_id=member.family_id if member else None)

    refresh = create_refresh_token(db, user.id, request)
    db.commit()
    return TokenOut(
        access_token=create_access_token(user.id),
        refresh_token=refresh,
        family_id=member.family_id if member else None,
    )


@router.post("/refresh", response_model=RefreshOut)
def refresh(payload: RefreshIn, request: Request, db: Session = Depends(get_db)):
    """Rotate the refresh token and issue a new access token.

    The old refresh token is revoked on every use. If a revoked token is
    presented (indicating possible theft), all tokens for that user are
    revoked and the request fails with 401.
    """
    user, new_refresh = rotate_refresh_token(db, payload.refresh_token, request)
    db.commit()
    return RefreshOut(
        access_token=create_access_token(user.id),
        refresh_token=new_refresh,
    )


@router.post("/logout", status_code=204)
def logout(payload: LogoutIn, db: Session = Depends(get_db)):
    """Revoke the presented refresh token."""
    revoke_refresh_token(db, payload.refresh_token)
    db.commit()


# ------------------------------------------------------------------ notification preferences

class NotificationPreferencesOut(BaseModel):
    channels: list[str]
    send_hour: int
    timezone: str
    muted_categories: list[str]
    weekly_digest: bool
    digest_day: int


class NotificationPreferencesIn(BaseModel):
    channels: list[str] | None = None
    send_hour: int | None = None
    timezone: str | None = None
    muted_categories: list[str] | None = None
    weekly_digest: bool | None = None
    digest_day: int | None = None


@router.get("/preferences", response_model=NotificationPreferencesOut)
def get_preferences(user: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.services import reminders
    prefs = reminders.get_user_preferences(db, user.id)
    return NotificationPreferencesOut(
        channels=prefs.channels or ["email"],
        send_hour=prefs.send_hour,
        timezone=prefs.timezone or "Asia/Kolkata",
        muted_categories=prefs.muted_categories or [],
        weekly_digest=prefs.weekly_digest,
        digest_day=prefs.digest_day,
    )


@router.put("/preferences", response_model=NotificationPreferencesOut)
def update_preferences(
    payload: NotificationPreferencesIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    from app.services import reminders
    prefs = reminders.get_user_preferences(db, user.id)
    if payload.channels is not None:
        prefs.channels = payload.channels
    if payload.send_hour is not None:
        if not (0 <= payload.send_hour <= 23):
            raise HTTPException(status_code=400, detail="Send hour must be between 0 and 23.")
        prefs.send_hour = payload.send_hour
    if payload.timezone is not None:
        prefs.timezone = payload.timezone
    if payload.muted_categories is not None:
        prefs.muted_categories = payload.muted_categories
    if payload.weekly_digest is not None:
        prefs.weekly_digest = payload.weekly_digest
    if payload.digest_day is not None:
        if not (0 <= payload.digest_day <= 6):
            raise HTTPException(status_code=400, detail="Digest day must be between 0 (Mon) and 6 (Sun).")
        prefs.digest_day = payload.digest_day

    db.commit()
    return NotificationPreferencesOut(
        channels=prefs.channels or ["email"],
        send_hour=prefs.send_hour,
        timezone=prefs.timezone or "Asia/Kolkata",
        muted_categories=prefs.muted_categories or [],
        weekly_digest=prefs.weekly_digest,
        digest_day=prefs.digest_day,
    )

