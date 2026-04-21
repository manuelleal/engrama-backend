"""rls policies

Revision ID: 029_rls_policies
Revises: 028_enable_rls
Create Date: 2026-04-20

Aplica las políticas RLS definidas en SPECS/00b-rls-policies.md.

Estructura:
  1. Patrón base `tenant_isolation_select` + `tenant_isolation_insert`
     para las 19 tablas listadas en sección 1 del spec.
  2. Políticas especiales (secciones 2.1–2.8).

Nota sobre `question_bank`:
  El spec lo lista en sección 1 (patrón base) Y en sección 2.8 (política
  especial de SELECT que permite `tenant_id IS NULL` para preguntas
  globales). Ambas políticas coexisten sin conflicto: PostgreSQL combina
  políticas del mismo comando con OR, por lo que el resultado neto es
  "ves la fila si tu tenant coincide O si tenant_id es NULL", que es el
  comportamiento esperado del spec.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "029_rls_policies"
down_revision: Union[str, None] = "028_enable_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# -----------------------------------------------------------------------------
# Patrón base: tenant_isolation (SELECT + INSERT) para tablas transaccionales
# Ver sección 1 del spec.
# -----------------------------------------------------------------------------
_BASE_PATTERN_TABLES: list[str] = [
    "memberships",
    "groups",
    "teacher_groups",
    "attendance_sessions",
    "attendance",
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
    "badge_unlocks",
    "bets",
    "announcements",
    "ai_usage_logs",
]


def _base_select_sql(table: str) -> str:
    return f"""
        CREATE POLICY "tenant_isolation_select" ON {table}
          FOR SELECT TO authenticated
          USING (
            tenant_id IN (
              SELECT tenant_id FROM memberships
              WHERE profile_id = auth.uid()
                AND is_active = TRUE
            )
          );
    """


def _base_insert_sql(table: str) -> str:
    return f"""
        CREATE POLICY "tenant_isolation_insert" ON {table}
          FOR INSERT TO authenticated
          WITH CHECK (
            tenant_id IN (
              SELECT tenant_id FROM memberships
              WHERE profile_id = auth.uid()
                AND is_active = TRUE
            )
          );
    """


# -----------------------------------------------------------------------------
# challenge_questions NO tiene columna tenant_id (hereda por challenge_id).
# El spec lo lista en la sección 1 pero la tabla no tiene tenant_id directo.
# Revisa migración 011 — challenge_questions sólo tiene challenge_id FK.
# Redefinimos la política vía JOIN con challenges para ese caso puntual.
# -----------------------------------------------------------------------------
_CHALLENGE_QUESTIONS_SELECT = """
    CREATE POLICY "tenant_isolation_select" ON challenge_questions
      FOR SELECT TO authenticated
      USING (
        challenge_id IN (
          SELECT c.id FROM challenges c
          WHERE c.tenant_id IN (
            SELECT tenant_id FROM memberships
            WHERE profile_id = auth.uid()
              AND is_active = TRUE
          )
        )
      );
"""

_CHALLENGE_QUESTIONS_INSERT = """
    CREATE POLICY "tenant_isolation_insert" ON challenge_questions
      FOR INSERT TO authenticated
      WITH CHECK (
        challenge_id IN (
          SELECT c.id FROM challenges c
          WHERE c.tenant_id IN (
            SELECT tenant_id FROM memberships
            WHERE profile_id = auth.uid()
              AND is_active = TRUE
          )
        )
      );
"""


# -----------------------------------------------------------------------------
# Políticas especiales — sección 2 del spec. Una constante por SQL.
# -----------------------------------------------------------------------------

# 2.1 profiles
_PROFILES_SELECT_OWN = """
    CREATE POLICY "profiles_select_own" ON profiles
      FOR SELECT TO authenticated
      USING (id = auth.uid());
"""

_PROFILES_SELECT_TEACHER = """
    CREATE POLICY "profiles_select_teacher" ON profiles
      FOR SELECT TO authenticated
      USING (
        EXISTS (
          SELECT 1 FROM memberships m_teacher
          JOIN memberships m_student
            ON m_student.tenant_id = m_teacher.tenant_id
           AND m_student.group_code = m_teacher.group_code
          WHERE m_teacher.profile_id = auth.uid()
            AND m_teacher.role = 'teacher'
            AND m_student.profile_id = profiles.id
            AND m_teacher.is_active = TRUE
        )
      );
"""

_PROFILES_SELECT_ADMIN = """
    CREATE POLICY "profiles_select_admin" ON profiles
      FOR SELECT TO authenticated
      USING (
        EXISTS (
          SELECT 1 FROM memberships
          WHERE profile_id = auth.uid()
            AND role IN ('admin', 'super_admin')
            AND is_active = TRUE
        )
      );
"""

_PROFILES_UPDATE_OWN = """
    CREATE POLICY "profiles_update_own" ON profiles
      FOR UPDATE TO authenticated
      USING (id = auth.uid())
      WITH CHECK (id = auth.uid());
"""

# 2.2 tenants
_TENANTS_SELECT_ADMIN = """
    CREATE POLICY "tenants_select_admin" ON tenants
      FOR SELECT TO authenticated
      USING (
        id IN (
          SELECT tenant_id FROM memberships
          WHERE profile_id = auth.uid()
            AND role IN ('admin', 'super_admin')
            AND is_active = TRUE
        )
      );
"""

# 2.3 coin_wallets
_COIN_WALLETS_SELECT_OWN = """
    CREATE POLICY "coin_wallets_select_own" ON coin_wallets
      FOR SELECT TO authenticated
      USING (
        (owner_type = 'profile' AND owner_id = auth.uid())
        OR
        (
          tenant_id IN (
            SELECT tenant_id FROM memberships
            WHERE profile_id = auth.uid()
              AND role IN ('teacher', 'admin', 'super_admin')
              AND is_active = TRUE
          )
        )
      );
"""

# 2.4 coin_ledger
_COIN_LEDGER_SELECT_OWN = """
    CREATE POLICY "coin_ledger_select_own" ON coin_ledger
      FOR SELECT TO authenticated
      USING (
        from_wallet_id IN (
          SELECT id FROM coin_wallets
          WHERE owner_type = 'profile' AND owner_id = auth.uid()
        )
        OR
        to_wallet_id IN (
          SELECT id FROM coin_wallets
          WHERE owner_type = 'profile' AND owner_id = auth.uid()
        )
        OR
        tenant_id IN (
          SELECT tenant_id FROM memberships
          WHERE profile_id = auth.uid()
            AND role IN ('teacher', 'admin', 'super_admin')
            AND is_active = TRUE
        )
      );
"""

# 2.5 challenges
_CHALLENGES_SELECT_STUDENT = """
    CREATE POLICY "challenges_select_student" ON challenges
      FOR SELECT TO authenticated
      USING (
        status = 'active'
        AND tenant_id IN (
          SELECT tenant_id FROM memberships
          WHERE profile_id = auth.uid() AND is_active = TRUE
        )
        AND (
          group_id IS NULL
          OR
          group_id IN (
            SELECT g.id FROM groups g
            JOIN memberships m
              ON m.group_code = g.group_code
             AND m.tenant_id = g.tenant_id
            WHERE m.profile_id = auth.uid() AND m.is_active = TRUE
          )
        )
      );
"""

_CHALLENGES_SELECT_TEACHER = """
    CREATE POLICY "challenges_select_teacher" ON challenges
      FOR SELECT TO authenticated
      USING (
        tenant_id IN (
          SELECT tenant_id FROM memberships
          WHERE profile_id = auth.uid()
            AND role IN ('teacher', 'admin', 'super_admin')
            AND is_active = TRUE
        )
      );
"""

_CHALLENGES_INSERT_TEACHER = """
    CREATE POLICY "challenges_insert_teacher" ON challenges
      FOR INSERT TO authenticated
      WITH CHECK (
        tenant_id IN (
          SELECT tenant_id FROM memberships
          WHERE profile_id = auth.uid()
            AND role IN ('teacher', 'admin', 'super_admin')
            AND is_active = TRUE
        )
        AND created_by = auth.uid()
      );
"""

# 2.6 audit_logs
_AUDIT_LOGS_SELECT_STAFF = """
    CREATE POLICY "audit_logs_select_staff" ON audit_logs
      FOR SELECT TO authenticated
      USING (
        tenant_id IN (
          SELECT tenant_id FROM memberships
          WHERE profile_id = auth.uid()
            AND role IN ('teacher', 'admin', 'super_admin')
            AND is_active = TRUE
        )
      );
"""

# 2.7 badges
_BADGES_SELECT_ALL = """
    CREATE POLICY "badges_select_all" ON badges
      FOR SELECT TO authenticated
      USING (
        tenant_id IS NULL
        OR
        tenant_id IN (
          SELECT tenant_id FROM memberships
          WHERE profile_id = auth.uid() AND is_active = TRUE
        )
      );
"""

# 2.8 question_bank
_QUESTION_BANK_SELECT = """
    CREATE POLICY "question_bank_select" ON question_bank
      FOR SELECT TO authenticated
      USING (
        tenant_id IS NULL
        OR
        tenant_id IN (
          SELECT tenant_id FROM memberships
          WHERE profile_id = auth.uid() AND is_active = TRUE
        )
      );
"""


# -----------------------------------------------------------------------------
# Pares (tabla, nombre_politica) — usado por downgrade() para hacer DROP.
# -----------------------------------------------------------------------------
def _base_pattern_policies() -> list[tuple[str, str]]:
    """Devuelve (tabla, nombre_politica) para todas las tablas del patrón base."""
    out: list[tuple[str, str]] = []
    for table in _BASE_PATTERN_TABLES:
        out.append((table, "tenant_isolation_select"))
        out.append((table, "tenant_isolation_insert"))
    return out


_SPECIAL_POLICIES: list[tuple[str, str]] = [
    ("profiles", "profiles_select_own"),
    ("profiles", "profiles_select_teacher"),
    ("profiles", "profiles_select_admin"),
    ("profiles", "profiles_update_own"),
    ("tenants", "tenants_select_admin"),
    ("coin_wallets", "coin_wallets_select_own"),
    ("coin_ledger", "coin_ledger_select_own"),
    ("challenges", "challenges_select_student"),
    ("challenges", "challenges_select_teacher"),
    ("challenges", "challenges_insert_teacher"),
    ("audit_logs", "audit_logs_select_staff"),
    ("badges", "badges_select_all"),
    ("question_bank", "question_bank_select"),
]


# -----------------------------------------------------------------------------
# upgrade / downgrade
# -----------------------------------------------------------------------------
def upgrade() -> None:
    # 1. Patrón base para tablas con tenant_id directo
    for table in _BASE_PATTERN_TABLES:
        if table == "challenge_questions":
            # challenge_questions no tiene tenant_id directo; usamos JOIN.
            op.execute(_CHALLENGE_QUESTIONS_SELECT)
            op.execute(_CHALLENGE_QUESTIONS_INSERT)
        else:
            op.execute(_base_select_sql(table))
            op.execute(_base_insert_sql(table))

    # 2. Políticas especiales (sección 2.1–2.8)
    op.execute(_PROFILES_SELECT_OWN)
    op.execute(_PROFILES_SELECT_TEACHER)
    op.execute(_PROFILES_SELECT_ADMIN)
    op.execute(_PROFILES_UPDATE_OWN)
    op.execute(_TENANTS_SELECT_ADMIN)
    op.execute(_COIN_WALLETS_SELECT_OWN)
    op.execute(_COIN_LEDGER_SELECT_OWN)
    op.execute(_CHALLENGES_SELECT_STUDENT)
    op.execute(_CHALLENGES_SELECT_TEACHER)
    op.execute(_CHALLENGES_INSERT_TEACHER)
    op.execute(_AUDIT_LOGS_SELECT_STAFF)
    op.execute(_BADGES_SELECT_ALL)
    op.execute(_QUESTION_BANK_SELECT)


def downgrade() -> None:
    # DROP en orden inverso: primero las especiales, luego las base.
    for table, policy in reversed(_SPECIAL_POLICIES):
        op.execute(f'DROP POLICY IF EXISTS "{policy}" ON {table};')

    for table, policy in reversed(_base_pattern_policies()):
        op.execute(f'DROP POLICY IF EXISTS "{policy}" ON {table};')
