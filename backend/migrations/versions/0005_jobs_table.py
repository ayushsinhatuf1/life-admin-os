"""add jobs table for durable Postgres-backed queue

Revision ID: 0005_jobs_table
Revises: 0004_invite_token_hash
Create Date: 2026-09-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_jobs_table"
down_revision: Union[str, None] = "0004_invite_token_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE jobs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            kind            TEXT NOT NULL,
            payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
            status          TEXT NOT NULL DEFAULT 'pending',
            attempts        INT NOT NULL DEFAULT 0,
            max_attempts    INT NOT NULL DEFAULT 3,
            run_after       TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_error      TEXT,
            locked_by       TEXT,
            locked_at       TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at    TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_jobs_poll ON jobs (run_after) WHERE status = 'pending'")
    op.execute("CREATE INDEX idx_jobs_status ON jobs (status)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS jobs CASCADE")
