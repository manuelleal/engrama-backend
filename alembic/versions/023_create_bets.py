"""create bets

Revision ID: 023_bets
Revises: 022_badge_unlocks
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "023_bets"
down_revision: Union[str, None] = "022_badge_unlocks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE bets (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          tenant_id UUID NOT NULL REFERENCES tenants(id),
          challenger_id UUID NOT NULL REFERENCES profiles(id),
          opponent_id UUID NOT NULL REFERENCES profiles(id),
          challenge_id UUID REFERENCES challenges(id),
          stake_coins INTEGER NOT NULL CHECK (stake_coins > 0),
          status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending','accepted','in_progress','completed','cancelled')),
          winner_id UUID REFERENCES profiles(id),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          resolved_at TIMESTAMPTZ
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bets;")
