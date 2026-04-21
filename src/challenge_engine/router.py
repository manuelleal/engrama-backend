"""Endpoints HTTP del módulo challenge_engine — SPECS/03-challenges.md §6.

Montado en main.py con prefijo `/challenges`. Endpoints finales:

  # Teacher:
  POST   /challenges/
  POST   /challenges/generate
  GET    /challenges/all
  PATCH  /challenges/{challenge_id}/status

  # Student:
  GET    /challenges/
  GET    /challenges/{challenge_id}
  POST   /challenges/{challenge_id}/attempt
  POST   /challenges/attempts/{attempt_id}/submit
  GET    /challenges/attempts/history

NOTA: el spec declara los endpoints de attempts bajo `/attempts/...`,
pero al montar el router con `prefix="/challenges"` quedarían fuera
del prefijo. Para mantener coherencia y RESTful nesting, los exponemos
bajo `/challenges/attempts/...`. El frontend los reconoce igual porque
el OpenAPI generado lista las rutas exactas.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.challenge_engine.schemas import (
    AttemptHistoryOut,
    AttemptStartOut,
    AttemptSubmitOut,
    AttemptSubmitRequest,
    ChallengeCreate,
    ChallengeGenerateRequest,
    ChallengeOut,
    ChallengeStatusUpdate,
)
from src.challenge_engine.service import attempts as attempts_service
from src.challenge_engine.service import challenges as challenges_service
from src.challenge_engine.service import generator as generator_service
from src.shared.db import get_db
from src.shared.deps import get_current_user, require_teacher

router = APIRouter()


# =============================================================================
# TEACHER
# =============================================================================
@router.post(
    "/",
    response_model=ChallengeOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_challenge(
    payload: ChallengeCreate,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> ChallengeOut:
    """Crea un challenge manual (con preguntas provistas por el teacher)."""
    challenge = await challenges_service.create_challenge(
        db,
        teacher_id=auth.profile_id,
        tenant_id=auth.tenant_id,
        data=payload,
    )
    await db.commit()
    return await challenges_service.hydrate(db, challenge)


@router.post(
    "/generate",
    response_model=ChallengeOut,
    status_code=status.HTTP_201_CREATED,
)
async def generate_challenge_endpoint(
    payload: ChallengeGenerateRequest,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> ChallengeOut:
    """Genera un challenge con IA (Anthropic) y lo persiste."""
    draft = await generator_service.generate_challenge(
        cefr_level=payload.cefr_level,
        skill=payload.skill,
        topic=payload.topic,
        num_questions=payload.num_questions,
        specific_instructions=payload.specific_instructions,
        group_id=payload.group_id,
    )
    tokens_used = int(draft.__dict__.get("_ai_tokens_used", 0))
    challenge = await challenges_service.create_challenge(
        db,
        teacher_id=auth.profile_id,
        tenant_id=auth.tenant_id,
        data=draft,
    )
    # Log de uso IA — best-effort, nunca tumba el request.
    await generator_service.log_ai_usage(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.profile_id,
        tokens_used=tokens_used,
        cefr_level=payload.cefr_level,
        skill=payload.skill,
        topic=payload.topic,
    )
    await db.commit()
    return await challenges_service.hydrate(db, challenge)


@router.get(
    "/all",
    response_model=list[ChallengeOut],
    status_code=status.HTTP_200_OK,
)
async def list_all_challenges(
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> list[ChallengeOut]:
    """Lista TODOS los challenges del tenant (cualquier status) — vista docente."""
    rows = await challenges_service.list_challenges_for_teacher(
        db, tenant_id=auth.tenant_id
    )
    return [await challenges_service.hydrate(db, c) for c in rows]


@router.patch(
    "/{challenge_id}/status",
    response_model=ChallengeOut,
    status_code=status.HTTP_200_OK,
)
async def update_status(
    challenge_id: UUID,
    payload: ChallengeStatusUpdate,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> ChallengeOut:
    """Cambia `status` del challenge (active / inactive / archived)."""
    challenge = await challenges_service.update_challenge_status(
        db, challenge_id, auth.tenant_id, payload.status
    )
    await db.commit()
    return await challenges_service.hydrate(db, challenge)


# =============================================================================
# STUDENT — listado y detalle
# =============================================================================
@router.get(
    "/",
    response_model=list[ChallengeOut],
    status_code=status.HTTP_200_OK,
)
async def list_challenges(
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChallengeOut]:
    """Feed de challenges disponibles para el estudiante (sin correct_answer)."""
    rows = await challenges_service.list_challenges_for_student(
        db,
        student_id=auth.profile_id,
        tenant_id=auth.tenant_id,
        group_code=auth.group_code,
    )
    return [await challenges_service.hydrate(db, c) for c in rows]


@router.get(
    "/attempts/history",
    response_model=list[AttemptHistoryOut],
    status_code=status.HTTP_200_OK,
)
async def read_attempts_history(
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AttemptHistoryOut]:
    """Historial de intentos del estudiante (últimos 20).

    NOTA: esta ruta DEBE declararse antes de `/{challenge_id}` para que
    FastAPI no la matchee como `challenge_id='attempts'`.
    """
    return await attempts_service.get_attempt_history(
        db, student_id=auth.profile_id, tenant_id=auth.tenant_id
    )


@router.post(
    "/attempts/{attempt_id}/submit",
    response_model=AttemptSubmitOut,
    status_code=status.HTTP_200_OK,
)
async def submit_attempt(
    attempt_id: UUID,
    payload: AttemptSubmitRequest,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AttemptSubmitOut:
    """Envía respuestas → califica → otorga coins/XP → revela respuestas correctas."""
    result = await attempts_service.submit_attempt(
        db,
        student_id=auth.profile_id,
        tenant_id=auth.tenant_id,
        attempt_id=attempt_id,
        answers=payload.answers,
    )
    await db.commit()
    return result


@router.get(
    "/{challenge_id}",
    response_model=ChallengeOut,
    status_code=status.HTTP_200_OK,
)
async def get_challenge(
    challenge_id: UUID,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChallengeOut:
    """Detalle del challenge (sin correct_answer en las preguntas)."""
    challenge = await challenges_service.get_challenge(
        db, challenge_id, auth.tenant_id
    )
    return await challenges_service.hydrate(db, challenge)


@router.post(
    "/{challenge_id}/attempt",
    response_model=AttemptStartOut,
    status_code=status.HTTP_201_CREATED,
)
async def start_attempt(
    challenge_id: UUID,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AttemptStartOut:
    """Inicia un intento (o retorna el `in_progress` existente)."""
    result = await attempts_service.start_attempt(
        db,
        student_id=auth.profile_id,
        tenant_id=auth.tenant_id,
        challenge_id=challenge_id,
    )
    await db.commit()
    return result
