"""CRUD de challenges — SPECS/03-challenges.md §3.

Cubre:
  - create_challenge           : crea Challenge + sus ChallengeQuestions.
  - list_challenges_for_student: feed visible al estudiante (con filtros).
  - list_challenges_for_teacher: todos los del tenant (vista docente).
  - get_challenge              : detalle con preguntas (solo por tenant).
  - get_challenge_for          : detalle para quien pide: un estudiante solo
                                 ve los globales y los de su grupo (BUG-15).
  - update_challenge_status    : activate/inactivate/archive.

Reglas de dominio aplicadas:
  - Todo query filtra por `tenant_id` explícito (WINDSURF §3).
  - Para estudiantes se excluyen challenges con cupo lleno
    (`current_winners >= max_winners`) y aquellos en los que el
    estudiante agotó `max_attempts`.
  - `get_challenge` retorna preguntas ordenadas por `order_index`.
  - `correct_answer` no se expone aquí — los schemas `ChallengeOut` /
    `ChallengeQuestionOut` lo omiten a nivel Pydantic.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.challenge_engine.schemas import (
    CHALLENGE_STATUSES,
    ChallengeCreate,
    ChallengeQuestionIn,
    ChallengeOut,
    ChallengeQuestionOut,
)
from src.curriculo import service as curriculo_service
from src.shared.models import (
    Challenge,
    ChallengeAttempt,
    ChallengeQuestion,
    Group,
)


# =============================================================================
# 3.1 create_challenge
# =============================================================================
async def nodos_de_las_preguntas(
    db: AsyncSession, preguntas: list[ChallengeQuestionIn]
) -> list[list[str]]:
    """Los nodos VIGENTES de cada pregunta (ESPEC_foco_grupo §1.1).

    422 `nodo_desconocido` si alguno no está en el catálogo. Sin nodos no
    consulta nada: un reto sin etiquetas se crea igual que siempre.
    """
    return [await curriculo_service.canonicos(db, q.nodos) if q.nodos else []
            for q in preguntas]


async def create_challenge(
    db: AsyncSession,
    *,
    teacher_id: UUID,
    tenant_id: UUID,
    data: ChallengeCreate,
) -> Challenge:
    """Crea un Challenge + sus ChallengeQuestions en una sola transacción.

    Validaciones:
      - Si `group_id` viene, debe existir y pertenecer al tenant (404 si no).
    `require_teacher` aguas arriba ya garantiza el rol del creador.
    """
    if data.group_id is not None:
        grp = await db.execute(
            select(Group.id).where(
                Group.id == data.group_id, Group.tenant_id == tenant_id
            )
        )
        if grp.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="group_id not found in tenant",
            )

    # Antes de escribir nada: un nodo desconocido no deja un reto a medias.
    nodos = await nodos_de_las_preguntas(db, data.questions)

    challenge = Challenge(
        tenant_id=tenant_id,
        group_id=data.group_id,
        created_by=teacher_id,
        title=data.title,
        description=data.description,
        challenge_type=data.challenge_type,
        cefr_level=data.cefr_level,
        skill=data.skill,
        topic=data.topic,
        specific_instructions=data.specific_instructions,
        coins_reward=data.coins_reward,
        xp_reward=data.xp_reward,
        max_attempts=data.max_attempts,
        max_winners=data.max_winners,
    )
    db.add(challenge)
    await db.flush()  # necesitamos challenge.id para las preguntas

    for i, q in enumerate(data.questions, start=1):
        db.add(
            ChallengeQuestion(
                challenge_id=challenge.id,
                question_type=q.question_type,
                question_text=q.question_text,
                options_json=q.options_json,
                correct_answer=q.correct_answer,
                order_index=q.order_index or i,
                nodes=nodos[i - 1],
                item_ref=q.item_ref,
                family_ref=q.familia,
                form_role=q.rol,
            )
        )
    await db.flush()
    return challenge


# =============================================================================
# 3.2 list_challenges_for_student
# =============================================================================
def filtro_grupo_estudiante(tenant_id: UUID, group_code: str | None) -> ColumnElement[bool]:
    """Qué retos ve un estudiante: los globales y los de SU grupo (BUG-15).

    Es la ÚNICA fuente de esta regla: la usan el feed y el detalle/arranque
    (`get_challenge_for`), para que no puedan divergir
    (docs/ESPEC_bug13a15.md §1.3, C17). Extraído sin cambios del feed.
    """
    # Subquery: ids de grupos del estudiante (vía group_code).
    # Si el estudiante no tiene group_code, solo ve challenges globales.
    if group_code:
        student_group_ids = (
            select(Group.id)
            .where(
                Group.tenant_id == tenant_id,
                Group.group_code == group_code,
            )
            .scalar_subquery()
        )
        return or_(
            Challenge.group_id.is_(None),
            Challenge.group_id.in_(student_group_ids),
        )
    return Challenge.group_id.is_(None)


async def list_challenges_for_student(
    db: AsyncSession,
    *,
    student_id: UUID,
    tenant_id: UUID,
    group_code: str | None,
) -> list[Challenge]:
    """Feed de challenges disponibles para el estudiante.

    Incluye challenges:
      - del tenant
      - con status='active'
      - globales (group_id IS NULL) o asignados al grupo del estudiante
      - con cupo disponible (current_winners < max_winners)
      - en los que el estudiante NO haya agotado max_attempts
    """
    group_filter = filtro_grupo_estudiante(tenant_id, group_code)

    # Subquery: cantidad de intentos del estudiante por challenge_id.
    attempts_count = (
        select(func.count())
        .select_from(ChallengeAttempt)
        .where(
            ChallengeAttempt.challenge_id == Challenge.id,
            ChallengeAttempt.student_id == student_id,
        )
        .correlate(Challenge)
        .scalar_subquery()
    )

    stmt = (
        select(Challenge)
        .where(
            Challenge.tenant_id == tenant_id,
            Challenge.status == "active",
            Challenge.current_winners < Challenge.max_winners,
            group_filter,
            attempts_count < Challenge.max_attempts,
        )
        .order_by(Challenge.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


# =============================================================================
# 3.2b list_challenges_for_teacher
# =============================================================================
async def list_challenges_for_teacher(
    db: AsyncSession, *, tenant_id: UUID
) -> list[Challenge]:
    """Todos los challenges del tenant (cualquier status) para el dashboard docente."""
    stmt = (
        select(Challenge)
        .where(Challenge.tenant_id == tenant_id)
        .order_by(Challenge.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


# =============================================================================
# 3.3 get_challenge
# =============================================================================
def stmt_reto_del_tenant(challenge_id: UUID, tenant_id: UUID) -> Select[tuple[Challenge]]:
    """El reto por id, SOLO dentro del tenant: la barrera de tenant del detalle.

    Es su ÚNICA fuente (ESPEC_bug13a15 §1.3, errata ERR-26): la usan
    `get_challenge` (personal, submit, T6, PATCH) y `get_challenge_for`
    (estudiante, que le agrega el filtro de grupo). Ninguna otra consulta de
    este camino repite `Challenge.tenant_id ==`.
    """
    return select(Challenge).where(
        Challenge.id == challenge_id, Challenge.tenant_id == tenant_id
    )


async def get_challenge(
    db: AsyncSession, challenge_id: UUID, tenant_id: UUID
) -> Challenge:
    """Fetch un Challenge por id + tenant. 404 si no existe."""
    stmt = stmt_reto_del_tenant(challenge_id, tenant_id)
    challenge = (await db.execute(stmt)).scalar_one_or_none()
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Challenge not found",
        )
    return challenge


# =============================================================================
# 3.3b get_challenge_for — el detalle según quién lo pide (BUG-15)
# =============================================================================
async def get_challenge_for(
    db: AsyncSession,
    challenge_id: UUID,
    *,
    tenant_id: UUID,
    group_code: str | None,
    es_personal: bool,
) -> Challenge:
    """El reto, solo si quien lo pide puede verlo. 404 si no (nunca 403).

    - Personal (docente o admin): igual que `get_challenge`, solo por tenant
      (el personal no cambia en BUG-15; ESPEC §1.3 y §9).
    - Estudiante: además, `filtro_grupo_estudiante`: un reto de otro grupo
      responde el MISMO 404 que un id que no existe, así no delata que existe.
    """
    if es_personal:
        return await get_challenge(db, challenge_id, tenant_id)
    stmt = stmt_reto_del_tenant(challenge_id, tenant_id).where(
        filtro_grupo_estudiante(tenant_id, group_code)
    )
    challenge = (await db.execute(stmt)).scalar_one_or_none()
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Challenge not found",
        )
    return challenge


async def get_questions(
    db: AsyncSession, challenge_id: UUID
) -> list[ChallengeQuestion]:
    """Preguntas de un challenge ordenadas. Usado al armar ChallengeOut."""
    stmt = (
        select(ChallengeQuestion)
        .where(ChallengeQuestion.challenge_id == challenge_id)
        .order_by(ChallengeQuestion.order_index)
    )
    return list((await db.execute(stmt)).scalars().all())


# =============================================================================
# 3.4 update_challenge_status
# =============================================================================
async def update_challenge_status(
    db: AsyncSession,
    challenge_id: UUID,
    tenant_id: UUID,
    new_status: str,
) -> Challenge:
    """Cambia `status`. Valida contra los permitidos por el CHECK de DB."""
    if new_status not in CHALLENGE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Allowed: {CHALLENGE_STATUSES}",
        )
    challenge = await get_challenge(db, challenge_id, tenant_id)
    challenge.status = new_status
    await db.flush()
    return challenge


# =============================================================================
# Serializers (ORM → Pydantic)
# =============================================================================
def question_to_schema(q: ChallengeQuestion) -> ChallengeQuestionOut:
    """Proyecta una pregunta omitiendo `correct_answer` (regla §9)."""
    opts = q.options_json
    # DB JSONB puede traer dict o list; normalizamos a list[dict] | None.
    if opts is None:
        options: list[dict[str, Any]] | None = None
    elif isinstance(opts, list):
        options = opts
    else:
        # Forma inesperada: la envolvemos como lista de un solo dict para
        # no romper el contrato del schema. No debería ocurrir con datos
        # creados por nosotros, pero blindaje defensivo.
        options = [opts] if isinstance(opts, dict) else None
    return ChallengeQuestionOut(
        id=q.id,
        question_type=q.question_type,
        question_text=q.question_text,
        options_json=options,
        order_index=q.order_index,
    )


def challenge_to_schema(
    challenge: Challenge, questions: list[ChallengeQuestion]
) -> ChallengeOut:
    """Arma un ChallengeOut completo (con preguntas serializadas)."""
    return ChallengeOut(
        id=challenge.id,
        title=challenge.title,
        description=challenge.description,
        challenge_type=challenge.challenge_type,
        cefr_level=challenge.cefr_level,
        skill=challenge.skill,
        topic=challenge.topic,
        coins_reward=challenge.coins_reward,
        xp_reward=challenge.xp_reward,
        max_attempts=challenge.max_attempts,
        max_winners=challenge.max_winners,
        current_winners=challenge.current_winners,
        status=challenge.status,
        questions=[question_to_schema(q) for q in questions],
        created_at=challenge.created_at,
    )


async def hydrate(db: AsyncSession, challenge: Challenge) -> ChallengeOut:
    """Atajo: carga las preguntas y devuelve el ChallengeOut listo."""
    questions = await get_questions(db, challenge.id)
    return challenge_to_schema(challenge, questions)


__all__ = [
    "create_challenge",
    "list_challenges_for_student",
    "list_challenges_for_teacher",
    "get_challenge",
    "get_challenge_for",
    "stmt_reto_del_tenant",
    "filtro_grupo_estudiante",
    "get_questions",
    "update_challenge_status",
    "question_to_schema",
    "challenge_to_schema",
    "hydrate",
]

# Silencia el "unused import" de `and_` en algunos linters estrictos; lo
# dejamos importado por si aparecen filtros compuestos en el futuro.
_ = and_
