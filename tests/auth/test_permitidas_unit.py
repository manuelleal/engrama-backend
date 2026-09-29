"""UP3 (C15): la lista de rutas permitidas con contraseña temporal — ESPEC_login_piloto §1.5.

No-integ: solo introspecciona `app.routes` (sin HTTP ni base).

Para cada `APIRoute` y cada método de `route.methods`,
`puede_con_contrasena_temporal(path, método)` es verdadero SOLO para los 4
pares permitidos. Además, 4 pares que hoy NO existen dan falso: con las rutas
de hoy cada path permitido tiene un solo método, así que solo estos pares
distinguen una lista indexada por `(path, método)` de una indexada por path (H-4).

La función se llama por el módulo (`auth_service.…`) para que un tramposo que
la reemplace en `src.auth.service` (ZP7, ZP20) la alcance.
"""
from __future__ import annotations

from fastapi.routing import APIRoute

from src.auth import service as auth_service
from src.main import app

PERMITIDAS = {
    ("/auth/me", "GET"), ("/auth/session", "POST"),
    ("/auth/logout", "POST"), ("/auth/contrasena", "POST"),
}
INEXISTENTES = (
    ("/auth/me", "POST"), ("/auth/me", "DELETE"),
    ("/auth/contrasena", "GET"), ("/auth/session", "GET"),
)


def test_up3_permitidas_por_path_y_metodo() -> None:
    """UP3 (C15): verdadero solo para los 4 pares; los 4 inexistentes, falso."""
    rutas = {(r.path, m) for r in app.routes if isinstance(r, APIRoute) for m in r.methods}
    permitidas = {par for par in rutas if auth_service.puede_con_contrasena_temporal(*par)}
    inexistentes = {par: auth_service.puede_con_contrasena_temporal(*par) for par in INEXISTENTES}
    assert {"permitidas": permitidas, "inexistentes": inexistentes} == {
        "permitidas": PERMITIDAS,
        "inexistentes": dict.fromkeys(INEXISTENTES, False),
    }
