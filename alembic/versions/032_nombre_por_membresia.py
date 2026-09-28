"""nombre del estudiante por membresía (BUG-11)

Revision ID: 032_nombre_por_membresia
Revises: 031_sin_acceso_directo
Create Date: 2026-09-28

Espec: docs/ESPEC_bug11.md §1.

El problema (BUG-11): el nombre del estudiante vivía en `profiles.full_name`,
que es GLOBAL (un solo perfil por `documento_id`). Si el colegio A matriculaba
a D con el nombre N1 y después el colegio B matriculaba al MISMO D con N2, el
backend reusaba el perfil y descartaba N2 en silencio: el colegio B veía N1,
un dato que escribió OTRO colegio.

La regla nueva: lo que pone un colegio vive en SU membresía. La identidad
sigue siendo global (un `profile_id` por `documento_id`); el nombre, no.

Qué hace (`SQL_SUBIR`, idempotente):
  1. Agrega `memberships.full_name` (nullable: docentes y admins no tienen un
     nombre puesto por el colegio).
  2. Backfill: cada membresía `student` recibe el nombre que hoy tiene su
     perfil (es lo que T2 y T5 mostraban hasta ahora).
  3. CHECK: un `student` nunca queda sin nombre. Así T2 no necesita un
     respaldo en `profiles` (un COALESCE reabriría el hueco).

Qué NO hace: no toca `profiles` (ni esquema ni datos). `profiles.full_name`
queda como "nombre propio de la cuenta", nunca un dato de un colegio.

Downgrade (`SQL_BAJAR`): devuelve el comportamiento viejo, CON su hueco.
Restaura el nombre del perfil desde la membresía más antigua, solo donde el
perfil tiene `''` (los perfiles que M3/M4 crearon después de la 032). Pierde,
a propósito, los nombres de los demás colegios (ESPEC §7): en producción no
se hace downgrade, se restaura el respaldo.

`upgrade()` y `downgrade()` solo recorren estas tuplas: los tests de
`tests/integ/test_migracion_032.py` ejecutan exactamente el mismo SQL.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "032_nombre_por_membresia"
down_revision: Union[str, None] = "031_sin_acceso_directo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_SUBIR: tuple[str, ...] = (
    "ALTER TABLE memberships ADD COLUMN IF NOT EXISTS full_name TEXT;",
    """
    UPDATE memberships m SET full_name = p.full_name
      FROM profiles p
     WHERE p.id = m.profile_id AND m.role = 'student' AND m.full_name IS NULL;
    """,
    "ALTER TABLE memberships DROP CONSTRAINT IF EXISTS memberships_student_full_name_check;",
    """
    ALTER TABLE memberships ADD CONSTRAINT memberships_student_full_name_check
      CHECK (role <> 'student' OR full_name IS NOT NULL);
    """,
)

SQL_BAJAR: tuple[str, ...] = (
    """
    UPDATE profiles p SET full_name = m.full_name
      FROM (SELECT DISTINCT ON (profile_id) profile_id, full_name
              FROM memberships
             WHERE role = 'student' AND full_name IS NOT NULL
             ORDER BY profile_id, created_at, id) m
     WHERE p.id = m.profile_id AND p.full_name = '';
    """,
    "ALTER TABLE memberships DROP CONSTRAINT IF EXISTS memberships_student_full_name_check;",
    "ALTER TABLE memberships DROP COLUMN IF EXISTS full_name;",
)


def upgrade() -> None:
    for sql in SQL_SUBIR:
        op.execute(sql)


def downgrade() -> None:
    for sql in SQL_BAJAR:
        op.execute(sql)
