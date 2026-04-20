"""create improvement_plans

Revision ID: 016_improvement_plans
Revises: 015_student_analytics
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "016_improvement_plans"
down_revision: Union[str, None] = "015_student_analytics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE improvement_plans (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL REFERENCES tenants(id),
          student_id UUID NOT NULL REFERENCES profiles(id),
          teacher_id UUID NOT NULL REFERENCES profiles(id),
          focus_topic TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'ASSIGNED'
            CHECK (status IN ('ASSIGNED','IN_PROGRESS','COMPLETED')),
          entry_cost_coins INTEGER NOT NULL DEFAULT 5,
          reward_coins INTEGER NOT NULL DEFAULT 50,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          completed_at TIMESTAMPTZ
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS improvement_plans;")
