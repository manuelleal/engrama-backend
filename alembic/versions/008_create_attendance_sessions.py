"""create attendance_sessions

Revision ID: 008_attendance_sessions
Revises: 007_coin_ledger
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "008_attendance_sessions"
down_revision: Union[str, None] = "007_coin_ledger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE attendance_sessions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL REFERENCES tenants(id),
          group_id UUID NOT NULL REFERENCES groups(id),
          session_code TEXT NOT NULL UNIQUE,
          qr_payload JSONB,
          admin_lat DOUBLE PRECISION,
          admin_lng DOUBLE PRECISION,
          starts_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          expires_at TIMESTAMPTZ NOT NULL,
          created_by UUID NOT NULL REFERENCES profiles(id),
          status TEXT NOT NULL DEFAULT 'active'
            CHECK (status IN ('active','expired','cancelled')),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS attendance_sessions;")
