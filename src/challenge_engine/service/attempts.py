"""Lógica de intentos (attempts) — SPECS/03-challenges.md §4.

Un `ChallengeAttempt` representa a un estudiante resolviendo un challenge:
  - start_attempt   : crea la fila in_progress (o reusa una existente).
  - submit_attempt  : califica, otorga coins/XP vía engrama_core, revela
                      respuestas correctas, persiste resultado.
  - get_attempt_history

Reglas:
  - Un estudiante NO puede tener dos intentos `in_progress` simultáneos
    del mismo challenge → si ya hay uno, se retorna.
  - `max_attempts` cuenta intentos `completed` (+ el in_progress actual
    si existe). Una vez agotado → 429.
  - Grading:
      * multiple_choice / listening → is_correct = score_percent == 100.
      * open / fill_blank            → is_correct = score_percent >= 70.
  - Si el intento fue correcto Y aún hay cupo (`current_winners <
    max_winners`), se intenta pagar `coins_reward` con la llave
    `challenge:<reto>:<estudiante>` (033, BUG-13): UNA sola paga por
    (reto, estudiante), la haga el intento que la haga. Solo si la paga
    ocurre se otorga `xp_reward` y se incrementa `current_winners`. Quien
    vuelve a ganar un reto ya cobrado recibe el resultado correcto con 0
    monedas y 0 XP, y no gasta cupo de ganador. Si no queda cupo el
    estudiante recibe el resultado correcto pero sin premios (política
    conservadora, spec §3.2 dice "excluir challenges con cupo lleno del
    feed"; si llega aquí es porque otro ganó entre que abrió el challenge
    y lo envió).
  - El intento se lee con `SELECT ... FOR UPDATE` (`_tomar_intento`): dos
    envíos simultáneos del MISMO intento se serializan y el segundo ve
    `completed` y responde 409 (docs/ESPEC_bug13a15.md §1.1).
  - Comparación case-insensitive + strip para texto libre.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.challenge_engine.schemas import (
    AnswerSubmit,
    AttemptHistoryOut,
    AttemptStartOut,
    AttemptSubmitOut,
    CorrectAnswerReveal,
)
from src.challenge_engine.service import challenges as challenges_service
from src.engrama_core.service import coins as coins_service
from src.shared.models import (
    Challenge,
    ChallengeAttempt,
    ChallengeQuestion,
    Profile,
)


# =============================================================================
# Helpers puros (unit-testables)
# =============================================================================
_PARTIAL_CREDIT_TYPES = {"open", "fill_blank"}
_PARTIAL_CREDIT_THRESHOLD = 70.0


def _normalize_answer(value: str) -> str:
    """Normaliza texto para comparación: trim + lowercase."""
    return value.strip().lower()


def grade_answers(
    questions: list[ChallengeQuestion],
    submitted: list[AnswerSubmit],
) -> tuple[float, list[dict[str, Any]]]:
    """Califica respuestas y devuelve (score_percent, lista detallada).

    La lista detallada tiene una entrada por pregunta:
      {question_id, given_answer, correct_answer, is_correct}

    Si el estudiante no envió respuesta para alguna pregunta queda como
    incorrecta con given_answer="". Si envió respuestas para preguntas
    que no pertenecen al challenge, se ignoran (la validación de
    coincidencia ya se hace en submit_attempt).
    """
    if not questions:
        return 0.0, []

    by_id: dict[str, str | None] = {str(a.question_id): a.answer for a in submitted}
    details: list[dict[str, Any]] = []
    correct_count = 0
    for q in questions:
        given = by_id.get(str(q.id), "") or ""
        correct = q.correct_answer or ""
        is_ok = _normalize_answer(given) == _normalize_answer(correct)
        if is_ok:
            correct_count += 1
        details.append(
            {
                "question_id": str(q.id),
                "given_answer": given,
                "correct_answer": correct,
                "is_correct": is_ok,
            }
        )
    score_percent = (correct_count / len(questions)) * 100.0
    return score_percent, details


def is_attempt_correct(challenge_type: str, score_percent: float) -> bool:
    """Decide si el intento cuenta como ganador según el tipo de challenge."""
    if challenge_type in _PARTIAL_CREDIT_TYPES:
        return score_percent >= _PARTIAL_CREDIT_THRESHOLD
    # multiple_choice, listening → exige 100%.
    return score_percent >= 100.0


# =============================================================================
# 4.1 start_attempt
# =============================================================================
async def start_attempt(
    db: AsyncSession,
    *,
    student_id: UUID,
    tenant_id: UUID,
    challenge_id: UUID,
    group_code: str | None,
    es_personal: bool,
) -> AttemptStartOut:
    """Crea un intento `in_progress` o retorna el existente del estudiante."""
    # 1. Challenge existe + está activo + mismo tenant + visible para quien
    # lo arranca (BUG-15: un estudiante, solo globales o de su grupo; si no,
    # el mismo 404 de un id inexistente).
    challenge = await challenges_service.get_challenge_for(
        db, challenge_id, tenant_id=tenant_id, group_code=group_code,
        es_personal=es_personal,
    )
    if challenge.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Challenge is not active",
        )

    # 2. ¿Ya tiene un intento in_progress? → retornarlo.
    in_progress_stmt = select(ChallengeAttempt).where(
        ChallengeAttempt.tenant_id == tenant_id,
        ChallengeAttempt.challenge_id == challenge_id,
        ChallengeAttempt.student_id == student_id,
        ChallengeAttempt.status == "in_progress",
    )
    existing = (await db.execute(in_progress_stmt)).scalar_one_or_none()

    # 3. Contar intentos previos (completados + el in_progress si existe).
    count_stmt = (
        select(func.count())
        .select_from(ChallengeAttempt)
        .where(
            ChallengeAttempt.tenant_id == tenant_id,
            ChallengeAttempt.challenge_id == challenge_id,
            ChallengeAttempt.student_id == student_id,
        )
    )
    total_attempts = int((await db.execute(count_stmt)).scalar_one())

    if existing is not None:
        attempt = existing
    else:
        # 4. Si no hay in_progress, validar cupo de intentos antes de crear.
        if total_attempts >= challenge.max_attempts:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="No attempts remaining for this challenge",
            )
        attempt = ChallengeAttempt(
            tenant_id=tenant_id,
            challenge_id=challenge_id,
            student_id=student_id,
            status="in_progress",
        )
        db.add(attempt)
        await db.flush()
        total_attempts += 1

    challenge_schema = await challenges_service.hydrate(db, challenge)
    return AttemptStartOut(
        attempt_id=attempt.id,
        challenge=challenge_schema,
        attempt_number=total_attempts,
    )


# =============================================================================
# 4.2 submit_attempt
# =============================================================================
def llave_reto(challenge_id: UUID, student_id: UUID) -> str:
    """Llave de idempotencia de la paga de un reto (mismo formato que el backfill de la 033)."""
    return f"challenge:{challenge_id}:{student_id}"


async def _tomar_intento(
    db: AsyncSession, *, attempt_id: UUID, tenant_id: UUID, student_id: UUID
) -> ChallengeAttempt | None:
    """Lee el intento del estudiante y BLOQUEA su fila hasta el commit.

    Así un doble toque sobre el mismo intento se serializa: el segundo
    request espera aquí, y al seguir ya ve `completed` (→ 409). No cierra
    dos intentos DISTINTOS en vuelo: eso lo cierra la llave de la paga.
    """
    stmt = (
        select(ChallengeAttempt)
        .where(
            ChallengeAttempt.id == attempt_id,
            ChallengeAttempt.tenant_id == tenant_id,
            ChallengeAttempt.student_id == student_id,
        )
        .with_for_update()
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def submit_attempt(
    db: AsyncSession,
    *,
    student_id: UUID,
    tenant_id: UUID,
    attempt_id: UUID,
    answers: list[AnswerSubmit],
) -> AttemptSubmitOut:
    """Califica el intento, actualiza balances, persiste resultado."""
    # 1. Cargar (y bloquear) el attempt validando ownership y status.
    attempt = await _tomar_intento(
        db, attempt_id=attempt_id, tenant_id=tenant_id, student_id=student_id
    )
    if attempt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attempt not found",
        )
    if attempt.status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attempt already completed or abandoned",
        )

    # 2. Cargar challenge + preguntas.
    challenge = await challenges_service.get_challenge(
        db, attempt.challenge_id, tenant_id
    )
    questions = await challenges_service.get_questions(db, challenge.id)
    if len(answers) != len(questions):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Expected {len(questions)} answers, got {len(answers)}"
            ),
        )

    # 3. Calificar.
    score_percent, details = grade_answers(questions, answers)
    is_correct = is_attempt_correct(challenge.challenge_type, score_percent)

    # 4. Premios. Respetamos el cupo de max_winners: si justo se llenó
    # entre que el estudiante abrió el challenge y envió, no duplicamos
    # ganadores pero SÍ devolvemos is_correct/score para feedback.
    # La paga lleva llave (BUG-13): si este estudiante ya cobró este reto,
    # `award_coins` devuelve None y aquí no se suma nada más.
    coins_earned = 0
    xp_earned = 0
    if is_correct and challenge.current_winners < challenge.max_winners:
        entrada = await coins_service.award_coins(
            db,
            student_id=student_id,
            tenant_id=tenant_id,
            amount=challenge.coins_reward,
            action="challenge",
            metadata={
                "challenge_id": str(challenge.id),
                "attempt_id": str(attempt.id),
            },
            idempotency_key=llave_reto(challenge.id, student_id),
        )
        if entrada is not None:
            coins_earned = challenge.coins_reward
            xp_earned = challenge.xp_reward
            # XP al perfil.
            profile = await db.get(Profile, student_id)
            if profile is not None:
                profile.xp = profile.xp + xp_earned
            # +1 ganador en el challenge.
            challenge.current_winners = challenge.current_winners + 1

    # 5. Persistir el intento.
    attempt.status = "completed"
    attempt.completed_at = datetime.now(UTC)
    attempt.answers = details
    attempt.score_percent = score_percent
    attempt.is_correct = is_correct
    attempt.coins_earned = coins_earned
    attempt.xp_earned = xp_earned
    attempt.streak_bonus = 0  # reservado para Fase 3

    # 6. Contar intentos usados para el payload.
    used_stmt = (
        select(func.count())
        .select_from(ChallengeAttempt)
        .where(
            ChallengeAttempt.tenant_id == tenant_id,
            ChallengeAttempt.challenge_id == challenge.id,
            ChallengeAttempt.student_id == student_id,
            ChallengeAttempt.status == "completed",
        )
    )
    await db.flush()  # asegura que el UPDATE de este attempt cuente
    total_used = int((await db.execute(used_stmt)).scalar_one())
    remaining = max(challenge.max_attempts - total_used, 0)

    return AttemptSubmitOut(
        attempt_id=attempt.id,
        is_correct=is_correct,
        score_percent=score_percent,
        coins_earned=coins_earned,
        xp_earned=xp_earned,
        streak_bonus=0,
        correct_answers=[
            CorrectAnswerReveal(
                question_id=UUID(str(d["question_id"])),
                correct_answer=str(d["correct_answer"]),
            )
            for d in details
        ],
        drako_feedback=None,  # TODO Fase 2: generate_feedback via LLM
        total_attempts_used=total_used,
        attempts_remaining=remaining,
    )


# =============================================================================
# 4.3 get_attempt_history
# =============================================================================
async def get_attempt_history(
    db: AsyncSession,
    *,
    student_id: UUID,
    tenant_id: UUID,
    limit: int = 20,
) -> list[AttemptHistoryOut]:
    """Últimos N intentos del estudiante, más reciente primero."""
    stmt = (
        select(ChallengeAttempt)
        .where(
            ChallengeAttempt.student_id == student_id,
            ChallengeAttempt.tenant_id == tenant_id,
        )
        .order_by(ChallengeAttempt.created_at.desc())
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    return [
        AttemptHistoryOut(
            id=r.id,
            challenge_id=r.challenge_id,
            status=r.status,
            score_percent=float(r.score_percent),
            is_correct=r.is_correct,
            coins_earned=r.coins_earned,
            xp_earned=r.xp_earned,
            started_at=r.started_at,
            completed_at=r.completed_at,
        )
        for r in rows
    ]


# Silencia "unused" del import Challenge en type checkers estrictos.
_ = Challenge
