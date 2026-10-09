"""Tramposos ZK del desglose del check-in — `docs/ESPEC_economia_oleada0.md` §13.2.

Una versión ROTA a propósito de `economia.cobro_de_asistencia` (la que `check_in`
usa), inyectada con monkeypatch en el módulo donde se USA. Se corre el cuerpo del
test real y se exige `AssertionError` con el mensaje del mecanismo. Se automatiza
la DIAGONAL (la columna "Rojo predicho"); los cruces no se miden.

  contra el test puro (no-integ)            contra la ruta (integ)
  ZK1  el desglose no suma (base + 1)       ZK4  -> CK1
  ZK2  ya_cobrada_hoy siempre falso         ZK5  -> CK3
  ZK3  puntual siempre verdadero            ZK6  -> CK2
  (ZK1-ZK3 -> UK1)
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from src.engrama_core.service import economia as economia_mod
from tests.engrama_core import test_checkin_desglose as ck
from tests.engrama_core import test_checkin_desglose_unit as uk

_COBRO_BUENO = economia_mod.cobro_de_asistencia


def _cobro_que_no_suma(pago: economia_mod.DesgloseAsistencia, *,
                       ya_cobrada: bool) -> economia_mod.CobroAsistencia:
    """ZK1/ZK4: la base sale una moneda de más: base + puntualidad no suma el total."""
    c = _COBRO_BUENO(pago, ya_cobrada=ya_cobrada)
    return c._replace(base=c.base + 1)


def _cobro_siempre_no_cobrado(pago: economia_mod.DesgloseAsistencia, *,
                              ya_cobrada: bool) -> economia_mod.CobroAsistencia:
    """ZK2/ZK5: ignora que la paga de hoy ya estaba cobrada (la bandera siempre falsa)."""
    del ya_cobrada
    return _COBRO_BUENO(pago, ya_cobrada=False)


def _cobro_siempre_puntual(pago: economia_mod.DesgloseAsistencia, *,
                           ya_cobrada: bool) -> economia_mod.CobroAsistencia:
    """ZK3/ZK6: `puntual` verdadero aunque haya llegado tarde."""
    return _COBRO_BUENO(pago, ya_cobrada=ya_cobrada)._replace(puntual=True)


# id -> (función rota, test real, mensaje con el que debe caer)
PUROS: dict[str, tuple[Callable[..., Any], Callable[..., None], str]] = {
    "ZK1": (_cobro_que_no_suma, uk.test_uk1_el_cobro_de_la_asistencia_suma_y_distingue_ya_cobrada,
            r"UK1: \{'puntual': \(6, 5, True, False\)"),
    "ZK2": (_cobro_siempre_no_cobrado,
            uk.test_uk1_el_cobro_de_la_asistencia_suma_y_distingue_ya_cobrada,
            r"UK1: \{.*'ya cobrada, puntual': \(5, 5, True, False\)"),
    "ZK3": (_cobro_siempre_puntual,
            uk.test_uk1_el_cobro_de_la_asistencia_suma_y_distingue_ya_cobrada,
            r"UK1: \{.*'tarde': \(5, 0, True, False\)"),
}

DE_LA_RUTA: dict[str, tuple[Callable[..., Any], Callable[..., None], str]] = {
    "ZK4": (_cobro_que_no_suma, ck.test_ck1_el_checkin_puntual_dice_el_desglose,
            r"CK1: el desglose es \{'coins_awarded': 10, 'base': 6,"),
    "ZK5": (_cobro_siempre_no_cobrado,
            ck.test_ck3_la_segunda_sesion_del_dia_dice_que_ya_estaba_cobrada,
            r"CK3: la 2\.ª dijo \{'coins_awarded': 0, 'base': 5, 'puntualidad': 5, "
            r"'puntual': True, 'ya_cobrada_hoy': False\}"),
    "ZK6": (_cobro_siempre_puntual, ck.test_ck2_el_checkin_tarde_no_es_puntual,
            r"CK2: a los 5:01 el desglose es \{'coins_awarded': 5, 'base': 5, "
            r"'puntualidad': 0, 'puntual': True,"),
}


@pytest.mark.parametrize("clave", list(PUROS))
def test_tramposo_puro_pone_rojo_su_test(monkeypatch, clave: str) -> None:
    rota, test_real, motivo = PUROS[clave]
    monkeypatch.setattr(economia_mod, "cobro_de_asistencia", rota)
    with pytest.raises(AssertionError, match=motivo):
        test_real()


@pytest.mark.integ
@pytest.mark.parametrize("clave", list(DE_LA_RUTA))
def test_tramposo_de_la_ruta_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    rota, test_real, motivo = DE_LA_RUTA[clave]
    monkeypatch.setattr(economia_mod, "cobro_de_asistencia", rota)
    integ.truncar_todo()  # el test real arranca con la base vacía
    with pytest.raises(AssertionError, match=motivo):
        test_real(integ, monkeypatch)
