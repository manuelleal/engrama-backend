"""rls sin recursión en memberships (BUG-2)

Revision ID: 030_rls_sin_recursion
Revises: 029_rls_policies
Create Date: 2026-09-24

Espec: docs/ESPEC_bug2_rls_recursion.md.

El problema (BUG-2): en la 029, las políticas de `memberships` preguntan
"¿a qué colegios pertenece el usuario?" leyendo... `memberships`. Para leer
esa tabla PostgreSQL vuelve a aplicar su RLS, que vuelve a leerla, y así sin
fin: toda consulta con el rol `authenticated` que toque `memberships` (casi
todas: 49 de las 51 políticas la consultan) muere con 42P17 (recursión
infinita).

El arreglo: una función que responde esa pregunta SIN pasar por la RLS.
  - SECURITY DEFINER: corre con los permisos de su dueño (quien migra, dueño
    de la tabla), que no está sujeto a la RLS de `memberships`. Eso corta el
    ciclo.
  - Sin parámetros y filtrando por `auth.uid()` adentro: solo puede contestar
    por el usuario que llama; no hay forma de pedirle los colegios de otro.
  - search_path = '' y nombres calificados (public.memberships, auth.uid()):
    nadie puede "plantar" otra tabla `memberships` en su propio esquema para
    que la función la lea con privilegios de dueño.
  - STABLE: dentro de una misma consulta devuelve lo mismo, y el planificador
    puede evaluarla una sola vez.
  - Vive en `app_private`, no en `public`: la API de Supabase (PostgREST) no
    la publica como RPC, y `anon` no puede ni entrar al esquema.

Solo cambian las DOS políticas de `memberships`; las otras 49 siguen iguales
y dejan de romperse porque, al consultar `memberships`, ya no hay ciclo.

La 029 no se edita: puede estar aplicada en engrama-2.0. El downgrade deja
las dos políticas exactamente como las creó la 029.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "030_rls_sin_recursion"
down_revision: Union[str, None] = "029_rls_policies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FUNCION = """
    CREATE FUNCTION app_private.user_tenant_ids()
      RETURNS SETOF uuid
      LANGUAGE sql
      STABLE
      SECURITY DEFINER
      SET search_path = ''
    AS $$
      SELECT m.tenant_id
      FROM public.memberships m
      WHERE m.profile_id = auth.uid()
        AND m.is_active = TRUE
    $$;
"""

# Políticas nuevas: misma tabla, mismo nombre, mismo comando y mismo rol que
# en la 029; solo cambia de dónde sale la lista de colegios del usuario.
_SELECT_NUEVA = """
    CREATE POLICY "tenant_isolation_select" ON memberships
      FOR SELECT TO authenticated
      USING (
        tenant_id IN (SELECT app_private.user_tenant_ids())
      );
"""

_INSERT_NUEVA = """
    CREATE POLICY "tenant_isolation_insert" ON memberships
      FOR INSERT TO authenticated
      WITH CHECK (
        tenant_id IN (SELECT app_private.user_tenant_ids())
      );
"""

# Copia literal de lo que crea la 029 para `memberships` (_base_select_sql y
# _base_insert_sql). Se usa en el downgrade para volver al estado exacto.
_SELECT_029 = """
    CREATE POLICY "tenant_isolation_select" ON memberships
      FOR SELECT TO authenticated
      USING (
        tenant_id IN (
          SELECT tenant_id FROM memberships
          WHERE profile_id = auth.uid()
            AND is_active = TRUE
        )
      );
"""

_INSERT_029 = """
    CREATE POLICY "tenant_isolation_insert" ON memberships
      FOR INSERT TO authenticated
      WITH CHECK (
        tenant_id IN (
          SELECT tenant_id FROM memberships
          WHERE profile_id = auth.uid()
            AND is_active = TRUE
        )
      );
"""


def _reemplazar_politicas(select_sql: str, insert_sql: str) -> None:
    op.execute('DROP POLICY "tenant_isolation_select" ON memberships;')
    op.execute('DROP POLICY "tenant_isolation_insert" ON memberships;')
    op.execute(select_sql)
    op.execute(insert_sql)


def upgrade() -> None:
    # 1. Esquema privado: nadie lo usa salvo `authenticated`, y sin CREATE.
    op.execute("CREATE SCHEMA app_private;")
    op.execute("REVOKE ALL ON SCHEMA app_private FROM PUBLIC;")
    op.execute("GRANT USAGE ON SCHEMA app_private TO authenticated;")

    # 2. La función. Por defecto PostgreSQL da EXECUTE a PUBLIC: se quita y
    #    se da solo a `authenticated` (anon no tiene nada que preguntar).
    op.execute(_FUNCION)
    op.execute("REVOKE ALL ON FUNCTION app_private.user_tenant_ids() FROM PUBLIC;")
    op.execute("GRANT EXECUTE ON FUNCTION app_private.user_tenant_ids() TO authenticated;")

    # 3. Las dos políticas de memberships dejan de consultarse a sí mismas.
    _reemplazar_politicas(_SELECT_NUEVA, _INSERT_NUEVA)


def downgrade() -> None:
    # Orden inverso: primero las políticas (dependen de la función).
    _reemplazar_politicas(_SELECT_029, _INSERT_029)
    op.execute("DROP FUNCTION app_private.user_tenant_ids();")
    op.execute("DROP SCHEMA app_private;")
