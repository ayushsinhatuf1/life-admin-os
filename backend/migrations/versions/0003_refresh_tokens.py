"""add refresh_tokens table

Revision ID: 0003_refresh_tokens
Revises: 0002_template
Create Date: 2026-09-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_refresh_tokens"
down_revision: Union[str, None] = "0002_template"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE refresh_tokens (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash      TEXT NOT NULL UNIQUE,
            expires_at      TIMESTAMPTZ NOT NULL,
            revoked_at      TIMESTAMPTZ,
            user_agent      TEXT,
            ip_address      INET,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ON refresh_tokens (user_id)")
    op.execute("CREATE INDEX ON refresh_tokens (token_hash)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS refresh_tokens CASCADE")
