"""OV-U1: ¿la respuesta es una de las opciones de la pregunta? Puro, sin base.

`docs/ESPEC_opcion_valida.md` §2 (C1) y §5 (réplica). Lo observado va en un
dict que se compara ENTERO. Tramposos: `tests/tramposos/test_tramposos_opcion_valida.py`.
"""
from __future__ import annotations

from typing import Any

from src.challenge_engine.service import calificar as cal
from src.challenge_engine.service.calificar import Pregunta

# La V/F/ND como la crea el sembrador (engrama-web/herramientas/sembrar/mapeo.mjs).
VFND = Pregunta("multiple_choice", "V", options=(
    {"label": "V", "value": "True"}, {"label": "F", "value": "False"},
    {"label": "ND", "value": "Not given"}))
ABC = Pregunta("multiple_choice", "A", options=(
    {"label": "A", "value": "goes"}, {"label": "B", "value": "go"},
    {"label": "C", "value": "going"}))
ESCRITA = Pregunta("fill_blank", "don't")
MC_SIN_OPCIONES = Pregunta("multiple_choice", "A")


def _replica() -> Pregunta:
    """Un juego de opciones que no está en ningún banco (§5)."""
    etiquetas = ("Yes", "No", "Maybe")
    valores = ("Afirmativo", "Negativo", "Tal vez")
    return Pregunta("multiple_choice", "Yes", options=tuple(
        {"label": e, "value": v} for e, v in zip(etiquetas, valores, strict=True)))


def _valida(p: Pregunta, *respuestas: str) -> dict[str, bool]:
    return {r: cal.es_opcion_valida(p, r) for r in respuestas}


def test_ovu1_la_respuesta_es_una_opcion() -> None:
    """OV-U1 (C1): label o value, con la normalización de la calificación; la escrita, todo."""
    observado: dict[str, Any] = {
        "vfnd": _valida(VFND, "V", "F", "ND", " v ", "nd.", "True", "false", "Not given",
                        "A", "Verdadero", "", "   ", "VF", "T"),
        "abc": _valida(ABC, "A", "b", "goes", "D", "V"),
        "escrita": _valida(ESCRITA, "lo que sea", ""),
        "mc_sin_opciones": _valida(MC_SIN_OPCIONES, "lo que sea"),
        "replica": _valida(_replica(), "Yes", "maybe", "Tal vez", "negativo.", "V", "Si"),
    }
    assert observado == {
        "vfnd": {"V": True, "F": True, "ND": True, " v ": True, "nd.": True, "True": True,
                 "false": True, "Not given": True, "A": False, "Verdadero": False, "": False,
                 "   ": False, "VF": False, "T": False},
        "abc": {"A": True, "b": True, "goes": True, "D": False, "V": False},
        "escrita": {"lo que sea": True, "": True},
        "mc_sin_opciones": {"lo que sea": True},
        "replica": {"Yes": True, "maybe": True, "Tal vez": True, "negativo.": True,
                    "V": False, "Si": False},
    }, f"OV-U1: {observado}"
