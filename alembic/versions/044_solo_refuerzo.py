"""retos solo de refuerzo y días sin contenido

Revision ID: 044_solo_refuerzo
Revises: 043_practica_y_tanda
Create Date: 2026-10-13

Espec: docs/ESPEC_solo_refuerzo.md §1.6 (dictamen pedagógico 04, hecho 2 y §1.3).

Qué hace (`SQL_SUBIR`, idempotente y ADITIVA; ninguna tabla nueva):
  1. `challenges.solo_refuerzo`: el reto no sale en el feed ni en la tanda de
     retos nuevos; sus preguntas son formas para la cola de repaso y para la
     segunda vuelta. Los retos que ya existen quedan en FALSE.
  2. `activity_days.sin_contenido`: ese día el estudiante pidió practicar y la
     institución no tenía qué servirle. La semana que lo contiene no rompe la
     racha al cerrar.

Downgrade (`SQL_BAJAR`): quita las dos columnas. En producción NO se baja.

`upgrade()` y `downgrade()` solo recorren estas tuplas: el test de
`tests/integ/test_migracion_044.py` ejecuta exactamente el mismo SQL.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "044_solo_refuerzo"
down_revision: Union[str, None] = "043_practica_y_tanda"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_SUBIR: tuple[str, ...] = (
    "ALTER TABLE challenges ADD COLUMN IF NOT EXISTS solo_refuerzo BOOLEAN NOT NULL "
    "DEFAULT FALSE;",
    "ALTER TABLE activity_days ADD COLUMN IF NOT EXISTS sin_contenido BOOLEAN NOT NULL "
    "DEFAULT FALSE;",
)

SQL_BAJAR: tuple[str, ...] = (
    "ALTER TABLE activity_days DROP COLUMN IF EXISTS sin_contenido;",
    "ALTER TABLE challenges DROP COLUMN IF EXISTS solo_refuerzo;",
)


def upgrade() -> None:
    for sql in SQL_SUBIR:
        op.execute(sql)


def downgrade() -> None:
    for sql in SQL_BAJAR:
        op.execute(sql)
