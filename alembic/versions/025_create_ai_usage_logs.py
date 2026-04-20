"""create ai_usage_logs

Revision ID: 025_ai_usage_logs
Revises: 024_announcements
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "025_ai_usage_logs"
down_revision: Union[str, None] = "024_announcements"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ai_usage_logs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL REFERENCES tenants(id),
          user_id UUID REFERENCES profiles(id),
          provider TEXT,
          model TEXT,
          tokens_used INTEGER NOT NULL DEFAULT 0,
          credits_charged INTEGER NOT NULL DEFAULT 0,
          cefr_level TEXT,
          skill TEXT,
          topic TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_usage_logs;")
