"""Tests for PDF page rasterisation, signed page URLs, and bounding box extraction (P2.2).

Verifies:
- PDF pages are rasterised to WebP at 150 dpi and stored under the document prefix
- Images are rasterised to page 1 WebP
- GET /documents/{id}/pages/{n} returns signed URL with proper authorization checks
- Bounding boxes are found and normalized (0.0 to 1.0)
- ExtractedField.source_bbox is persisted and serialized in API responses
"""
import io
import uuid
from unittest.mock import patch, MagicMock

try:
    import fitz
except ImportError:
    fitz = None

try:
    import pytest
except ImportError:
    pytest = None
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.ai import pipeline
from app.db import SessionLocal
from app.models import Document, ExtractedField, Family, FamilyMember, User
from app.security import hash_password, create_access_token
from app.services import storage

client = TestClient(app)


def _create_test_pdf(num_pages: int = 2) -> bytes:
    """Create a minimal multi-page PDF in-memory with PyMuPDF."""
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 100), f"Life Admin Test Page {i + 1}")
        page.insert_text((72, 150), f"Policy Number: POL-999{i + 1}")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _create_test_image() -> bytes:
    """Create a minimal PNG image in-memory."""
    img = Image.new("RGB", (200, 200), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _setup_user_and_family():
    db = SessionLocal()
    try:
        user_id = uuid.uuid4()
        family_id = uuid.uuid4()
        user = User(
            id=user_id,
            email=f"user-{uuid.uuid4()}@example.com",
            password_hash=hash_password("password123"),
            full_name="Page Test User",
            is_active=True,
        )
        family = Family(id=family_id, name="Test Family")
        member = FamilyMember(
            family_id=family_id,
            user_id=user_id,
            role="admin",
            access="owner",
        )
        db.add_all([user, family, member])
        db.commit()
        token = create_access_token(user_id)
        return user, family, token
    finally:
        db.close()


def test_rasterise_pages_pdf():
    pdf_bytes = _create_test_pdf(2)
    storage_key = "families/11111111-1111-1111-1111-111111111111/documents/22222222-2222-2222-2222-222222222222/test.pdf"

    stored_objects = {}

    def mock_put(key, data, content_type):
        stored_objects[key] = (data, content_type)
        return "fake-sha"

    with patch.object(storage, "put", side_effect=mock_put):
        page_count = pipeline.rasterise_pages(pdf_bytes, "application/pdf", storage_key)

    assert page_count == 2
    prefix = storage_key.rsplit("/", 1)[0]
    p1_key = f"{prefix}/pages/1.webp"
    p2_key = f"{prefix}/pages/2.webp"

    assert p1_key in stored_objects
    assert p2_key in stored_objects
    assert stored_objects[p1_key][1] == "image/webp"
    assert stored_objects[p2_key][1] == "image/webp"

    # Verify that stored data is a valid WebP image
    img1 = Image.open(io.BytesIO(stored_objects[p1_key][0]))
    assert img1.format == "WEBP"


def test_rasterise_pages_image():
    img_bytes = _create_test_image()
    storage_key = "families/11111111-1111-1111-1111-111111111111/documents/33333333-3333-3333-3333-333333333333/test.png"

    stored_objects = {}

    def mock_put(key, data, content_type):
        stored_objects[key] = (data, content_type)
        return "fake-sha"

    with patch.object(storage, "put", side_effect=mock_put):
        page_count = pipeline.rasterise_pages(img_bytes, "image/png", storage_key)

    assert page_count == 1
    prefix = storage_key.rsplit("/", 1)[0]
    p1_key = f"{prefix}/pages/1.webp"
    assert p1_key in stored_objects
    assert stored_objects[p1_key][1] == "image/webp"


def test_find_bbox_in_pdf():
    pdf_bytes = _create_test_pdf(2)
    bbox = pipeline._find_bbox_in_pdf(pdf_bytes, 1, "Policy Number: POL-9991")
    assert bbox is not None
    assert "x" in bbox and "y" in bbox and "w" in bbox and "h" in bbox
    assert 0.0 <= bbox["x"] <= 1.0
    assert 0.0 <= bbox["y"] <= 1.0
    assert 0.0 < bbox["w"] <= 1.0
    assert 0.0 < bbox["h"] <= 1.0

    # Non-existent text returns None
    missing_bbox = pipeline._find_bbox_in_pdf(pdf_bytes, 1, "NON_EXISTENT_STRING_XYZ")
    assert missing_bbox is None


def test_get_page_image_authorized_and_unauthorized():
    user_a, family_a, token_a = _setup_user_and_family()
    _, _, token_b = _setup_user_and_family()

    db = SessionLocal()
    try:
        doc = Document(
            family_id=family_a.id,
            uploaded_by=user_a.id,
            title="Insurance Policy.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
            sha256="fake-hash-" + uuid.uuid4().hex,
            storage_key=f"families/{family_a.id}/documents/{uuid.uuid4()}/policy.pdf",
            page_count=3,
            status="needs_review",
        )
        db.add(doc)
        db.commit()
        doc_id = doc.id
    finally:
        db.close()

    # User A (authorized) can get page 1
    with patch.object(storage, "signed_url", return_value="https://minio.example.com/signed-page-1"):
        r = client.get(
            f"/api/v1/families/{family_a.id}/documents/{doc_id}/pages/1",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["page"] == 1
        assert body["url"] == "https://minio.example.com/signed-page-1"

    # User A requests invalid page number (e.g. 0 or 4 when page_count=3)
    r = client.get(
        f"/api/v1/families/{family_a.id}/documents/{doc_id}/pages/0",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r.status_code == 404

    r = client.get(
        f"/api/v1/families/{family_a.id}/documents/{doc_id}/pages/4",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r.status_code == 404

    # User B (different family) is rejected with 404
    r = client.get(
        f"/api/v1/families/{family_a.id}/documents/{doc_id}/pages/1",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r.status_code == 404

    # Direct routes work as well
    with patch.object(storage, "signed_url", return_value="https://minio.example.com/signed-page-1"):
        r_direct = client.get(
            f"/api/v1/documents/{doc_id}/pages/1",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert r_direct.status_code == 200
        assert r_direct.json()["url"] == "https://minio.example.com/signed-page-1"

        r_short = client.get(
            f"/documents/{doc_id}/pages/1",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert r_short.status_code == 200


def test_source_bbox_persisted_and_returned():
    user, family, token = _setup_user_and_family()
    db = SessionLocal()
    try:
        doc = Document(
            family_id=family.id,
            uploaded_by=user.id,
            title="Vehicle RC.pdf",
            mime_type="application/pdf",
            size_bytes=2048,
            sha256="fake-hash-" + uuid.uuid4().hex,
            storage_key=f"families/{family.id}/documents/{uuid.uuid4()}/rc.pdf",
            page_count=1,
            status="needs_review",
        )
        db.add(doc)
        db.flush()

        field = ExtractedField(
            family_id=family.id,
            document_id=doc.id,
            subject_type="document",
            subject_id=doc.id,
            field_key="registration_number",
            field_value="MH12AB1234",
            data_type="string",
            confidence=0.98,
            source="ai_extracted",
            source_page=1,
            source_snippet="Reg: MH12AB1234",
            source_bbox={"x": 0.12, "y": 0.34, "w": 0.25, "h": 0.05},
            verification="unverified",
        )
        db.add(field)
        db.commit()
        doc_id = doc.id
    finally:
        db.close()

    r = client.get(
        f"/api/v1/families/{family.id}/documents/{doc_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["fields"]) == 1
    f = data["fields"][0]
    assert f["field_key"] == "registration_number"
    assert f["source_bbox"] == {"x": 0.12, "y": 0.34, "w": 0.25, "h": 0.05}
