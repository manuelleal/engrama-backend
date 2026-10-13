"""Las preguntas de UN intento — ESPEC_l1_correccion_por_pregunta §10.4.

Casi siempre son las del reto. Pero quien ya respondió ese reto pregunta por
pregunta (ya vio sus claves) recibe, al reintentar, la forma GEMELA de cada
pregunta si existe una que no haya visto: así el segundo intento no se gana
copiando. El intento recuerda qué preguntas se le sirvieron
(`challenge_attempts.served_questions`).

No importa `attempts` (lo usa él): aquí solo hay lecturas y la elección.
"""
from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.challenge_engine.schemas import ChallengeOut
from src.challenge_engine.service import challenges as challenges_service
from src.refuerzo import formas as refuerzo_formas
from src.refuerzo import reglas as refuerzo_reglas
from src.refuerzo.reglas import Forma
from src.shared.models import (
    Challenge,
    ChallengeAttempt,
    ChallengeAttemptAnswer,
    ChallengeQuestion,
)


async def tiene_respuestas(db: AsyncSession, attempt_id: UUID) -> bool:
    """¿Ese intento ya tiene respuestas guardadas por `/answers`?"""
    return (await db.execute(
        select(ChallengeAttemptAnswer.id)
        .where(ChallengeAttemptAnswer.attempt_id == attempt_id).limit(1)
    )).scalar_one_or_none() is not None


async def preguntas_del_intento(db: AsyncSession,
                                attempt: ChallengeAttempt) -> list[ChallengeQuestion]:
    """Las preguntas que se califican en ESE intento, en su orden."""
    if not attempt.served_questions:
        return await challenges_service.get_questions(db, attempt.challenge_id)
    filas = (await db.execute(select(ChallengeQuestion).where(
        ChallengeQuestion.id.in_(list(attempt.served_questions))))).scalars().all()
    por_id = {q.id: q for q in filas}
    return [por_id[i] for i in attempt.served_questions if i in por_id]


def esquema_del_intento(challenge: Challenge,
                        preguntas: list[ChallengeQuestion]) -> ChallengeOut:
    """El reto con las preguntas servidas (sin clave), numeradas en su orden."""
    esquema = challenges_service.challenge_to_schema(challenge, preguntas)
    return esquema.model_copy(update={"questions": [
        q.model_copy(update={"order_index": i})
        for i, q in enumerate(esquema.questions, start=1)]})


async def _ya_vio_las_claves(db: AsyncSession, tenant_id: UUID, student_id: UUID,
                             challenge_id: UUID) -> bool:
    """¿Respondió antes ESTE reto pregunta por pregunta? (Cada respuesta le mostró la clave.)"""
    return (await db.execute(
        select(ChallengeAttemptAnswer.id)
        .join(ChallengeAttempt, ChallengeAttempt.id == ChallengeAttemptAnswer.attempt_id)
        .where(ChallengeAttempt.tenant_id == tenant_id,
               ChallengeAttempt.student_id == student_id,
               ChallengeAttempt.challenge_id == challenge_id).limit(1)
    )).scalar_one_or_none() is not None


async def _de_las_familias(db: AsyncSession, tenant_id: UUID, group_code: str | None,
                           familias: list[str]) -> dict[str, list[tuple[Forma, str]]]:
    """`{familia: [(forma, tipo de pregunta)]}` de retos ACTIVOS que el grupo ve."""
    filas = (await db.execute(
        select(ChallengeQuestion.id, ChallengeQuestion.item_ref, ChallengeQuestion.family_ref,
               ChallengeQuestion.form_role, ChallengeQuestion.question_type)
        .join(Challenge, Challenge.id == ChallengeQuestion.challenge_id)
        .where(Challenge.tenant_id == tenant_id, Challenge.status == "active",
               challenges_service.filtro_grupo_estudiante(tenant_id, group_code),
               ChallengeQuestion.family_ref.in_(familias)))).all()
    por_familia: dict[str, list[tuple[Forma, str]]] = defaultdict(list)
    for question_id, item_ref, familia, rol, tipo in filas:
        forma = Forma(question_id, refuerzo_reglas.clave_de_forma(item_ref, question_id),
                      familia, rol)
        por_familia[familia].append((forma, tipo))
    return por_familia


async def formas_del_reintento(db: AsyncSession, *, tenant_id: UUID, student_id: UUID,
                               group_code: str | None,
                               challenge: Challenge) -> list[UUID] | None:
    """Las preguntas de un REINTENTO, o `None` si son las del reto.

    Solo para quien ya vio las claves por `/answers`. Cada pregunta con familia
    cambia por una forma de su familia que no ha visto (gemela, después
    repaso), del mismo tipo; la que no tiene, se repite.
    """
    if not await _ya_vio_las_claves(db, tenant_id, student_id, challenge.id):
        return None
    preguntas = await challenges_service.get_questions(db, challenge.id)
    familias = sorted({q.family_ref for q in preguntas if q.family_ref})
    if not familias:
        return None
    candidatas = await _de_las_familias(db, tenant_id, group_code, familias)
    vistas = (await refuerzo_formas.vistas(db, tenant_id, [student_id]))[student_id]
    servidas: list[UUID] = []
    usadas: set[str] = set()
    for q in preguntas:
        del_tipo = [f for f, tipo in candidatas.get(q.family_ref or "", [])
                    if tipo == q.question_type]
        forma = refuerzo_reglas.elegir(del_tipo, vistas, familia=q.family_ref,
                                       etapa=refuerzo_reglas.ETAPA_REFUERZO, usadas=usadas)
        if forma is None:
            servidas.append(q.id)
            continue
        servidas.append(forma.question_id)
        usadas.add(forma.clave)
    return servidas if usadas else None
