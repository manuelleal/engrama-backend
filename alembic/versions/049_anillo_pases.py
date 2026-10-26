"""el pase acotado del anillo: una fila por pase, con su huella y no el pase

Revision ID: 049_anillo_pases
Revises: 048_limite_compartido
Create Date: 2026-10-20 (renumerada de 046 a 049 al integrar en fase0/backend, ERR-45)

Espec: docs/ESPEC_pase_acotado.md §1.5 (auditoría de seguridad 03, S-10).

Qué hace (`SQL_SUBIR`, idempotente y ADITIVA):
  1. `anillo_pases`: una fila por pase emitido para EVA o SET. Guarda la huella
     (`sha256` en hexadecimal; nunca el pase), de quién es, de qué institución,
     para qué audiencia, cuándo vence y cuándo se gastó. `usado_en` nulo = vivo.
  2. Dos índices: por persona (el tope de pases vivos) y por vencimiento (la
     limpieza de los vencidos hace más de un día).
  3. RLS activo y SIN políticas, como la 045. Los privilegios de los clientes de
     Supabase ya los niega la 031 (ALTER DEFAULT PRIVILEGES).

Downgrade (`SQL_BAJAR`): borra la tabla. En producción NO se baja.

`upgrade()` y `downgrade()` solo recorren estas tuplas: el test de
`tests/integ/test_migracion_049.py` ejecuta exactamente el mismo SQL.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "049_anillo_pases"
down_revision: Union[str, None] = "048_limite_compartido"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_SUBIR: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS anillo_pases (
      id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      hash        TEXT NOT NULL,
      profile_id  UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
      tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
      audiencia   TEXT NOT NULL,
      creado_en   TIMESTAMPTZ NOT NULL DEFAULT now(),
      expira_en   TIMESTAMPTZ NOT NULL,
      usado_en    TIMESTAMPTZ,
      CONSTRAINT anillo_pases_hash_key UNIQUE (hash),
      CONSTRAINT anillo_pases_audiencia_check CHECK (audiencia IN ('eva','set')),
      CONSTRAINT anillo_pases_hash_check CHECK (hash ~ '^[0-9a-f]{64}$')
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_anillo_pases_perfil ON anillo_pases (profile_id);",
    "CREATE INDEX IF NOT EXISTS idx_anillo_pases_expira ON anillo_pases (expira_en);",
    "ALTER TABLE anillo_pases ENABLE ROW LEVEL SECURITY;",
)

SQL_BAJAR: tuple[str, ...] = (
    "DROP TABLE IF EXISTS anillo_pases;",
)


def upgrade() -> None:
    for sql in SQL_SUBIR:
        op.execute(sql)


def downgrade() -> None:
    for sql in SQL_BAJAR:
        op.execute(sql)
