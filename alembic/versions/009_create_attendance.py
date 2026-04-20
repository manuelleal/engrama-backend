"""create attendance

Revision ID: 009_attendance
Revises: 008_attendance_sessions
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "009_attendance"
down_revision: Union[str, None] = "008_attendance_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE attendance (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL REFERENCES tenants(id),
          session_id UUID NOT NULL REFERENCES attendance_sessions(id),
          student_id UUID NOT NULL REFERENCES profiles(id),
          attendance_date DATE NOT NULL DEFAULT CURRENT_DATE,
          latitude NUMERIC,
          longitude NUMERIC,
          geo_status TEXT,
          coins_awarded INTEGER NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (session_id, student_id)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS attendance;")
