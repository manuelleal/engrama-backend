"""Lo que ENTRA a la cola de refuerzo — ESPEC_refuerzo §1.1.

Dos ganchos, uno por origen: `desde_hoja` (el Grader guardó una hoja) y
`desde_intento` (un reto se calificó). Ninguno hace `commit`: van en la
transacción de quien los llama. Entra el NODO, una fila por
`(institución, estudiante, nodo)`.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, case, delete, exists, func, select
from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.grader import reglas as grader_reglas
from src.grader.schemas import HojaIn
from src.refuerzo import reglas
from src.shared.models import (
    Challenge,
    ChallengeQuestion,
    GraderExam,
    GraderExamItem,
    ReinforcementAnswer,
    ReinforcementQueue,
)

ORIGEN_GRADER = "grader"
ORIGEN_RETO = "reto"


@dataclass(frozen=True)
class Fallo:
    nodo: str
    familia: str | None


def _solo_si_es_otro_origen(nueva: Insert) -> ColumnElement[bool]:
    """La MISMA hoja o el MISMO intento no cuentan dos veces."""
    return ReinforcementQueue.origin_ref != nueva.excluded.origin_ref


async def registrar_fallos(db: AsyncSession, *, tenant_id: UUID, profile_id: UUID,
                           fallos: Sequence[Fallo], origen: str, origen_ref: str) -> None:
    """Mete cada nodo fallado. Si ya estaba: suma un fallo y vuelve a `en_refuerzo`
    (un nodo `superado` se reabre). Una sentencia por nodo: dos a la vez no duplican."""
    por_nodo: dict[str, str | None] = {}
    for fallo in fallos:
        por_nodo[fallo.nodo] = por_nodo.get(fallo.nodo) or fallo.familia
    for nodo, familia in sorted(por_nodo.items()):
        nueva = pg_insert(ReinforcementQueue).values(
            tenant_id=tenant_id, profile_id=profile_id, node_id=nodo,
            status=reglas.EN_REFUERZO, family_ref=familia, origin=origen, origin_ref=origen_ref)
        era_superado = case((ReinforcementQueue.status == reglas.SUPERADO, 1), else_=0)
        await db.execute(nueva.on_conflict_do_update(
            constraint="reinforcement_queue_owner_node_key",
            set_={"status": reglas.EN_REFUERZO, "hits": 0, "next_due_at": None,
                  "mastered_at": None, "failures": ReinforcementQueue.failures + 1,
                  "reopened": ReinforcementQueue.reopened + era_superado,
                  "family_ref": func.coalesce(nueva.excluded.family_ref,
                                              ReinforcementQueue.family_ref),
                  "origin": origen, "origin_ref": origen_ref, "updated_at": func.now()},
            where=_solo_si_es_otro_origen(nueva)))


async def retirar_intactas(db: AsyncSession, *, tenant_id: UUID, profile_id: UUID,
                           origen_ref: str, conservar: set[str]) -> None:
    """La hoja corregida ya no falla un ítem: se va la entrada que ESA hoja creó, solo si
    nadie la ha tocado (primer fallo, sin reabrir, sin respuestas)."""
    con_respuestas = exists().where(ReinforcementAnswer.queue_id == ReinforcementQueue.id)
    await db.execute(delete(ReinforcementQueue).where(
        ReinforcementQueue.tenant_id == tenant_id, ReinforcementQueue.profile_id == profile_id,
        ReinforcementQueue.origin_ref == origen_ref,
        ReinforcementQueue.status == reglas.EN_REFUERZO, ReinforcementQueue.failures == 1,
        ReinforcementQueue.reopened == 0, ReinforcementQueue.node_id.not_in(conservar or {""}),
        ~con_respuestas))


# ------------------------------------------------------------------ el Grader
def fallados_de_la_hoja(hoja: HojaIn) -> list[str]:
    """Los ítems que NO fueron acierto: marcada incorrecta, vacía o doble."""
    return [item.item_id for item in hoja.items if not grader_reglas.es_acierto(item)]


async def _nodos_de_los_items(db: AsyncSession, exam_id: UUID) -> dict[str, list[str]]:
    filas = (await db.execute(
        select(GraderExamItem.item_id, GraderExamItem.nodos)
        .where(GraderExamItem.exam_id == exam_id,
               func.cardinality(GraderExamItem.nodos) > 0))).all()
    return {item_id: list(nodos) for item_id, nodos in filas}


async def _familias_de(db: AsyncSession, tenant_id: UUID, items: list[str]) -> dict[str, str]:
    """La familia de cada ítem, si ese mismo ítem está sembrado en un reto de la institución."""
    if not items:
        return {}
    filas = (await db.execute(
        select(ChallengeQuestion.item_ref, ChallengeQuestion.family_ref)
        .join(Challenge, Challenge.id == ChallengeQuestion.challenge_id)
        .where(Challenge.tenant_id == tenant_id, ChallengeQuestion.item_ref.in_(items),
               ChallengeQuestion.family_ref.is_not(None)))).all()
    return {item: familia for item, familia in filas}


async def desde_hoja(db: AsyncSession, examen: GraderExam, hoja: HojaIn, *,
                     profile_id: UUID) -> None:
    """Gancho del Grader: tras guardar una hoja, sus fallos con nodos entran a la cola."""
    nodos_de = await _nodos_de_los_items(db, examen.id)
    if not nodos_de:
        return  # el examen no lleva nodos: nada que hacer
    fallados = [i for i in fallados_de_la_hoja(hoja) if i in nodos_de]
    familias = await _familias_de(db, examen.tenant_id, fallados)
    fallos = [Fallo(nodo, familias.get(item)) for item in fallados for nodo in nodos_de[item]]
    ref = grader_reglas.event_id_de(examen.codigo, hoja.numero)
    await retirar_intactas(db, tenant_id=examen.tenant_id, profile_id=profile_id,
                           origen_ref=ref, conservar={f.nodo for f in fallos})
    await registrar_fallos(db, tenant_id=examen.tenant_id, profile_id=profile_id,
                           fallos=fallos, origen=ORIGEN_GRADER, origen_ref=ref)


# -------------------------------------------------------------------- un reto
async def desde_intento(db: AsyncSession, *, tenant_id: UUID, student_id: UUID,
                        attempt_id: UUID, questions: Sequence[ChallengeQuestion],
                        details: Sequence[dict[str, Any]]) -> None:
    """Gancho de `/submit`: las preguntas falladas meten sus nodos. Sin nodos, no consulta."""
    con_nodos = {str(q.id): q for q in questions if q.nodes}
    if not con_nodos:
        return
    fallos = [Fallo(nodo, con_nodos[str(d["question_id"])].family_ref)
              for d in details
              if not d.get("is_correct") and str(d.get("question_id")) in con_nodos
              for nodo in con_nodos[str(d["question_id"])].nodes]
    if fallos:
        await registrar_fallos(db, tenant_id=tenant_id, profile_id=student_id, fallos=fallos,
                               origen=ORIGEN_RETO, origen_ref=f"attempt:{attempt_id}")
