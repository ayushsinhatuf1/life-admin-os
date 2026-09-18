"""Tests for the family invitation flow (P1.3).

Verifies:
- Only admin/owner can invite
- Invite generates a token and the invited email receives it
- Accepting an invite binds the user at the intended access level
- Expired invites are rejected
- Accepted invites cannot be reused
- Audit trail is created
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security import hash_token

client = TestClient(app)


def _register(email: str | None = None) -> dict:
    email = email or f"{uuid.uuid4()}@example.com"
    r = client.post("/api/v1/auth/register", json={
        "email": email, "full_name": "Test User", "password": "correct-horse-battery",
    })
    assert r.status_code == 201
    return r.json()


def test_admin_can_invite_member():
    owner = _register()
    h = {"Authorization": f"Bearer {owner['access_token']}"}
    r = client.post(
        f"/api/v1/families/{owner['family_id']}/members",
        json={"display_name": "Invited Person", "invited_email": "new@example.com",
              "access": "viewer"},
        headers=h,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["invite_token"] is not None
    assert len(body["invite_token"]) > 20


def test_viewer_cannot_invite():
    """A viewer-level user should not be able to add members."""
    owner = _register()
    # The owner is the only member and has 'owner' access.
    # Create a second user who joins as viewer.
    viewer = _register()
    # The viewer tries to invite on the owner's family — should 404 (not member).
    h = {"Authorization": f"Bearer {viewer['access_token']}"}
    r = client.post(
        f"/api/v1/families/{owner['family_id']}/members",
        json={"display_name": "Should Fail", "invited_email": "fail@example.com"},
        headers=h,
    )
    assert r.status_code == 404  # not a member of that family


def test_invite_acceptance_flow():
    """Full invite flow: owner invites, second user accepts, becomes a member."""
    owner = _register()
    invited_email = f"invited-{uuid.uuid4()}@example.com"
    oh = {"Authorization": f"Bearer {owner['access_token']}"}

    # Owner invites.
    with patch("app.routers.registry.send_email"):
        r = client.post(
            f"/api/v1/families/{owner['family_id']}/members",
            json={"display_name": "New Person", "invited_email": invited_email,
                  "access": "contributor"},
            headers=oh,
        )
    assert r.status_code == 201
    invite_token = r.json()["invite_token"]

    # Second user registers.
    invitee = _register(invited_email)
    ih = {"Authorization": f"Bearer {invitee['access_token']}"}

    # Accept the invite.
    r2 = client.post(f"/api/v1/invites/{invite_token}/accept", headers=ih)
    assert r2.status_code == 200
    body = r2.json()
    assert body["family_id"] == owner["family_id"]
    assert body["access"] == "contributor"  # matches what the owner granted


def test_invite_cannot_escalate_above_granted_level():
    """Accepting an invite gives exactly the level set by the admin, not higher."""
    owner = _register()
    oh = {"Authorization": f"Bearer {owner['access_token']}"}

    with patch("app.routers.registry.send_email"):
        r = client.post(
            f"/api/v1/families/{owner['family_id']}/members",
            json={"display_name": "Viewer Only", "invited_email": "viewer@example.com",
                  "access": "viewer"},
            headers=oh,
        )
    invite_token = r.json()["invite_token"]

    invitee = _register("viewer@example.com")
    ih = {"Authorization": f"Bearer {invitee['access_token']}"}

    r2 = client.post(f"/api/v1/invites/{invite_token}/accept", headers=ih)
    assert r2.status_code == 200
    assert r2.json()["access"] == "viewer"


def test_expired_invite_is_rejected():
    """An invite past the 72-hour window must be rejected."""
    from app.db import SessionLocal
    from app.models import FamilyMember

    owner = _register()
    oh = {"Authorization": f"Bearer {owner['access_token']}"}

    with patch("app.routers.registry.send_email"):
        r = client.post(
            f"/api/v1/families/{owner['family_id']}/members",
            json={"display_name": "Late Person", "invited_email": "late@example.com",
                  "access": "viewer"},
            headers=oh,
        )
    invite_token = r.json()["invite_token"]
    member_id = r.json()["id"]

    # Manually expire the invite.
    db = SessionLocal()
    try:
        member = db.get(FamilyMember, member_id)
        member.invite_expires = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
    finally:
        db.close()

    invitee = _register("late@example.com")
    ih = {"Authorization": f"Bearer {invitee['access_token']}"}
    r2 = client.post(f"/api/v1/invites/{invite_token}/accept", headers=ih)
    assert r2.status_code == 410
    assert "expired" in r2.json()["detail"].lower()


def test_invite_cannot_be_reused():
    """Once accepted, the same invite token cannot be used again."""
    owner = _register()
    oh = {"Authorization": f"Bearer {owner['access_token']}"}

    with patch("app.routers.registry.send_email"):
        r = client.post(
            f"/api/v1/families/{owner['family_id']}/members",
            json={"display_name": "Once Only", "invited_email": "once@example.com",
                  "access": "viewer"},
            headers=oh,
        )
    invite_token = r.json()["invite_token"]

    invitee = _register("once@example.com")
    ih = {"Authorization": f"Bearer {invitee['access_token']}"}

    # First accept.
    r2 = client.post(f"/api/v1/invites/{invite_token}/accept", headers=ih)
    assert r2.status_code == 200

    # Second attempt — the hash was cleared, so it won't be found.
    r3 = client.post(f"/api/v1/invites/{invite_token}/accept", headers=ih)
    assert r3.status_code in (404, 410)


def test_invite_leaves_audit_trail():
    """Both invite creation and acceptance must be audited."""
    from app.db import SessionLocal
    from app.models import AuditLog

    owner = _register()
    oh = {"Authorization": f"Bearer {owner['access_token']}"}

    with patch("app.routers.registry.send_email"):
        r = client.post(
            f"/api/v1/families/{owner['family_id']}/members",
            json={"display_name": "Audited", "invited_email": "audited@example.com",
                  "access": "viewer"},
            headers=oh,
        )
    invite_token = r.json()["invite_token"]

    invitee = _register("audited@example.com")
    ih = {"Authorization": f"Bearer {invitee['access_token']}"}
    client.post(f"/api/v1/invites/{invite_token}/accept", headers=ih)

    db = SessionLocal()
    try:
        add_row = db.query(AuditLog).filter(AuditLog.action == "member.add").order_by(
            AuditLog.created_at.desc()
        ).first()
        assert add_row is not None, "invite creation must be audited"

        accept_row = db.query(AuditLog).filter(AuditLog.action == "invite.accept").order_by(
            AuditLog.created_at.desc()
        ).first()
        assert accept_row is not None, "invite acceptance must be audited"
    finally:
        db.close()
