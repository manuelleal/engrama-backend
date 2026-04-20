"""create announcements

Revision ID: 024_announcements
Revises: 023_bets
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "024_announcements"
down_revision: Union[str, None] = "023_bets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE announcements (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID REFERENCES tenants(id),
          title TEXT,
          message TEXT NOT NULL,
          alert_type TEXT NOT NULL DEFAULT 'info'
            CHECK (alert_type IN ('info','warning','success','error')),
          target_group TEXT,
          links JSONB,
          expiry_date DATE NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS announcements;")
