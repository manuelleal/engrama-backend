"""OV-A1: `/answers` rechaza con 422, sin escribir nada, lo que no es una opción.

`docs/ESPEC_opcion_valida.md` §2 (C2 a C5), por HTTP. Lo observado va en un
dict que se compara ENTERO y se escribe en el humo ANTES de afirmar.
Tramposos: `tests/tramposos/test_tramposos_opcion_valida.py`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.challenge_engine import _l1 as l1
from tests.grader import _ayuda as gr

pytestmark = pytest.mark.integ

RUTA_HUMO = Path(__file__).resolve().parent.parent / "_salida" / "humo_opcion_valida.json"
NO_ES_OPCION = "Answer is not one of the question's options"
VFND = {"V": "True", "F": "False", "ND": "Not given"}
EXPLICACION_VFND = {"regla": "El texto dice que Tom vive en Lima.",
                    "por_opcion": {"F": "El texto sí lo dice: Tom lives in Lima.",
                                   "ND": "El texto lo dice en la primera línea."},
                    "ejemplo": "Tom lives in Lima."}


def test_ova1_lo_que_no_es_opcion_da_422_sin_escribir(integ) -> None:
    """OV-A1 (C2 a C5): V/F/ND, opción múltiple y escrita, por HTTP."""
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    lectura, qv = l1.reto(integ, c.profe, "lectura", [
        l1.pregunta("Tom lives in Lima.", "V", opciones=VFND, explanation=EXPLICACION_VFND),
        l1.pregunta("Tom has a cat.", "V", opciones=VFND)], grupo=c.grupo)
    abc, qa = l1.reto(integ, c.profe, "abc", [l1.pregunta()], grupo=c.grupo)
    escrita, qe = l1.reto(integ, c.profe, "escrita", [
        l1.pregunta("I ____ like fish.", "don't", tipo="fill_blank")], grupo=c.grupo)
    iv = l1.intento(integ, ana, lectura)[0]
    ia = l1.intento(integ, ana, abc)[0]
    ie = l1.intento(integ, ana, escrita)[0]
    observado: dict[str, Any] = {
        "vfnd_A": l1.responder(integ, ana, iv, qv[0], "A"),
        "vfnd_Verdadero": l1.responder(integ, ana, iv, qv[0], "Verdadero"),
        "mc_D": l1.responder(integ, ana, ia, qa[0], "D"),
        "tras_los_422": (
            l1.filas(integ, "select count(*) from challenge_attempt_answers"),
            int(integ.valor("select count(*) from coin_ledger")),
            integ.saldo("profile", ana),
            sorted(str(s) for (s,) in l1.filas(integ, "select status from challenge_attempts"))),
        "vfnd_F_valida": l1.responder(integ, ana, iv, qv[0], "F"),
        "vfnd_por_valor_True": l1.responder(integ, ana, iv, qv[1], "True"),
        "mc_B": l1.corta(l1.responder(integ, ana, ia, qa[0], "B")),
        "escrita": l1.corta(l1.responder(integ, ana, ie, qe[0], "cualquier cosa")),
    }
    RUTA_HUMO.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO.write_text(json.dumps(observado, ensure_ascii=False, indent=2, default=str),
                         encoding="utf-8")
    assert observado == {
        "vfnd_A": (422, NO_ES_OPCION),
        "vfnd_Verdadero": (422, NO_ES_OPCION),
        "mc_D": (422, NO_ES_OPCION),
        "tras_los_422": ([(0,)], 0, None, ["in_progress", "in_progress", "in_progress"]),
        "vfnd_F_valida": (200, (False, "F", "V", "True", {
            "idioma": "es", "regla": "El texto dice que Tom vive en Lima.",
            "por_opcion": "El texto sí lo dice: Tom lives in Lima.",
            "ejemplo": "Tom lives in Lima."}, False, 1, 2)),
        "vfnd_por_valor_True": (200, (True, "True", "V", "True", None, False, 2, 2)),
        "mc_B": (200, False, "B", False),
        "escrita": (200, False, "cualquier cosa", False),
    }, f"OV-A1: {observado}"
