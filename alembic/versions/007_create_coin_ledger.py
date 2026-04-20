"""create coin_ledger

Revision ID: 007_coin_ledger
Revises: 006_coin_wallets
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "007_coin_ledger"
down_revision: Union[str, None] = "006_coin_wallets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE coin_ledger (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL REFERENCES tenants(id),
          from_wallet_id UUID REFERENCES coin_wallets(id),
          to_wallet_id UUID REFERENCES coin_wallets(id),
          amount BIGINT NOT NULL CHECK (amount > 0),
          action TEXT NOT NULL,
          created_by_profile_id UUID REFERENCES profiles(id),
          metadata JSONB NOT NULL DEFAULT '{}',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS coin_ledger;")
