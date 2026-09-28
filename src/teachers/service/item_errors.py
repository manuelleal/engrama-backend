"""T7 — indicador n.º 1 del pedagogo: ítems con más error — ESPEC §2.3 (ERR-16).

Mismo alcance que T5 (`achievement.primeros_en_ventana`), agrupado por
`question_id` en vez de por eje. Funciones puras (`compute_item_errors`,
`_top_distractor`) + `build_response`, que es la única parte con DB.
"""
from __future__ import annotations

import functools
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.models import ChallengeQuestion, Group
from src.teachers.schemas import (
    DistractorOut,
    ItemErrorOut,
    ItemErrorsMethodOut,
    ItemErrorsOut,
)
from src.teachers.service import achievement as achievement_service
from src.teachers.service import panel as panel_service
from src.teachers.service.achievement import AttemptRow, skill_to_axis

MIN_RESPONDENTS = 5

METHOD = ItemErrorsMethodOut(
    window_days=achievement_service.WINDOW_DAYS,
    first_attempt_only=True,
    min_respondents=MIN_RESPONDENTS,
    excluded_types=list(achievement_service.EXCLUDED_TYPES),
)


@dataclass(frozen=True)
class QuestionMeta:
    """Lo que se necesita de `challenge_questions` para un ítem — §2.3."""

    question_id: UUID
    order_index: int
    question_text: str
    options_json: list[dict[str, Any]] | None
    correct_answer: str | None


def _normalizar(texto: str | None) -> str:
    return (texto or "").strip().lower()


def _buscar_opcion(
    dado_norm: str, opciones: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """§2.3.3.1: compara primero con `value`, después con `label`."""
    for op in opciones:
        if dado_norm == _normalizar(str(op.get("value", ""))):
            return op
    for op in opciones:
        if dado_norm == _normalizar(str(op.get("label", ""))):
            return op
    return None


def _es_la_opcion_correcta(opcion: dict[str, Any], correct_answer: str | None) -> bool:
    """§2.3.3.3: nunca cuenta la opción de `correct_answer` (por value O label)."""
    if correct_answer is None:
        return False
    ca = _normalizar(correct_answer)
    return ca == _normalizar(str(opcion.get("value", ""))) or ca == _normalizar(
        str(opcion.get("label", ""))
    )


def _top_distractor(
    respuestas_incorrectas: list[str], pregunta: QuestionMeta
) -> DistractorOut | None:
    """§2.3.3: la opción incorrecta más elegida, o `None`."""
    opciones = pregunta.options_json or []
    conteo: Counter[tuple[str, str]] = Counter()
    for dado in respuestas_incorrectas:
        dado_norm = _normalizar(dado)
        if not dado_norm:
            continue  # la vacía no cuenta
        opcion = _buscar_opcion(dado_norm, opciones)
        if opcion is None:
            continue  # no coincide con ninguna opción
        if _es_la_opcion_correcta(opcion, pregunta.correct_answer):
            continue  # nunca la correcta
        conteo[(str(opcion.get("label", "")), str(opcion.get("value", "")))] += 1

    if not conteo:
        return None
    maximo = max(conteo.values())
    ganadoras = {clave for clave, n in conteo.items() if n == maximo}
    if len(ganadoras) > 1:
        # Empate: la primera en options_json.
        for op in opciones:
            clave = (str(op.get("label", "")), str(op.get("value", "")))
            if clave in ganadoras:
                return DistractorOut(label=clave[0], value=clave[1], count=maximo)
    ganadora = next(iter(ganadoras))
    return DistractorOut(label=ganadora[0], value=ganadora[1], count=maximo)


def compute_item_errors(
    calificados: list[tuple[UUID, AttemptRow]],
    preguntas: dict[UUID, QuestionMeta],
    *, min_respondents: int = MIN_RESPONDENTS,
) -> dict[str, Any]:
    """`calificados`: (student_id, primer-intento-en-ventana) de TODO el roster.

    Un ítem cuya `question_id` no está en `preguntas` se omite por completo
    (§2.3: "un ítem cuya pregunta ya no existe se omite" — ni cuenta ni
    suprime).
    """
    por_pregunta: dict[UUID, list[tuple[UUID, AttemptRow, dict[str, Any]]]] = defaultdict(list)
    for student_id, intento in calificados:
        for item in intento.answers:
            qid_crudo = item.get("question_id")
            if not qid_crudo:
                continue
            qid = UUID(str(qid_crudo))
            if qid not in preguntas:
                continue
            por_pregunta[qid].append((student_id, intento, item))

    items_out: list[dict[str, Any]] = []
    suprimidos = 0
    for qid, filas in por_pregunta.items():
        respondents = len({sid for sid, _i, _it in filas})
        if respondents < min_respondents:
            suprimidos += 1
            continue
        errors = sum(1 for _s, _i, it in filas if not it.get("is_correct"))
        blank = sum(1 for _s, _i, it in filas if not _normalizar(str(it.get("given_answer"))))
        pregunta = preguntas[qid]
        distractor = _top_distractor(
            [str(it.get("given_answer") or "") for _s, _i, it in filas if not it.get("is_correct")],
            pregunta,
        )
        ejemplo = filas[0][1]
        items_out.append({
            "challenge_id": ejemplo.challenge_id, "title": ejemplo.title,
            "question_id": qid, "order_index": pregunta.order_index,
            "question_text": pregunta.question_text, "skill": ejemplo.skill,
            "axis": skill_to_axis(ejemplo.skill),
            "respondents": respondents, "errors": errors, "blank_answers": blank,
            "top_distractor": distractor,
        })

    def _comparar(a: dict[str, Any], b: dict[str, Any]) -> int:
        # §2.3: tasa de error DESCENDENTE, como fracción exacta (sin float).
        izq = a["errors"] * b["respondents"]
        der = b["errors"] * a["respondents"]
        if izq != der:
            return -1 if izq > der else 1
        if a["errors"] != b["errors"]:
            return -1 if a["errors"] > b["errors"] else 1
        if a["title"] != b["title"]:
            return -1 if a["title"] < b["title"] else 1
        return -1 if a["order_index"] < b["order_index"] else 1

    items_out.sort(key=functools.cmp_to_key(_comparar))
    return {"items": items_out, "suppressed_items": suprimidos}


# =============================================================================
# DB wiring
# =============================================================================
def _normalizar_opciones(crudo: Any) -> list[dict[str, Any]] | None:
    """`ChallengeQuestion.options_json` está tipado como `dict | None` en el
    ORM (`shared/models.py:464`) aunque en la práctica guarda una lista de
    opciones — mismo patrón defensivo que `challenges.question_to_schema`."""
    if crudo is None:
        return None
    if isinstance(crudo, list):
        return crudo
    return [crudo] if isinstance(crudo, dict) else None


async def _cargar_preguntas(db: AsyncSession, qids: set[UUID]) -> dict[UUID, QuestionMeta]:
    if not qids:
        return {}
    stmt = select(ChallengeQuestion).where(ChallengeQuestion.id.in_(qids))
    filas = (await db.execute(stmt)).scalars().all()
    return {
        r.id: QuestionMeta(
            question_id=r.id, order_index=r.order_index, question_text=r.question_text,
            options_json=_normalizar_opciones(r.options_json), correct_answer=r.correct_answer,
        )
        for r in filas
    }


async def build_response(db: AsyncSession, group: Group, *, now: datetime) -> ItemErrorsOut:
    """T7 completo: mismo alcance que T5, agregado por ítem."""
    roster = await panel_service.roster(db, group)
    por_estudiante = await achievement_service.intentos_del_grupo(
        db, group, [s.profile_id for s in roster]
    )
    calificados: list[tuple[UUID, AttemptRow]] = [
        (s.profile_id, primero)
        for s in roster
        for primero in achievement_service.primeros_en_ventana(
            por_estudiante.get(s.profile_id, []), now
        )
    ]
    qids = {
        UUID(str(item["question_id"]))
        for _sid, primero in calificados
        for item in primero.answers
        if item.get("question_id")
    }
    preguntas = await _cargar_preguntas(db, qids)
    resultado = compute_item_errors(calificados, preguntas)
    return ItemErrorsOut(
        method=METHOD,
        items=[ItemErrorOut(**i) for i in resultado["items"]],
        suppressed_items=resultado["suppressed_items"],
    )


__all__ = [
    "QuestionMeta", "compute_item_errors", "build_response", "METHOD", "MIN_RESPONDENTS",
]
