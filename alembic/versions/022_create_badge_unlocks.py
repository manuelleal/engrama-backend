"""create badge_unlocks

Revision ID: 022_badge_unlocks
Revises: 021_badges
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "022_badge_unlocks"
down_revision: Union[str, None] = "021_badges"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE badge_unlocks (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL REFERENCES tenants(id),
          student_id UUID NOT NULL REFERENCES profiles(id),
          badge_id UUID NOT NULL REFERENCES badges(id),
          unlocked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (student_id, badge_id)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS badge_unlocks;")
