"""Upload -> validate -> OCR -> classify -> extract -> confidence -> human review.

This is Section 11 of the blueprint, in code. The one rule that matters: nothing
reaches a user-visible record as trusted data without passing through
human verification. Low confidence does not block extraction; it routes the
document to the review queue.
"""
from __future__ import annotations

import io
import json
import logging
import uuid
from datetime import datetime, timezone

import fitz  # PyMuPDF
import pytesseract
from anthropic import Anthropic
from PIL import Image
from sqlalchemy.orm import Session

from app.ai import schemas
from app.ai.prompts import CLASSIFY_SYSTEM, EXTRACT_SYSTEM
from app.config import settings
from app.models import Deadline, Document, ExtractedField
from app.services import storage

log = logging.getLogger(__name__)
client = Anthropic(api_key=settings.anthropic_api_key)

AUTO_VERIFY_FLOOR = 0.95   # above this we still ask, but pre-tick the checkbox
REVIEW_CEILING = 0.70      # below this the field is highlighted for correction


# ------------------------------------------------------------------ OCR
def extract_text(data: bytes, mime_type: str) -> tuple[str, int]:
    """Return (text, page_count). Falls back to OCR when a PDF has no text layer."""
    if mime_type == "application/pdf":
        doc = fitz.open(stream=data, filetype="pdf")
        pages: list[str] = []
        for page in doc:
            text = page.get_text().strip()
            if len(text) < 40:  # scanned page, rasterise and OCR it
                pix = page.get_pixmap(dpi=300)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                text = pytesseract.image_to_string(img, lang="eng+hin")
            pages.append(f"<page n={page.number + 1}>\n{text}\n</page>")
        return "\n".join(pages), doc.page_count

    img = Image.open(io.BytesIO(data))
    return f"<page n=1>\n{pytesseract.image_to_string(img, lang='eng+hin')}\n</page>", 1


# ------------------------------------------------------------------ model calls
def _json_call(system: str, user: str, max_tokens: int = 2000) -> dict:
    response = client.messages.create(
        model=settings.extraction_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw = "".join(b.text for b in response.content if b.type == "text").strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)


def classify(text: str) -> dict:
    return _json_call(CLASSIFY_SYSTEM, text[:12000], max_tokens=300)


def extract(text: str, category: str) -> dict:
    schema = schemas.for_category(category)
    user = (
        f"Requested schema for a '{category}' document:\n"
        f"{json.dumps(schema, indent=2)}\n\n"
        f"Document text:\n{text[:40000]}"
    )
    return _json_call(EXTRACT_SYSTEM, user)


# ------------------------------------------------------------------ rasterisation & bboxes
def rasterise_pages(data: bytes, mime_type: str, storage_key: str) -> int:
    """Rasterise each PDF page to a WebP at 150 dpi and store alongside the original."""
    if mime_type == "application/pdf":
        doc = fitz.open(stream=data, filetype="pdf")
        count = doc.page_count
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=150)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            buf = io.BytesIO()
            img.save(buf, format="WEBP")
            key = storage.page_key(storage_key, i)
            storage.put(key, buf.getvalue(), "image/webp")
        return count
    else:
        img = Image.open(io.BytesIO(data))
        buf = io.BytesIO()
        img.save(buf, format="WEBP")
        key = storage.page_key(storage_key, 1)
        storage.put(key, buf.getvalue(), "image/webp")
        return 1


def _find_bbox_in_pdf(data: bytes, page_no: int | None, value: str, snippet: str | None = None) -> dict | None:
    """Search for the value or snippet in the PDF page and return normalised {x,y,w,h}."""
    if not page_no or not value:
        return None
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        if page_no < 1 or page_no > doc.page_count:
            return None
        page = doc[page_no - 1]
        pw, ph = page.rect.width, page.rect.height
        if pw <= 0 or ph <= 0:
            return None
        rects = page.search_for(value)
        if not rects and snippet:
            rects = page.search_for(snippet[:30])
        if rects:
            r = rects[0]
            return {
                "x": round(max(0.0, min(1.0, r.x0 / pw)), 4),
                "y": round(max(0.0, min(1.0, r.y0 / ph)), 4),
                "w": round(max(0.0, min(1.0, r.width / pw)), 4),
                "h": round(max(0.0, min(1.0, r.height / ph)), 4),
            }
    except Exception:
        pass
    return None


# ------------------------------------------------------------------ orchestration
def process_document(db: Session, document_id: uuid.UUID) -> None:
    """Run the whole pipeline for one document. Call from a background worker."""
    doc = db.get(Document, document_id)
    if doc is None:
        return

    try:
        doc.status = "processing"
        db.commit()

        data = storage.get(doc.storage_key)
        page_count = rasterise_pages(data, doc.mime_type, doc.storage_key)
        text, _ = extract_text(data, doc.mime_type)
        doc.ocr_text = text
        doc.page_count = page_count

        # DPDP Check (Section 18): verify user has active ai_processing consent
        from app.services import dpdp
        if doc.uploaded_by and not dpdp.has_consent(db, doc.uploaded_by, "ai_processing"):
            log.info("AI processing stopped for document %s: user %s has withdrawn AI consent", doc.id, doc.uploaded_by)
            doc.status = "ai_consent_withdrawn"
            db.commit()
            return

        verdict = classify(text)
        doc.category = verdict.get("category", "other")
        doc.category_conf = verdict.get("confidence")

        result = extract(text, doc.category)
        for item in result.get("fields", []):
            bbox = item.get("bbox")
            if not bbox and doc.mime_type == "application/pdf":
                bbox = _find_bbox_in_pdf(data, item.get("page"), item.get("value", ""), item.get("snippet"))
            db.add(
                ExtractedField(
                    family_id=doc.family_id,
                    document_id=doc.id,
                    subject_type="document",
                    subject_id=doc.id,
                    field_key=item["key"],
                    field_value=str(item.get("value", "")),
                    data_type=schemas.type_of(doc.category, item["key"]),
                    confidence=item.get("confidence"),
                    source="ai_extracted",
                    source_page=item.get("page"),
                    source_snippet=item.get("snippet"),
                    source_bbox=bbox,
                    verification="unverified",
                    model_name=settings.extraction_model,
                )
            )

        # Ingest chunks and embeddings for hybrid retrieval (P5.1)
        try:
            from app.ai import assistant
            assistant.ingest_document_chunks(db, doc)
        except Exception as chunk_exc:
            log.warning("Chunk ingestion failed for document %s: %s", doc.id, chunk_exc)

        _propose_deadlines(db, doc)
        doc.status = "needs_review"
        db.commit()

    except Exception as exc:  # noqa: BLE001 — pipeline must never poison the queue
        log.exception("Processing failed for document %s", document_id)
        db.rollback()
        doc = db.get(Document, document_id)
        if doc:
            doc.status = "failed"
            doc.error_message = str(exc)[:500]
            db.commit()


def _propose_deadlines(db: Session, doc: Document) -> None:
    """Turn date fields into draft deadlines. They stay 'open' but every one is
    tied back to the field it came from, so the user can see why it exists."""
    date_keys = schemas.deadline_keys(doc.category)
    for field in db.query(ExtractedField).filter(
        ExtractedField.document_id == doc.id,
        ExtractedField.field_key.in_(date_keys),
    ):
        if not field.field_value or len(field.field_value) < 10:
            continue
        try:
            due = datetime.fromisoformat(field.field_value).date()
        except ValueError:
            continue
        db.add(
            Deadline(
                family_id=doc.family_id,
                title=f"{schemas.label_for(field.field_key)} — {doc.title}",
                description=f"Detected from {doc.title}, page {field.source_page}.",
                due_date=due,
                priority="high" if field.field_key.endswith("expiry_date") else "medium",
                source_type="document",
                source_id=doc.id,
            )
        )


def confidence_band(value: float | None) -> str:
    if value is None:
        return "review"
    if value >= AUTO_VERIFY_FLOOR:
        return "high"
    if value >= REVIEW_CEILING:
        return "medium"
    return "review"


def mark_verified(db: Session, field: ExtractedField, user_id: uuid.UUID, new_value: str | None) -> None:
    if new_value is not None and new_value != field.field_value:
        field.field_value = new_value
        field.source = "user_entered"
        field.confidence = 1.0
    field.verification = "verified"
    field.verified_by = user_id
    field.verified_at = datetime.now(timezone.utc)
