"""el límite del registro compartido entre procesos: tabla limite_intentos

Revision ID: 046_limite_compartido
Revises: 045_correccion_por_pregunta
Create Date: 2026-10-20

Espec: docs/ESPEC_limites_registro.md §1.2 (auditoría 03, S-3 resto).

Por qué existe: los cuatro contadores del registro (`src/registro/limite.py`)
vivían en la memoria de cada proceso de uvicorn. Con `--workers 2` cada tope
valía hasta el doble y un reinicio los ponía en cero. Lo único que los dos
procesos comparten es esta base: los eventos del límite pasan a esta tabla.

Qué hace (`SQL_SUBIR`, idempotente y ADITIVA):
  1. `limite_intentos`, UNLOGGED: es estado de 10 minutos. No escribe WAL (barato
     si alguien la martilla) y, si Postgres se cae sin apagarse bien, vuelve
     vacía: el límite arranca en cero, como hoy al reiniciar el backend.
     `llave` es una huella HMAC (nunca la IP ni el código); `momento`, los
     segundos del reloj del backend.
  2. Dos índices: uno para contar (contador, llave, momento) y otro para purgar
     lo vencido de cada contador (contador, momento).
  3. RLS activo y SIN políticas (como la 045): nadie de afuera la lee; el
     backend entra como dueño de la tabla.

Downgrade (`SQL_BAJAR`): borra la tabla. Lo que se pierde son, a lo sumo, diez
minutos de conteo.

`upgrade()` y `downgrade()` solo recorren estas tuplas: el test de
`tests/integ/test_migracion_046.py` ejecuta exactamente el mismo SQL.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "046_limite_compartido"
down_revision: Union[str, None] = "045_correccion_por_pregunta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_SUBIR: tuple[str, ...] = (
    """
    CREATE UNLOGGED TABLE IF NOT EXISTS limite_intentos (
      id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      contador TEXT NOT NULL,
      llave    TEXT NOT NULL,
      momento  DOUBLE PRECISION NOT NULL,
      CONSTRAINT limite_intentos_contador_check
        CHECK (contador IN ('por_ip','malos_por_ip','por_codigo','global'))
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_limite_intentos_llave
      ON limite_intentos (contador, llave, momento);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_limite_intentos_purga
      ON limite_intentos (contador, momento);
    """,
    "ALTER TABLE limite_intentos ENABLE ROW LEVEL SECURITY;",
)

SQL_BAJAR: tuple[str, ...] = (
    "DROP TABLE IF EXISTS limite_intentos;",
)


def upgrade() -> None:
    for sql in SQL_SUBIR:
        op.execute(sql)


def downgrade() -> None:
    for sql in SQL_BAJAR:
        op.execute(sql)
