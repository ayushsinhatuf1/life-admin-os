"""add events table for product analytics

Revision ID: 0007_events_analytics
Revises: 0006_reminder_preferences
Create Date: 2026-09-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_events_analytics"
down_revision: Union[str, None] = "0006_reminder_preferences"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE events (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_name      TEXT NOT NULL,
            family_id       UUID REFERENCES families(id) ON DELETE CASCADE,
            user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
            properties      JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_events_name_created ON events (event_name, created_at)")
    op.execute("CREATE INDEX idx_events_family ON events (family_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS events CASCADE")
