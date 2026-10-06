"""catálogo de nodos del mapa curricular (curriculum_nodes)

Revision ID: 038_catalogo_nodos
Revises: 037_eventos_anillo
Create Date: 2026-10-06

Espec: docs/ESPEC_catalogo_nodos.md §1.5.

Qué hace (`SQL_SUBIR`, idempotente):
  1. `curriculum_nodes`: una fila por nodo del mapa (`curriculo/nodos.json`).
     El `id` es texto OPACO: el backend no lo interpreta, solo lo compara.
     `replaced_by` apunta al nodo vigente cuando dos se fusionan: un nodo no
     se borra (decisión 012 §1), se marca "reemplazado por".
  2. RLS activo SIN políticas: ningún rol de cliente lee ni escribe; el
     catálogo sale solo por el backend.

No lleva `tenant_id`: el catálogo es el mismo para todas las instituciones y
no guarda datos de nadie. Lo llena la orden `python -m src.curriculo cargar`.

Downgrade (`SQL_BAJAR`): borra la tabla. El catálogo se recarga con la orden.

`upgrade()` y `downgrade()` solo recorren estas tuplas: el test de
`tests/integ/test_migracion_038.py` ejecuta exactamente el mismo SQL.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "038_catalogo_nodos"
down_revision: Union[str, None] = "037_eventos_anillo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_SUBIR: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS curriculum_nodes (
      id          TEXT PRIMARY KEY,
      kind        TEXT NOT NULL,
      level       TEXT NOT NULL,
      name_es     TEXT NOT NULL,
      replaced_by TEXT REFERENCES curriculum_nodes(id),
      map_version TEXT NOT NULL,
      loaded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT curriculum_nodes_id_check CHECK (char_length(id) BETWEEN 1 AND 128),
      CONSTRAINT curriculum_nodes_replaced_check
        CHECK (replaced_by IS NULL OR replaced_by <> id)
    );
    """,
    "ALTER TABLE curriculum_nodes ENABLE ROW LEVEL SECURITY;",
)

SQL_BAJAR: tuple[str, ...] = ("DROP TABLE IF EXISTS curriculum_nodes;",)


def upgrade() -> None:
    for sql in SQL_SUBIR:
        op.execute(sql)


def downgrade() -> None:
    for sql in SQL_BAJAR:
        op.execute(sql)
