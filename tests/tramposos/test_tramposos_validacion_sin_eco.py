"""Tramposos ZV (no-integ) del 422 sin eco — `docs/ESPEC_autorregistro.md` §13.1.

Una versión ROTA a propósito de `validacion.sin_valores_enviados` (la que
`RutaSinEco` usa), inyectada con monkeypatch en el módulo donde se USA. Se corre
el cuerpo del test real y se exige `AssertionError` con el mensaje del mecanismo.
Se automatiza la DIAGONAL (la columna "Rojo predicho"); los cruces no se miden.

  ZV1  devuelve la lista tal cual (el comportamiento de hoy)  -> VE1, VE2, VE3
  ZV2  quita `input` solo si es texto (deja el cuerpo entero del campo faltante)
                                                              -> VE1, VE2, VE3
  ZV3  deja solo `msg` (cambia la forma del error)            -> VE1, VE2, VE3
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pytest

from src.shared import validacion
from tests.registro import test_validacion_sin_eco as ve


def _tal_cual(errores: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """ZV1: no quita nada (lo que hacía el backend antes de este cambio)."""
    return [dict(e) for e in errores]


def _solo_si_es_texto(errores: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """ZV2: quita `input` de los errores de campo (texto) y deja pasar el cuerpo entero."""
    return [{k: v for k, v in e.items() if not (k == "input" and isinstance(v, str))}
            for e in errores]


def _solo_msg(errores: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """ZV3: deja solo `msg` (sin `input`, pero también sin `loc` ni `type`)."""
    return [{"msg": e.get("msg")} for e in errores]


Registro = dict[str, tuple[Callable[..., Any], list[tuple[Callable[[], None], str]]]]

TRAMPOSOS: Registro = {
    "ZV1": (_tal_cual, [
        (ve.test_ve1_sin_valores_enviados_quita_input_y_nada_mas, r"VE1: quedó un input"),
        (ve.test_ve2_el_422_del_registro_no_devuelve_valores,
         r"VE2: \d+ problemas en \d+ casos: .*un error trae `input`"),
        (ve.test_ve3_el_422_del_cambio_de_contrasena_no_devuelve_valores,
         r"VE3: \d+ problemas: .*un error trae `input`"),
    ]),
    "ZV2": (_solo_si_es_texto, [
        (ve.test_ve1_sin_valores_enviados_quita_input_y_nada_mas, r"VE1: quedó un input"),
        (ve.test_ve2_el_422_del_registro_no_devuelve_valores,
         r"VE2: \d+ problemas en \d+ casos: .*falta (codigo|contrasena): devolvió la marca"),
        (ve.test_ve3_el_422_del_cambio_de_contrasena_no_devuelve_valores,
         r"VE3: \d+ problemas: .*falta nueva y campo de mas: devolvió la marca 'MARCA-VIEJA'"),
    ]),
    "ZV3": (_solo_msg, [
        (ve.test_ve1_sin_valores_enviados_quita_input_y_nada_mas,
         r"VE1: cambió algo más que input"),
        (ve.test_ve2_el_422_del_registro_no_devuelve_valores,
         r"VE2: \d+ problemas en \d+ casos: .*le falta loc, msg o type"),
        (ve.test_ve3_el_422_del_cambio_de_contrasena_no_devuelve_valores,
         r"VE3: \d+ problemas: .*le falta loc, msg o type"),
    ]),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(monkeypatch, clave: str) -> None:
    rota, diagonal = TRAMPOSOS[clave]
    monkeypatch.setattr(validacion, "sin_valores_enviados", rota)
    for test_real, motivo in diagonal:
        with pytest.raises(AssertionError, match=motivo):
            test_real()
