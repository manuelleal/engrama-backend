"""create memberships

Revision ID: 003_memberships
Revises: 002_profiles
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "003_memberships"
down_revision: Union[str, None] = "002_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE memberships (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
          group_code TEXT,
          role TEXT NOT NULL DEFAULT 'student'
            CHECK (role IN ('admin','teacher','student')),
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (tenant_id, profile_id)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS memberships;")
