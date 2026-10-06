"""AH19 y sus tramposos — `docs/ESPEC_endurecimiento_piloto.md`, H-19.

El bloqueo por contraseña temporal, probado por HTTP en TODAS las rutas
registradas (antes: la función pura en UP3 y dos rutas de muestra en AP9).

Un usuario con `force_password_reset = true` llama a cada `(ruta, método)` de
`app.routes`, con los parámetros de ruta rellenados y sin cuerpo:
  - las rutas PÚBLICAS (sin `get_current_user`) deben ser exactamente las de
    `PUBLICAS`: una ruta nueva sin guarda hace fallar este test hasta que
    alguien la declare pública a propósito;
  - los 4 pares permitidos NO dan 403 `must_change_password`;
  - todas las demás dan EXACTAMENTE 403 `must_change_password`.

Como recorre `app.routes`, una ruta nueva entra sola.
"""
from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from src.auth import service as auth_service
from src.main import app
from tests.auth.test_permitidas_unit import PERMITIDAS
from tests.seguridad.veredictos import sembrar
from tests.teachers.test_access import guardia

pytestmark = pytest.mark.integ
client = TestClient(app, raise_server_exceptions=False)

# Las únicas rutas sin usuario. Agregar una aquí es una decisión, no un descuido.
# `/events/batch` no lleva usuario: la autentica la firma HMAC (ESPEC_eventos_anillo).
PUBLICAS = {("/health", "GET"), ("/auth/registro", "POST"), ("/events/batch", "POST")}
BLOQUEO = (403, "must_change_password")
_RELLENO = "11111111-1111-4111-8111-111111111111"


def _llamar(ruta: str, metodo: str, headers: dict[str, str]) -> tuple[int, Any]:
    url = re.sub(r"\{[^}]+\}", _RELLENO, ruta)
    r = client.request(metodo, url, headers=headers)
    try:
        detalle = r.json().get("detail")
    except (ValueError, AttributeError):
        detalle = None
    return r.status_code, detalle


def test_ah19_contrasena_temporal_bloquea_todas_las_rutas(integ) -> None:
    """AH19 (H-19): con contraseña temporal, 403 en todo menos en las 4 permitidas."""
    perfil = integ.crear_perfil(integ.crear_tenant(), rol="admin")
    sembrar(integ, "update profiles set force_password_reset = true where id = :p", p=perfil)
    headers = integ.headers(perfil)
    rutas = sorted({(r.path, m) for r in app.routes if isinstance(r, APIRoute)
                    for m in r.methods})
    publicas = {(r.path, m) for r in app.routes if isinstance(r, APIRoute)
                and guardia(r) == "public" for m in r.methods}
    respuestas = {par: _llamar(*par, headers) for par in rutas if par not in publicas}
    observado = {
        "publicas": sorted(publicas),
        "permitidas_que_se_bloquean": sorted(p for p in PERMITIDAS
                                             if respuestas.get(p) == BLOQUEO),
        "permitidas_que_no_existen": sorted(PERMITIDAS - set(respuestas)),
        "sin_bloquear": {f"{m} {p}": respuestas[(p, m)] for p, m in respuestas
                         if (p, m) not in PERMITIDAS and respuestas[(p, m)] != BLOQUEO},
        "hay_rutas": len(respuestas) >= 40,
    }
    assert observado == {
        "publicas": sorted(PUBLICAS), "permitidas_que_se_bloquean": [],
        "permitidas_que_no_existen": [], "sin_bloquear": {}, "hay_rutas": True,
    }, f"AH19: {observado}"


def test_zh19a_tramposo_todo_esta_permitido(integ, monkeypatch) -> None:
    """ZH19a: si la lista de permitidas deja pasar todo, AH19 lo ve en cada ruta."""
    monkeypatch.setattr(auth_service, "puede_con_contrasena_temporal", lambda *_: True)
    with pytest.raises(AssertionError, match=r"'sin_bloquear': \{'POST /admin/groups': \(422"):
        test_ah19_contrasena_temporal_bloquea_todas_las_rutas(integ)


async def _sin_guarda() -> dict[str, str]:
    return {"dato": "de alguien"}


def test_zh19b_tramposo_una_ruta_nueva_sin_guarda(integ, monkeypatch) -> None:
    """ZH19b: una ruta que no pasa por `get_current_user` aparece como pública no declarada."""
    rutas = [*app.router.routes, APIRoute("/core/sintetica", _sin_guarda, methods=["GET"])]
    monkeypatch.setattr(app.router, "routes", rutas)
    with pytest.raises(AssertionError, match=r"\('/core/sintetica', 'GET'\)"):
        test_ah19_contrasena_temporal_bloquea_todas_las_rutas(integ)
