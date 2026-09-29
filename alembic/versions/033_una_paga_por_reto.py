"""una sola paga por reto: llave de idempotencia en coin_ledger (BUG-13)

Revision ID: 033_una_paga_por_reto
Revises: 032_nombre_por_membresia
Create Date: 2026-09-28

Espec: docs/ESPEC_bug13a15.md §1.1.

El problema (BUG-13): `submit_attempt` pagaba cada victoria sin mirar si el
estudiante ya había cobrado ese reto. Un segundo intento correcto (o dos
envíos simultáneos) pagaba otra vez.

La regla nueva vive en la BD, no en la app: cada paga que trae llave ocupa
UNA fila por `(tenant_id, idempotency_key)`. Para los retos la llave es
`challenge:<reto>:<estudiante>`, así que venga por donde venga la paga
(secuencial, concurrente, `/submit` o un `/finish` futuro) solo entra una.

Qué hace (`SQL_SUBIR`, idempotente):
  1. Agrega `coin_ledger.idempotency_key` (nullable: la asistencia y todo lo
     que no pase llave queda idéntico; en PostgreSQL los NULL no chocan).
  2. Backfill: a la fila de reto MÁS ANTIGUA de cada (tenant, reto,
     estudiante) le pone su llave. Las repetidas (dobles pagas históricas)
     quedan en NULL: no se revierten solas (ESPEC §7). El `NOT EXISTS` hace
     que correrlo dos veces no choque.
  3. UNIQUE `coin_ledger_idempotency_key (tenant_id, idempotency_key)`.

No crea tablas, vistas, secuencias ni funciones, ni toca políticas.

Downgrade (`SQL_BAJAR`): quita el UNIQUE y la columna; solo se pierden las
llaves, que el código viejo no lee.

`upgrade()` y `downgrade()` solo recorren estas tuplas: los tests de
`tests/integ/test_migracion_033.py` ejecutan exactamente el mismo SQL.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "033_una_paga_por_reto"
down_revision: Union[str, None] = "032_nombre_por_membresia"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_SUBIR: tuple[str, ...] = (
    "ALTER TABLE coin_ledger ADD COLUMN IF NOT EXISTS idempotency_key TEXT;",
    """
    WITH candidatos AS (
      SELECT l.id, l.tenant_id, l.created_at,
             'challenge:' || (l.metadata->>'challenge_id') || ':' || w.owner_id::text AS clave
        FROM coin_ledger l
        JOIN coin_wallets w ON w.id = l.to_wallet_id AND w.owner_type = 'profile'
       WHERE l.action = 'challenge' AND l.metadata ? 'challenge_id'
         AND l.idempotency_key IS NULL
    ), primeros AS (
      SELECT DISTINCT ON (c.tenant_id, c.clave) c.id, c.clave
        FROM candidatos c
       WHERE NOT EXISTS (SELECT 1 FROM coin_ledger x
                          WHERE x.tenant_id = c.tenant_id AND x.idempotency_key = c.clave)
       ORDER BY c.tenant_id, c.clave, c.created_at, c.id
    )
    UPDATE coin_ledger l SET idempotency_key = p.clave FROM primeros p WHERE l.id = p.id;
    """,
    "ALTER TABLE coin_ledger DROP CONSTRAINT IF EXISTS coin_ledger_idempotency_key;",
    """
    ALTER TABLE coin_ledger ADD CONSTRAINT coin_ledger_idempotency_key
      UNIQUE (tenant_id, idempotency_key);
    """,
)

SQL_BAJAR: tuple[str, ...] = (
    "ALTER TABLE coin_ledger DROP CONSTRAINT IF EXISTS coin_ledger_idempotency_key;",
    "ALTER TABLE coin_ledger DROP COLUMN IF EXISTS idempotency_key;",
)


def upgrade() -> None:
    for sql in SQL_SUBIR:
        op.execute(sql)


def downgrade() -> None:
    for sql in SQL_BAJAR:
        op.execute(sql)
