"""initial schema matching db/schema.sql v1.0

Revision ID: 0001_initial
Revises: None
Create Date: 2026-09-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------------------------------------------------------- extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "citext"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')

    # ---------------------------------------------------------------- enums
    op.execute("CREATE TYPE access_level   AS ENUM ('owner','admin','contributor','viewer')")
    op.execute(
        "CREATE TYPE doc_status     AS ENUM "
        "('uploaded','scanning','processing','needs_review','verified','failed','archived')"
    )
    op.execute("CREATE TYPE field_source   AS ENUM ('ai_extracted','user_entered','imported','system_derived')")
    op.execute("CREATE TYPE verify_status  AS ENUM ('unverified','verified','disputed','rejected')")
    op.execute(
        "CREATE TYPE asset_type     AS ENUM "
        "('bank_account','investment','insurance','vehicle','jewellery','business','loan','subscription','other')"
    )
    op.execute(
        "CREATE TYPE property_type  AS ENUM "
        "('agricultural_land','residential_plot','house','apartment','commercial','ancestral_land','other')"
    )
    op.execute("CREATE TYPE deadline_status AS ENUM ('open','snoozed','done','dismissed','expired')")
    op.execute("CREATE TYPE priority_level  AS ENUM ('low','medium','high','critical')")

    # ---------------------------------------------------------------- identity
    op.execute("""
        CREATE TABLE users (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email           CITEXT UNIQUE NOT NULL,
            full_name       TEXT NOT NULL,
            password_hash   TEXT,
            auth_provider   TEXT NOT NULL DEFAULT 'local',
            external_id     TEXT,
            phone           TEXT,
            locale          TEXT NOT NULL DEFAULT 'en-IN',
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE families (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name            TEXT NOT NULL,
            owner_user_id   UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            settings        JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE family_members (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
            user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
            display_name    TEXT NOT NULL,
            relationship    TEXT,
            date_of_birth   DATE,
            date_of_death   DATE,
            is_deceased     BOOLEAN NOT NULL DEFAULT FALSE,
            access          access_level NOT NULL DEFAULT 'viewer',
            invited_email   CITEXT,
            invite_token    TEXT,
            invite_expires  TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (family_id, user_id)
        )
    """)
    op.execute("CREATE INDEX ON family_members (family_id)")

    op.execute("""
        CREATE TABLE family_relationships (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
            from_member_id  UUID NOT NULL REFERENCES family_members(id) ON DELETE CASCADE,
            to_member_id    UUID NOT NULL REFERENCES family_members(id) ON DELETE CASCADE,
            relation_type   TEXT NOT NULL,
            CHECK (from_member_id <> to_member_id),
            UNIQUE (from_member_id, to_member_id, relation_type)
        )
    """)

    # ---------------------------------------------------------------- documents
    op.execute("""
        CREATE TABLE documents (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
            uploaded_by     UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            title           TEXT NOT NULL,
            category        TEXT,
            category_conf   NUMERIC(4,3),
            mime_type       TEXT NOT NULL,
            size_bytes      BIGINT NOT NULL,
            sha256          TEXT NOT NULL,
            storage_key     TEXT NOT NULL,
            page_count      INT,
            status          doc_status NOT NULL DEFAULT 'uploaded',
            ocr_text        TEXT,
            error_message   TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ON documents (family_id, status)")
    op.execute("CREATE INDEX documents_text_trgm ON documents USING gin (ocr_text gin_trgm_ops)")

    op.execute("""
        CREATE TABLE document_versions (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            version_no      INT NOT NULL,
            storage_key     TEXT NOT NULL,
            sha256          TEXT NOT NULL,
            created_by      UUID REFERENCES users(id),
            note            TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (document_id, version_no)
        )
    """)

    op.execute("""
        CREATE TABLE document_chunks (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
            page_no         INT,
            chunk_index     INT NOT NULL,
            content         TEXT NOT NULL,
            embedding       vector(1024)
        )
    """)
    op.execute("CREATE INDEX ON document_chunks (family_id)")
    op.execute("CREATE INDEX document_chunks_vec ON document_chunks USING hnsw (embedding vector_cosine_ops)")

    # ------------------------------------------------- provenance
    op.execute("""
        CREATE TABLE extracted_fields (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
            document_id     UUID REFERENCES documents(id) ON DELETE CASCADE,
            subject_type    TEXT NOT NULL,
            subject_id      UUID,
            field_key       TEXT NOT NULL,
            field_value     TEXT,
            value_json      JSONB,
            data_type       TEXT NOT NULL DEFAULT 'string',
            confidence      NUMERIC(4,3),
            source          field_source NOT NULL DEFAULT 'ai_extracted',
            source_page     INT,
            source_snippet  TEXT,
            source_bbox     JSONB,
            verification    verify_status NOT NULL DEFAULT 'unverified',
            verified_by     UUID REFERENCES users(id),
            verified_at     TIMESTAMPTZ,
            model_name      TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ON extracted_fields (subject_type, subject_id)")
    op.execute("CREATE INDEX ON extracted_fields (document_id)")

    # ---------------------------------------------------------------- registry
    op.execute("""
        CREATE TABLE assets (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
            type            asset_type NOT NULL,
            name            TEXT NOT NULL,
            institution     TEXT,
            identifier_last4 TEXT,
            value_estimate  NUMERIC(18,2),
            value_currency  TEXT DEFAULT 'INR',
            value_as_of     DATE,
            verification    verify_status NOT NULL DEFAULT 'unverified',
            notes           TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ON assets (family_id, type)")

    op.execute("""
        CREATE TABLE properties (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
            label           TEXT NOT NULL,
            type            property_type NOT NULL,
            address_line    TEXT,
            village_locality TEXT,
            district        TEXT,
            state           TEXT,
            country         TEXT DEFAULT 'IN',
            pincode         TEXT,
            latitude        NUMERIC(9,6),
            longitude       NUMERIC(9,6),
            survey_number   TEXT,
            plot_number     TEXT,
            khata_number    TEXT,
            area_value      NUMERIC(14,4),
            area_unit       TEXT,
            recorded_holder TEXT,
            acquired_on     DATE,
            value_estimate  NUMERIC(18,2),
            value_as_of     DATE,
            verification    verify_status NOT NULL DEFAULT 'unverified',
            history_note    TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ON properties (family_id)")

    op.execute("""
        CREATE TABLE ownership_records (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
            member_id       UUID REFERENCES family_members(id) ON DELETE SET NULL,
            external_holder TEXT,
            subject_type    TEXT NOT NULL CHECK (subject_type IN ('asset','property')),
            subject_id      UUID NOT NULL,
            relationship    TEXT NOT NULL,
            share_percent   NUMERIC(6,3),
            valid_from      DATE,
            valid_to        DATE,
            provenance_note TEXT NOT NULL DEFAULT 'family-reported, not verified against official records',
            verification    verify_status NOT NULL DEFAULT 'unverified',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ON ownership_records (subject_type, subject_id)")

    op.execute("""
        CREATE TABLE links (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
            from_type       TEXT NOT NULL,
            from_id         UUID NOT NULL,
            to_type         TEXT NOT NULL,
            to_id           UUID NOT NULL,
            link_type       TEXT NOT NULL DEFAULT 'relates_to',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (from_type, from_id, to_type, to_id, link_type)
        )
    """)
    op.execute("CREATE INDEX ON links (family_id, from_type, from_id)")
    op.execute("CREATE INDEX ON links (family_id, to_type, to_id)")

    # ---------------------------------------------------------------- deadlines
    op.execute("""
        CREATE TABLE deadlines (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
            title           TEXT NOT NULL,
            description     TEXT,
            due_date        DATE NOT NULL,
            priority        priority_level NOT NULL DEFAULT 'medium',
            status          deadline_status NOT NULL DEFAULT 'open',
            recurrence_rule TEXT,
            source_type     TEXT,
            source_id       UUID,
            assigned_to     UUID REFERENCES family_members(id) ON DELETE SET NULL,
            completed_at    TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ON deadlines (family_id, status, due_date)")

    op.execute("""
        CREATE TABLE reminders (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            deadline_id     UUID NOT NULL REFERENCES deadlines(id) ON DELETE CASCADE,
            remind_at       TIMESTAMPTZ NOT NULL,
            channel         TEXT NOT NULL DEFAULT 'email',
            recipient_user  UUID REFERENCES users(id) ON DELETE CASCADE,
            delivery_status TEXT NOT NULL DEFAULT 'pending',
            attempts        INT NOT NULL DEFAULT 0,
            sent_at         TIMESTAMPTZ,
            error_message   TEXT
        )
    """)
    op.execute("CREATE INDEX ON reminders (remind_at) WHERE delivery_status = 'pending'")

    # ---------------------------------------------------------------- legacy
    op.execute("""
        CREATE TABLE legacy_entries (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
            author_member   UUID REFERENCES family_members(id) ON DELETE SET NULL,
            title           TEXT NOT NULL,
            body            TEXT,
            audio_key       TEXT,
            transcript      TEXT,
            about_type      TEXT,
            about_id        UUID,
            release_policy  TEXT NOT NULL DEFAULT 'immediate',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # ---------------------------------------------------------------- security
    op.execute("""
        CREATE TABLE permissions (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
            member_id       UUID NOT NULL REFERENCES family_members(id) ON DELETE CASCADE,
            resource_type   TEXT NOT NULL,
            resource_id     UUID,
            access          access_level NOT NULL,
            granted_by      UUID REFERENCES users(id),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (member_id, resource_type, resource_id)
        )
    """)

    op.execute("""
        CREATE TABLE audit_logs (
            id              BIGSERIAL PRIMARY KEY,
            family_id       UUID,
            actor_user_id   UUID,
            action          TEXT NOT NULL,
            resource_type   TEXT,
            resource_id     UUID,
            ip_address      INET,
            user_agent      TEXT,
            metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ON audit_logs (family_id, created_at DESC)")
    op.execute("CREATE INDEX ON audit_logs (resource_type, resource_id)")

    op.execute("""
        CREATE TABLE ai_conversations (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            family_id       UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            query           TEXT NOT NULL,
            answer          TEXT,
            retrieved_ids   JSONB NOT NULL DEFAULT '[]'::jsonb,
            refused         BOOLEAN NOT NULL DEFAULT FALSE,
            model_name      TEXT,
            latency_ms      INT,
            token_usage     JSONB,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # ---------------------------------------------------------------- DPDP compliance
    op.execute("""
        CREATE TABLE consents (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            purpose         TEXT NOT NULL,
            granted         BOOLEAN NOT NULL,
            notice_version  TEXT NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE data_requests (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind            TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'received',
            result_key      TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at    TIMESTAMPTZ
        )
    """)


def downgrade() -> None:
    # Drop in reverse dependency order.
    op.execute("DROP TABLE IF EXISTS data_requests CASCADE")
    op.execute("DROP TABLE IF EXISTS consents CASCADE")
    op.execute("DROP TABLE IF EXISTS ai_conversations CASCADE")
    op.execute("DROP TABLE IF EXISTS audit_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS permissions CASCADE")
    op.execute("DROP TABLE IF EXISTS legacy_entries CASCADE")
    op.execute("DROP TABLE IF EXISTS reminders CASCADE")
    op.execute("DROP TABLE IF EXISTS deadlines CASCADE")
    op.execute("DROP TABLE IF EXISTS links CASCADE")
    op.execute("DROP TABLE IF EXISTS ownership_records CASCADE")
    op.execute("DROP TABLE IF EXISTS properties CASCADE")
    op.execute("DROP TABLE IF EXISTS assets CASCADE")
    op.execute("DROP TABLE IF EXISTS extracted_fields CASCADE")
    op.execute("DROP TABLE IF EXISTS document_chunks CASCADE")
    op.execute("DROP TABLE IF EXISTS document_versions CASCADE")
    op.execute("DROP TABLE IF EXISTS documents CASCADE")
    op.execute("DROP TABLE IF EXISTS family_relationships CASCADE")
    op.execute("DROP TABLE IF EXISTS family_members CASCADE")
    op.execute("DROP TABLE IF EXISTS families CASCADE")
    op.execute("DROP TABLE IF EXISTS users CASCADE")

    op.execute("DROP TYPE IF EXISTS priority_level")
    op.execute("DROP TYPE IF EXISTS deadline_status")
    op.execute("DROP TYPE IF EXISTS property_type")
    op.execute("DROP TYPE IF EXISTS asset_type")
    op.execute("DROP TYPE IF EXISTS verify_status")
    op.execute("DROP TYPE IF EXISTS field_source")
    op.execute("DROP TYPE IF EXISTS doc_status")
    op.execute("DROP TYPE IF EXISTS access_level")
