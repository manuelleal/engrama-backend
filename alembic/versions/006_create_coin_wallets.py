"""create coin_wallets

Revision ID: 006_coin_wallets
Revises: 005_teacher_groups
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "006_coin_wallets"
down_revision: Union[str, None] = "005_teacher_groups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE coin_wallets (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID REFERENCES tenants(id),
          owner_type TEXT NOT NULL CHECK (owner_type IN ('system','tenant','profile')),
          owner_id UUID NOT NULL,
          currency TEXT NOT NULL DEFAULT 'COIN',
          balance BIGINT NOT NULL DEFAULT 0 CHECK (balance >= 0),
          metadata JSONB NOT NULL DEFAULT '{}',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (owner_type, owner_id, currency)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS coin_wallets;")
