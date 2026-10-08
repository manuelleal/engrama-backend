"""Tramposos ZE (no-integ) de la economía, oleada 0 — `docs/ESPEC_economia_oleada0.md` §3.2.

Una versión ROTA a propósito, inyectada con monkeypatch en el módulo donde se
USA; se corre el cuerpo del test puro y se exige `AssertionError` con el
mensaje del mecanismo. Aquí se automatiza la DIAGONAL (la columna "Rojo
predicho" de la espec); lo que cada tramposo deja verde se mide aparte.

  ZE1  el redondeo usa round(n / d)    -> UE1 (5/2 da 2)
  ZE2  la guardia no mira los float    -> UE2 (0 violaciones donde debe haber una)
  ZE3  la puntualidad se paga siempre  -> UE3 (5:01 da 10)
  ZE4  la misma fecha devuelve 1       -> UE4
  ZE6  el tope no se valida ni se aplica -> UE6 (21 pasa)

Los de la recarga y la alerta (ZE5, ZE7) entran con el commit que crea su pieza.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Any

import pytest

from src.engrama_core.service import attendance as attendance_mod
from src.engrama_core.service import economia as economia_mod
from tests.challenge_engine import test_economia_retos as er
from tests.engrama_core import guardia_monedas as guardia_mod
from tests.engrama_core import test_economia_unit as ue

Aplicar = Callable[[pytest.MonkeyPatch], None]


def _siempre_puntual(llegada: datetime, apertura: datetime, minutos: int) -> bool:
    """ZE3: no mira el reloj; todos son puntuales."""
    del llegada, apertura, minutos
    return True


_SIGUIENTE_RACHA_BUENA = attendance_mod.compute_next_streak


def _misma_fecha_reinicia(last_attendance_date: date | None, today: date) -> int:
    """ZE4: con la misma fecha devuelve 1 (como el código de antes de la oleada 0)."""
    bueno = _SIGUIENTE_RACHA_BUENA(last_attendance_date, today)
    return 1 if bueno == 0 else bueno


def _redondeo_de_python(numerador: int, denominador: int) -> int:
    """ZE1: round(n / d), el redondeo bancario de Python (round(2.5) == 2)."""
    return round(numerador / denominador)


_VIOLACIONES_BUENA = guardia_mod.violaciones


def _guardia_ciega_a_los_float(texto: str, *, solo_monedas: bool) -> list[str]:
    """ZE2: la guardia no mira las constantes ni las llamadas `float`."""
    return [v for v in _VIOLACIONES_BUENA(texto, solo_monedas=solo_monedas) if "float" not in v]


def _sin_tope(coins_reward: int, tope: int) -> int:
    """ZE6: ni valida ni topa (devuelve el valor tal cual)."""
    del tope
    return coins_reward


def _parche(modulo: Any, nombre: str, valor: Any) -> Aplicar:
    return lambda mp: mp.setattr(modulo, nombre, valor)


def _varios(*aplicar: Aplicar) -> Aplicar:
    def todos(mp: pytest.MonkeyPatch) -> None:
        for uno in aplicar:
            uno(mp)
    return todos


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[[], None], str]] = {
    "ZE1": (_parche(economia_mod, "redondear_monedas", _redondeo_de_python),
            ue.test_ue1_el_redondeo_es_la_mitad_hacia_arriba,
            r"UE1: \{'5/2': 2,"),
    "ZE2": (_parche(guardia_mod, "violaciones", _guardia_ciega_a_los_float),
            ue.test_ue2_la_guardia_estatica_del_redondeo,
            r"UE2: violaciones por texto \{.*'float': 0"),
    "ZE3": (_parche(economia_mod, "es_puntual", _siempre_puntual),
            ue.test_ue3_la_asistencia_paga_5_mas_5_por_puntualidad,
            r"UE3: \{.*'5:01': 10"),
    "ZE4": (_parche(attendance_mod, "compute_next_streak", _misma_fecha_reinicia),
            ue.test_ue4_la_misma_fecha_no_cambia_la_racha,
            r"UE4: \{'misma fecha': 1,"),
    "ZE6": (_varios(_parche(economia_mod, "exigir_tope_del_reto", _sin_tope),
                    _parche(economia_mod, "recompensa_del_reto", _sin_tope)),
            er.test_ue6_el_tope_se_valida_y_se_aplica,
            r"UE6: 21 pasó la validación del tope"),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        test_real()
