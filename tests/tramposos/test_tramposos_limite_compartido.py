"""Tramposos del límite compartido — `docs/ESPEC_limites_registro.md` §3.

Una versión ROTA a propósito; se corre el cuerpo del test real y se exige
`AssertionError` con el mensaje del mecanismo (la diagonal).

  ZR38  IPv6 por dirección completa (`_agrupar` tal cual)           -> LC1
  ZR39  `anotar_codigo` anota siempre (el código de antes de 33a0796) -> LC2
  ZR40  el candado ocupado no se trata (sube como 500)              -> LC3
  ZR41  los contadores en la memoria de cada proceso (el de f7f7aeb) -> DP1
  ZR42  sin candado entre revisar y anotar                          -> DP1
  ZR43  la bajada de 046 no hace nada                               -> MG46

ZR41 y ZR42 se aplican DENTRO de los procesos hijos (`--modo` de
`tests/registro/_dos_procesos.py`): un monkeypatch aquí no los alcanzaría.
"""
from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from src.registro import limite as limite_mod
from tests.integ import test_migracion_046 as mg
from tests.registro import test_limite_compartido as tlc

pytestmark = pytest.mark.integ

Correr = Callable[[Any, pytest.MonkeyPatch], None]
_ANOTAR_CODIGO_BUENO = limite_mod.anotar_codigo


async def _anota_siempre(conn: Any, huella_del_codigo: str, *, valido: bool) -> None:
    await _ANOTAR_CODIGO_BUENO(conn, huella_del_codigo, valido=True)


def _zr38(integ: Any, mp: pytest.MonkeyPatch) -> None:
    mp.setattr(limite_mod, "_agrupar", lambda valor: valor)
    tlc.test_lc1_un_64_que_rota_direcciones_es_un_solo_cubo(integ)


def _zr39(integ: Any, mp: pytest.MonkeyPatch) -> None:
    mp.setattr(limite_mod, "anotar_codigo", _anota_siempre)
    tlc.test_lc2_la_avalancha_anonima_no_bloquea_a_los_grupos(integ)


def _zr40(integ: Any, mp: pytest.MonkeyPatch) -> None:
    mp.setattr(limite_mod, "_es_candado_ocupado", lambda exc: False)
    tlc.test_lc3_con_el_candado_ocupado_429_y_no_500(integ, mp)


def _dp1_con(modo: str) -> Correr:
    def correr(integ: Any, mp: pytest.MonkeyPatch) -> None:
        observado = tlc.medir_dos_procesos(integ, modo)
        observado.pop("por_proceso")
        assert observado == {
            "salidas": [0, 0], "se_solaparon": True, "admitidos": 10,
            "una_llave_por_proceso": [1, 1],
            "filas_por_ip": 10, "filas_global": 6, "global_lleno_visto_desde_aqui": True,
            "errores": [],
        }, f"DP1 ({modo}): {observado}"
    return correr


def _zr43(integ: Any, mp: pytest.MonkeyPatch) -> None:
    """La migración cuya bajada no borra nada."""
    mg.cuerpo_mg46(integ, SimpleNamespace(SQL_SUBIR=mg.M046.SQL_SUBIR, SQL_BAJAR=()))


TRAMPOSOS: dict[str, tuple[Correr, str]] = {
    "ZR38": (_zr38, r"'el_61': \(403, 'codigo_no_valido', False\)"),
    "ZR39": (_zr39, r"'basura': \[403, 403, 403, 403, 403, 429"),
    "ZR40": (_zr40, r"'con_candado_tomado': \(500"),
    # Sin exigir que los procesos se solapen: en memoria salen 20 igual, y sin
    # candado la carrera se ve ya dentro de cada proceso (30 a la vez).
    "ZR41": (_dp1_con("memoria"), r"'admitidos': 20, 'una_llave_por_proceso': \[1, 1\], "
                                  r"'filas_por_ip': 0"),
    "ZR42": (_dp1_con("sin_candado"), r"'admitidos': (1[1-9]|[2-9]\d)\b"),
    "ZR43": (_zr43, r"'tras_bajar': \{'la_tabla': \{'existe': True"),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    correr, motivo = TRAMPOSOS[clave]
    with pytest.raises(AssertionError, match=motivo):
        correr(integ, monkeypatch)
