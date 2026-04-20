"""create groups

Revision ID: 004_groups
Revises: 003_memberships
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "004_groups"
down_revision: Union[str, None] = "003_memberships"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE groups (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          group_code TEXT NOT NULL,
          max_capacity INTEGER,
          last_admin_lat DOUBLE PRECISION,
          last_admin_lng DOUBLE PRECISION,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (tenant_id, group_code)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS groups;")
