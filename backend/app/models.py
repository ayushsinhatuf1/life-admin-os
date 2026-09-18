"""SQLAlchemy models. Mirrors db/schema.sql — keep the two in sync via Alembic."""
from __future__ import annotations

from typing import Any
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String)
    auth_provider: Mapped[str] = mapped_column(String, default="local")
    phone: Mapped[str | None] = mapped_column(String)
    locale: Mapped[str] = mapped_column(String, default="en-IN")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Family(Base):
    __tablename__ = "families"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String, nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FamilyMember(Base):
    __tablename__ = "family_members"
    id: Mapped[uuid.UUID] = _pk()
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    relationship_label: Mapped[str | None] = mapped_column("relationship", String)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    is_deceased: Mapped[bool] = mapped_column(Boolean, default=False)
    access: Mapped[str] = mapped_column(String, default="viewer")
    invited_email: Mapped[str | None] = mapped_column(String)
    invite_token_hash: Mapped[str | None] = mapped_column(String)
    invite_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invite_accepted: Mapped[bool] = mapped_column(Boolean, default=False)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = _pk()
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str | None] = mapped_column(String)
    category_conf: Mapped[float | None] = mapped_column(Numeric(4, 3))
    mime_type: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String)
    storage_key: Mapped[str] = mapped_column(String)
    page_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="uploaded")
    ocr_text: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    fields: Mapped[list["ExtractedField"]] = relationship(back_populates="document")


class DocumentChunk(Base):
    """Chunked text + embeddings for grounded assistant retrieval (FR-015)."""
    __tablename__ = "document_chunks"
    id: Mapped[uuid.UUID] = _pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    page_no: Mapped[int | None] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any | None] = mapped_column(Text)



class ExtractedField(Base):
    """One fact, with where it came from and whether a human confirmed it."""
    __tablename__ = "extracted_fields"
    id: Mapped[uuid.UUID] = _pk()
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    subject_type: Mapped[str] = mapped_column(String, default="document")
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    field_key: Mapped[str] = mapped_column(String)
    field_value: Mapped[str | None] = mapped_column(Text)
    value_json: Mapped[dict | None] = mapped_column(JSONB)
    data_type: Mapped[str] = mapped_column(String, default="string")
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    source: Mapped[str] = mapped_column(String, default="ai_extracted")
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_snippet: Mapped[str | None] = mapped_column(Text)
    source_bbox: Mapped[dict | None] = mapped_column(JSONB)
    verification: Mapped[str] = mapped_column(String, default="unverified")
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model_name: Mapped[str | None] = mapped_column(String)

    document: Mapped[Document | None] = relationship(back_populates="fields")


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[uuid.UUID] = _pk()
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    institution: Mapped[str | None] = mapped_column(String)
    identifier_last4: Mapped[str | None] = mapped_column(String)
    value_estimate: Mapped[float | None] = mapped_column(Numeric(18, 2))
    value_as_of: Mapped[date | None] = mapped_column(Date)
    verification: Mapped[str] = mapped_column(String, default="unverified")
    notes: Mapped[str | None] = mapped_column(Text)


class Property(Base):
    __tablename__ = "properties"
    id: Mapped[uuid.UUID] = _pk()
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)
    village_locality: Mapped[str | None] = mapped_column(String)
    district: Mapped[str | None] = mapped_column(String)
    state: Mapped[str | None] = mapped_column(String)
    survey_number: Mapped[str | None] = mapped_column(String)
    plot_number: Mapped[str | None] = mapped_column(String)
    khata_number: Mapped[str | None] = mapped_column(String)
    area_value: Mapped[float | None] = mapped_column(Numeric(14, 4))
    area_unit: Mapped[str | None] = mapped_column(String)
    recorded_holder: Mapped[str | None] = mapped_column(String)
    value_estimate: Mapped[float | None] = mapped_column(Numeric(18, 2))
    verification: Mapped[str] = mapped_column(String, default="unverified")
    history_note: Mapped[str | None] = mapped_column(Text)


class OwnershipRecord(Base):
    __tablename__ = "ownership_records"
    id: Mapped[uuid.UUID] = _pk()
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    member_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("family_members.id"))
    external_holder: Mapped[str | None] = mapped_column(String)
    subject_type: Mapped[str] = mapped_column(String)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    relationship_label: Mapped[str] = mapped_column("relationship", String)
    share_percent: Mapped[float | None] = mapped_column(Numeric(6, 3))
    provenance_note: Mapped[str] = mapped_column(Text)
    verification: Mapped[str] = mapped_column(String, default="unverified")


class Link(Base):
    __tablename__ = "links"
    id: Mapped[uuid.UUID] = _pk()
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    from_type: Mapped[str] = mapped_column(String)
    from_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    to_type: Mapped[str] = mapped_column(String)
    to_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    link_type: Mapped[str] = mapped_column(String, default="relates_to")


class Deadline(Base):
    __tablename__ = "deadlines"
    id: Mapped[uuid.UUID] = _pk()
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date] = mapped_column(Date)
    priority: Mapped[str] = mapped_column(String, default="medium")
    status: Mapped[str] = mapped_column(String, default="open")
    recurrence_rule: Mapped[str | None] = mapped_column(String)
    source_type: Mapped[str | None] = mapped_column(String)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[uuid.UUID] = _pk()
    deadline_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("deadlines.id", ondelete="CASCADE"))
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    channel: Mapped[str] = mapped_column(String, default="email")
    recipient_user: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    delivery_status: Mapped[str] = mapped_column(String, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    family_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String)
    resource_type: Mapped[str | None] = mapped_column(String)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ip_address: Mapped[str | None] = mapped_column(String)
    user_agent: Mapped[str | None] = mapped_column(String)
    audit_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AIConversation(Base):
    __tablename__ = "ai_conversations"
    id: Mapped[uuid.UUID] = _pk()
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    query: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    retrieved_ids: Mapped[list] = mapped_column(JSONB, default=list)
    refused: Mapped[bool] = mapped_column(Boolean, default=False)
    model_name: Mapped[str | None] = mapped_column(String)
    latency_ms: Mapped[int | None] = mapped_column(Integer)


class RefreshToken(Base):
    """Refresh tokens for session management.

    Only the token hash is stored — never the raw token. Reuse detection
    works by checking revoked_at: if a revoked token is presented, the
    entire token family for that user is revoked.
    """
    __tablename__ = "refresh_tokens"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String)
    ip_address: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Job(Base):
    """Durable job queue backed by Postgres.

    Workers claim jobs with SELECT ... FOR UPDATE SKIP LOCKED, ensuring
    crash-safety: if the worker dies, the lock releases and another worker
    picks it up on the next poll.
    """
    __tablename__ = "jobs"
    id: Mapped[uuid.UUID] = _pk()
    kind: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)
    locked_by: Mapped[str | None] = mapped_column(String)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationPreference(Base):
    """Per-user notification preferences: channels, send hour, quiet hours, mute categories, weekly digest."""
    __tablename__ = "notification_preferences"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    channels: Mapped[list] = mapped_column(JSONB, default=lambda: ["email"])
    send_hour: Mapped[int] = mapped_column(Integer, default=9)
    timezone: Mapped[str] = mapped_column(String, default="Asia/Kolkata")
    muted_categories: Mapped[list] = mapped_column(JSONB, default=list)
    weekly_digest: Mapped[bool] = mapped_column(Boolean, default=False)
    digest_day: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ReminderDelivery(Base):
    """Enforces exactly-once reminder sending via UNIQUE(reminder_id) constraint in Postgres."""
    __tablename__ = "reminder_deliveries"
    id: Mapped[uuid.UUID] = _pk()
    reminder_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reminders.id", ondelete="CASCADE"), unique=True)
    deadline_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("deadlines.id", ondelete="CASCADE"))
    recipient_user: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String, default="email")
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Consent(Base):
    """Consent capture for DPDP Act compliance (Section 18).

    Versioned against notice text, one row per purpose ('ai_processing', 'email_reminders', 'family_sharing').
    """
    __tablename__ = "consents"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    notice_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataRequest(Base):
    """Data-subject rights requests under DPDP (export, erasure, correction)."""
    __tablename__ = "data_requests"
    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String, nullable=False)  # 'export', 'erasure', 'correction'
    status: Mapped[str] = mapped_column(String, default="received")  # 'received', 'processing', 'completed', 'failed'
    result_key: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Event(Base):
    """Product analytics events (Section 34).

    No personal data or document contents ever enter event payloads.
    """
    __tablename__ = "events"
    id: Mapped[uuid.UUID] = _pk()
    event_name: Mapped[str] = mapped_column(String, nullable=False)
    family_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    properties: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())



