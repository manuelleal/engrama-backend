"""create shop_items

Revision ID: 017_shop_items
Revises: 016_improvement_plans
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "017_shop_items"
down_revision: Union[str, None] = "016_improvement_plans"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE shop_items (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL REFERENCES tenants(id),
          name TEXT NOT NULL,
          description TEXT,
          item_type TEXT NOT NULL DEFAULT 'reward',
          price_coins INTEGER NOT NULL CHECK (price_coins >= 0),
          stock INTEGER,
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS shop_items;")
