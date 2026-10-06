"""autorregistro: códigos de inscripción por grupo y solicitudes pendientes

Revision ID: 035_autorregistro
Revises: 034_consentimiento
Create Date: 2026-10-06

Espec: docs/ESPEC_autorregistro.md §1.10.

Qué hace (`SQL_SUBIR`, idempotente):
  1. `codigos_inscripcion`: el código que el profe genera para un grupo. Solo
     se guarda su huella (HMAC-SHA256 en hexadecimal): el CHECK exige 64
     hexadecimales, así que el código en claro NO CABE en la columna.
     `usos BETWEEN 0 AND cupo` es la barrera del cupo en la base: ni un código
     roto de la aplicación puede pasarse. Un solo código activo por grupo
     (índice único parcial).
  2. `solicitudes_inscripcion`: quién pidió entrar con qué código.
     `creando` (el perfil existe, la cuenta todavía no), `pendiente` (espera
     al profe) o `aprobada`. No hay `rechazada`: rechazar BORRA el perfil y
     esta fila cae en cascada. El CHECK de `declaro_mayor_de_edad` impide una
     solicitud sin esa declaración.
  3. RLS activo y SIN políticas en las dos: ningún rol de cliente lee ni
     escribe (además, por la 031, no reciben privilegios sobre tablas nuevas).

No guarda correos, IP ni fecha de nacimiento.

Downgrade (`SQL_BAJAR`): borra las dos tablas. Se pierde quién aprobó a
quién; las membresías y las cuentas ya creadas no se tocan. En producción NO
se baja: se restaura el respaldo.

`upgrade()` y `downgrade()` solo recorren estas tuplas: el test de
`tests/integ/test_migracion_035.py` ejecuta exactamente el mismo SQL.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "035_autorregistro"
down_revision: Union[str, None] = "034_consentimiento"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_SUBIR: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS codigos_inscripcion (
      id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      group_id    UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
      codigo_hash TEXT NOT NULL,
      expires_at  TIMESTAMPTZ NOT NULL,
      cupo        INTEGER NOT NULL,
      usos        INTEGER NOT NULL DEFAULT 0,
      activo      BOOLEAN NOT NULL DEFAULT TRUE,
      created_by  UUID NOT NULL REFERENCES profiles(id),
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT codigos_inscripcion_hash_key UNIQUE (codigo_hash),
      CONSTRAINT codigos_inscripcion_hash_check CHECK (codigo_hash ~ '^[0-9a-f]{64}$'),
      CONSTRAINT codigos_inscripcion_cupo_check CHECK (cupo BETWEEN 1 AND 200),
      CONSTRAINT codigos_inscripcion_usos_check CHECK (usos BETWEEN 0 AND cupo)
    );
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS codigos_inscripcion_uno_activo
      ON codigos_inscripcion (group_id) WHERE activo;
    """,
    "ALTER TABLE codigos_inscripcion ENABLE ROW LEVEL SECURITY;",
    """
    CREATE TABLE IF NOT EXISTS solicitudes_inscripcion (
      id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      tenant_id             UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      group_id              UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
      codigo_id             BIGINT NOT NULL REFERENCES codigos_inscripcion(id) ON DELETE CASCADE,
      profile_id            UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      estado                TEXT NOT NULL DEFAULT 'creando',
      declaro_mayor_de_edad BOOLEAN NOT NULL,
      created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
      decidida_por          UUID REFERENCES profiles(id),
      decidida_en           TIMESTAMPTZ,
      CONSTRAINT solicitudes_inscripcion_perfil_key UNIQUE (profile_id),
      CONSTRAINT solicitudes_inscripcion_estado_check
        CHECK (estado IN ('creando','pendiente','aprobada')),
      CONSTRAINT solicitudes_inscripcion_mayor_check CHECK (declaro_mayor_de_edad),
      CONSTRAINT solicitudes_inscripcion_decision_check
        CHECK ((estado = 'aprobada') = (decidida_por IS NOT NULL AND decidida_en IS NOT NULL))
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_solicitudes_inscripcion_grupo
      ON solicitudes_inscripcion (group_id, estado);
    """,
    "ALTER TABLE solicitudes_inscripcion ENABLE ROW LEVEL SECURITY;",
)

SQL_BAJAR: tuple[str, ...] = (
    "DROP TABLE IF EXISTS solicitudes_inscripcion;",
    "DROP TABLE IF EXISTS codigos_inscripcion;",
)


def upgrade() -> None:
    for sql in SQL_SUBIR:
        op.execute(sql)


def downgrade() -> None:
    for sql in SQL_BAJAR:
        op.execute(sql)
