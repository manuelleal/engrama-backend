"""Tramposos ZOV1-ZOV4 de la respuesta que debe ser una opción.

`docs/ESPEC_opcion_valida.md` §3. Una versión ROTA a propósito, inyectada con
monkeypatch en el módulo donde se USA (`calificar`, que `por_pregunta` llama
por el módulo); se corre el cuerpo del test real y se exige `AssertionError`
con el mensaje del mecanismo. Los de OV-U1 son no-integ; los de OV-A1, integ.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from src.challenge_engine.service import calificar as cal_mod
from src.challenge_engine.service.calificar import Pregunta
from tests.challenge_engine import test_opcion_valida as ta
from tests.challenge_engine import test_opcion_valida_unit as tu
from tests.tramposos.test_tramposos_l1 import correr


def _siempre_valida(p: Pregunta, respuesta: str) -> bool:
    """ZOV1: el comportamiento viejo (todo se califica y se guarda)."""
    return True


def _solo_labels(p: Pregunta, respuesta: str) -> bool:
    """ZOV2: compara solo la `label`; el `value` ("True") ya no vale."""
    if not any(str(o.get("label") or "").strip() for o in p.options):
        return True
    dada = cal_mod.normalizar(respuesta)
    return bool(dada) and dada in {cal_mod.normalizar(str(o.get("label") or ""))
                                   for o in p.options}


def _sin_normalizar(p: Pregunta, respuesta: str) -> bool:
    """ZOV3: compara el texto exacto (" v " o "true" ya no valen)."""
    if not any(str(o.get("label") or "").strip() for o in p.options):
        return True
    return respuesta in {str(o.get(c)) for o in p.options for c in ("label", "value")}


def _todo_es_cerrado(p: Pregunta, respuesta: str) -> bool:
    """ZOV4: toda pregunta es de opciones; la escrita sin opciones se rechaza siempre."""
    dada = cal_mod.normalizar(respuesta)
    return bool(dada) and dada in {cal_mod.normalizar(str(o.get(c) or ""))
                                   for o in p.options for c in ("label", "value")}


def _parche(valor: Callable[[Pregunta, str], bool]) -> Callable[[pytest.MonkeyPatch], None]:
    return lambda mp: mp.setattr(cal_mod, "es_opcion_valida", valor)


TRAMPOSOS: dict[str, tuple[Callable[[pytest.MonkeyPatch], None], Callable[..., None], str]] = {
    "ZOV1-U": (_parche(_siempre_valida), tu.test_ovu1_la_respuesta_es_una_opcion,
               r"'A': True"),
    "ZOV2-U": (_parche(_solo_labels), tu.test_ovu1_la_respuesta_es_una_opcion,
               r"'True': False"),
    "ZOV3-U": (_parche(_sin_normalizar), tu.test_ovu1_la_respuesta_es_una_opcion,
               r"' v ': False"),
    "ZOV4-U": (_parche(_todo_es_cerrado), tu.test_ovu1_la_respuesta_es_una_opcion,
               r"'lo que sea': False"),
    "ZOV1-A": (_parche(_siempre_valida), ta.test_ova1_lo_que_no_es_opcion_da_422_sin_escribir,
               r"'vfnd_A': \(200"),
    "ZOV2-A": (_parche(_solo_labels), ta.test_ova1_lo_que_no_es_opcion_da_422_sin_escribir,
               r"'vfnd_por_valor_True': \(422"),
    "ZOV4-A": (_parche(_todo_es_cerrado), ta.test_ova1_lo_que_no_es_opcion_da_422_sin_escribir,
               r"'escrita': \(422"),
}
SIN_BASE = tuple(c for c in TRAMPOSOS if c.endswith("-U"))


@pytest.mark.parametrize("clave", SIN_BASE)
def test_tramposo_puro_pone_rojo_su_test(monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        correr(test_real, {"monkeypatch": monkeypatch})


@pytest.mark.integ
@pytest.mark.parametrize("clave", [c for c in TRAMPOSOS if c not in SIN_BASE])
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    disponibles: dict[str, Any] = {"integ": integ, "monkeypatch": monkeypatch}
    with pytest.raises(AssertionError, match=motivo):
        correr(test_real, disponibles)
