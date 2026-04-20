"""create auction_bids

Revision ID: 020_auction_bids
Revises: 019_auctions
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "020_auction_bids"
down_revision: Union[str, None] = "019_auctions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE auction_bids (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL REFERENCES tenants(id),
          auction_id UUID NOT NULL REFERENCES auctions(id) ON DELETE CASCADE,
          bidder_id UUID NOT NULL REFERENCES profiles(id),
          bid_amount INTEGER NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auction_bids;")
