"""Las formas candidatas de un nodo y lo que cada estudiante ya vio — ESPEC_refuerzo §1.2.

Dos consultas en bloque (sirven a un estudiante o a todo un grupo): las
preguntas con esos nodos que el grupo puede ver, y las identidades vistas.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from uuid import UUID

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.challenge_engine.service import challenges as challenges_service
from src.refuerzo.reglas import Forma, clave_de_forma
from src.shared.models import (
    Challenge,
    ChallengeAttempt,
    ChallengeQuestion,
    GraderSheet,
    GraderSheetItem,
    ReinforcementAnswer,
)

TIPOS_SIN_AUTOCALIFICAR = ("open",)


def _visibles(tenant_id: UUID, group_code: str | None) -> ColumnElement[bool]:
    """Qué retos ve el estudiante: la MISMA regla del feed (BUG-15; una sola fuente)."""
    return challenges_service.filtro_grupo_estudiante(tenant_id, group_code)


async def candidatas(db: AsyncSession, tenant_id: UUID, group_code: str | None,
                     nodos: Collection[str]) -> dict[str, list[Forma]]:
    """`{nodo: [formas]}`: preguntas con ese nodo, de retos ACTIVOS que el grupo ve."""
    if not nodos:
        return {}
    filas = (await db.execute(
        select(ChallengeQuestion.id, ChallengeQuestion.nodes, ChallengeQuestion.item_ref,
               ChallengeQuestion.family_ref, ChallengeQuestion.form_role)
        .join(Challenge, Challenge.id == ChallengeQuestion.challenge_id)
        .where(Challenge.tenant_id == tenant_id, Challenge.status == "active",
               _visibles(tenant_id, group_code),
               ChallengeQuestion.question_type.not_in(TIPOS_SIN_AUTOCALIFICAR),
               ChallengeQuestion.nodes.overlap(list(nodos))))).all()
    por_nodo: dict[str, list[Forma]] = defaultdict(list)
    for question_id, sus_nodos, item_ref, familia, rol in filas:
        forma = Forma(question_id, clave_de_forma(item_ref, question_id), familia, rol)
        for nodo in set(sus_nodos) & set(nodos):
            por_nodo[nodo].append(forma)
    return por_nodo


async def vistas(db: AsyncSession, tenant_id: UUID,
                 profile_ids: Collection[UUID]) -> dict[UUID, set[str]]:
    """`{estudiante: identidades que ya vio}`: en retos, en el refuerzo y en exámenes."""
    visto: dict[UUID, set[str]] = defaultdict(set)
    if not profile_ids:
        return visto
    ids = list(profile_ids)
    en_retos = (await db.execute(  # toda pregunta de un reto que abrió, lo haya enviado o no
        select(ChallengeAttempt.student_id, ChallengeQuestion.id, ChallengeQuestion.item_ref)
        .join(ChallengeQuestion, ChallengeQuestion.challenge_id == ChallengeAttempt.challenge_id)
        .where(ChallengeAttempt.tenant_id == tenant_id,
               ChallengeAttempt.student_id.in_(ids)).distinct())).all()
    for estudiante, question_id, item_ref in en_retos:
        visto[estudiante].add(clave_de_forma(item_ref, question_id))
    en_refuerzo = (await db.execute(
        select(ReinforcementAnswer.profile_id, ReinforcementAnswer.form_key)
        .where(ReinforcementAnswer.tenant_id == tenant_id,
               ReinforcementAnswer.profile_id.in_(ids)))).all()
    for estudiante, clave in en_refuerzo:
        visto[estudiante].add(clave)
    en_examenes = (await db.execute(  # el `item_id` de la hoja ES el `item_ref` del banco
        select(GraderSheet.profile_id, GraderSheetItem.item_id)
        .join(GraderSheetItem, GraderSheetItem.sheet_id == GraderSheet.id)
        .where(GraderSheet.tenant_id == tenant_id,
               GraderSheet.profile_id.in_(ids)).distinct())).all()
    for estudiante, item_id in en_examenes:
        visto[estudiante].add(item_id)
    return visto
