"""Pruebas PURAS (sin base) de `economia.py` — `docs/ESPEC_economia_oleada0.md` §2.

  UE3  la asistencia: 5 por asistir + 5 por puntualidad (C1)

Cada test llama a la función por el módulo (`economia.f(...)`, no `from ... import`)
para que su tramposo (`tests/tramposos/test_tramposos_economia_unit.py`) pueda
reemplazarla. Los siguientes commits de la oleada agregan aquí UE4 (racha),
UE1 y UE2 (redondeo y guardia estática).
"""
from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

from src.engrama_core.service import economia
from src.shared.config import Settings

APERTURA = datetime(2026, 10, 6, 23, 0, tzinfo=UTC)  # las 18:00 de Bogotá


def _pago(segundos: int, *, base: int = 5, bono: int = 5, minutos: int = 5) -> int:
    llegada = APERTURA + timedelta(seconds=segundos)
    return economia.desglose_asistencia(
        llegada, APERTURA, base=base, bono=bono, minutos=minutos
    ).total


def test_ue3_la_asistencia_paga_5_mas_5_por_puntualidad() -> None:
    """C1: el límite de los 5 minutos es inclusivo; la racha no entra; los defectos son 5, 5, 5."""
    tabla = {
        "0 s": _pago(0),
        "5:00": _pago(5 * 60),
        "5:01": _pago(5 * 60 + 1),
        "antes de abrir": _pago(-30),
        # con otra configuración (4, 3 y 10 minutos) la misma función paga 7 y 4
        "min 8 con 4+3/10": _pago(8 * 60, base=4, bono=3, minutos=10),
        "min 10 con 4+3/10": _pago(10 * 60, base=4, bono=3, minutos=10),
        "min 11 con 4+3/10": _pago(11 * 60, base=4, bono=3, minutos=10),
    }
    assert tabla == {
        "0 s": 10, "5:00": 10, "5:01": 5, "antes de abrir": 10,
        "min 8 con 4+3/10": 7, "min 10 con 4+3/10": 7, "min 11 con 4+3/10": 4,
    }, f"UE3: {tabla}"

    # El desglose dice de dónde sale cada moneda (va al asiento del libro).
    tarde = economia.desglose_asistencia(
        APERTURA + timedelta(minutes=6), APERTURA, base=5, bono=5, minutos=5
    )
    assert (tarde.base, tarde.puntualidad, tarde.puntual) == (5, 0, False), f"UE3: {tarde}"

    # La función NO recibe la racha: no hay forma de que multiplique.
    parametros = set(inspect.signature(economia.desglose_asistencia).parameters)
    assert parametros == {"llegada", "apertura", "base", "bono", "minutos"}, f"UE3: {parametros}"

    # Los tres defectos son los de la espec (se leen de la clase, no del .env).
    campos = Settings.model_fields
    defectos = {n: campos[n].default for n in (
        "asistencia_monedas_base", "asistencia_monedas_puntualidad",
        "asistencia_minutos_puntualidad")}
    assert defectos == {"asistencia_monedas_base": 5, "asistencia_monedas_puntualidad": 5,
                        "asistencia_minutos_puntualidad": 5}, f"UE3: {defectos}"
