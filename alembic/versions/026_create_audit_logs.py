"""create audit_logs

Revision ID: 026_audit_logs
Revises: 025_ai_usage_logs
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "026_audit_logs"
down_revision: Union[str, None] = "025_ai_usage_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE audit_logs (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID REFERENCES tenants(id),
          user_id UUID REFERENCES profiles(id),
          action_type TEXT NOT NULL,
          result TEXT,
          metadata JSONB NOT NULL DEFAULT '{}',
          ip_address TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_logs;")
