"""create challenge_questions

Revision ID: 011_challenge_questions
Revises: 010_challenges
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "011_challenge_questions"
down_revision: Union[str, None] = "010_challenges"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE challenge_questions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          challenge_id UUID NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
          question_type TEXT NOT NULL DEFAULT 'multiple_choice',
          question_text TEXT NOT NULL,
          options_json JSONB,
          correct_answer TEXT,
          order_index INTEGER NOT NULL DEFAULT 1,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS challenge_questions;")
