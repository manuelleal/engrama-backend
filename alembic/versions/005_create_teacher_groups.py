"""create teacher_groups

Revision ID: 005_teacher_groups
Revises: 004_groups
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "005_teacher_groups"
down_revision: Union[str, None] = "004_groups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE teacher_groups (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL REFERENCES tenants(id),
          teacher_id UUID NOT NULL REFERENCES profiles(id),
          group_id UUID NOT NULL REFERENCES groups(id),
          assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (teacher_id, group_id)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS teacher_groups;")
