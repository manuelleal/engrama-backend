"""enable row level security en las 26 tablas

Revision ID: 028_enable_rls
Revises: 027_indexes
Create Date: 2026-04-19

Solo activa RLS (ENABLE ROW LEVEL SECURITY). NO crea políticas.
Las políticas concretas viven en SPECS/00b-rls-policies.md (pendiente)
y se aplicarán en migraciones posteriores (029+).

Consecuencia práctica: con RLS activo y sin políticas, los clientes con
JWT de usuario no ven nada. Las conexiones `service_role` (admin_session,
alembic, Celery) siguen pasando porque bypasean RLS — así los tests y
migraciones no se rompen.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "028_enable_rls"
down_revision: Union[str, None] = "027_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Orden de la sección 1 del spec (001–026).
_TABLES: list[str] = [
    "tenants",
    "profiles",
    "memberships",
    "groups",
    "teacher_groups",
    "coin_wallets",
    "coin_ledger",
    "attendance_sessions",
    "attendance",
    "challenges",
    "challenge_questions",
    "challenge_attempts",
    "question_bank",
    "student_progress",
    "student_analytics",
    "improvement_plans",
    "shop_items",
    "inventory",
    "auctions",
    "auction_bids",
    "badges",
    "badge_unlocks",
    "bets",
    "announcements",
    "ai_usage_logs",
    "audit_logs",
]


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
