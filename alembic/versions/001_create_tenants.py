"""create tenants

Revision ID: 001_tenants
Revises: 000_ext
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "001_tenants"
down_revision: Union[str, None] = "000_ext"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenants (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          name TEXT NOT NULL,
          slug TEXT NOT NULL UNIQUE,
          subscription_plan TEXT NOT NULL DEFAULT 'BASIC'
            CHECK (subscription_plan IN ('BASIC','PRO','PREMIUM','ENTERPRISE')),
          ai_credit_pool INTEGER NOT NULL DEFAULT 10,
          ai_credits_used INTEGER NOT NULL DEFAULT 0,
          active_ai_provider TEXT NOT NULL DEFAULT 'claude'
            CHECK (active_ai_provider IN ('claude','chatgpt','gemini')),
          coin_pool INTEGER NOT NULL DEFAULT 0,
          is_suspended BOOLEAN NOT NULL DEFAULT FALSE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenants;")
