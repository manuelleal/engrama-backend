"""BUG-2: la función SECURITY DEFINER de la 030 no abre un hueco nuevo.

Espec: docs/ESPEC_bug2_rls_recursion.md §2 y §4.

Una función SECURITY DEFINER corre con los permisos de su dueño, que no está
sujeto a la RLS de `memberships`. Por eso se prueban dos cosas:
  - blindada: cómo está declarada (search_path fijo, STABLE, dueño correcto,
    quién puede ejecutarla). Es lo que evita el secuestro por search_path y
    que `anon` la use.
  - no_filtra: lo que devuelve. Solo los colegios activos del que llama; ni un
    colegio ajeno, ni una membresía inactiva. Desde la 031, `memberships`
    leída directo da 42501 (docs/ESPEC_bug3a9_sin_acceso_directo.md §2).
Tramposos: tests/tramposos/test_tramposos_bug2.py.
"""
from __future__ import annotations

import pytest

from tests.seguridad.veredictos import PruebaRota, colegios, identidad, sembrar, sin_acceso

pytestmark = pytest.mark.integ

FUNCION = "app_private.user_tenant_ids()"


def test_bug2_funcion_blindada(integ) -> None:
    """pg_proc y permisos: search_path fijo, STABLE, DEFINER, dueño = el de la tabla."""
    fila = integ.fila(
        "select p.prosecdef as definer, p.provolatile::text as volatilidad, "
        "       p.proconfig as config, "
        "       pg_get_userbyid(p.proowner) = t.tableowner as dueno_es_el_de_la_tabla, "
        "       c.relforcerowsecurity as force_rls "
        "from pg_proc p, pg_tables t, pg_class c "
        f"where p.oid = to_regprocedure('{FUNCION}') "
        "  and t.schemaname = 'public' and t.tablename = 'memberships' "
        "  and c.oid = 'public.memberships'::regclass"
    )
    if fila is None:  # control: si la función no existe, el test está roto
        raise PruebaRota(f"no existe {FUNCION}: ¿se aplicó la migración 030?")
    assert fila["config"] == ['search_path=""'], (
        f"la función no fija search_path vacío: proconfig = {fila['config']}"
    )
    assert fila["definer"] is True, "la función no es SECURITY DEFINER"
    assert fila["volatilidad"] == "s", f"la función no es STABLE: {fila['volatilidad']!r}"
    # Si el dueño no fuera el de la tabla (o la tabla forzara RLS), la función
    # volvería a pasar por la RLS de memberships y la recursión regresaría.
    assert fila["dueno_es_el_de_la_tabla"] is True, "el dueño de la función no es el de memberships"
    assert fila["force_rls"] is False, "memberships tiene FORCE ROW LEVEL SECURITY"

    permisos = integ.fila(
        f"select has_function_privilege('anon', '{FUNCION}', 'EXECUTE') as anon_execute, "
        f"       has_function_privilege('authenticated', '{FUNCION}', 'EXECUTE') "
        "         as authenticated_execute, "
        "       has_schema_privilege('anon', 'app_private', 'USAGE') as anon_usage, "
        "       has_schema_privilege('authenticated', 'app_private', 'CREATE') "
        "         as authenticated_create"
    )
    assert permisos == {
        "anon_execute": False,
        "authenticated_execute": True,
        "anon_usage": False,
        "authenticated_create": False,
    }, f"permisos de la función o del esquema: {permisos}"


def test_bug2_funcion_no_filtra(integ) -> None:
    """La función muestra solo los colegios ACTIVOS del que llama; memberships directo, 42501."""
    propio, ajeno = colegios(integ)
    alumno = integ.crear_perfil(propio)
    integ.crear_perfil(ajeno)  # otra persona, activa, en el colegio ajeno
    # Membresía INACTIVA del alumno en el colegio ajeno, y de admin: no debe contar.
    sembrar(integ, "insert into memberships (tenant_id, profile_id, role, is_active) "
                   "values (:t, :p, 'admin', false)", t=ajeno, p=alumno)
    # Control: sin RLS hay membresías en los dos colegios (si no, no probaría nada).
    assert integ.valor("select count(distinct tenant_id) from memberships") == 2
    identidad(integ, alumno)

    res = integ.como(alumno, f"select t from {FUNCION} t")
    assert res.sqlstate is None, f"la función falla: {res.sqlstate} {res.mensaje}"
    assert res.filas == [{"t": propio}], f"la función devuelve colegios ajenos: {res.filas}"

    # Desde la 031 el alumno no lee memberships directo (decisión 005): la
    # función es lo único que responde "mis colegios", y sin salir por la API.
    sin_acceso(integ.como(alumno, "select distinct tenant_id from memberships"),
               "memberships", "el alumno lee memberships directo")

    res = integ.como(None, f"select * from {FUNCION}")
    assert res.sqlstate == "42501", f"anon ejecuta la función: {res.sqlstate} {res.filas}"
