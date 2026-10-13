"""el nivel de práctica y las tandas del día

Revision ID: 043_practica_y_tanda
Revises: 042_racha_semanal
Create Date: 2026-10-12

Espec: docs/ESPEC_practica_y_tanda.md §1.3 (dictamen pedagógico 04 §1.3).

Qué hace (`SQL_SUBIR`, idempotente y ADITIVA):
  1. `practice_levels`: el nivel de PRÁCTICA por `(institución, estudiante)`.
     No es el nivel del estudiante: `confirmed_levels` no se toca. `ancla` es
     el nivel de SET con el que se fijó (o NULL si no había).
  2. `practice_tandas`: cada tanda servida, por día. `nivel_agotado` es el
     hueco de contenido; `repaso_desde` marca qué respuestas del repaso son
     de esta tanda.
  3. RLS activo SIN políticas en las dos.

Downgrade (`SQL_BAJAR`): borra las dos tablas. En producción NO se baja.

`upgrade()` y `downgrade()` solo recorren estas tuplas: el test de
`tests/integ/test_migracion_043.py` ejecuta exactamente el mismo SQL.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "043_practica_y_tanda"
down_revision: Union[str, None] = "042_racha_semanal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_SUBIR: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS practice_levels (
      id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      profile_id    UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      nivel         TEXT NOT NULL,
      ancla         TEXT,
      decisiones    INTEGER NOT NULL DEFAULT 0,
      ventana_desde TIMESTAMPTZ NOT NULL DEFAULT now(),
      created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT practice_levels_owner_key UNIQUE (tenant_id, profile_id),
      CONSTRAINT practice_levels_nivel_check CHECK (nivel IN ('A1','A2','B1','B2','C1')),
      CONSTRAINT practice_levels_ancla_check
        CHECK (ancla IS NULL OR ancla IN ('A1','A2','B1','B2','C1')),
      CONSTRAINT practice_levels_decisiones_check CHECK (decisiones >= 0)
    );
    """,
    "ALTER TABLE practice_levels ENABLE ROW LEVEL SECURITY;",
    """
    CREATE TABLE IF NOT EXISTS practice_tandas (
      id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      profile_id    UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      local_date    DATE NOT NULL,
      numero        INTEGER NOT NULL,
      modo          TEXT NOT NULL,
      nivel         TEXT NOT NULL,
      nivel_agotado TEXT,
      retos         UUID[] NOT NULL DEFAULT '{}',
      repasos       BIGINT[] NOT NULL DEFAULT '{}',
      repaso_desde  BIGINT NOT NULL DEFAULT 0,
      preguntas     INTEGER NOT NULL DEFAULT 0,
      created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT practice_tandas_owner_date_numero_key
        UNIQUE (tenant_id, profile_id, local_date, numero),
      CONSTRAINT practice_tandas_modo_check
        CHECK (modo IN ('nuevo','segunda_vuelta','repetir')),
      CONSTRAINT practice_tandas_numero_check CHECK (numero >= 1 AND preguntas >= 0)
    );
    """,
    "ALTER TABLE practice_tandas ENABLE ROW LEVEL SECURITY;",
)

SQL_BAJAR: tuple[str, ...] = (
    "DROP TABLE IF EXISTS practice_tandas;",
    "DROP TABLE IF EXISTS practice_levels;",
)


def upgrade() -> None:
    for sql in SQL_SUBIR:
        op.execute(sql)


def downgrade() -> None:
    for sql in SQL_BAJAR:
        op.execute(sql)
