"""Leer y reemplazar los nodos de las preguntas de un reto — ESPEC_foco_grupo §1.1.

Es el contrato para etiquetar los retos YA sembrados. Sin IA: los nodos los
manda quien siembra, y aquí solo se comprueba que existan en el catálogo.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.challenge_engine.service import challenges as challenges_service
from src.curriculo import service as curriculo_service
from src.foco.schemas import EtiquetasIn, EtiquetasOut, PreguntaNodosOut
from src.shared.models import Challenge, ChallengeQuestion
from src.teachers.service import access as access_service

PREGUNTA_AJENA = "pregunta_ajena"
NO_ENCONTRADO = "Challenge not found"


async def puede_etiquetar(db: AsyncSession, auth: AuthContext, reto: Challenge) -> bool:
    """El admin, cualquier reto de su institución; el docente, los de un grupo que dicta."""
    if reto.group_id is None:
        return auth.is_admin
    visibles = {g.id for g in await access_service.visible_groups(db, auth)}
    return reto.group_id in visibles


async def reto_etiquetable(db: AsyncSession, auth: AuthContext, challenge_id: UUID) -> Challenge:
    """El reto, solo si `auth` puede etiquetarlo. Si no, 404 (nunca 403)."""
    stmt = challenges_service.stmt_reto_del_tenant(challenge_id, auth.tenant_id)
    reto = (await db.execute(stmt)).scalar_one_or_none()
    if reto is None or not await puede_etiquetar(db, auth, reto):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_ENCONTRADO)
    return reto


async def leer(db: AsyncSession, challenge_id: UUID) -> EtiquetasOut:
    """Las preguntas del reto con sus nodos, releídas de la base (no de la sesión)."""
    stmt = (select(ChallengeQuestion).where(ChallengeQuestion.challenge_id == challenge_id)
            .order_by(ChallengeQuestion.order_index)
            .execution_options(populate_existing=True))
    preguntas = (await db.execute(stmt)).scalars().all()
    return EtiquetasOut(challenge_id=challenge_id, preguntas=[
        PreguntaNodosOut(question_id=q.id, order_index=q.order_index, nodos=list(q.nodes or []),
                         item_ref=q.item_ref, familia=q.family_ref, rol=q.form_role)
        for q in preguntas])


def exigir_que_sean_del_reto(pedidas: list[UUID], del_reto: set[UUID]) -> None:
    if any(qid not in del_reto for qid in pedidas):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=PREGUNTA_AJENA)


async def reetiquetar(db: AsyncSession, reto: Challenge, datos: EtiquetasIn) -> None:
    """Reemplaza los nodos de las preguntas nombradas. Todo o nada; no hace `commit`."""
    del_reto = {q.id for q in await challenges_service.get_questions(db, reto.id)}
    exigir_que_sean_del_reto([p.question_id for p in datos.preguntas], del_reto)
    # Primero se resuelven TODOS: un nodo desconocido no deja nada a medias.
    resueltos = [(p, await curriculo_service.canonicos(db, p.nodos)) for p in datos.preguntas]
    columnas = {"item_ref": "item_ref", "familia": "family_ref", "rol": "form_role"}
    for pedida, nodos in resueltos:
        # La identidad, la familia y el rol solo se tocan si VINIERON en el cuerpo.
        extra = {columna: getattr(pedida, campo) for campo, columna in columnas.items()
                 if campo in pedida.model_fields_set}
        await db.execute(update(ChallengeQuestion)
                         .where(ChallengeQuestion.id == pedida.question_id)
                         .values(nodes=nodos, **extra))
    await db.flush()
