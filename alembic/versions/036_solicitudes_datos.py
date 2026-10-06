"""solicitudes_datos: el canal para ejercer los derechos sobre los datos personales (Ley 1581)

Revision ID: 036_solicitudes_datos
Revises: 035_autorregistro
Create Date: 2026-10-06

Espec: docs/ESPEC_solicitud_datos.md §1.7.

Una fila por solicitud (conocer, actualizar, rectificar o suprimir). El backend
SOLO registra y deja traza: quién pidió, qué, quién respondió y cuándo. No
ejecuta nada.

Qué hace (`SQL_SUBIR`, idempotente):
  1. Crea `solicitudes_datos`. Los CHECK repiten las reglas de la API: un tipo
     inventado o un mensaje de 1001 caracteres no entran ni aunque la API los
     dejara pasar.
  2. `profile_id ... ON DELETE SET NULL`: si el operador borra el perfil (una
     supresión atendida a mano), la solicitud se conserva sin la persona.
     Queda la prueba de que se atendió.
  3. `solicitudes_datos_traza_check`: solo una solicitud `abierta` puede estar
     sin respuesta y sin fecha de respuesta.
  4. RLS activo SIN políticas: ningún rol de cliente lee ni escribe.

Downgrade (`SQL_BAJAR`): borra la tabla, y con ella las solicitudes y su
traza. En producción NO se baja: se restaura el respaldo.

`upgrade()` y `downgrade()` solo recorren estas tuplas: el test de
`tests/integ/test_migracion_036.py` ejecuta exactamente el mismo SQL.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "036_solicitudes_datos"
down_revision: Union[str, None] = "035_autorregistro"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_SUBIR: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS solicitudes_datos (
      id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      profile_id     UUID REFERENCES profiles(id) ON DELETE SET NULL,
      tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      tipo           TEXT NOT NULL,
      mensaje        TEXT NOT NULL,
      estado         TEXT NOT NULL DEFAULT 'abierta',
      created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
      respuesta      TEXT,
      respondida_por UUID REFERENCES profiles(id) ON DELETE SET NULL,
      respondida_en  TIMESTAMPTZ,
      CONSTRAINT solicitudes_datos_tipo_check
        CHECK (tipo IN ('conocer','actualizar','rectificar','suprimir')),
      CONSTRAINT solicitudes_datos_estado_check
        CHECK (estado IN ('abierta','en_tramite','resuelta','rechazada')),
      CONSTRAINT solicitudes_datos_mensaje_check
        CHECK (char_length(mensaje) BETWEEN 1 AND 1000),
      CONSTRAINT solicitudes_datos_respuesta_check
        CHECK (respuesta IS NULL OR char_length(respuesta) BETWEEN 1 AND 1000),
      CONSTRAINT solicitudes_datos_traza_check
        CHECK ((estado = 'abierta') = (respondida_en IS NULL AND respuesta IS NULL))
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_solicitudes_datos_perfil ON solicitudes_datos (profile_id);",
    """
    CREATE INDEX IF NOT EXISTS idx_solicitudes_datos_tenant
      ON solicitudes_datos (tenant_id, estado);
    """,
    "ALTER TABLE solicitudes_datos ENABLE ROW LEVEL SECURITY;",
)

SQL_BAJAR: tuple[str, ...] = (
    "DROP TABLE IF EXISTS solicitudes_datos;",
)


def upgrade() -> None:
    for sql in SQL_SUBIR:
        op.execute(sql)


def downgrade() -> None:
    for sql in SQL_BAJAR:
        op.execute(sql)
