"""Consultas de la tanda que no deciden nada — ESPEC_solo_refuerzo §1.3 y §1.5.

Lo que la tanda necesita LEER para la segunda vuelta, para saber si hay con qué
hacer un día activo y para decir en qué va cada reto. Los filtros de
visibilidad y de nivel llegan de `practica.service` (su única fuente): aquí no
se repite ninguno. Nada escribe.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.practica import reglas
from src.practica.reglas import Candidato, FormaDeReto
from src.refuerzo import formas as refuerzo_formas
from src.refuerzo.reglas import clave_de_forma
from src.shared.models import (
    Challenge,
    ChallengeAttempt,
    ChallengeQuestion,
    PracticeTanda,
    ReinforcementAnswer,
)

PENDIENTE, JUGADO, GANADO = "pendiente", "jugado", "ganado"


def intentos_de(profile_id: UUID) -> Any:
    """Cuántos intentos lleva ese estudiante en el reto de la fila (subconsulta)."""
    return (select(func.count()).select_from(ChallengeAttempt)
            .where(ChallengeAttempt.challenge_id == Challenge.id,
                   ChallengeAttempt.student_id == profile_id)
            .correlate(Challenge).scalar_subquery())


async def vistas_de(db: AsyncSession, tenant_id: UUID, profile_id: UUID) -> set[str]:
    """Las identidades que ya vio: la MISMA regla de la cola de repaso."""
    return (await refuerzo_formas.vistas(db, tenant_id, [profile_id]))[profile_id]


async def original_jugado(db: AsyncSession, tenant_id: UUID, profile_id: UUID,
                          familias: Sequence[str],
                          del_feed: ColumnElement[bool]) -> dict[str, datetime]:
    """`{familia: último intento completado de un reto del feed con su original}`."""
    if not familias:
        return {}
    filas = (await db.execute(
        select(ChallengeQuestion.family_ref, func.max(ChallengeAttempt.completed_at))
        .join(Challenge, Challenge.id == ChallengeQuestion.challenge_id)
        .join(ChallengeAttempt, ChallengeAttempt.challenge_id == Challenge.id)
        .where(ChallengeAttempt.tenant_id == tenant_id,
               ChallengeAttempt.student_id == profile_id,
               ChallengeAttempt.status == "completed", del_feed,
               ChallengeQuestion.form_role == "original",
               ChallengeQuestion.family_ref.in_(list(familias)))
        .group_by(ChallengeQuestion.family_ref))).all()
    return {familia: cuando for familia, cuando in filas if cuando is not None}


async def segunda_vuelta(db: AsyncSession, tenant_id: UUID, profile_id: UUID, nivel: str, *,
                         donde: Sequence[ColumnElement[bool]], del_feed: ColumnElement[bool],
                         ahora: datetime, dias: int) -> list[Candidato]:
    """Los retos `solo_refuerzo` que entran a la segunda vuelta de ese estudiante (§1.3):
    gemelas que no ha visto, con el original de su familia jugado hace `dias` o más.

    `donde`: los filtros de quien llama (activo, visible, del nivel, con cupo...).
    """
    filas = (await db.execute(
        select(Challenge.id, Challenge.topic, Challenge.skill, Challenge.title,
               ChallengeQuestion.id, ChallengeQuestion.item_ref,
               ChallengeQuestion.family_ref, ChallengeQuestion.form_role)
        .join(ChallengeQuestion, ChallengeQuestion.challenge_id == Challenge.id)
        .where(Challenge.tenant_id == tenant_id, Challenge.solo_refuerzo.is_(True),
               *donde))).all()
    if not filas:
        return []  # sin retos de refuerzo en el nivel: ni una consulta más
    datos: dict[UUID, tuple[str | None, str | None, str]] = {}
    formas: dict[UUID, list[FormaDeReto]] = {}
    for reto, topic, skill, title, pregunta, item_ref, familia, rol in filas:
        datos[reto] = (topic, skill, title)
        formas.setdefault(reto, []).append(
            FormaDeReto(clave_de_forma(item_ref, pregunta), familia, rol))
    vistas = await vistas_de(db, tenant_id, profile_id)
    familias = sorted({f.familia for fs in formas.values() for f in fs if f.familia})
    jugado = await original_jugado(db, tenant_id, profile_id, familias, del_feed)
    return [Candidato(str(reto), *datos[reto], len(fs), nivel)
            for reto, fs in formas.items()
            if reglas.elegible_segunda_vuelta(fs, vistas, jugado, ahora, dias)]


async def servible(db: AsyncSession, tenant_id: UUID, *,
                   donde: Sequence[ColumnElement[bool]]) -> int:
    """Cuántas preguntas de retos del feed podría responder hoy, de CUALQUIER nivel."""
    return int((await db.execute(
        select(func.count(ChallengeQuestion.id))
        .join(Challenge, Challenge.id == ChallengeQuestion.challenge_id)
        .where(Challenge.tenant_id == tenant_id, *donde))).scalar_one())


async def aciertos(db: AsyncSession, tenant_id: UUID, profile_id: UUID, desde: datetime,
                   cuantas: int, *, donde: Sequence[ColumnElement[bool]]) -> list[bool]:
    """Los aciertos de los últimos `cuantas` intentos completados que cumplen `donde`,
    pregunta por pregunta, del más viejo al más nuevo (la ventana de la escalera)."""
    filas = (await db.execute(
        select(ChallengeAttempt.answers)
        .join(Challenge, Challenge.id == ChallengeAttempt.challenge_id)
        .where(ChallengeAttempt.tenant_id == tenant_id,
               ChallengeAttempt.student_id == profile_id,
               ChallengeAttempt.status == "completed",
               ChallengeAttempt.completed_at > desde, *donde)
        .order_by(ChallengeAttempt.completed_at.desc(), ChallengeAttempt.id)
        .limit(cuantas))).scalars().all()
    resultados: list[bool] = []
    for respuestas in reversed(filas):  # del más viejo al más nuevo
        resultados.extend(bool(r.get("is_correct")) for r in respuestas or []
                          if isinstance(r, dict))
    return resultados


async def repasos_respondidos(db: AsyncSession, tenant_id: UUID, profile_id: UUID,
                              tanda: PracticeTanda) -> set[int]:
    """Las entradas de repaso de esa tanda que ya se respondieron EN ella."""
    return set((await db.execute(
        select(ReinforcementAnswer.queue_id)
        .where(ReinforcementAnswer.tenant_id == tenant_id,
               ReinforcementAnswer.profile_id == profile_id,
               ReinforcementAnswer.queue_id.in_(list(tanda.repasos)),
               ReinforcementAnswer.id > tanda.repaso_desde))).scalars().all())


async def estados_de(db: AsyncSession, tenant_id: UUID, profile_id: UUID,
                     tanda: PracticeTanda) -> dict[UUID, str]:
    """`{reto: pendiente | jugado | ganado}` de los retos de esa tanda."""
    estados: dict[UUID, str] = {r: PENDIENTE for r in tanda.retos}
    if not tanda.retos:
        return estados
    filas = (await db.execute(
        select(ChallengeAttempt.challenge_id, ChallengeAttempt.is_correct,
               ChallengeAttempt.completed_at)
        .where(ChallengeAttempt.tenant_id == tenant_id,
               ChallengeAttempt.student_id == profile_id,
               ChallengeAttempt.status == "completed",
               ChallengeAttempt.challenge_id.in_(list(tanda.retos))))).all()
    for reto, gano, cuando in filas:
        if gano:
            estados[reto] = GANADO
        elif estados[reto] != GANADO and cuando is not None and cuando >= tanda.created_at:
            estados[reto] = JUGADO
    if tanda.modo == reglas.MODO_REPETIR:  # ya estaban ganados: cuenta volver a jugarlos
        de_la_tanda = {reto for reto, _gano, cuando in filas
                       if cuando is not None and cuando >= tanda.created_at}
        estados = {r: (JUGADO if r in de_la_tanda else PENDIENTE) for r in tanda.retos}
    return estados
