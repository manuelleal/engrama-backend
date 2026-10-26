"""Responder pregunta por pregunta — ESPEC_l1_correccion_por_pregunta §1.1, §1.2 y §10.3.

  - `responder`: guarda UNA respuesta y devuelve si acertó, la correcta y la
    explicación. Gana la primera: repetirla devuelve lo guardado. No paga.
  - `retomar`: lo ya respondido de un intento (para volver a entrar). No escribe.
  - `terminar`: cierra el intento con lo guardado, por el MISMO camino de
    `/submit` (`attempts.cerrar_intento`): una paga, la racha, la cola y la escalera.

La clave de una pregunta nunca sale antes de responder ESA pregunta. Ninguna
función hace `commit`: van en la transacción de la ruta.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.challenge_engine.schemas import (
    AttemptSubmitOut,
    EstadoDeIntentoOut,
    ExplicacionOut,
    RespuestaDeIntentoOut,
)
from src.challenge_engine.service import attempts as attempts_service
from src.challenge_engine.service import calificar, explicar, intento_formas
from src.challenge_engine.service import challenges as challenges_service
from src.shared.models import ChallengeAttempt, ChallengeAttemptAnswer, ChallengeQuestion

NO_ENCONTRADO = "Attempt not found"
YA_CERRADO = "Attempt already completed or abandoned"
PREGUNTA_AJENA = "Question not found in this attempt"
NO_ES_OPCION = "Answer is not one of the question's options"


def _ahora() -> datetime:
    """El instante del SERVIDOR en que llegó la respuesta (dato de vigilancia)."""
    return datetime.now(UTC)


async def _tomar(db: AsyncSession, *, attempt_id: UUID, tenant_id: UUID,
                 student_id: UUID) -> ChallengeAttempt:
    """El intento ABIERTO de ese estudiante, bloqueado. 404 si no es suyo; 409 si ya cerró."""
    attempt = await attempts_service._tomar_intento(
        db, attempt_id=attempt_id, tenant_id=tenant_id, student_id=student_id)
    if attempt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_ENCONTRADO)
    if attempt.status != "in_progress":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=YA_CERRADO)
    return attempt


async def _guardadas(db: AsyncSession,
                     attempt_id: UUID) -> dict[UUID, ChallengeAttemptAnswer]:
    filas = (await db.execute(
        select(ChallengeAttemptAnswer)
        .where(ChallengeAttemptAnswer.attempt_id == attempt_id)
        .order_by(ChallengeAttemptAnswer.id)
        .execution_options(populate_existing=True))).scalars().all()
    return {f.question_id: f for f in filas}


async def _guardar_primera(db: AsyncSession, attempt: ChallengeAttempt,
                           pregunta: ChallengeQuestion, respuesta: str,
                           acerto: bool) -> tuple[ChallengeAttemptAnswer, bool]:
    """Guarda la respuesta SOLO si esa pregunta no tenía: `(la que quedó, ¿ya estaba?)`.

    Una sentencia `ON CONFLICT DO NOTHING` sobre `(intento, pregunta)`: gana la
    primera, también si llegan dos a la vez.
    """
    nueva = (await db.execute(
        pg_insert(ChallengeAttemptAnswer).values(
            tenant_id=attempt.tenant_id, attempt_id=attempt.id,
            profile_id=attempt.student_id, question_id=pregunta.id, answer=respuesta,
            is_correct=acerto, answered_at=_ahora())
        .on_conflict_do_nothing(constraint="challenge_attempt_answers_attempt_question_key")
        .returning(ChallengeAttemptAnswer.id))).scalar_one_or_none()
    fila = (await _guardadas(db, attempt.id))[pregunta.id]
    return fila, nueva is None


def _salida(fila: ChallengeAttemptAnswer, pregunta: ChallengeQuestion, nivel: str | None, *,
            repetida: bool, respondidas: int, total: int) -> RespuestaDeIntentoOut:
    """Lo que se dice de UNA pregunta ya respondida (y de ninguna otra)."""
    oracion, explicacion = explicar.retroalimentar(
        pregunta, nivel, respuesta=fila.answer, acerto=fila.is_correct)
    return RespuestaDeIntentoOut(
        question_id=pregunta.id, is_correct=fila.is_correct, answer=fila.answer,
        correct_answer=pregunta.correct_answer or "", oracion_correcta=oracion,
        explanation=None if explicacion is None else ExplicacionOut(**explicacion),
        repetida=repetida, respondidas=respondidas, total=total)


async def responder(db: AsyncSession, *, student_id: UUID, tenant_id: UUID, attempt_id: UUID,
                    question_id: UUID, answer: str) -> RespuestaDeIntentoOut:
    """Una respuesta: se califica, se guarda (gana la primera) y se explica. No paga."""
    attempt = await _tomar(db, attempt_id=attempt_id, tenant_id=tenant_id,
                           student_id=student_id)
    challenge = await challenges_service.get_challenge(db, attempt.challenge_id, tenant_id)
    preguntas = await intento_formas.preguntas_del_intento(db, attempt)
    pregunta = next((q for q in preguntas if q.id == question_id), None)
    if pregunta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=PREGUNTA_AJENA)
    # ESPEC_opcion_valida: en una pregunta de opciones, lo que no es ninguna de
    # ellas no se califica ni se guarda (no ocupa la "primera respuesta", no cuenta
    # como fallada). El texto es fijo: no repite lo enviado.
    if not calificar.es_opcion_valida(explicar.a_pregunta(pregunta), answer):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=NO_ES_OPCION)
    fila, repetida = await _guardar_primera(
        db, attempt, pregunta, answer, explicar.acerto(pregunta, answer))
    respondidas = len(await _guardadas(db, attempt.id))
    return _salida(fila, pregunta, challenge.cefr_level, repetida=repetida,
                   respondidas=respondidas, total=len(preguntas))


async def retomar(db: AsyncSession, *, student_id: UUID, tenant_id: UUID,
                  attempt_id: UUID) -> EstadoDeIntentoOut:
    """Lo ya respondido de ese intento y la letra de las pistas. NO escribe ni bloquea."""
    attempt = (await db.execute(select(ChallengeAttempt).where(
        ChallengeAttempt.id == attempt_id, ChallengeAttempt.tenant_id == tenant_id,
        ChallengeAttempt.student_id == student_id))).scalar_one_or_none()
    if attempt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_ENCONTRADO)
    challenge = await challenges_service.get_challenge(db, attempt.challenge_id, tenant_id)
    preguntas = await intento_formas.preguntas_del_intento(db, attempt)
    guardadas = await _guardadas(db, attempt.id)
    pistas = {str(q.id): letra for q in preguntas
              if (letra := calificar.pista_de(explicar.a_pregunta(q))) is not None}
    return EstadoDeIntentoOut(
        status=attempt.status, total=len(preguntas), pistas=pistas,
        respondidas=[_salida(guardadas[q.id], q, challenge.cefr_level, repetida=True,
                             respondidas=len(guardadas), total=len(preguntas))
                     for q in preguntas if q.id in guardadas])


def detalles(preguntas: list[ChallengeQuestion],
             guardadas: dict[UUID, ChallengeAttemptAnswer]) -> tuple[float, list[dict[str, Any]]]:
    """`(puntaje, detalle)` con la MISMA forma que deja `/submit`; lo que falta es incorrecto."""
    lista = [{"question_id": str(q.id),
              "given_answer": guardadas[q.id].answer if q.id in guardadas else "",
              "correct_answer": q.correct_answer or "",
              "is_correct": bool(q.id in guardadas and guardadas[q.id].is_correct)}
             for q in preguntas]
    if not lista:
        return 0.0, []
    return sum(1 for d in lista if d["is_correct"]) / len(lista) * 100.0, lista


async def terminar(db: AsyncSession, *, student_id: UUID, tenant_id: UUID,
                   attempt_id: UUID) -> AttemptSubmitOut:
    """Cierra el intento con las respuestas guardadas. Paga como `/submit`: una vez."""
    attempt = await _tomar(db, attempt_id=attempt_id, tenant_id=tenant_id,
                           student_id=student_id)
    challenge = await challenges_service.get_challenge(db, attempt.challenge_id, tenant_id)
    preguntas = await intento_formas.preguntas_del_intento(db, attempt)
    puntaje, detalle = detalles(preguntas, await _guardadas(db, attempt.id))
    return await attempts_service.cerrar_intento(
        db, attempt=attempt, challenge=challenge, questions=preguntas, details=detalle,
        score_percent=puntaje, student_id=student_id, tenant_id=tenant_id)
