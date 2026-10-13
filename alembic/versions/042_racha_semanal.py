"""la racha semanal por institución: días activos y estado de la racha

Revision ID: 042_racha_semanal
Revises: 041_refuerzo
Create Date: 2026-10-12

Espec: docs/ESPEC_racha_semanal.md §1.4 (dictamen pedagógico 04 §1.1).

Qué hace (`SQL_SUBIR`, idempotente y ADITIVA: no toca ningún dato existente):
  1. `activity_days`: una fila por `(institución, estudiante, día local)`.
     `preguntas` recuerda cada pregunta respondida ese día con su mejor
     resultado (cada una cuenta una vez); `primeras_correctas` y `por_origen`
     son datos de vigilancia.
  2. `streak_state`: una fila por `(institución, estudiante)`. Cierra BUG-12:
     la racha deja de ser global del perfil.
  3. RLS activo SIN políticas en las dos (los clientes no entran directo, 031).

`profiles.current_streak` NO se toca: el check-in la sigue moviendo.

Downgrade (`SQL_BAJAR`): borra las dos tablas. Se pierde la racha semanal. En
producción NO se baja.

`upgrade()` y `downgrade()` solo recorren estas tuplas: el test de
`tests/integ/test_migracion_042.py` ejecuta exactamente el mismo SQL.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "042_racha_semanal"
down_revision: Union[str, None] = "041_refuerzo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_SUBIR: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS activity_days (
      id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      tenant_id          UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      profile_id         UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      local_date         DATE NOT NULL,
      via_asistencia     BOOLEAN NOT NULL DEFAULT FALSE,
      respuestas         INTEGER NOT NULL DEFAULT 0,
      correctas          INTEGER NOT NULL DEFAULT 0,
      primeras_correctas INTEGER NOT NULL DEFAULT 0,
      activo             BOOLEAN NOT NULL DEFAULT FALSE,
      preguntas          JSONB NOT NULL DEFAULT '{}'::jsonb,
      por_origen         JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT activity_days_owner_date_key UNIQUE (tenant_id, profile_id, local_date),
      CONSTRAINT activity_days_counts_check
        CHECK (respuestas >= 0 AND correctas >= 0 AND primeras_correctas >= 0
               AND correctas <= respuestas AND primeras_correctas <= correctas)
    );
    """,
    "ALTER TABLE activity_days ENABLE ROW LEVEL SECURITY;",
    """
    CREATE TABLE IF NOT EXISTS streak_state (
      id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      tenant_id             UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      profile_id            UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      racha_semanas         INTEGER NOT NULL DEFAULT 0,
      mejor_racha           INTEGER NOT NULL DEFAULT 0,
      semanas_cumplidas     INTEGER NOT NULL DEFAULT 0,
      protectores           INTEGER NOT NULL DEFAULT 0,
      ultima_semana_cerrada DATE NOT NULL,
      created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT streak_state_owner_key UNIQUE (tenant_id, profile_id),
      CONSTRAINT streak_state_counts_check
        CHECK (racha_semanas >= 0 AND mejor_racha >= racha_semanas
               AND semanas_cumplidas >= 0 AND protectores BETWEEN 0 AND 10)
    );
    """,
    "ALTER TABLE streak_state ENABLE ROW LEVEL SECURITY;",
)

SQL_BAJAR: tuple[str, ...] = (
    "DROP TABLE IF EXISTS streak_state;",
    "DROP TABLE IF EXISTS activity_days;",
)


def upgrade() -> None:
    for sql in SQL_SUBIR:
        op.execute(sql)


def downgrade() -> None:
    for sql in SQL_BAJAR:
        op.execute(sql)
