"""create student_analytics

Revision ID: 015_student_analytics
Revises: 014_student_progress
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "015_student_analytics"
down_revision: Union[str, None] = "014_student_progress"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE student_analytics (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL REFERENCES tenants(id),
          student_id UUID NOT NULL REFERENCES profiles(id),
          topic TEXT NOT NULL,
          time_spent_seconds INTEGER NOT NULL DEFAULT 0,
          failed_attempts INTEGER NOT NULL DEFAULT 0,
          success_rate NUMERIC NOT NULL DEFAULT 0.0,
          last_assessed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS student_analytics;")
