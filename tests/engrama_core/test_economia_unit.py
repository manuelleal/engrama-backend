"""Pruebas PURAS (sin base) de `economia.py` — `docs/ESPEC_economia_oleada0.md` §2.

  UE3  la asistencia: 5 por asistir + 5 por puntualidad (C1)
  UE4  `compute_next_streak`: la misma fecha (o una futura) = 0, "sin cambio" (C6)
  UE1  `redondear_monedas`: la mitad hacia arriba, solo con enteros (C22)
  UE2  la guardia estática: ni `round`, ni `float`, ni `/` donde se calculan monedas (C23)

Cada test llama a la función por el módulo (`economia.f(...)`, no `from ... import`)
para que su tramposo (`tests/tramposos/test_tramposos_economia_unit.py`) pueda
reemplazarla.
"""
from __future__ import annotations

import inspect
from datetime import UTC, date, datetime, timedelta

import pytest

from src.engrama_core.service import attendance as attendance_mod
from src.engrama_core.service import economia
from src.shared.config import Settings
from tests.engrama_core import guardia_monedas as guardia

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


def test_ue4_la_misma_fecha_no_cambia_la_racha() -> None:
    """C6: 0 = sin cambio con la misma fecha y con una futura; los 4 casos de antes, idénticos."""
    hoy = date(2026, 4, 20)
    f = attendance_mod.compute_next_streak
    resultado = {
        "misma fecha": f(hoy, hoy),
        "fecha futura": f(hoy + timedelta(days=3), hoy),
        # los cuatro casos de siempre (también en test_attendance.TestComputeNextStreak)
        "nunca": f(None, hoy),
        "ayer": f(hoy - timedelta(days=1), hoy),
        "hace dos días": f(hoy - timedelta(days=2), hoy),
        "hace una semana": f(hoy - timedelta(days=7), hoy),
    }
    assert resultado == {"misma fecha": 0, "fecha futura": 0, "nunca": 1, "ayer": -1,
                         "hace dos días": 1, "hace una semana": 1}, f"UE4: {resultado}"


def test_ue1_el_redondeo_es_la_mitad_hacia_arriba() -> None:
    """C22: 2,5 -> 3 y 0,5 -> 1 (Python con round() daría 2 y 0); el denominador 0 es un error."""
    f = economia.redondear_monedas
    tabla = {"5/2": f(5, 2), "1/2": f(1, 2), "3/2": f(3, 2), "7/2": f(7, 2), "12/5": f(12, 5),
             "13/5": f(13, 5), "0/7": f(0, 7), "20/1": f(20, 1)}
    assert tabla == {"5/2": 3, "1/2": 1, "3/2": 2, "7/2": 4, "12/5": 2, "13/5": 3, "0/7": 0,
                     "20/1": 20}, f"UE1: {tabla}"
    for numerador, denominador in ((1, 0), (1, -2), (-1, 2)):
        with pytest.raises(ValueError):
            f(numerador, denominador)


def test_ue2_la_guardia_estatica_del_redondeo() -> None:
    """C23: 0 violaciones sobre el código real; y SÍ ve un `round(`, un `float` y un `/`."""
    # El control: la guardia mira de verdad el módulo de monedas (no un directorio vacío).
    assert (guardia.RAIZ_SRC / guardia.MODULOS_DE_MONEDAS[0]).is_file(), "UE2: no hay economia.py"
    real = guardia.revisar_codigo()
    assert real == {}, f"UE2: el código real tiene violaciones: {real}"

    casos = {  # texto -> (solo_monedas, violaciones esperadas)
        "round(": ("monto = round(n)\n", True, 1),
        "round( en todo src": ("monto = round(n)\n", False, 1),
        "float": ("monto = BASE * 1.5\n", True, 1),
        "float() ": ("monto = float(n)\n", True, 1),
        "división /": ("monto = n / d\n", True, 1),
        "/= ": ("monto /= 2\n", True, 1),
        # Fuera de los módulos de monedas el float y el / son legítimos (geocerca, porcentaje).
        "float fuera de monedas": ("distancia = 2 * 6371.5 / 3\n", False, 0),
        # Lo permitido: división entera y enteros.
        "// entera": ("monto = (2 * n + d) // (2 * d)\n", True, 0),
    }
    medido = {nombre: len(guardia.violaciones(texto, solo_monedas=monedas))
              for nombre, (texto, monedas, _) in casos.items()}
    esperado = {nombre: n for nombre, (_, _, n) in casos.items()}
    assert medido == esperado, f"UE2: violaciones por texto {medido}, esperadas {esperado}"
