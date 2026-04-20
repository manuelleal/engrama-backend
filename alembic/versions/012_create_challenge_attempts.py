"""create challenge_attempts

Revision ID: 012_challenge_attempts
Revises: 011_challenge_questions
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "012_challenge_attempts"
down_revision: Union[str, None] = "011_challenge_questions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE challenge_attempts (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL REFERENCES tenants(id),
          challenge_id UUID NOT NULL REFERENCES challenges(id),
          student_id UUID NOT NULL REFERENCES profiles(id),
          status TEXT NOT NULL DEFAULT 'in_progress'
            CHECK (status IN ('in_progress','completed','abandoned')),
          current_question_index INTEGER NOT NULL DEFAULT 0,
          answers JSONB NOT NULL DEFAULT '[]',
          score_percent NUMERIC NOT NULL DEFAULT 0,
          is_correct BOOLEAN,
          coins_earned INTEGER NOT NULL DEFAULT 0,
          xp_earned INTEGER NOT NULL DEFAULT 0,
          streak_bonus INTEGER NOT NULL DEFAULT 0,
          weak_skills JSONB NOT NULL DEFAULT '[]',
          drako_feedback TEXT,
          started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          completed_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS challenge_attempts;")
