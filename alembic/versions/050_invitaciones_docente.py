"""invitaciones de profes por correo

Revision ID: 050_invitaciones_docente
Revises: 047_economia_ola1
Create Date: 2026-10-26

Espec: docs/ESPEC_invitar_profe.md §3.6.

Número 050 reservado por el coordinador: la 048 y la 049 son de otro agente
(ERR-45). En esta rama sube sobre la 047; al integrar, la que llegue después
cambia su `down_revision`.

Qué hace (`SQL_SUBIR`, idempotente):
  1. `invitaciones_docente`: a quién invitó el admin de UNA institución, a qué
     grupo, con qué correo y cuándo pidió el último envío. El perfil del profe
     (rol `teacher`, `force_password_reset = true`) nace con la invitación; la
     invitación está "aceptada" cuando esa bandera baja (no hay columna de
     estado que se pueda desincronizar).
     - `UNIQUE (tenant_id, correo)`: el mismo correo una sola vez POR
       institución (otra institución puede invitarlo: no se entera de nada).
     - el CHECK exige el correo en minúsculas: dos escrituras del mismo correo
       no pueden ser dos invitaciones.
  2. RLS activo y SIN políticas (como 035 y 036): ningún rol de cliente lee ni
     escribe; por la 031, tampoco reciben privilegios sobre tablas nuevas. El
     aislamiento por institución lo hace el backend (`tenant_id` en cada ruta).

El correo del profe se guarda solo aquí, en la fila de su institución.

Downgrade (`SQL_BAJAR`): borra la tabla. Los perfiles y las membresías de los
profes invitados no se tocan. En producción NO se baja: se restaura el respaldo.

`upgrade()` y `downgrade()` solo recorren estas tuplas: el test
`tests/integ/test_migracion_050.py` ejecuta exactamente el mismo SQL.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "050_invitaciones_docente"
down_revision: Union[str, None] = "047_economia_ola1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_SUBIR: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS invitaciones_docente (
      id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      profile_id      UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      group_id        UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
      correo          TEXT NOT NULL,
      invitada_por    UUID REFERENCES profiles(id) ON DELETE SET NULL,
      created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
      ultimo_envio_en TIMESTAMPTZ NOT NULL DEFAULT now(),
      envios          INTEGER NOT NULL DEFAULT 1,
      CONSTRAINT invitaciones_docente_perfil_key UNIQUE (profile_id),
      CONSTRAINT invitaciones_docente_correo_key UNIQUE (tenant_id, correo),
      CONSTRAINT invitaciones_docente_correo_check
        CHECK (correo = lower(correo) AND length(correo) BETWEEN 3 AND 254),
      CONSTRAINT invitaciones_docente_envios_check CHECK (envios >= 1)
    );
    """,
    "ALTER TABLE invitaciones_docente ENABLE ROW LEVEL SECURITY;",
)

SQL_BAJAR: tuple[str, ...] = (
    "DROP TABLE IF EXISTS invitaciones_docente;",
)


def upgrade() -> None:
    for sql in SQL_SUBIR:
        op.execute(sql)


def downgrade() -> None:
    for sql in SQL_BAJAR:
        op.execute(sql)
