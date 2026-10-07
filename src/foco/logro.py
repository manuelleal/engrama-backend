"""El logro del GRUPO por nodo — ESPEC_foco_grupo §1.4.

El alcance es el de T5 y T7, sin copiarlo: `achievement.intentos_del_grupo` y
`achievement.primeros_en_ventana` (el primer intento de cada estudiante en
cada reto asignado al grupo, 28 días, sin `open`). Una respuesta cuenta para
un nodo si SU pregunta lleva ese nodo.

Es un dato del grupo: no nombra ni ordena estudiantes. Los mínimos y los
cortes se toman de T5 y T7 y están PENDIENTES del pedagogo para nodos
(ERR-16; ESPEC §9): por eso son constantes con nombre.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.foco import service as foco_service
from src.foco.schemas import LogroMetodoOut, LogroNodoOut, LogroOut, PeriodoOut
from src.shared.models import ChallengeQuestion, Group
from src.teachers.service import achievement as achievement_service
from src.teachers.service import item_errors as item_errors_service
from src.teachers.service import panel as panel_service
from src.teachers.service.achievement import AttemptRow

MIN_STUDENTS = item_errors_service.MIN_RESPONDENTS  # 5, el mínimo por ítem de T7
MIN_ITEMS = achievement_service.MIN_ITEMS  # 8, el mínimo por eje de T5
THRESHOLD_LOGRADO = achievement_service.THRESHOLD_LOGRADO
THRESHOLD_EN_DESARROLLO = achievement_service.THRESHOLD_EN_DESARROLLO

ETIQUETAS = {"logrado": "logrado", "en_desarrollo": "en desarrollo",
             "a_reforzar": "a reforzar", "datos_insuficientes": "datos insuficientes"}


def metodo() -> LogroMetodoOut:
    return LogroMetodoOut(
        window_days=achievement_service.WINDOW_DAYS, first_attempt_only=True,
        min_students=MIN_STUDENTS, min_items=MIN_ITEMS,
        thresholds={"logrado": THRESHOLD_LOGRADO, "en_desarrollo": THRESHOLD_EN_DESARROLLO},
        excluded_types=list(achievement_service.EXCLUDED_TYPES),
        scope="retos asignados al grupo; es el logro del GRUPO, no el nivel de nadie")


def estado_del_nodo(students: int, items: int, correct: int) -> str:
    """Con enteros (nunca float): mínimo de evidencia y después los cortes."""
    if students < MIN_STUDENTS or items < MIN_ITEMS:
        return "datos_insuficientes"
    if 100 * correct >= THRESHOLD_LOGRADO * items:
        return "logrado"
    if 100 * correct >= THRESHOLD_EN_DESARROLLO * items:
        return "en_desarrollo"
    return "a_reforzar"


@dataclass
class Conteo:
    students: set[UUID] = field(default_factory=set)
    challenges: set[UUID] = field(default_factory=set)
    items: int = 0
    correct: int = 0


def calificados(por_estudiante: dict[UUID, list[AttemptRow]],
                now: datetime) -> list[tuple[UUID, AttemptRow]]:
    """(estudiante, su PRIMER intento en la ventana) de cada reto — la regla de T5 y T7."""
    return [(estudiante, primero) for estudiante, intentos in por_estudiante.items()
            for primero in achievement_service.primeros_en_ventana(intentos, now)]


def contar(filas: Sequence[tuple[UUID, AttemptRow]], nodos_de: dict[UUID, set[str]],
           del_foco: Sequence[str]) -> dict[str, Conteo]:
    """Por nodo del foco: quiénes respondieron, cuántas respuestas y cuántas correctas."""
    conteos = {nodo: Conteo() for nodo in del_foco}
    for estudiante, intento in filas:
        for respuesta in intento.answers:
            crudo = respuesta.get("question_id")
            if not crudo:
                continue
            for nodo in nodos_de.get(UUID(str(crudo)), set()) & set(del_foco):
                c = conteos[nodo]
                c.students.add(estudiante)
                c.challenges.add(intento.challenge_id)
                c.items += 1
                c.correct += int(bool(respuesta.get("is_correct")))
    return conteos


async def _nodos_de_las_preguntas(db: AsyncSession, ids: set[UUID]) -> dict[UUID, set[str]]:
    if not ids:
        return {}
    filas = (await db.execute(select(ChallengeQuestion.id, ChallengeQuestion.nodes)
                              .where(ChallengeQuestion.id.in_(ids)))).all()
    return {qid: set(nodos or []) for qid, nodos in filas}


def _ids_de_preguntas(filas: Sequence[tuple[UUID, AttemptRow]]) -> set[UUID]:
    crudos: list[Any] = [r.get("question_id") for _e, intento in filas for r in intento.answers]
    return {UUID(str(c)) for c in crudos if c}


async def build_response(db: AsyncSession, group: Group, *, now: datetime,
                         dia: date) -> LogroOut:
    """El logro de los nodos del foco VIGENTE del grupo. Sin foco: lista vacía."""
    roster = await panel_service.roster(db, group)
    foco = await foco_service.vigente_del_grupo(db, group.id, dia)
    if foco is None:
        return LogroOut(method=metodo(), foco=None, group_students=len(roster), nodos=[])
    por_estudiante = await achievement_service.intentos_del_grupo(
        db, group, [s.profile_id for s in roster])
    filas = calificados(por_estudiante, now)
    conteos = contar(filas, await _nodos_de_las_preguntas(db, _ids_de_preguntas(filas)),
                     foco.nodes)
    nodos = await foco_service.nodos_a_esquema(db, foco.nodes)
    salida = []
    for nodo in nodos:
        c = conteos[nodo.id]
        estado = estado_del_nodo(len(c.students), c.items, c.correct)
        salida.append(LogroNodoOut(nodo=nodo, students=len(c.students), items=c.items,
                                   correct=c.correct, challenges=len(c.challenges),
                                   status=estado, label=ETIQUETAS[estado]))
    return LogroOut(method=metodo(), foco=PeriodoOut(desde=foco.starts_on, hasta=foco.ends_on),
                    group_students=len(roster), nodos=salida)
