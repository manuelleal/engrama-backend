"""UI1-UI3: el adaptador de GoTrue para invitar profes, sin red — `docs/ESPEC_invitar_profe.md` §4.

GoTrue se reemplaza por un `httpx.MockTransport` que contesta lo MEDIDO en el
banco (§1.1, P1-P9 y L1) y guarda cada petición. Cada test arma un dict con lo
observado y lo compara ENTERO (el mensaje lo trae).
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
import pytest

from src.onboarding import cuentas as cuentas_mod
from src.onboarding.cuentas import ErrorCuenta, GoTrueAdmin

ID = UUID("11111111-2222-4333-8444-555555555555")
CORREO = "profe@sintetico.test"
_ASYNC_CLIENT_REAL = httpx.AsyncClient

Respuesta = Callable[[httpx.Request], httpx.Response]


def con_gotrue(responder: Respuesta) -> tuple[GoTrueAdmin, list[dict[str, Any]]]:
    """Un `GoTrueAdmin` cuyo httpx habla con `responder`; devuelve también las peticiones."""
    vistas: list[dict[str, Any]] = []

    def transporte(peticion: httpx.Request) -> httpx.Response:
        cuerpo = json.loads(peticion.content) if peticion.content else None
        vistas.append({"metodo": peticion.method, "ruta": peticion.url.path, "cuerpo": cuerpo})
        return responder(peticion)

    def fabrica(**kw: Any) -> httpx.AsyncClient:
        return _ASYNC_CLIENT_REAL(transport=httpx.MockTransport(transporte), **kw)

    mp = pytest.MonkeyPatch()
    mp.setattr(cuentas_mod.httpx, "AsyncClient", fabrica)
    _PARCHES.append(mp)
    return GoTrueAdmin("http://gotrue.sintetico", "clave-sintetica"), vistas


_PARCHES: list[pytest.MonkeyPatch] = []


@pytest.fixture(autouse=True)
def _soltar() -> Any:
    yield
    while _PARCHES:
        _PARCHES.pop().undo()


def fija(status: int, cuerpo: dict[str, Any]) -> Respuesta:
    return lambda _p: httpx.Response(status, json=cuerpo)


def correr(coro: Any) -> Any:
    try:
        return asyncio.run(coro)
    except ErrorCuenta as exc:
        return f"ErrorCuenta: {exc}"


def test_ui1_crear_invitado_sin_clave_y_sin_confirmar() -> None:
    admin, vistas = con_gotrue(fija(200, {"id": str(ID), "email": CORREO}))
    creada = correr(admin.crear_invitado(ID, CORREO))
    admin2, _ = con_gotrue(fija(422, {"error_code": "email_exists", "msg": "x"}))
    en_uso = correr(admin2.crear_invitado(ID, CORREO))
    admin3, _ = con_gotrue(fija(200, {"id": "otro-id"}))
    ignora_id = correr(admin3.crear_invitado(ID, CORREO))
    observado = {"peticion": vistas, "creada": creada, "en_uso": en_uso,
                 "ignora_id": ignora_id}
    assert observado == {
        "peticion": [{"metodo": "POST", "ruta": "/admin/users",
                      "cuerpo": {"id": str(ID), "email": CORREO, "email_confirm": False}}],
        "creada": "creada", "en_uso": "correo_en_uso",
        "ignora_id": "ErrorCuenta: crear_invitado: GoTrue no respetó el id pedido (P1)",
    }, f"UI1: {observado}"


def test_ui2_invitar_y_recuperar_mapean_lo_medido() -> None:
    casos = {
        "200": fija(200, {"id": str(ID)}),
        "429": fija(429, {"error_code": "over_email_send_rate_limit"}),
        "422_email_exists": fija(422, {"error_code": "email_exists"}),
        "500": fija(500, {"error_code": "unexpected_failure"}),
    }
    observado: dict[str, Any] = {}
    for nombre, responder in casos.items():
        admin, vistas = con_gotrue(responder)
        observado[f"invitar_{nombre}"] = correr(admin.invitar(CORREO))
        observado[f"recuperar_{nombre}"] = correr(admin.recuperar(CORREO))
        observado.setdefault("rutas", [v["ruta"] for v in vistas])
        observado.setdefault("cuerpos", [v["cuerpo"] for v in vistas])
    assert observado == {
        "rutas": ["/invite", "/recover"],
        "cuerpos": [{"email": CORREO}, {"email": CORREO}],
        "invitar_200": "enviada", "recuperar_200": "enviada",
        "invitar_429": "limite_de_correos", "recuperar_429": "limite_de_correos",
        "invitar_422_email_exists": "ya_confirmada", "recuperar_422_email_exists": "ya_confirmada",
        "invitar_500": "ErrorCuenta: invitar: GoTrue respondió 500 unexpected_failure",
        "recuperar_500": "ErrorCuenta: recuperar: GoTrue respondió 500 unexpected_failure",
    }, f"UI2: {observado}"


def test_ui3_estado_de_cuenta_lee_la_confirmacion() -> None:
    def estado(responder: Respuesta) -> Any:
        admin, vistas = con_gotrue(responder)  # cada parche se usa enseguida: es global
        return correr(admin.estado_de_cuenta(ID)), vistas

    no_existe, _ = estado(fija(404, {"error_code": "user_not_found"}))
    sin_confirmar, vistas = estado(fija(200, {"email": CORREO, "email_confirmed_at": None}))
    confirmada, _ = estado(fija(200, {"email": CORREO,
                                      "email_confirmed_at": "2026-10-26T20:42:55Z"}))
    caida, _ = estado(fija(503, {}))
    observado = {"no_existe": no_existe, "sin_confirmar": sin_confirmar,
                 "confirmada": confirmada, "caida": caida, "peticion": vistas}
    assert observado == {
        "no_existe": None,
        "sin_confirmar": (CORREO, False),
        "confirmada": (CORREO, True),
        "caida": "ErrorCuenta: estado: GoTrue respondió 503 ",
        "peticion": [{"metodo": "GET", "ruta": f"/admin/users/{ID}", "cuerpo": None}],
    }, f"UI3: {observado}"
