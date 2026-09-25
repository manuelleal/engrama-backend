"""sin acceso directo de clientes a public (BUG-3..9, decisión 005)

Revision ID: 031_sin_acceso_directo
Revises: 030_rls_sin_recursion
Create Date: 2026-09-25

Espec: docs/ESPEC_bug3a9_sin_acceso_directo.md. Decisión: INGLES/decisiones/005.

El problema (BUG-3..9): Supabase da por defecto TODOS los permisos sobre las
tablas de `public` a `anon` (quien no inició sesión) y a `authenticated`
(cualquier usuario con sesión). Con eso, un alumno con la clave pública de
Supabase puede hablarle a la base directo, sin pasar por el backend, y la
única barrera es la RLS. Y la RLS de la 029 deja pasar varios ataques: leer
`correct_answer`, crearse intentos ganados, darse membresía de admin, editar
su propia racha, marcarse asistencia, escribir en tablas de módulos sin
código, y que un admin lea el `pin_hash` de otro colegio.

La decisión 005: el celular y la web hablan SOLO con el backend. Entonces
los clientes no necesitan ningún permiso directo, y se les quitan todos. La
RLS se queda como segunda barrera (defensa en profundidad), no como la
principal.

Qué hace, en SQL (6 sentencias):
  1-3. REVOKE ALL sobre lo que YA existe en `public` (tablas, secuencias y
       funciones) a `anon` y `authenticated`.
  4-6. ALTER DEFAULT PRIVILEGES: lo que `postgres` cree MAÑANA en `public`
       tampoco nace abierto para ellos.

Qué NO hace (a propósito):
  - No toca a `service_role` ni a `postgres`: el backend se conecta con
    ellos (src/shared/db.py:4).
  - No quita el USAGE del esquema `public`: sin él, ni `service_role` por
    PostgREST podría nombrar las tablas; lo que importa son los permisos
    sobre cada tabla.
  - No toca `app_private.user_tenant_ids()` (030): su EXECUTE para
    `authenticated` se mantiene; solo devuelve los colegios del que llama y
    no sale por la API de Supabase.
  - No quita el EXECUTE que PostgreSQL da a PUBLIC en cada función nueva:
    eso no se puede quitar por esquema. Cada función futura en `public` debe
    hacer su propio `REVOKE ... FROM PUBLIC` (como la 030); el test D12 lo
    detecta si se olvida.
  - Lo que cree `supabase_admin` en `public` sigue naciendo abierto: la 031
    solo cambia los DEFAULT de `postgres` (quien migra). `postgres` no puede
    cambiar los de `supabase_admin` (42501). Ver docs/PRODUCCION_030.md.

Downgrade: las mismas 6 sentencias con GRANT ALL, en orden inverso (primero
los DEFAULT, después los objetos). Las ACL quedan iguales como conjunto; el
orden textual de `relacl` puede cambiar.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "031_sin_acceso_directo"
down_revision: Union[str, None] = "030_rls_sin_recursion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Los roles de cliente de Supabase. Ninguno de los dos habla con la base
# desde que todo pasa por el backend (decisión 005).
_CLIENTES = "anon, authenticated"

# Tipos de objeto de `public`. ROUTINES = funciones y procedimientos.
_OBJETOS = ("TABLES", "SEQUENCES", "ROUTINES")


def upgrade() -> None:
    # 1-3. Lo que ya existe.
    for objetos in _OBJETOS:
        op.execute(f"REVOKE ALL ON ALL {objetos} IN SCHEMA public FROM {_CLIENTES};")
    # 4-6. Lo que `postgres` cree después.
    for objetos in _OBJETOS:
        op.execute(
            "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
            f"REVOKE ALL ON {objetos} FROM {_CLIENTES};"
        )


def downgrade() -> None:
    # Orden inverso: primero los DEFAULT, después los objetos.
    for objetos in reversed(_OBJETOS):
        op.execute(
            "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
            f"GRANT ALL ON {objetos} TO {_CLIENTES};"
        )
    for objetos in reversed(_OBJETOS):
        op.execute(f"GRANT ALL ON ALL {objetos} IN SCHEMA public TO {_CLIENTES};")
