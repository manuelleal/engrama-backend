"""consentimientos: quién aceptó qué versión del aviso de datos (Ley 1581)

Revision ID: 034_consentimiento
Revises: 033_una_paga_por_reto
Create Date: 2026-10-06

Espec: docs/ESPEC_consentimiento.md §1.5.

Una fila por (perfil, versión del aviso). El consentimiento es de la PERSONA,
no de una institución: quien está en dos instituciones acepta una vez.

Qué hace (`SQL_SUBIR`, idempotente):
  1. Crea `consentimientos`. El `id` es una identidad creciente: "la última
     aceptada" se decide por `id`, no por `accepted_at`, porque la fecha
     depende del reloj de la base y un reloj puede retroceder.
  2. El UNIQUE (profile_id, version) hace idempotente repetir una versión.
  3. El CHECK repite la regla de la API (1 a 32 caracteres, sin espacios al
     borde): una versión vacía no entra ni aunque la API la dejara pasar.
  4. Activa RLS SIN políticas: ningún rol de cliente lee ni escribe. Además,
     por la 031, los clientes no reciben privilegios sobre tablas nuevas.
     El backend entra como `service_role`.

No guarda IP ni dispositivo (dato mínimo).

Downgrade (`SQL_BAJAR`): borra la tabla, y con ella el historial de
aceptaciones. En producción NO se baja: se restaura el respaldo.

`upgrade()` y `downgrade()` solo recorren estas tuplas: el test de
`tests/integ/test_migracion_034.py` ejecuta exactamente el mismo SQL.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "034_consentimiento"
down_revision: Union[str, None] = "033_una_paga_por_reto"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_SUBIR: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS consentimientos (
      id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      profile_id  UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      version     TEXT NOT NULL,
      accepted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT consentimientos_perfil_version UNIQUE (profile_id, version),
      CONSTRAINT consentimientos_version_check
        CHECK (char_length(version) BETWEEN 1 AND 32 AND version = btrim(version))
    );
    """,
    "ALTER TABLE consentimientos ENABLE ROW LEVEL SECURITY;",
)

SQL_BAJAR: tuple[str, ...] = (
    "DROP TABLE IF EXISTS consentimientos;",
)


def upgrade() -> None:
    for sql in SQL_SUBIR:
        op.execute(sql)


def downgrade() -> None:
    for sql in SQL_BAJAR:
        op.execute(sql)
