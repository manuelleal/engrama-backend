"""create question_bank

Revision ID: 013_question_bank
Revises: 012_challenge_attempts
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "013_question_bank"
down_revision: Union[str, None] = "012_challenge_attempts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE question_bank (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID REFERENCES tenants(id),
          module_type TEXT NOT NULL DEFAULT 'GENERAL',
          question_text TEXT NOT NULL DEFAULT '',
          options_json JSONB NOT NULL DEFAULT '[]',
          correct_answer TEXT,
          difficulty TEXT NOT NULL DEFAULT 'MEDIUM',
          cefr_level TEXT NOT NULL DEFAULT 'B1'
            CHECK (cefr_level IN ('A1','A1+','A2','A2+','B1-','B1','B1+','B2','B2+','C1','C1+')),
          pillar_type TEXT NOT NULL DEFAULT 'EXAM_PREP'
            CHECK (pillar_type IN ('CONTEXTUAL','EXAM_PREP','TECHNICAL')),
          exam_format TEXT NOT NULL DEFAULT 'NONE'
            CHECK (exam_format IN ('ICFES','IELTS','CAMBRIDGE_PET','TOEFL','NONE')),
          technical_domain TEXT NOT NULL DEFAULT 'NONE'
            CHECK (technical_domain IN ('SOFTWARE','MEDICINE','BUSINESS','NONE')),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS question_bank;")
