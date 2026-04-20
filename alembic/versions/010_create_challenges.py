"""create challenges

Revision ID: 010_challenges
Revises: 009_attendance
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "010_challenges"
down_revision: Union[str, None] = "009_attendance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE challenges (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL REFERENCES tenants(id),
          group_id UUID REFERENCES groups(id),
          created_by UUID NOT NULL REFERENCES profiles(id),
          title TEXT NOT NULL,
          description TEXT NOT NULL,
          challenge_type TEXT NOT NULL DEFAULT 'multiple_choice'
            CHECK (challenge_type IN ('multiple_choice','open','fill_blank','listening')),
          cefr_level TEXT
            CHECK (cefr_level IN ('A1','A1+','A2','A2+','B1-','B1','B1+','B2','B2+','C1','C1+')),
          skill TEXT,
          topic TEXT,
          specific_instructions TEXT,
          coins_reward INTEGER NOT NULL DEFAULT 10,
          xp_reward INTEGER NOT NULL DEFAULT 10,
          max_attempts INTEGER NOT NULL DEFAULT 2,
          max_winners INTEGER NOT NULL DEFAULT 10,
          current_winners INTEGER NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'active'
            CHECK (status IN ('active','inactive','archived')),
          question_payload JSONB,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS challenges;")
