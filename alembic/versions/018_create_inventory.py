"""create inventory

Revision ID: 018_inventory
Revises: 017_shop_items
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "018_inventory"
down_revision: Union[str, None] = "017_shop_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE inventory (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL REFERENCES tenants(id),
          student_id UUID NOT NULL REFERENCES profiles(id),
          item_id UUID NOT NULL REFERENCES shop_items(id),
          source TEXT NOT NULL DEFAULT 'shop'
            CHECK (source IN ('shop','auction','reward')),
          status TEXT NOT NULL DEFAULT 'available'
            CHECK (status IN ('available','pending_delivery','delivered','expired','archived')),
          purchased_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          activated_at TIMESTAMPTZ,
          expires_at TIMESTAMPTZ,
          resolved_by UUID REFERENCES profiles(id),
          resolved_at TIMESTAMPTZ
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS inventory;")
