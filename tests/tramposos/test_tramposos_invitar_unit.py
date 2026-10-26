"""Tramposos sin base de invitar profes — `docs/ESPEC_invitar_profe.md` §4.1.

  XP9   `crear_invitado` crea la cuenta ya confirmada (GoTrue no invitaría, P7) -> UI1
  XP12  `enviar` deja salir la excepción de GoTrue                               -> UI5
  XP13  `enviar` escribe el correo en el log                                     -> UI5
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest

from src.invitar import envio as envio_mod
from src.onboarding.cuentas import CORREO_EN_USO, CREADA, GoTrueAdmin
from tests.invitar import test_adaptador as ta
from tests.invitar import test_envio as te

Aplicar = Callable[[pytest.MonkeyPatch], None]


async def _crea_confirmada(self: GoTrueAdmin, id: UUID, correo: str) -> str:
    r = await self._pedir("POST", "/admin/users",
                          {"id": str(id), "email": correo, "email_confirm": True})
    if r.status_code in (200, 201):
        return CREADA
    return CORREO_EN_USO


_ENVIAR_INTERNO = envio_mod._enviar


async def _deja_salir(cuentas: Any, pedido: envio_mod.PedidoDeEnvio) -> str:
    return await _ENVIAR_INTERNO(cuentas, pedido)


async def _con_el_correo(cuentas: Any, pedido: envio_mod.PedidoDeEnvio) -> str:
    resultado = await _ENVIAR_INTERNO(cuentas, pedido)
    logging.getLogger("engrama.invitar").info("invitar: invitacion=%s correo=%s",
                                              pedido.invitacion_id, pedido.correo)
    return resultado


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[[], None], str]] = {
    "XP9": (lambda mp: mp.setattr(GoTrueAdmin, "crear_invitado", _crea_confirmada),
            ta.test_ui1_crear_invitado_sin_clave_y_sin_confirmar, r"'email_confirm': True"),
    "XP12": (lambda mp: mp.setattr(envio_mod, "enviar", _deja_salir),
             te.test_ui5_enviar_no_lanza_y_no_escribe_el_correo,
             r"'resultados': \('enviada', 'escapó ErrorCuenta', 'escapó RuntimeError'"),
    "XP13": (lambda mp: mp.setattr(envio_mod, "enviar", _con_el_correo),
             te.test_ui5_enviar_no_lanza_y_no_escribe_el_correo,
             r"'con_el_correo': \['invitar: invitacion=7 correo=profe-ui5@sintetico\.test'"),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(monkeypatch: pytest.MonkeyPatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    try:
        with pytest.raises(AssertionError, match=motivo):
            test_real()
    finally:
        # Los parches de httpx que deja `con_gotrue` (UI1) se sueltan aquí: fuera de su
        # módulo no corre su fixture `_soltar`.
        while ta._PARCHES:
            ta._PARCHES.pop().undo()
