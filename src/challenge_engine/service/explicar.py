"""De la pregunta guardada a lo que se le dice al estudiante — ESPEC_l1 §10.2.

El puente entre el ORM y las funciones puras de `calificar`: lo usan la
respuesta por pregunta (`/answers`) y el repaso, para calificar igual y
explicar igual. No escribe nada.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from src.challenge_engine.service import calificar
from src.challenge_engine.service.calificar import Pregunta
from src.shared.config import settings
from src.shared.models import ChallengeQuestion


def a_pregunta(q: ChallengeQuestion) -> Pregunta:
    """Lo que hace falta de la pregunta para calificarla (sin ORM)."""
    opciones = q.options_json if isinstance(q.options_json, list) else ()
    return Pregunta(
        question_type=q.question_type, correct_answer=q.correct_answer or "",
        options=tuple(o for o in opciones if isinstance(o, dict)),
        accepted_answers=tuple(q.accepted_answers or ()),
        tolerancia=q.tolerance or calificar.EXACTA, pista_inicial=bool(q.hint_initial))


@lru_cache(maxsize=4)
def _leer_vocabulario(ruta: str) -> frozenset[str]:
    """Las palabras del archivo (una por línea), ya normalizadas. Sin archivo, ninguna."""
    if not ruta:
        return frozenset()
    try:
        lineas = Path(ruta).read_text(encoding="utf-8").splitlines()
    except OSError:
        return frozenset()  # sin vocabulario la tolerancia es más amplia; no tumba nada
    return frozenset(n for n in (calificar.normalizar(x) for x in lineas) if n)


def vocabulario() -> frozenset[str]:
    """Las "palabras válidas" para la tolerancia de una letra (`LEXICO_ARCHIVO`)."""
    return _leer_vocabulario(settings.lexico_archivo)


def acerto(q: ChallengeQuestion, respuesta: str) -> bool:
    """¿Acertó esa pregunta? La ÚNICA calificación de `/answers` y del repaso."""
    return calificar.calificar(a_pregunta(q), respuesta, vocabulario())


def retroalimentar(q: ChallengeQuestion, nivel: str | None, *, respuesta: str,
                   acerto: bool) -> tuple[str, dict[str, Any] | None]:
    """`(la oración completa correcta, la explicación)` de UNA pregunta ya respondida.

    La explicación trae `por_opcion` solo de la opción que eligió y solo si
    falló; su idioma sale del banco o del nivel del reto. Sin explicación
    sembrada, `None` (la oración sale igual).
    """
    p = a_pregunta(q)
    guardada = q.explanation if isinstance(q.explanation, dict) else None
    oracion = calificar.oracion_correcta(
        q.question_text, p, (guardada or {}).get("oracion_correcta"))
    explicacion = calificar.explicacion_para(
        guardada, elegida=calificar.label_de(p, respuesta), acerto=acerto, nivel=nivel)
    return oracion, explicacion
