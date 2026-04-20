"""create profiles

Revision ID: 002_profiles
Revises: 001_tenants
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "002_profiles"
down_revision: Union[str, None] = "001_tenants"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE profiles (
          id UUID PRIMARY KEY,
          documento_id TEXT NOT NULL UNIQUE,
          full_name TEXT NOT NULL,
          pin_hash TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'student'
            CHECK (role IN ('super_admin','admin','teacher','student')),
          current_streak INTEGER NOT NULL DEFAULT 0,
          longest_streak INTEGER NOT NULL DEFAULT 0,
          last_attendance_date DATE,
          xp INTEGER NOT NULL DEFAULT 0,
          level INTEGER NOT NULL DEFAULT 1,
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          account_locked BOOLEAN NOT NULL DEFAULT FALSE,
          force_password_reset BOOLEAN NOT NULL DEFAULT FALSE,
          last_login_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS profiles;")
