"""Tramposos ZGA1 y ZGA2 del generador apagado — `docs/ESPEC_generador_apagado.md` §3.

Una versión ROTA a propósito; se corre el cuerpo de GA1 y se exige
`AssertionError` con el mensaje del mecanismo. No-integ.
"""
from __future__ import annotations

from collections.abc import Callable

import pytest

from src.challenge_engine import router as retos_router
from src.shared.config import Settings
from tests.challenge_engine import test_generador_apagado as ga

Aplicar = Callable[[pytest.MonkeyPatch], None]


def _sin_interruptor(mp: pytest.MonkeyPatch) -> None:
    """ZGA1: el endpoint no mira el interruptor."""
    mp.setattr(retos_router, "_exigir_generador_encendido", lambda: None)


class _SettingsEncendido(Settings):
    """La configuración rota de ZGA2: el interruptor nace en `True`."""

    challenges_generate_enabled: bool = True


def _encendido_por_defecto(mp: pytest.MonkeyPatch) -> None:
    """ZGA2: el valor por defecto es `True` (GA1 lee `Settings` de su módulo)."""
    mp.setattr(ga, "Settings", _SettingsEncendido)


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[..., None], str]] = {
    "ZGA1": (_sin_interruptor, ga.test_ga1_el_generador_nace_apagado,
             r"'apagado': \(418, 'llegó al generador', 1\)"),
    "ZGA2": (_encendido_por_defecto, ga.test_ga1_el_generador_nace_apagado,
             r"GA1: \{'por_defecto': True"),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        test_real(monkeypatch)
