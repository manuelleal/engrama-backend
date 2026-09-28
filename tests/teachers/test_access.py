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

EXPECTED_GUARDS: dict[tuple[str, frozenset], str] = {**_PREVIAS, **_NUEVAS}  # type: ignore[type-arg]


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

# NOTA (commit 1, §7): un test "al final están las 11" no se agrega en esta
# tanda — T5 y T7 (`/achievement`, `/item-errors`) quedan BLOQUEADAS hasta que
# el pedagogo responda §2.4 (pasos 10-11), así que "las 11 completas" nunca es
# cierto en los pasos 1-9. Al terminar el paso 9 se agrega, en su lugar, un
# test que exige las 9 rutas EN ALCANCE (T1-T4, T6, M1-M4) — ver el commit de
# F12/.gitignore.
