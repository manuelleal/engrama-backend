"""indexes (sección 3 del spec)

Revision ID: 027_indexes
Revises: 026_audit_logs
Create Date: 2026-04-19
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "027_indexes"
down_revision: Union[str, None] = "026_audit_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Lista de (nombre_indice, tabla, columnas) — espeja la sección 3 del spec.
_INDEXES: list[tuple[str, str, str]] = [
    ("idx_memberships_tenant_profile", "memberships", "(tenant_id, profile_id)"),
    ("idx_memberships_profile", "memberships", "(profile_id)"),
    ("idx_attendance_session", "attendance", "(session_id)"),
    ("idx_attendance_student", "attendance", "(student_id)"),
    ("idx_attendance_date", "attendance", "(attendance_date)"),
    ("idx_attempts_challenge", "challenge_attempts", "(challenge_id)"),
    ("idx_attempts_student", "challenge_attempts", "(student_id)"),
    ("idx_attempts_tenant", "challenge_attempts", "(tenant_id)"),
    ("idx_ledger_tenant", "coin_ledger", "(tenant_id)"),
    ("idx_ledger_from_wallet", "coin_ledger", "(from_wallet_id)"),
    ("idx_ledger_to_wallet", "coin_ledger", "(to_wallet_id)"),
    ("idx_ledger_created_at", "coin_ledger", "(created_at)"),
    ("idx_profiles_documento", "profiles", "(documento_id)"),
    ("idx_progress_student_skill", "student_progress", "(student_id, skill)"),
]


def upgrade() -> None:
    for name, table, cols in _INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {cols};")


def downgrade() -> None:
    for name, _table, _cols in reversed(_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name};")
