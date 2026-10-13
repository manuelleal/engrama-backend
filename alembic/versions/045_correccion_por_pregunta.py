"""la corrección por pregunta: explicación, respuestas del intento y formas servidas

Revision ID: 045_correccion_por_pregunta
Revises: 044_solo_refuerzo
Create Date: 2026-10-13

Espec: docs/ESPEC_l1_correccion_por_pregunta.md §10.5 (dictamen pedagógico 04 §1.5).

Qué hace (`SQL_SUBIR`, idempotente y ADITIVA):
  1. `challenge_questions`: la explicación (`explanation`), las respuestas que
     también se aceptan (`accepted_answers`), la tolerancia de tipeo
     (`tolerance`, por defecto `exacta`) y la pista con inicial (`hint_initial`).
     Las preguntas que ya existen quedan sin explicación, exactas y sin pista.
  2. `challenge_attempts.served_questions`: las preguntas que se le sirvieron
     a ESE intento cuando no son las del reto (el reintento con gemelas).
  3. `challenge_attempt_answers`: una fila por `(intento, pregunta)`; gana la
     primera respuesta. Con institución y dueño, RLS activo y SIN políticas.

Downgrade (`SQL_BAJAR`): borra la tabla y las cinco columnas. En producción NO se baja.

`upgrade()` y `downgrade()` solo recorren estas tuplas: el test de
`tests/integ/test_migracion_045.py` ejecuta exactamente el mismo SQL.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "045_correccion_por_pregunta"
down_revision: Union[str, None] = "044_solo_refuerzo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_SUBIR: tuple[str, ...] = (
    "ALTER TABLE challenge_questions ADD COLUMN IF NOT EXISTS explanation JSONB;",
    "ALTER TABLE challenge_questions ADD COLUMN IF NOT EXISTS accepted_answers TEXT[];",
    "ALTER TABLE challenge_questions ADD COLUMN IF NOT EXISTS tolerance TEXT NOT NULL "
    "DEFAULT 'exacta';",
    "ALTER TABLE challenge_questions ADD COLUMN IF NOT EXISTS hint_initial BOOLEAN NOT NULL "
    "DEFAULT FALSE;",
    "ALTER TABLE challenge_questions DROP CONSTRAINT IF EXISTS "
    "challenge_questions_tolerance_check;",
    """
    ALTER TABLE challenge_questions ADD CONSTRAINT challenge_questions_tolerance_check
      CHECK (tolerance IN ('exacta','1_letra'));
    """,
    "ALTER TABLE challenge_attempts ADD COLUMN IF NOT EXISTS served_questions UUID[];",
    """
    CREATE TABLE IF NOT EXISTS challenge_attempt_answers (
      id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      attempt_id  UUID NOT NULL REFERENCES challenge_attempts(id) ON DELETE CASCADE,
      profile_id  UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      question_id UUID NOT NULL REFERENCES challenge_questions(id) ON DELETE CASCADE,
      answer      TEXT NOT NULL,
      is_correct  BOOLEAN NOT NULL,
      answered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT challenge_attempt_answers_attempt_question_key
        UNIQUE (attempt_id, question_id)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_challenge_attempt_answers_owner
      ON challenge_attempt_answers (tenant_id, profile_id);
    """,
    "ALTER TABLE challenge_attempt_answers ENABLE ROW LEVEL SECURITY;",
)

SQL_BAJAR: tuple[str, ...] = (
    "DROP TABLE IF EXISTS challenge_attempt_answers;",
    "ALTER TABLE challenge_attempts DROP COLUMN IF EXISTS served_questions;",
    "ALTER TABLE challenge_questions DROP CONSTRAINT IF EXISTS "
    "challenge_questions_tolerance_check;",
    "ALTER TABLE challenge_questions DROP COLUMN IF EXISTS hint_initial;",
    "ALTER TABLE challenge_questions DROP COLUMN IF EXISTS tolerance;",
    "ALTER TABLE challenge_questions DROP COLUMN IF EXISTS accepted_answers;",
    "ALTER TABLE challenge_questions DROP COLUMN IF EXISTS explanation;",
)


def upgrade() -> None:
    for sql in SQL_SUBIR:
        op.execute(sql)


def downgrade() -> None:
    for sql in SQL_BAJAR:
        op.execute(sql)
