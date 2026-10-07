"""Lo que el estudiante ve y responde de su refuerzo — ESPEC_refuerzo §1.3 a §1.5.

`planear` es la ÚNICA función que decide qué forma le toca a cada entrada: la
usan la lectura del estudiante, su respuesta (para exigir que conteste la
forma vigente) y el panel del profe (para saber quién está en espera).
"""
from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.challenge_engine.schemas import AnswerSubmit
from src.challenge_engine.service import attempts as attempts_service
from src.challenge_engine.service import challenges as challenges_service
from src.foco import service as foco_service
from src.refuerzo import formas, reglas
from src.refuerzo.reglas import Estado, Forma, Regla
from src.refuerzo.schemas import PendienteOut, RefuerzoOut, RespuestaOut
from src.shared.config import settings
from src.shared.models import ChallengeQuestion, ReinforcementAnswer, ReinforcementQueue

NO_TOCA = "no_toca_todavia"
FORMA_NO_VIGENTE = "forma_no_vigente"
NO_ENCONTRADA = "Reinforcement entry not found"


def _ahora() -> datetime:
    return datetime.now(UTC)


def regla() -> Regla:
    """La regla de "superado", de la configuración. La fija el pedagogo (ERR-16)."""
    return Regla(aciertos_para_repaso=settings.refuerzo_aciertos_para_repaso,
                 dias_repaso=settings.refuerzo_dias_repaso)


async def entradas(db: AsyncSession, tenant_id: UUID,
                   profile_ids: Collection[UUID]) -> list[ReinforcementQueue]:
    """Las entradas de esos estudiantes EN esa institución, de la más vieja a la más nueva."""
    if not profile_ids:
        return []
    stmt = (select(ReinforcementQueue)
            .where(ReinforcementQueue.tenant_id == tenant_id,
                   ReinforcementQueue.profile_id.in_(list(profile_ids)))
            .order_by(ReinforcementQueue.entered_at, ReinforcementQueue.id))
    return list((await db.execute(stmt)).scalars().all())


async def planear(db: AsyncSession, *, tenant_id: UUID, group_code: str | None,
                  cola: Sequence[ReinforcementQueue], ahora: datetime) -> dict[int, Forma | None]:
    """`{entrada: forma a servir, o None si está en espera de contenido}`, de las que TOCAN."""
    tocan = [e for e in cola if reglas.toca(e.status, e.next_due_at, ahora)]
    por_nodo = await formas.candidatas(db, tenant_id, group_code, {e.node_id for e in tocan})
    vistas = await formas.vistas(db, tenant_id, {e.profile_id for e in tocan})
    plan: dict[int, Forma | None] = {}
    usadas: dict[UUID, set[str]] = {}
    for e in tocan:
        dadas = usadas.setdefault(e.profile_id, set())
        forma = reglas.elegir(por_nodo.get(e.node_id, []), vistas[e.profile_id],
                              familia=e.family_ref, etapa=reglas.etapa_de(e.status) or "",
                              usadas=dadas)
        plan[e.id] = forma
        if forma is not None:
            dadas.add(forma.clave)
    return plan


async def leer(db: AsyncSession, *, tenant_id: UUID, profile_id: UUID,
               group_code: str | None) -> RefuerzoOut:
    """Las entradas que tocan, cada una con su forma no vista. No escribe nada."""
    ahora = _ahora()
    cola = await entradas(db, tenant_id, [profile_id])
    plan = await planear(db, tenant_id=tenant_id, group_code=group_code, cola=cola, ahora=ahora)
    con_forma = [(e, plan[e.id]) for e in cola if plan.get(e.id) is not None]
    servidas = con_forma[:settings.refuerzo_max_por_vez]
    nodos = {n.id: n for n in await foco_service.nodos_a_esquema(
        db, [e.node_id for e, _ in servidas])}
    pendientes = []
    for e, forma in servidas:
        assert forma is not None
        pregunta = await db.get(ChallengeQuestion, forma.question_id)
        assert pregunta is not None  # recién leída entre las candidatas
        pendientes.append(PendienteOut(
            entrada_id=e.id, etapa=reglas.etapa_de(e.status) or "", nodo=nodos[e.node_id],
            pregunta=challenges_service.question_to_schema(pregunta)))
    return RefuerzoOut(
        pendientes=pendientes,
        por_repasar=sum(1 for e in cola if e.status == reglas.POR_REPASAR and e.id not in plan),
        en_espera_de_contenido=sum(1 for forma in plan.values() if forma is None),
        superados=sum(1 for e in cola if e.status == reglas.SUPERADO))


# ------------------------------------------------------------------ responder
async def _entrada_del_estudiante(db: AsyncSession, tenant_id: UUID, profile_id: UUID,
                                  entrada_id: int) -> ReinforcementQueue | None:
    """La entrada, SOLO si es de ese estudiante en esa institución. Bloquea la fila."""
    stmt = (select(ReinforcementQueue)
            .where(ReinforcementQueue.id == entrada_id,
                   ReinforcementQueue.tenant_id == tenant_id,
                   ReinforcementQueue.profile_id == profile_id).with_for_update())
    return (await db.execute(stmt)).scalar_one_or_none()


async def _respuesta_previa(db: AsyncSession, entrada_id: int,
                            question_id: UUID) -> ReinforcementAnswer | None:
    return (await db.execute(select(ReinforcementAnswer).where(
        ReinforcementAnswer.queue_id == entrada_id,
        ReinforcementAnswer.question_id == question_id))).scalar_one_or_none()


def _exigir_forma_vigente(forma: Forma | None, question_id: UUID) -> None:
    """Solo se responde LA forma que el servidor serviría ahora: ni una vista, ni otra."""
    if forma is None or forma.question_id != question_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=FORMA_NO_VIGENTE)


def _salida(entrada_id: int, pregunta: ChallengeQuestion, *, acerto: bool, estado: str,
            proxima: datetime | None, repetida: bool) -> RespuestaOut:
    return RespuestaOut(entrada_id=entrada_id, question_id=pregunta.id, is_correct=acerto,
                        correct_answer=pregunta.correct_answer or "", explanation=None,
                        estado=estado, proxima_fecha=proxima, repetida=repetida, coins_earned=0)


async def responder(db: AsyncSession, *, tenant_id: UUID, profile_id: UUID,
                    group_code: str | None, entrada_id: int, question_id: UUID,
                    answer: str) -> RespuestaOut:
    """Califica la forma vigente y mueve el estado. Sin monedas. No hace `commit`."""
    entrada = await _entrada_del_estudiante(db, tenant_id, profile_id, entrada_id)
    if entrada is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_ENCONTRADA)
    previa = await _respuesta_previa(db, entrada.id, question_id)
    pregunta = await db.get(ChallengeQuestion, question_id)
    if previa is not None and pregunta is not None:  # gana la primera: se devuelve lo guardado
        return _salida(entrada.id, pregunta, acerto=previa.is_correct,
                       estado=previa.status_after, proxima=previa.due_after, repetida=True)
    ahora = _ahora()
    if not reglas.toca(entrada.status, entrada.next_due_at, ahora):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=NO_TOCA)
    cola = await entradas(db, tenant_id, [profile_id])
    plan = await planear(db, tenant_id=tenant_id, group_code=group_code, cola=cola, ahora=ahora)
    _exigir_forma_vigente(plan.get(entrada.id), question_id)
    if pregunta is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=FORMA_NO_VIGENTE)
    # La MISMA calificación de `/submit`: una sola fuente.
    _puntaje, detalle = attempts_service.grade_answers(
        [pregunta], [AnswerSubmit(question_id=question_id, answer=answer)])
    acerto = bool(detalle[0]["is_correct"])
    etapa = reglas.etapa_de(entrada.status) or ""
    nuevo = reglas.transicion(
        Estado(entrada.status, entrada.hits, entrada.next_due_at, entrada.mastered_at),
        acerto, ahora, regla())
    entrada.status, entrada.hits = nuevo.status, nuevo.hits
    entrada.next_due_at, entrada.mastered_at = nuevo.next_due_at, nuevo.mastered_at
    entrada.updated_at = ahora
    db.add(ReinforcementAnswer(
        queue_id=entrada.id, tenant_id=tenant_id, profile_id=profile_id,
        question_id=question_id, form_key=reglas.clave_de_forma(pregunta.item_ref, pregunta.id),
        stage=etapa, answer=answer, is_correct=acerto, status_after=nuevo.status,
        due_after=nuevo.next_due_at))
    await db.flush()
    return _salida(entrada.id, pregunta, acerto=acerto, estado=nuevo.status,
                   proxima=nuevo.next_due_at, repetida=False)
