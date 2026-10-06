"""U4: el mapa de guardas de TODAS las rutas — docs/ESPEC_grupos_y_panel_docente.md §4.

No pega a la base (sin `integ`): solo introspecciona `app.routes` y el árbol de
`Depends` de cada una (`route.dependant`). Así este test corre siempre, incluso
sin Docker, y es la "regresión = identidad" de METODO.md regla 4 para las 20
rutas que ya existían antes de esta espec.

`EXPECTED_GUARDS` es el mapa COMPLETO al final de la espec: 20 rutas previas +
10 nuevas de `/teachers` y `/admin` (commit 10). Se escribe una sola vez aquí
y el test compara contra las que existan en `app.routes` EN ESE COMMIT — así
cada commit que agrega una ruta nueva la ve aparecer sin tocar este archivo
de nuevo, y el propio test detecta si una ruta ya escrita cambia de guarda o
si sobra alguna que no está en el mapa.
"""
from __future__ import annotations

from collections.abc import Iterable

from fastapi.routing import APIRoute

from src.main import app
from src.shared.deps import get_current_user, require_admin, require_teacher

# -----------------------------------------------------------------------------
# Clasificación de guardas por introspección de Depends (sin HTTP, sin DB).
# -----------------------------------------------------------------------------
def _recolectar(dependants: Iterable) -> set:  # type: ignore[type-arg]
    """Todas las funciones `Depends(...)` de una ruta, recursivamente."""
    vistas: set = set()  # type: ignore[type-arg]
    for d in dependants:
        vistas.add(d.call)
        vistas |= _recolectar(d.dependencies)
    return vistas


def guardia(route: APIRoute) -> str:
    """'admin' / 'teacher' / 'user' / 'public' según la Depends más estricta.

    `require_admin` y `require_teacher` dependen a su vez de `get_current_user`
    (deps.py), así que basta buscar la más estricta presente en el árbol.
    """
    funciones = _recolectar(route.dependant.dependencies)
    if require_admin in funciones:
        return "admin"
    if require_teacher in funciones:
        return "teacher"
    if get_current_user in funciones:
        return "user"
    return "public"


# -----------------------------------------------------------------------------
# Las 20 rutas previas a esta espec (medidas en §0: ruff 0, mypy 0, 163
# passed). NO se editan: si una cambia de guarda, es una regresión real.
# -----------------------------------------------------------------------------
_PREVIAS: dict[tuple[str, frozenset], str] = {  # type: ignore[type-arg]
    ("/health", frozenset({"GET"})): "public",
    ("/auth/session", frozenset({"POST"})): "user",
    ("/auth/me", frozenset({"GET"})): "user",
    ("/auth/logout", frozenset({"POST"})): "user",
    ("/core/coins/balance", frozenset({"GET"})): "user",
    ("/core/coins/history", frozenset({"GET"})): "user",
    ("/core/attendance/sessions", frozenset({"POST"})): "teacher",
    ("/core/attendance/sessions/active", frozenset({"GET"})): "teacher",
    ("/core/attendance/check-in", frozenset({"POST"})): "user",
    ("/core/attendance/history", frozenset({"GET"})): "user",
    ("/core/attendance/history/{student_id}", frozenset({"GET"})): "teacher",
    ("/challenges/", frozenset({"POST"})): "teacher",
    ("/challenges/generate", frozenset({"POST"})): "teacher",
    ("/challenges/all", frozenset({"GET"})): "teacher",
    ("/challenges/{challenge_id}/status", frozenset({"PATCH"})): "teacher",
    ("/challenges/", frozenset({"GET"})): "user",
    ("/challenges/attempts/history", frozenset({"GET"})): "user",
    ("/challenges/attempts/{attempt_id}/submit", frozenset({"POST"})): "user",
    ("/challenges/{challenge_id}", frozenset({"GET"})): "user",
    ("/challenges/{challenge_id}/attempt", frozenset({"POST"})): "user",
}

# -----------------------------------------------------------------------------
# Las 11 nuevas — T1-T7 en /teachers, M1-M4 en /admin (§2 de la espec,
# corregida por ERR-16). T5 (`/achievement`) y T7 (`/item-errors`) están
# BLOQUEADAS hasta que el pedagogo responda §2.4 (pasos 10-11 de §7): se
# listan aquí para documentar la meta, pero no nacen en los pasos 1-9. Este
# test no exige que existan (ver `test_u4_guardas_de_las_rutas_existentes`).
# -----------------------------------------------------------------------------
_NUEVAS: dict[tuple[str, frozenset], str] = {  # type: ignore[type-arg]
    ("/teachers/groups", frozenset({"GET"})): "teacher",                       # T1
    ("/teachers/groups/{gid}/students", frozenset({"GET"})): "teacher",        # T2
    ("/teachers/groups/{gid}/attendance-sessions", frozenset({"POST"})): "teacher",  # T3
    ("/teachers/attendance-sessions/{sid}/close", frozenset({"POST"})): "teacher",   # T4
    ("/teachers/groups/{gid}/achievement", frozenset({"GET"})): "teacher",     # T5 — bloqueada
    ("/teachers/groups/{gid}/challenges/{cid}", frozenset({"PUT"})): "teacher",  # T6
    ("/teachers/groups/{gid}/item-errors", frozenset({"GET"})): "teacher",     # T7 — bloqueada
    ("/admin/groups", frozenset({"POST"})): "admin",                           # M1
    ("/admin/groups/{gid}/teachers", frozenset({"POST"})): "admin",            # M2
    ("/admin/groups/{gid}/students", frozenset({"POST"})): "admin",            # M3
    ("/admin/groups/{gid}/students/import", frozenset({"POST"})): "admin",     # M4
}

# -----------------------------------------------------------------------------
# docs/ESPEC_login_piloto.md §1.5: cambio de la contraseña temporal.
# -----------------------------------------------------------------------------
_LOGIN_PILOTO: dict[tuple[str, frozenset], str] = {  # type: ignore[type-arg]
    ("/auth/contrasena", frozenset({"POST"})): "user",
    # docs/ESPEC_consentimiento.md: la aceptación del aviso de datos.
    ("/auth/consentimiento", frozenset({"POST"})): "user",
}

# -----------------------------------------------------------------------------
# docs/ESPEC_autorregistro.md: la única ruta pública que escribe, y las del profe.
# -----------------------------------------------------------------------------
_AUTORREGISTRO: dict[tuple[str, frozenset], str] = {  # type: ignore[type-arg]
    ("/auth/registro", frozenset({"POST"})): "public",
    ("/teachers/groups/{gid}/codigo-inscripcion", frozenset({"POST"})): "teacher",
    ("/teachers/groups/{gid}/codigo-inscripcion", frozenset({"GET"})): "teacher",
    ("/teachers/groups/{gid}/codigo-inscripcion", frozenset({"DELETE"})): "teacher",
    ("/teachers/groups/{gid}/solicitudes", frozenset({"GET"})): "teacher",
    ("/teachers/groups/{gid}/solicitudes/{sid}/aprobar", frozenset({"POST"})): "teacher",
    ("/teachers/groups/{gid}/solicitudes/{sid}/rechazar", frozenset({"POST"})): "teacher",
}

EXPECTED_GUARDS: dict[tuple[str, frozenset], str] = {  # type: ignore[type-arg]
    **_PREVIAS, **_NUEVAS, **_LOGIN_PILOTO, **_AUTORREGISTRO}


def test_u4_guardas_de_las_rutas_existentes() -> None:
    """Cada ruta que YA existe en `app.routes` tiene exactamente la guarda del mapa.

    No exige que las 30 existan todavía (las 10 nuevas nacen a lo largo de
    los commits 2-9): exige que ninguna ruta existente falte del mapa, que
    ninguna tenga otra guarda, y que las 20 previas sigan ahí sin cambiar
    (regresión = identidad, METODO.md regla 4).
    """
    actuales = {
        (r.path, frozenset(r.methods)): guardia(r)
        for r in app.routes
        if isinstance(r, APIRoute)
    }
    faltantes_en_mapa = set(actuales) - set(EXPECTED_GUARDS)
    assert not faltantes_en_mapa, f"rutas sin guarda esperada en el mapa: {faltantes_en_mapa}"

    for clave, esperada in EXPECTED_GUARDS.items():
        if clave not in actuales:
            continue  # ruta nueva que este commit todavía no agregó
        assert actuales[clave] == esperada, (
            f"{clave}: guarda {actuales[clave]!r}, se esperaba {esperada!r}"
        )

    # Las 20 previas SIEMPRE deben estar (nunca se borran ni se renombran).
    faltan_previas = set(_PREVIAS) - set(actuales)
    assert not faltan_previas, f"rutas previas que desaparecieron: {faltan_previas}"


def test_u4_al_final_estan_las_11() -> None:
    """Cuando el módulo está completo (§2.4 respondida, T5 y T7 nacidas)."""
    actuales = {(r.path, frozenset(r.methods)) for r in app.routes if isinstance(r, APIRoute)}
    assert actuales == set(EXPECTED_GUARDS), (
        f"faltan: {set(EXPECTED_GUARDS) - actuales}; sobran: {actuales - set(EXPECTED_GUARDS)}"
    )


def test_h3_sin_overrides_de_dependencias_filtrados() -> None:
    """H-3 (auditor): ninguna guarda queda anulada en runtime al terminar la suite.

    `app.dependency_overrides` es un dict GLOBAL, compartido por todo el
    proceso de pytest. Los tramposos X3/X4 (`tests/tramposos/
    test_tramposos_grupos.py`, `_override`) lo usan para reemplazar
    `require_teacher`/`require_admin` y siempre lo deshacen en un `finally` —
    pero si algún test (presente o futuro) olvidara ese `finally`, TODAS las
    rutas que dependen de esa guarda quedarían abiertas para el resto de la
    suite (y para cualquiera que reimporte `src.main.app`), sin que ningún
    otro test lo note. Este test es el canario: falla si queda CUALQUIER
    override puesto, sea cual sea.

    Verificado en rojo/verde a mano (no queda como tramposo permanente,
    ERR-12/§4 no lo cuenta como test nuevo de la matriz): con
    `app.dependency_overrides[get_current_user] = lambda: None` puesto,
    este test falla con el mensaje de abajo; al hacer
    `app.dependency_overrides.clear()`, vuelve a pasar.
    """
    assert app.dependency_overrides == {}, (
        f"quedaron overrides de Depends sin deshacer: {list(app.dependency_overrides)}"
    )
