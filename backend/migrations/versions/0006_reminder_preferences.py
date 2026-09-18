"""add notification_preferences and reminder_deliveries with unique constraint

Revision ID: 0006_reminder_preferences
Revises: 0005_jobs_table
Create Date: 2026-09-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_reminder_preferences"
down_revision: Union[str, None] = "0005_jobs_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. User notification preferences
    op.execute("""
        CREATE TABLE notification_preferences (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id            UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,
            channels           JSONB NOT NULL DEFAULT '["email"]'::jsonb,
            send_hour          INT NOT NULL DEFAULT 9 CHECK (send_hour >= 0 AND send_hour <= 23),
            timezone           TEXT NOT NULL DEFAULT 'Asia/Kolkata',
            muted_categories   JSONB NOT NULL DEFAULT '[]'::jsonb,
            weekly_digest      BOOLEAN NOT NULL DEFAULT FALSE,
            digest_day         INT NOT NULL DEFAULT 0 CHECK (digest_day >= 0 AND digest_day <= 6),
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_notif_pref_user ON notification_preferences (user_id)")

    # 2. Reminder deliveries table with UNIQUE constraint to enforce exactly-once delivery
    op.execute("""
        CREATE TABLE reminder_deliveries (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            reminder_id     UUID NOT NULL UNIQUE REFERENCES reminders(id) ON DELETE CASCADE,
            deadline_id     UUID NOT NULL REFERENCES deadlines(id) ON DELETE CASCADE,
            recipient_user  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            channel         TEXT NOT NULL DEFAULT 'email',
            sent_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_reminder_deliv_user_sent ON reminder_deliveries (recipient_user, sent_at)")

    # 3. Unique constraint on reminders to prevent duplicate scheduling
    op.execute("""
        CREATE UNIQUE INDEX idx_reminders_unique_schedule
        ON reminders (deadline_id, recipient_user, remind_at, channel)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_reminders_unique_schedule CASCADE")
    op.execute("DROP TABLE IF EXISTS reminder_deliveries CASCADE")
    op.execute("DROP TABLE IF EXISTS notification_preferences CASCADE")
