"""la puerta del Grader: lista numerada, exámenes impresos y hojas calificadas por ítem

Revision ID: 039_grader
Revises: 038_catalogo_nodos
Create Date: 2026-10-06

Espec: docs/ESPEC_grader_anillo.md §1.5 y §9.4.

Qué hace (`SQL_SUBIR`, idempotente):
  1. `grader_list_numbers`: el número de lista de cada estudiante en un grupo.
     Estable y sin reutilizar: la fila de quien sale del grupo se queda.
  2. `grader_exams` + `grader_exam_items`: el examen impreso que registró el
     profe, con cada ítem y sus nodos del mapa (`nodos TEXT[]`). El UNIQUE
     `(tenant_id, codigo)` hace el registro idempotente, y deja que dos
     instituciones usen el mismo código sin verse.
  3. `grader_sheets` + `grader_sheet_items`: una hoja calificada por
     `(examen, numero)`; reenviarla REEMPLAZA. El CHECK de `estado` no admite
     `dudosa`, y `correcta` solo puede ser cierta en un ítem `marcada`.
  4. RLS activo SIN políticas en las cinco.

No guarda imágenes: no hay ninguna columna donde quepan.

Downgrade (`SQL_BAJAR`): borra las cinco. Se pierden los números de lista, los
exámenes y las hojas. En producción NO se baja: se restaura el respaldo.

`upgrade()` y `downgrade()` solo recorren estas tuplas: el test de
`tests/integ/test_migracion_039.py` ejecuta exactamente el mismo SQL.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "039_grader"
down_revision: Union[str, None] = "038_catalogo_nodos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_SUBIR: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS grader_list_numbers (
      id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      group_id    UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
      profile_id  UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      numero      INTEGER NOT NULL,
      assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT grader_list_numbers_group_numero_key UNIQUE (group_id, numero),
      CONSTRAINT grader_list_numbers_group_profile_key UNIQUE (group_id, profile_id),
      CONSTRAINT grader_list_numbers_numero_check CHECK (numero BETWEEN 1 AND 9999)
    );
    """,
    "ALTER TABLE grader_list_numbers ENABLE ROW LEVEL SECURITY;",
    """
    CREATE TABLE IF NOT EXISTS grader_exams (
      id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      group_id   UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
      codigo     TEXT NOT NULL,
      huella     TEXT NOT NULL,
      titulo     TEXT NOT NULL,
      nivel      TEXT NOT NULL,
      n_items    INTEGER NOT NULL,
      created_by UUID NOT NULL REFERENCES profiles(id),
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT grader_exams_tenant_codigo_key UNIQUE (tenant_id, codigo),
      CONSTRAINT grader_exams_huella_check CHECK (huella ~ '^[0-9a-f]{64}$'),
      CONSTRAINT grader_exams_n_items_check CHECK (n_items BETWEEN 1 AND 200)
    );
    """,
    "ALTER TABLE grader_exams ENABLE ROW LEVEL SECURITY;",
    """
    CREATE TABLE IF NOT EXISTS grader_exam_items (
      id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      exam_id        UUID NOT NULL REFERENCES grader_exams(id) ON DELETE CASCADE,
      posicion       INTEGER NOT NULL,
      item_id        TEXT NOT NULL,
      origen         TEXT NOT NULL,
      nivel          TEXT NOT NULL,
      destreza       TEXT NOT NULL,
      tema           TEXT NOT NULL,
      enunciado      TEXT NOT NULL,
      correcta_texto TEXT NOT NULL,
      explicacion    TEXT NOT NULL,
      nodos          TEXT[] NOT NULL DEFAULT '{}',
      CONSTRAINT grader_exam_items_exam_item_key UNIQUE (exam_id, item_id),
      CONSTRAINT grader_exam_items_origen_check CHECK (origen IN ('oficial','docente'))
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_grader_exam_items_nodos
      ON grader_exam_items USING GIN (nodos);
    """,
    "ALTER TABLE grader_exam_items ENABLE ROW LEVEL SECURITY;",
    """
    CREATE TABLE IF NOT EXISTS grader_sheets (
      id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      exam_id       UUID NOT NULL REFERENCES grader_exams(id) ON DELETE CASCADE,
      tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      profile_id    UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      numero        INTEGER NOT NULL,
      forma         TEXT NOT NULL,
      calificado_en TIMESTAMPTZ NOT NULL,
      aciertos      INTEGER NOT NULL,
      total         INTEGER NOT NULL,
      enviada_por   UUID NOT NULL REFERENCES profiles(id),
      recibida_en   TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT grader_sheets_exam_numero_key UNIQUE (exam_id, numero),
      CONSTRAINT grader_sheets_aciertos_check CHECK (aciertos BETWEEN 0 AND total)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_grader_sheets_profile
      ON grader_sheets (tenant_id, profile_id);
    """,
    "ALTER TABLE grader_sheets ENABLE ROW LEVEL SECURITY;",
    """
    CREATE TABLE IF NOT EXISTS grader_sheet_items (
      id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      sheet_id      UUID NOT NULL REFERENCES grader_sheets(id) ON DELETE CASCADE,
      item_id       TEXT NOT NULL,
      estado        TEXT NOT NULL,
      correcta      BOOLEAN NOT NULL,
      elegida_texto TEXT,
      resuelta_por  UUID REFERENCES profiles(id),
      CONSTRAINT grader_sheet_items_sheet_item_key UNIQUE (sheet_id, item_id),
      CONSTRAINT grader_sheet_items_estado_check
        CHECK (estado IN ('marcada','vacia','doble')),
      CONSTRAINT grader_sheet_items_correcta_check CHECK (NOT correcta OR estado = 'marcada')
    );
    """,
    "ALTER TABLE grader_sheet_items ENABLE ROW LEVEL SECURITY;",
)

SQL_BAJAR: tuple[str, ...] = (
    "DROP TABLE IF EXISTS grader_sheet_items;",
    "DROP TABLE IF EXISTS grader_sheets;",
    "DROP TABLE IF EXISTS grader_exam_items;",
    "DROP TABLE IF EXISTS grader_exams;",
    "DROP TABLE IF EXISTS grader_list_numbers;",
)


def upgrade() -> None:
    for sql in SQL_SUBIR:
        op.execute(sql)


def downgrade() -> None:
    for sql in SQL_BAJAR:
        op.execute(sql)
