"""eventos del anillo: el expediente (learning_events) y el nivel confirmado (confirmed_levels)

Revision ID: 037_eventos_anillo
Revises: 036_solicitudes_datos
Create Date: 2026-10-06

Espec: docs/ESPEC_eventos_anillo.md §1.9.

Qué hace (`SQL_SUBIR`, idempotente):
  1. `learning_events`: una fila por evento que entrega un satélite (EVA, SET).
     El UNIQUE `(tenant_id, event_id)` es la idempotencia: reenviar un lote no
     crea otra fila ni repite un efecto. Es de solo agregar; `effect` y
     `coins` dicen qué efecto tuvo, y se escriben en la misma transacción.
     El CHECK de `coins` impide una fila "acreditada" con 0 monedas, y al revés.
  2. `confirmed_levels`: el nivel MCER confirmado de una persona EN una
     institución. El CHECK de `source` no admite `live` ni `game`: ni un código
     roto puede guardar un nivel que venga del juego o de la clase en vivo.
  3. RLS activo SIN políticas en las dos: ningún rol de cliente lee ni escribe.

Downgrade (`SQL_BAJAR`): borra las dos tablas. Se pierden el expediente y los
niveles confirmados; las monedas ya acreditadas se quedan en `coin_ledger`.
En producción NO se baja: se restaura el respaldo.

`upgrade()` y `downgrade()` solo recorren estas tuplas: el test de
`tests/integ/test_migracion_037.py` ejecuta exactamente el mismo SQL.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "037_eventos_anillo"
down_revision: Union[str, None] = "036_solicitudes_datos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_SUBIR: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS learning_events (
      id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      event_id       TEXT NOT NULL,
      origin         TEXT NOT NULL,
      source         TEXT NOT NULL,
      type           TEXT NOT NULL,
      subject_id     UUID REFERENCES profiles(id) ON DELETE CASCADE,
      item_ref       TEXT,
      payload        JSONB NOT NULL,
      occurred_at    TIMESTAMPTZ NOT NULL,
      schema_version INTEGER NOT NULL,
      body_hash      TEXT NOT NULL,
      batch_id       TEXT NOT NULL,
      instance       TEXT NOT NULL,
      session_id     TEXT,
      effect         TEXT NOT NULL DEFAULT 'none',
      coins          INTEGER NOT NULL DEFAULT 0,
      received_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT learning_events_tenant_event_key UNIQUE (tenant_id, event_id),
      CONSTRAINT learning_events_event_id_check CHECK (char_length(event_id) BETWEEN 1 AND 256),
      CONSTRAINT learning_events_effect_check CHECK (effect IN
        ('none','coins_credited','pool_exhausted','session_cap_exceeded',
         'level_set','level_older')),
      CONSTRAINT learning_events_coins_check
        CHECK (coins >= 0 AND (coins = 0) = (effect <> 'coins_credited'))
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_learning_events_subject
      ON learning_events (tenant_id, subject_id, type);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_learning_events_session
      ON learning_events (tenant_id, session_id);
    """,
    "ALTER TABLE learning_events ENABLE ROW LEVEL SECURITY;",
    """
    CREATE TABLE IF NOT EXISTS confirmed_levels (
      id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      profile_id  UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      cefr        TEXT NOT NULL,
      source      TEXT NOT NULL,
      provisional BOOLEAN NOT NULL DEFAULT FALSE,
      score       INTEGER,
      assessed_at TIMESTAMPTZ NOT NULL,
      event_id    BIGINT REFERENCES learning_events(id) ON DELETE SET NULL,
      updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT confirmed_levels_tenant_profile_key UNIQUE (tenant_id, profile_id),
      CONSTRAINT confirmed_levels_cefr_check CHECK (cefr IN ('A1','A2','B1','B2','C1','C2')),
      CONSTRAINT confirmed_levels_source_check CHECK (source IN ('set','grader','teacher')),
      CONSTRAINT confirmed_levels_score_check CHECK (score IS NULL OR score BETWEEN 0 AND 100)
    );
    """,
    "ALTER TABLE confirmed_levels ENABLE ROW LEVEL SECURITY;",
)

SQL_BAJAR: tuple[str, ...] = (
    "DROP TABLE IF EXISTS confirmed_levels;",
    "DROP TABLE IF EXISTS learning_events;",
)


def upgrade() -> None:
    for sql in SQL_SUBIR:
        op.execute(sql)


def downgrade() -> None:
    for sql in SQL_BAJAR:
        op.execute(sql)
