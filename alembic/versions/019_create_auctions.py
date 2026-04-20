"""create auctions

Revision ID: 019_auctions
Revises: 018_inventory
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "019_auctions"
down_revision: Union[str, None] = "018_inventory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE auctions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL REFERENCES tenants(id),
          group_id UUID REFERENCES groups(id),
          item_name TEXT NOT NULL,
          description TEXT,
          item_type TEXT NOT NULL DEFAULT 'auction',
          base_price INTEGER NOT NULL,
          current_bid INTEGER NOT NULL DEFAULT 0,
          highest_bidder_id UUID REFERENCES profiles(id),
          highest_bidder_name TEXT,
          winner_id UUID REFERENCES profiles(id),
          stock_quantity INTEGER NOT NULL DEFAULT 1,
          duration_seconds INTEGER NOT NULL DEFAULT 60,
          start_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          status TEXT NOT NULL DEFAULT 'active'
            CHECK (status IN ('active','ended','cancelled')),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auctions;")
