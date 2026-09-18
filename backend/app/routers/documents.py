from __future__ import annotations

import hashlib
from typing import Any
import uuid

from fastapi import (
    APIRouter, Depends, File, HTTPException, Request, UploadFile,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import pipeline
from app.config import settings
from app.db import get_db
from app.models import Asset, Document, ExtractedField, Link, Property, User
from app.security import audit, current_user, membership, owned_or_404, require_access
from app.services import queue, storage, upload_security

router = APIRouter(prefix="/api/v1/families/{family_id}/documents", tags=["documents"])
ALLOWED = set(settings.allowed_mime.split(","))


class FieldOut(BaseModel):
    id: uuid.UUID
    field_key: str
    label: str
    field_value: str | None
    confidence: float | None
    band: str
    source: str
    source_page: int | None
    source_snippet: str | None
    source_bbox: dict | None = None
    verification: str


class DocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    category: str | None
    status: str
    page_count: int | None
    fields: list[FieldOut] = []





@router.post("", response_model=DocumentOut, status_code=201)
async def upload(
    family_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    member = membership(db, user, family_id)
    require_access(member, "contributor")

    # 1. Rate limiting per user
    if not upload_security.check_rate_limit(
        user.id,
        max_count=getattr(settings, "upload_rate_limit_count", 20),
        window_seconds=getattr(settings, "upload_rate_limit_seconds", 600),
    ):
        raise HTTPException(
            status_code=429,
            detail="Upload rate limit reached. Please wait before uploading more documents.",
        )

    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Files must be under {settings.max_upload_mb} MB.")

    # 2. Trust the sniffed type, not the client-declared one.
    try:
        import magic
        mime = magic.from_buffer(data[:4096], mime=True)
    except Exception:
        if data.startswith(b"%PDF"):
            mime = "application/pdf"
        elif data.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif data.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        else:
            mime = file.content_type or "application/octet-stream"

    if mime not in ALLOWED:
        raise HTTPException(status_code=415, detail=f"{mime} isn't a supported file type.")

    # 3. PDF Security: Active content rejection & zip-bomb protection
    detected_page_count = None
    if mime == "application/pdf":
        violations = upload_security.check_pdf_active_content(data)
        if violations:
            raise HTTPException(
                status_code=400,
                detail=f"Upload rejected: PDF contains disallowed active content ({', '.join(violations)}).",
            )
        try:
            detected_page_count, _ = upload_security.check_pdf_limits(
                data,
                max_pages=getattr(settings, "max_pdf_pages", 100),
                max_decompressed_bytes=getattr(settings, "max_decompressed_mb", 100) * 1024 * 1024,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # 4. Image Security: Strip EXIF metadata
    if mime.startswith("image/"):
        data, _ = upload_security.strip_exif(data, mime)

    # 5. Anti-virus scan via ClamAV if configured
    fail_closed = getattr(settings, "app_env", "development") == "production"
    try:
        virus = upload_security.scan_clamav(
            data,
            host=getattr(settings, "clamav_host", None),
            port=getattr(settings, "clamav_port", 3310),
            fail_closed=fail_closed,
        )
        if virus:
            raise HTTPException(
                status_code=400,
                detail=f"Security alert: malicious content detected in upload ({virus}).",
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    digest = hashlib.sha256(data).hexdigest()
    if db.scalar(select(Document).where(Document.family_id == family_id,
                                        Document.sha256 == digest)):
        raise HTTPException(status_code=409, detail="This file is already in the vault.")

    key = storage.build_key(family_id, file.filename or "document")
    storage.put(key, data, mime)

    doc = Document(family_id=family_id, uploaded_by=user.id,
                   title=file.filename or "Untitled", mime_type=mime,
                   size_bytes=len(data), sha256=digest, storage_key=key,
                   page_count=detected_page_count, status="scanning")
    db.add(doc)
    audit(db, request, user, "document.upload", family_id=family_id,
          resource_type="document", resource_id=doc.id, filename=file.filename)

    # Enqueue durable processing job instead of a fragile BackgroundTask.
    queue.enqueue(db, "document.process", {"document_id": str(doc.id)})
    db.commit()

    return DocumentOut(id=doc.id, title=doc.title, category=None,
                       status=doc.status, page_count=doc.page_count)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    family_id: uuid.UUID,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    membership(db, user, family_id)
    q = select(Document).where(Document.family_id == family_id)
    if status:
        q = q.where(Document.status == status)
    return [DocumentOut(id=d.id, title=d.title, category=d.category,
                        status=d.status, page_count=d.page_count)
            for d in db.scalars(q.order_by(Document.created_at.desc()))]


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    family_id: uuid.UUID, document_id: uuid.UUID,
    request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
):
    from app.ai import schemas
    doc = owned_or_404(db, user, Document, document_id)
    fields = db.scalars(select(ExtractedField).where(ExtractedField.document_id == doc.id)).all()
    audit(db, request, user, "document.view", family_id=doc.family_id,
          resource_type="document", resource_id=doc.id)
    db.commit()
    return DocumentOut(
        id=doc.id, title=doc.title, category=doc.category, status=doc.status,
        page_count=doc.page_count,
        fields=[FieldOut(id=f.id, field_key=f.field_key,
                         label=schemas.label_for(f.field_key),
                         field_value=f.field_value,
                         confidence=float(f.confidence) if f.confidence else None,
                         band=pipeline.confidence_band(float(f.confidence) if f.confidence else None),
                         source=f.source, source_page=f.source_page,
                         source_snippet=f.source_snippet,
                         source_bbox=f.source_bbox,
                         verification=f.verification)
                for f in fields],
    )


@router.get("/{document_id}/file")
def download(
    family_id: uuid.UUID, document_id: uuid.UUID,
    request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
):
    doc = owned_or_404(db, user, Document, document_id)
    audit(db, request, user, "document.download", family_id=doc.family_id,
          resource_type="document", resource_id=doc.id)
    db.commit()
    return {"url": storage.signed_url(doc.storage_key), "expires_in": 300}


@router.get("/{document_id}/pages/{page_no}")
def get_page(
    family_id: uuid.UUID, document_id: uuid.UUID, page_no: int,
    request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
):
    doc = owned_or_404(db, user, Document, document_id)
    if doc.family_id != family_id:
        raise HTTPException(status_code=404, detail="Not found.")
    if page_no < 1 or (doc.page_count is not None and page_no > doc.page_count):
        raise HTTPException(status_code=404, detail=f"Page {page_no} not found.")
    key = storage.page_key(doc.storage_key, page_no)
    audit(db, request, user, "document.page_view", family_id=doc.family_id,
          resource_type="document", resource_id=doc.id, page=page_no)
    db.commit()
    return {"url": storage.signed_url(key), "expires_in": 300, "page": page_no}


class VerifyIn(BaseModel):
    value: str | None = None


@router.post("/{document_id}/fields/{field_id}/verify", response_model=FieldOut)
def verify_field(
    family_id: uuid.UUID, document_id: uuid.UUID, field_id: uuid.UUID,
    payload: VerifyIn, request: Request,
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    from app.ai import schemas
    field = owned_or_404(db, user, ExtractedField, field_id, minimum="contributor")
    if field.document_id != document_id:
        raise HTTPException(status_code=404, detail="Not found.")

    pipeline.mark_verified(db, field, user.id, payload.value)
    audit(db, request, user, "field.verify", family_id=field.family_id,
          resource_type="extracted_field", resource_id=field.id,
          new_value_set=payload.value is not None)

    remaining = db.scalar(
        select(ExtractedField).where(ExtractedField.document_id == document_id,
                                     ExtractedField.verification == "unverified")
    )
    if remaining is None:
        doc = db.get(Document, document_id)
        doc.status = "verified"
    db.commit()
    return FieldOut(id=field.id, field_key=field.field_key,
                    label=schemas.label_for(field.field_key),
                    field_value=field.field_value,
                    confidence=float(field.confidence) if field.confidence else None,
                    band=pipeline.confidence_band(float(field.confidence) if field.confidence else None),
                    source=field.source, source_page=field.source_page,
                    source_snippet=field.source_snippet,
                    source_bbox=field.source_bbox,
                    verification=field.verification)


# Direct /documents/{id}/pages/{n} and promote routes (authorized via tenancy guard)
page_router = APIRouter(tags=["documents"])


class PromoteIn(BaseModel):
    target: str  # "asset" | "property"


class PromoteOut(BaseModel):
    record_id: uuid.UUID
    target: str
    action: str  # "created" | "updated"
    copied_fields: dict[str, str]
    skipped_fields: list[dict[str, str]]


def _promote_document(
    db: Session,
    user: User,
    doc: Document,
    target: str,
    request: Request,
) -> PromoteOut:
    from app.ai import schemas

    if target not in ("asset", "property"):
        raise HTTPException(status_code=400, detail="Target must be 'asset' or 'property'.")

    fields = db.scalars(
        select(ExtractedField).where(ExtractedField.document_id == doc.id)
    ).all()

    mapping = schemas.get_column_mapping(target)
    copied_values: dict[str, Any] = {}
    copied_summary: dict[str, str] = {}
    skipped: list[dict[str, str]] = []

    for f in fields:
        if f.verification != "verified":
            skipped.append({
                "field_key": f.field_key,
                "reason": f"unverified: human verification is required before promoting to a trusted {target} record",
            })
            continue

        if f.field_key not in mapping:
            skipped.append({
                "field_key": f.field_key,
                "reason": f"unmapped: field does not correspond to a {target} record column",
            })
            continue

        col_name = mapping[f.field_key]
        val = f.field_value

        # Type conversions for numeric/date columns
        if col_name in ("area_value", "value_estimate"):
            try:
                copied_values[col_name] = float(val) if val else None
            except (ValueError, TypeError):
                copied_values[col_name] = None
        else:
            copied_values[col_name] = val

        copied_summary[f.field_key] = f"{col_name} = {val}"

    # Check if a link from this document to a record of target type already exists (promoting twice updates)
    existing_link = db.scalar(
        select(Link).where(
            Link.family_id == doc.family_id,
            Link.from_type == "document",
            Link.from_id == doc.id,
            Link.to_type == target,
        )
    )

    if existing_link:
        record_id = existing_link.to_id
        if target == "property":
            record = db.get(Property, record_id)
        else:
            record = db.get(Asset, record_id)

        if record:
            for k, v in copied_values.items():
                if hasattr(record, k) and v is not None:
                    setattr(record, k, v)
            action = "updated"
        else:
            existing_link = None  # Orphan link, re-create

    if not existing_link:
        if target == "property":
            record = Property(
                family_id=doc.family_id,
                label=copied_values.get("label", doc.title),
                type=copied_values.get("type", "land_or_building"),
                verification="verified",
                **{k: v for k, v in copied_values.items() if k not in ("label", "type")},
            )
        else:
            record = Asset(
                family_id=doc.family_id,
                name=copied_values.get("name", doc.title),
                type=copied_values.get("type", doc.category or "asset"),
                verification="verified",
                **{k: v for k, v in copied_values.items() if k not in ("name", "type")},
            )
        db.add(record)
        db.flush()

        link = Link(
            family_id=doc.family_id,
            from_type="document",
            from_id=doc.id,
            to_type=target,
            to_id=record.id,
            link_type="relates_to",
        )
        db.add(link)
        action = "created"

    # Re-point source extracted_fields rows to the new record subject_id
    for f in fields:
        f.subject_type = target
        f.subject_id = record.id

    audit(
        db, request, user, "document.promote",
        family_id=doc.family_id,
        resource_type=target,
        resource_id=record.id,
        document_id=str(doc.id),
        action=action,
        copied_count=len(copied_summary),
    )
    db.commit()

    return PromoteOut(
        record_id=record.id,
        target=target,
        action=action,
        copied_fields=copied_summary,
        skipped_fields=skipped,
    )


@router.post("/{document_id}/promote", response_model=PromoteOut)
def promote_document(
    family_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: PromoteIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    doc = owned_or_404(db, user, Document, document_id, minimum="contributor")
    if doc.family_id != family_id:
        raise HTTPException(status_code=404, detail="Not found.")
    return _promote_document(db, user, doc, payload.target, request)


@page_router.post("/api/v1/documents/{document_id}/promote", response_model=PromoteOut)
@page_router.post("/documents/{document_id}/promote", response_model=PromoteOut)
def promote_document_direct(
    document_id: uuid.UUID,
    payload: PromoteIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    doc = owned_or_404(db, user, Document, document_id, minimum="contributor")
    return _promote_document(db, user, doc, payload.target, request)


@page_router.get("/api/v1/documents/{document_id}/pages/{page_no}")
@page_router.get("/documents/{document_id}/pages/{page_no}")
def get_page_direct(
    document_id: uuid.UUID, page_no: int,
    request: Request, db: Session = Depends(get_db), user: User = Depends(current_user),
):
    doc = owned_or_404(db, user, Document, document_id)
    if page_no < 1 or (doc.page_count is not None and page_no > doc.page_count):
        raise HTTPException(status_code=404, detail=f"Page {page_no} not found.")
    key = storage.page_key(doc.storage_key, page_no)
    audit(db, request, user, "document.page_view", family_id=doc.family_id,
          resource_type="document", resource_id=doc.id, page=page_no)
    db.commit()
    return {"url": storage.signed_url(key), "expires_in": 300, "page": page_no}


