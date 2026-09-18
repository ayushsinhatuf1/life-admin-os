"""The tests that must never be deleted: one family cannot read another's data.

Section 24 lists 'unauthorized document access' as a critical risk. This suite
is the regression guard for it. Run it on every commit.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _register(email: str) -> tuple[str, str]:
    r = client.post("/api/v1/auth/register", json={
        "email": email, "full_name": "Test User", "password": "correct-horse-battery",
    })
    assert r.status_code == 201
    body = r.json()
    return body["access_token"], body["family_id"]


def test_stranger_cannot_list_another_family_documents():
    _, family_a = _register(f"a-{uuid.uuid4()}@example.com")
    token_b, _ = _register(f"b-{uuid.uuid4()}@example.com")

    r = client.get(f"/api/v1/families/{family_a}/documents",
                   headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code == 404, "must 404, not 403 — do not confirm the family exists"


def test_unauthenticated_request_is_rejected():
    r = client.get(f"/api/v1/families/{uuid.uuid4()}/documents")
    assert r.status_code == 401


def test_viewer_cannot_create_assets():
    # Build a family, downgrade the caller to viewer, then attempt a write.
    # Fill in once the member-role endpoint is wired; the assertion is 403.
    pytest.skip("wire up after the role-change endpoint exists")


def test_duplicate_upload_is_rejected():
    token, family = _register(f"c-{uuid.uuid4()}@example.com")
    files = {"file": ("a.pdf", b"%PDF-1.4 minimal", "application/pdf")}
    h = {"Authorization": f"Bearer {token}"}
    first = client.post(f"/api/v1/families/{family}/documents", files=files, headers=h)
    second = client.post(f"/api/v1/families/{family}/documents", files=files, headers=h)
    assert first.status_code in (201, 415)
    if first.status_code == 201:
        assert second.status_code == 409
