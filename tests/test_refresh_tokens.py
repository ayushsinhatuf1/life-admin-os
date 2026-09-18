"""Tests for refresh token rotation, expiry, and reuse detection.

These verify the session management invariants from P1.2:
- A valid refresh token rotates correctly and issues new tokens
- An expired refresh token is rejected
- Replaying a revoked refresh token kills all sessions for that user
  and writes an audit row with action 'auth.token_reuse'
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security import hash_token

client = TestClient(app)


def _register() -> dict:
    r = client.post("/api/v1/auth/register", json={
        "email": f"{uuid.uuid4()}@example.com",
        "full_name": "Test User",
        "password": "correct-horse-battery",
    })
    assert r.status_code == 201
    body = r.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert "family_id" in body
    return body


def test_register_returns_refresh_token():
    body = _register()
    assert len(body["refresh_token"]) == 64  # hex(32 bytes)


def test_login_returns_refresh_token():
    email = f"{uuid.uuid4()}@example.com"
    client.post("/api/v1/auth/register", json={
        "email": email, "full_name": "Test", "password": "correct-horse-battery",
    })
    r = client.post("/api/v1/auth/login", json={
        "email": email, "password": "correct-horse-battery",
    })
    assert r.status_code == 200
    assert "refresh_token" in r.json()


def test_refresh_rotates_token():
    body = _register()
    old_refresh = body["refresh_token"]

    r = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 200
    new = r.json()

    assert "access_token" in new
    assert "refresh_token" in new
    assert new["refresh_token"] != old_refresh, "must issue a new refresh token"


def test_old_refresh_token_is_revoked_after_rotation():
    body = _register()
    old_refresh = body["refresh_token"]

    # First rotation succeeds.
    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r1.status_code == 200

    # Second use of the same token should fail (it was revoked).
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r2.status_code == 401, "revoked token must be rejected"


def test_reuse_detection_kills_all_sessions():
    """Replaying a revoked refresh token revokes ALL tokens for that user."""
    body = _register()
    first_refresh = body["refresh_token"]

    # Rotate to get a new token.
    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert r1.status_code == 200
    second_refresh = r1.json()["refresh_token"]

    # Replay the old token — this should trigger reuse detection.
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert r2.status_code == 401
    assert "compromised" in r2.json()["detail"].lower() or "ended" in r2.json()["detail"].lower()

    # The second (currently valid) token should also be killed.
    r3 = client.post("/api/v1/auth/refresh", json={"refresh_token": second_refresh})
    assert r3.status_code == 401, "all tokens for the user must be revoked"


def test_reuse_leaves_audit_row():
    """Token reuse must write an audit log with action 'auth.token_reuse'."""
    from app.db import SessionLocal
    from app.models import AuditLog

    body = _register()
    first_refresh = body["refresh_token"]

    # Rotate, then replay.
    client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})

    db = SessionLocal()
    try:
        row = db.query(AuditLog).filter(AuditLog.action == "auth.token_reuse").order_by(
            AuditLog.created_at.desc()
        ).first()
        assert row is not None, "must leave an audit row on reuse"
        assert row.action == "auth.token_reuse"
    finally:
        db.close()


def test_invalid_refresh_token_is_rejected():
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert r.status_code == 401


def test_logout_revokes_token():
    body = _register()
    refresh = body["refresh_token"]

    r = client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    assert r.status_code == 204

    # Token should no longer work.
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r2.status_code == 401


def test_expired_refresh_token_is_rejected():
    """Simulate an expired token by patching the expiry."""
    from app.db import SessionLocal
    from app.models import RefreshToken

    body = _register()
    refresh = body["refresh_token"]

    # Manually expire the token in the DB.
    db = SessionLocal()
    try:
        token_row = db.query(RefreshToken).filter(
            RefreshToken.token_hash == hash_token(refresh)
        ).first()
        token_row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
    finally:
        db.close()

    r = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 401
    assert "expired" in r.json()["detail"].lower()
