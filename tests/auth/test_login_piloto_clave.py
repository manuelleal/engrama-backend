"""Login del piloto, contraseña temporal — `docs/ESPEC_login_piloto.md` §1.5, C9 y C10.

  AP9   C9   con `force_password_reset = true`: `/auth/me` y `/auth/session`
             dan 200 (`must_change_password: true`); `GET /challenges/` y
             `GET /core/coins/balance` dan 403 `must_change_password`, también
             con un token que trae `user_metadata.must_change_password = false`.
             Control: otro usuario sin la bandera -> 200.
  AP10  C10  `POST /auth/contrasena`: "corta" -> 422 sin llamar a GoTrue; una
             clave válida -> 204, el doble registró (token, clave), la bandera
             queda en false y el MISMO token entra; si el doble falla -> 502 y
             la bandera sigue en true.

Viven aparte de `test_login_piloto.py` (AP1-AP8, SP1) para que ningún archivo
pase de 400 líneas (ESPEC §5). Mismas reglas (ESPEC §3): el cliente con
`raise_server_exceptions=False`, las claves con `.get()`, lo observado en un
dict comparado entero, y el estado previo sembrado en la base (ERR-9).

GoTrue se reemplaza por `CambioFalso` con `app.dependency_overrides`, que se
deshace SIEMPRE en un `finally` (`test_h3_sin_overrides_de_dependencias_filtrados`).
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.auth.cuentas import CambioFallido, get_cambio_de_clave
from src.main import app
from tests.seguridad.veredictos import sembrar

from .conftest import make_jwt
from .test_login_piloto import _cuerpo, _estado

pytestmark = pytest.mark.integ
client = TestClient(app, raise_server_exceptions=False)

DEBE_CAMBIAR = "must_change_password"
CLAVE_NUEVA = "Sintetica-2026-ok"


class CambioFalso:
    """Doble de `CambioDeClave`: registra (token, clave); con `fallar`, lanza `CambioFallido`."""

    def __init__(self) -> None:
        self.llamadas: list[tuple[str, str]] = []
        self.fallar = False

    async def cambiar(self, token: str, nueva: str) -> None:
        self.llamadas.append((token, nueva))
        if self.fallar:
            raise CambioFallido("doble")


@contextmanager
def gotrue_falso() -> Iterator[CambioFalso]:
    doble = CambioFalso()
    app.dependency_overrides[get_cambio_de_clave] = lambda: doble
    try:
        yield doble
    finally:
        app.dependency_overrides.pop(get_cambio_de_clave, None)


def _con_clave_temporal(integ: Any, tenant: UUID) -> UUID:
    alumno: UUID = integ.crear_perfil(tenant)
    sembrar(integ, "update profiles set force_password_reset = true where id = :p", p=alumno)
    return alumno


def _bandera(integ: Any, perfil: UUID) -> Any:
    return integ.valor("select force_password_reset from profiles where id = :p", p=perfil)


# =============================================================================
# AP9 — C9: el bloqueo
# =============================================================================
def test_ap9_contrasena_temporal_bloquea_menos_cuatro_rutas(integ) -> None:
    """AP9 (C9): con la bandera, `/auth/me` y `/auth/session` sí; lo demás, 403."""
    tenant = integ.crear_tenant()
    alumno = _con_clave_temporal(integ, tenant)
    otro = integ.crear_perfil(tenant)
    h = integ.headers(alumno)
    metadatos = {"Authorization": "Bearer " + make_jwt(
        sub=str(alumno), extra_claims={"user_metadata": {DEBE_CAMBIAR: False}})}

    me = client.get("/auth/me", headers=h)
    observado = {
        "me": (me.status_code, _cuerpo(me).get(DEBE_CAMBIAR)),
        "session": client.post("/auth/session", headers=h).status_code,
        "bloqueadas": {ruta: _estado(client.get(ruta, headers=h))
                       for ruta in ("/challenges/", "/core/coins/balance")},
        "con_metadatos_false": _estado(client.get("/challenges/", headers=metadatos)),
        "control_sin_bandera": {ruta: client.get(ruta, headers=integ.headers(otro)).status_code
                                for ruta in ("/challenges/", "/core/coins/balance")},
    }
    assert observado == {
        "me": (200, True),
        "session": 200,
        "bloqueadas": {"/challenges/": (403, DEBE_CAMBIAR),
                       "/core/coins/balance": (403, DEBE_CAMBIAR)},
        "con_metadatos_false": (403, DEBE_CAMBIAR),
        "control_sin_bandera": {"/challenges/": 200, "/core/coins/balance": 200},
    }


# =============================================================================
# AP10 — C10: el cambio
# =============================================================================
def test_ap10_cambio_de_contrasena(integ) -> None:
    """AP10 (C10): 422 sin llamar; 204 y la bandera en false; el doble falla -> 502."""
    tenant = integ.crear_tenant()
    alumno = _con_clave_temporal(integ, tenant)
    otro = _con_clave_temporal(integ, tenant)
    h = integ.headers(alumno)
    token = h["Authorization"].removeprefix("Bearer ")

    with gotrue_falso() as doble:
        corta = client.post("/auth/contrasena", headers=h, json={"nueva": "corta"})
        antes_de_cambiar = {"status": corta.status_code, "llamadas": list(doble.llamadas),
                            "bandera": _bandera(integ, alumno)}

        buena = client.post("/auth/contrasena", headers=h, json={"nueva": CLAVE_NUEVA})
        cambio = {"status": buena.status_code, "llamadas": list(doble.llamadas),
                  "bandera": _bandera(integ, alumno),
                  "mismo_token": client.get("/challenges/", headers=h).status_code}

        doble.fallar = True
        caida = client.post("/auth/contrasena", headers=integ.headers(otro),
                            json={"nueva": CLAVE_NUEVA})
        falla = {"status": _estado(caida), "bandera": _bandera(integ, otro)}

    assert {"corta": antes_de_cambiar, "valida": cambio, "gotrue_falla": falla} == {
        "corta": {"status": 422, "llamadas": [], "bandera": True},
        "valida": {"status": 204, "llamadas": [(token, CLAVE_NUEVA)], "bandera": False,
                   "mismo_token": 200},
        "gotrue_falla": {"status": (502, "password_change_failed"), "bandera": True},
    }
