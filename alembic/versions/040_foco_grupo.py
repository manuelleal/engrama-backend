"""el foco del grupo y las etiquetas de nodo de las preguntas de los retos

Revision ID: 040_foco_grupo
Revises: 039_grader
Create Date: 2026-10-06

Espec: docs/ESPEC_foco_grupo.md §1.5.

Qué hace (`SQL_SUBIR`, idempotente):
  1. `challenge_questions.nodes TEXT[]`: los nodos del mapa que practica cada
     pregunta (ids vigentes del catálogo). Nace vacío: los retos que ya
     existen no cambian. El índice GIN sirve la consulta "retos con algún
     nodo del foco".
  2. `group_focus`: un periodo del foco de un grupo, uno por `(grupo, día en
     que empieza)`, con a lo sumo 62 días y de 1 a 12 nodos. Que dos periodos
     del mismo grupo no se solapen lo exige el backend con un candado.
  3. RLS activo SIN políticas en `group_focus`. `challenge_questions` conserva
     las suyas.

Downgrade (`SQL_BAJAR`): borra `group_focus`, el índice y la columna. Se
pierden las etiquetas y los focos. En producción NO se baja.

`upgrade()` y `downgrade()` solo recorren estas tuplas: el test de
`tests/integ/test_migracion_040.py` ejecuta exactamente el mismo SQL.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "040_foco_grupo"
down_revision: Union[str, None] = "039_grader"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_SUBIR: tuple[str, ...] = (
    """
    ALTER TABLE challenge_questions
      ADD COLUMN IF NOT EXISTS nodes TEXT[] NOT NULL DEFAULT '{}';
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_challenge_questions_nodes
      ON challenge_questions USING GIN (nodes);
    """,
    """
    CREATE TABLE IF NOT EXISTS group_focus (
      id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      group_id   UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
      starts_on  DATE NOT NULL,
      ends_on    DATE NOT NULL,
      nodes      TEXT[] NOT NULL,
      set_by     UUID NOT NULL REFERENCES profiles(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT group_focus_group_start_key UNIQUE (group_id, starts_on),
      CONSTRAINT group_focus_dates_check
        CHECK (ends_on >= starts_on AND ends_on - starts_on <= 62),
      CONSTRAINT group_focus_nodes_check CHECK (cardinality(nodes) BETWEEN 1 AND 12)
    );
    """,
    "ALTER TABLE group_focus ENABLE ROW LEVEL SECURITY;",
)

SQL_BAJAR: tuple[str, ...] = (
    "DROP TABLE IF EXISTS group_focus;",
    "DROP INDEX IF EXISTS idx_challenge_questions_nodes;",
    "ALTER TABLE challenge_questions DROP COLUMN IF EXISTS nodes;",
)


def upgrade() -> None:
    for sql in SQL_SUBIR:
        op.execute(sql)


def downgrade() -> None:
    for sql in SQL_BAJAR:
        op.execute(sql)
