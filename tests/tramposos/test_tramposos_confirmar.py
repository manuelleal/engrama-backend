"""Tramposo ZR50 — `docs/ESPEC_confirmar_protegido.md` §2.

ZR50: el paso de GoTrue protege solo `ErrorCuenta`, como antes de este cambio.
Cualquier otra excepción sube sin compensar: 500, la cuenta queda viva y la
solicitud en `creando`. Rojo predicho: AR30, y solo AR30.

Va en su propio archivo (y no en el diccionario de
`test_tramposos_autorregistro.py`) para no chocar con las ramas paralelas que
también agregan tramposos ahí. Usa su mismo `correr`.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from src.onboarding.cuentas import ErrorCuenta
from src.registro import service as service_mod
from tests.registro import _ayuda as ay
from tests.registro import test_confirmar_protegido as tcp
from tests.tramposos.test_tramposos_autorregistro import correr

pytestmark = pytest.mark.integ


@pytest.fixture(autouse=True)
def _soltar_el_doble_al_terminar() -> Iterator[None]:
    """El doble de GoTrue no puede quedar puesto para el resto de la suite."""
    yield
    ay.soltar()


async def _protege_solo_error_cuenta(db: Any, cuentas: Any, reserva: Any, datos: Any) -> str:
    """El código de antes: solo `ErrorCuenta` se compensa."""
    try:
        return await service_mod._crear_cuenta(cuentas, reserva.profile_id,
                                               datos.correo_normalizado(), datos.contrasena)
    except ErrorCuenta as exc:
        await service_mod._deshacer(db, cuentas, reserva, puede_haber_cuenta=True)
        raise service_mod.RegistroNoDisponible() from exc


def test_zr50_tramposo_pone_rojo_ar30(integ, monkeypatch, caplog) -> None:
    monkeypatch.setattr(service_mod, "_crear_cuenta_o_deshacer", _protege_solo_error_cuenta)
    with pytest.raises(AssertionError,
                       match=r"AR30: \{'inesperado': \{'respuesta': \(500, None\), "
                             r"'borrar_la_cuenta_del_perfil': False, 'cuenta': True"):
        correr(tcp.test_ar30_si_crear_falla_con_cualquier_cosa_no_queda_cuenta,
               integ, monkeypatch, caplog)
