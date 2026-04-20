"""create student_progress

Revision ID: 014_student_progress
Revises: 013_question_bank
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "014_student_progress"
down_revision: Union[str, None] = "013_question_bank"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE student_progress (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL REFERENCES tenants(id),
          student_id UUID NOT NULL REFERENCES profiles(id),
          skill TEXT NOT NULL,
          cefr_level TEXT,
          total_attempts INTEGER NOT NULL DEFAULT 0,
          correct_attempts INTEGER NOT NULL DEFAULT 0,
          accuracy_percent NUMERIC NOT NULL DEFAULT 0,
          xp_total INTEGER NOT NULL DEFAULT 0,
          is_weak BOOLEAN NOT NULL DEFAULT FALSE,
          last_practiced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (tenant_id, student_id, skill)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS student_progress;")
