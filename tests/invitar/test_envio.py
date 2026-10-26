"""UI5: `envio.enviar` nunca deja salir una excepción y su log no lleva el correo — ESPEC §4.

Sin base: el doble `GoTrueFalso`. `enviar` corre DESPUÉS de responder; una
excepción ahí no la ve nadie (y en Starlette tumbaría la conexión), y el correo
del profe no va a ningún log.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from src.invitar import envio
from src.invitar.envio import PedidoDeEnvio
from tests.invitar._ayuda import GoTrueFalso

CORREO = "profe-ui5@sintetico.test"


class _Captura(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lineas: list[str] = []

    def emit(self, registro: logging.LogRecord) -> None:
        self.lineas.append(registro.getMessage())


def _correr(falso: Any, pedido: PedidoDeEnvio) -> tuple[Any, list[str]]:
    captura = _Captura()
    log = logging.getLogger("engrama.invitar")
    nivel = log.level
    log.addHandler(captura)
    log.setLevel(logging.DEBUG)
    try:
        try:
            resultado: Any = asyncio.run(envio.enviar(falso, pedido))
        except Exception as exc:  # noqa: BLE001 — salir con una excepción ES el criterio roto
            resultado = f"escapó {type(exc).__name__}"
    finally:
        log.removeHandler(captura)
        log.setLevel(nivel)
    return resultado, captura.lineas


class _Explota(GoTrueFalso):
    async def estado_de_cuenta(self, id: Any) -> Any:
        raise RuntimeError(f"algo raro con {CORREO}")


def test_ui5_enviar_no_lanza_y_no_escribe_el_correo() -> None:
    pedido = PedidoDeEnvio(7, uuid4(), CORREO)
    bien, log_bien = _correr(GoTrueFalso(), pedido)
    caido = GoTrueFalso()
    caido.fallar = True
    mal, log_mal = _correr(caido, pedido)
    raro, log_raro = _correr(_Explota(), pedido)
    ajeno = GoTrueFalso()
    ajeno.sembrar(CORREO)
    ajena, log_ajena = _correr(ajeno, pedido)
    lineas = log_bien + log_mal + log_raro + log_ajena
    observado = {
        "resultados": (bien, mal, raro, ajena),
        "lineas": len(lineas),
        "con_el_correo": [x for x in lineas if CORREO in x or "sintetico" in x],
        "todas_nombran_la_invitacion": all("invitacion=7" in x for x in lineas),
    }
    assert observado == {
        "resultados": ("enviada", "fallo", "fallo", "cuenta_ajena"),
        "lineas": 4, "con_el_correo": [], "todas_nombran_la_invitacion": True,
    }, f"UI5: {observado}"
