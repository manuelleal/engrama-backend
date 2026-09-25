"""Tramposos de BUG-2 (docs/ESPEC_bug2_rls_recursion.md §3).

Mismo patrón que test_tramposos_seguridad.py: se rompe la base a propósito
(confirmado, porque `como` usa su propia conexión), se corre el test real y se
exige AssertionError con el mensaje correcto.

  recursiva        la política SELECT de memberships vuelve a la de la 029  -> D3 (42P17)
  sin_search_path  ALTER FUNCTION ... RESET search_path                     -> blindada
  fuga             la función deja de filtrar por auth.uid()                -> no_filtra

Restauración: antes de romper se guarda la definición EXACTA que dejó la 030
(`pg_get_functiondef` y la condición de la política en pg_policies) y el
`finally` la vuelve a poner. El contenedor es desechable (tmpfs): si el
proceso muriera a mitad, el daño no sobrevive a la sesión.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

import tests.seguridad.test_aceptacion as seg
import tests.seguridad.test_bug2_funcion as funcion
import tests.seguridad.veredictos as veredictos
from tests.seguridad.veredictos import sembrar

pytestmark = pytest.mark.integ

_POLITICA = '"tenant_isolation_select" on memberships'

# La política SELECT de memberships tal como la crea la 029 (se consulta a sí misma).
_CONDICION_029 = (
    "tenant_id in (select tenant_id from memberships "
    "where profile_id = auth.uid() and is_active = true)"
)

# La función SIN el filtro por usuario: devuelve los colegios de todos.
_FUNCION_CON_FUGA = (
    "create or replace function app_private.user_tenant_ids() returns setof uuid "
    "language sql stable security definer set search_path = '' "
    "as $$ select m.tenant_id from public.memberships m where m.is_active = true $$"
)


def _politica_select(condicion: str) -> list[str]:
    return [f"drop policy {_POLITICA}",
            f"create policy {_POLITICA} for select to authenticated using ({condicion})"]


TRAMPOSOS: dict[str, tuple[list[str], Callable[[Any], None], str]] = {
    "recursiva": (_politica_select(_CONDICION_029),
                  seg.test_d3_alumno_no_edita_saldos, "42P17"),
    "sin_search_path": (["alter function app_private.user_tenant_ids() reset search_path"],
                        funcion.test_bug2_funcion_blindada, "search_path"),
    "fuga": ([_FUNCION_CON_FUGA],
             funcion.test_bug2_funcion_no_filtra, "colegios ajenos"),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_bug2_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    romper, test_real, motivo = TRAMPOSOS[clave]
    # Lo que dejó la 030, tal cual, para restaurarlo.
    definicion = integ.valor(
        "select pg_get_functiondef('app_private.user_tenant_ids()'::regprocedure)")
    condicion = integ.valor(
        "select qual from pg_policies where schemaname = 'public' "
        "and tablename = 'memberships' and policyname = 'tenant_isolation_select'")
    assert definicion and condicion, "control: la 030 no está aplicada"
    # El humo lo escribe la corrida real; un tramposo no debe ensuciarlo.
    monkeypatch.setattr(veredictos, "registrar_humo", lambda *_a, **_k: None)
    try:
        for sql in romper:
            sembrar(integ, sql)
        with pytest.raises(AssertionError, match=motivo):
            test_real(integ)
    finally:
        sembrar(integ, definicion)  # CREATE OR REPLACE: conserva dueño y permisos
        for sql in _politica_select(condicion):
            sembrar(integ, sql)
    # Control: quedó exactamente como estaba.
    assert integ.valor(
        "select pg_get_functiondef('app_private.user_tenant_ids()'::regprocedure)"
    ) == definicion
