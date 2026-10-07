"""la cola de refuerzo personalizado y la identidad de las preguntas de los retos

Revision ID: 041_refuerzo
Revises: 040_foco_grupo
Create Date: 2026-10-06

Espec: docs/ESPEC_refuerzo.md §1.7.

Qué hace (`SQL_SUBIR`, idempotente):
  1. `challenge_questions` gana `item_ref` (el id del ítem en el banco: la
     IDENTIDAD de la pregunta), `family_ref` (su familia) y `form_role`
     (original, gemela o repaso). Nacen en NULL: los retos que ya existen no
     cambian.
  2. `reinforcement_queue`: una fila por `(institución, estudiante, nodo)`.
     Los CHECK atan el estado a sus fechas: `por_repasar` siempre tiene
     `next_due_at` y `superado` siempre tiene `mastered_at`.
  3. `reinforcement_answers`: lo que el estudiante respondió en el refuerzo.
     El UNIQUE `(queue_id, question_id)` es la idempotencia: gana la primera.
  4. RLS activo SIN políticas en las dos tablas nuevas.

Downgrade (`SQL_BAJAR`): borra las dos tablas, el índice y las tres columnas.
Se pierde la cola. En producción NO se baja.

`upgrade()` y `downgrade()` solo recorren estas tuplas: el test de
`tests/integ/test_migracion_041.py` ejecuta exactamente el mismo SQL.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "041_refuerzo"
down_revision: Union[str, None] = "040_foco_grupo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_SUBIR: tuple[str, ...] = (
    "ALTER TABLE challenge_questions ADD COLUMN IF NOT EXISTS item_ref TEXT;",
    "ALTER TABLE challenge_questions ADD COLUMN IF NOT EXISTS family_ref TEXT;",
    "ALTER TABLE challenge_questions ADD COLUMN IF NOT EXISTS form_role TEXT;",
    "ALTER TABLE challenge_questions DROP CONSTRAINT IF EXISTS challenge_questions_form_role_check;",
    """
    ALTER TABLE challenge_questions ADD CONSTRAINT challenge_questions_form_role_check
      CHECK (form_role IS NULL OR form_role IN ('original','gemela','repaso'));
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_challenge_questions_item_ref
      ON challenge_questions (item_ref) WHERE item_ref IS NOT NULL;
    """,
    """
    CREATE TABLE IF NOT EXISTS reinforcement_queue (
      id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      profile_id  UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      node_id     TEXT NOT NULL,
      status      TEXT NOT NULL DEFAULT 'en_refuerzo',
      hits        INTEGER NOT NULL DEFAULT 0,
      failures    INTEGER NOT NULL DEFAULT 1,
      reopened    INTEGER NOT NULL DEFAULT 0,
      family_ref  TEXT,
      origin      TEXT NOT NULL,
      origin_ref  TEXT NOT NULL,
      next_due_at TIMESTAMPTZ,
      mastered_at TIMESTAMPTZ,
      entered_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT reinforcement_queue_owner_node_key UNIQUE (tenant_id, profile_id, node_id),
      CONSTRAINT reinforcement_queue_status_check
        CHECK (status IN ('en_refuerzo','por_repasar','superado')),
      CONSTRAINT reinforcement_queue_origin_check CHECK (origin IN ('grader','reto')),
      CONSTRAINT reinforcement_queue_due_check
        CHECK ((status = 'por_repasar') = (next_due_at IS NOT NULL)),
      CONSTRAINT reinforcement_queue_mastered_check
        CHECK ((status = 'superado') = (mastered_at IS NOT NULL)),
      CONSTRAINT reinforcement_queue_counts_check
        CHECK (hits >= 0 AND failures >= 1 AND reopened >= 0)
    );
    """,
    "ALTER TABLE reinforcement_queue ENABLE ROW LEVEL SECURITY;",
    """
    CREATE TABLE IF NOT EXISTS reinforcement_answers (
      id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      queue_id     BIGINT NOT NULL REFERENCES reinforcement_queue(id) ON DELETE CASCADE,
      tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      profile_id   UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      question_id  UUID NOT NULL REFERENCES challenge_questions(id) ON DELETE CASCADE,
      form_key     TEXT NOT NULL,
      stage        TEXT NOT NULL,
      answer       TEXT NOT NULL,
      is_correct   BOOLEAN NOT NULL,
      status_after TEXT NOT NULL,
      due_after    TIMESTAMPTZ,
      answered_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT reinforcement_answers_queue_question_key UNIQUE (queue_id, question_id),
      CONSTRAINT reinforcement_answers_stage_check CHECK (stage IN ('refuerzo','repaso'))
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_reinforcement_answers_profile
      ON reinforcement_answers (tenant_id, profile_id);
    """,
    "ALTER TABLE reinforcement_answers ENABLE ROW LEVEL SECURITY;",
)

SQL_BAJAR: tuple[str, ...] = (
    "DROP TABLE IF EXISTS reinforcement_answers;",
    "DROP TABLE IF EXISTS reinforcement_queue;",
    "DROP INDEX IF EXISTS idx_challenge_questions_item_ref;",
    "ALTER TABLE challenge_questions DROP CONSTRAINT IF EXISTS challenge_questions_form_role_check;",
    "ALTER TABLE challenge_questions DROP COLUMN IF EXISTS form_role;",
    "ALTER TABLE challenge_questions DROP COLUMN IF EXISTS family_ref;",
    "ALTER TABLE challenge_questions DROP COLUMN IF EXISTS item_ref;",
)


def upgrade() -> None:
    for sql in SQL_SUBIR:
        op.execute(sql)


def downgrade() -> None:
    for sql in SQL_BAJAR:
        op.execute(sql)
