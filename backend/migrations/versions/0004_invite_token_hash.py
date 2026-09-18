"""add invite_token_hash column and index to family_members

The existing invite_token column stores plaintext. For P1.3 we need a
secure hash-based invite flow. We add invite_token_hash alongside the
existing columns (invite_token, invite_expires) for backwards compatibility.

Revision ID: 0004_invite_token_hash
Revises: 0003_refresh_tokens
Create Date: 2026-09-18
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_invite_token_hash"
down_revision: Union[str, None] = "0003_refresh_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE family_members ADD COLUMN IF NOT EXISTS invite_token_hash TEXT")
    op.execute("ALTER TABLE family_members ADD COLUMN IF NOT EXISTS invite_accepted BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("CREATE INDEX IF NOT EXISTS idx_family_members_invite_hash ON family_members (invite_token_hash) WHERE invite_token_hash IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_family_members_invite_hash")
    op.execute("ALTER TABLE family_members DROP COLUMN IF EXISTS invite_accepted")
    op.execute("ALTER TABLE family_members DROP COLUMN IF EXISTS invite_token_hash")
