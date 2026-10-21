"""El camino de nivel contra la base — docs/ESPEC_camino_progreso.md §1.

  - `leer`: el camino del estudiante en su nivel de práctica. NO escribe nada,
    no hace `commit` y no toca monedas (el camino no paga: pedagogía 06 §2.5).

Toda consulta filtra por `tenant_id` y, lo del estudiante, por `profile_id`.
Qué retos ve sale de la MISMA regla del feed (`filtro_grupo_estudiante`) y sin
los `solo_refuerzo` (`fuera_de_refuerzo`): una sola fuente para las dos cosas.
Los estados, el bloqueo suave y la recomendada los decide `reglas` (puro).
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.camino import reglas
from src.camino.reglas import Demorada, Estacion, Intento, Umbrales
from src.camino.schemas import CaminoOut, EstacionOut, UnidadOut
from src.challenge_engine.service import calificar
from src.challenge_engine.service import challenges as challenges_service
from src.practica import reglas as practica_reglas
from src.practica import service as practica_service
from src.shared.config import settings
from src.shared.models import (
    Challenge,
    ChallengeAttempt,
    ChallengeAttemptAnswer,
    ChallengeQuestion,
    ReinforcementAnswer,
)

FORMAS_NO_VISTAS = ("gemela", "repaso")  # las que cuentan como evidencia demorada


def _instante() -> datetime:
    """El reloj real del proceso (el mismo que pone `started_at` y `completed_at`)."""
    return datetime.now(UTC)


def umbrales() -> Umbrales:
    return Umbrales(
        completada=settings.camino_umbral_completada, dominada=settings.camino_umbral_dominada,
        dias_atasco=settings.camino_dias_atasco, dias_dominio=settings.camino_dias_dominio,
        minimo_demoradas=settings.camino_minimo_demoradas)


def _visibles(tenant_id: UUID, group_code: str | None) -> ColumnElement[bool]:
    """Qué retos ve el estudiante: la MISMA regla del feed (BUG-15)."""
    return challenges_service.filtro_grupo_estudiante(tenant_id, group_code)


def _del_feed() -> ColumnElement[bool]:
    """Sin los `solo_refuerzo`: sus preguntas son formas del repaso, no estaciones."""
    return challenges_service.fuera_de_refuerzo()


def _del_estudiante(profile_id: UUID) -> ColumnElement[bool]:
    """Los intentos de ESE estudiante (con la institución, que va aparte)."""
    return ChallengeAttempt.student_id == profile_id


def _escrito(tipo: str | None) -> bool:
    """¿Se responde escribiendo? Lo que no es de opción (la misma regla de `calificar`)."""
    return (tipo or "multiple_choice") not in calificar.TIPOS_DE_OPCION


async def _retos_visibles(db: AsyncSession, tenant_id: UUID,
                          group_code: str | None) -> list[Any]:
    """Los retos del feed que ve el estudiante, de cualquier nivel, con su número de preguntas."""
    preguntas = (select(func.count()).select_from(ChallengeQuestion)
                 .where(ChallengeQuestion.challenge_id == Challenge.id)
                 .correlate(Challenge).scalar_subquery())
    filas = (await db.execute(
        select(Challenge.id, Challenge.topic, Challenge.skill, Challenge.title,
               Challenge.challenge_type, Challenge.max_attempts, Challenge.cefr_level,
               preguntas.label("preguntas"))
        .where(Challenge.tenant_id == tenant_id, Challenge.status == "active",
               _visibles(tenant_id, group_code), _del_feed(),
               Challenge.challenge_type.not_in(practica_service.TIPOS_FUERA),
               Challenge.topic.is_not(None), Challenge.cefr_level.is_not(None)))).all()
    return [f for f in filas if f.preguntas]


def _nivel_a_mostrar(por_nivel: dict[str, list[Any]], nivel: str) -> tuple[str, bool]:
    """`(nivel, prestado)`: el de práctica si tiene retos; si no, el más cercano que tenga."""
    if por_nivel.get(nivel):
        return nivel, False
    for otro in practica_reglas.otros_niveles(nivel):
        if por_nivel.get(otro):
            return otro, True
    return nivel, False


async def _intentos(db: AsyncSession, tenant_id: UUID, profile_id: UUID,
                    retos: Sequence[UUID]) -> dict[UUID, list[Intento]]:
    if not retos:
        return {}
    filas = (await db.execute(
        select(ChallengeAttempt.challenge_id, ChallengeAttempt.status,
               ChallengeAttempt.started_at, ChallengeAttempt.completed_at,
               ChallengeAttempt.answers, ChallengeAttempt.is_correct)
        .where(ChallengeAttempt.tenant_id == tenant_id, _del_estudiante(profile_id),
               ChallengeAttempt.challenge_id.in_(list(retos))))).all()
    salida: dict[UUID, list[Intento]] = defaultdict(list)
    for reto, estado, inicio, fin, respuestas, gano in filas:
        aciertos = sum(1 for r in respuestas or [] if isinstance(r, dict) and r.get("is_correct"))
        salida[reto].append(Intento(estado, inicio, fin if estado == "completed" else None,
                                    aciertos, bool(gano)))
    return salida


async def _demoradas(db: AsyncSession, tenant_id: UUID, profile_id: UUID,
                     topics: Sequence[str]) -> dict[str, list[Demorada]]:
    """Las respuestas de ese estudiante a formas gemela o repaso de esas unidades, con su hora:
    las de `/answers` (un reintento, la segunda vuelta) y las del repaso."""
    if not topics:
        return {}
    salida: dict[str, list[Demorada]] = defaultdict(list)
    for tabla in (ChallengeAttemptAnswer, ReinforcementAnswer):
        filas = (await db.execute(
            select(tabla.answered_at, tabla.is_correct, ChallengeQuestion.question_type,
                   Challenge.topic)
            .join(ChallengeQuestion, ChallengeQuestion.id == tabla.question_id)
            .join(Challenge, Challenge.id == ChallengeQuestion.challenge_id)
            .where(tabla.tenant_id == tenant_id, tabla.profile_id == profile_id,
                   Challenge.tenant_id == tenant_id, Challenge.topic.in_(list(topics)),
                   ChallengeQuestion.form_role.in_(FORMAS_NO_VISTAS)))).all()
        for cuando, acerto, tipo, topic in filas:
            salida[topic].append(Demorada(cuando, bool(acerto), _escrito(tipo)))
    return salida


def _estacion(fila: Any, intentos: list[Intento]) -> Estacion:
    return Estacion(str(fila.id), fila.title, fila.skill, fila.challenge_type,
                    int(fila.preguntas), int(fila.max_attempts), _escrito(fila.challenge_type),
                    tuple(intentos))


def _orden(fila: Any) -> tuple[str, int, str, str]:
    """El MISMO orden de la tanda (`practica.reglas.orden_fijo`)."""
    return practica_reglas.orden_fijo(practica_reglas.Candidato(
        str(fila.id), fila.topic, fila.skill, fila.title, int(fila.preguntas)))


def _unidad(topic: str, posicion: int, estaciones: list[Estacion], e: reglas.EstadoDeUnidad,
            a: reglas.Acceso, es_recomendada: bool) -> UnidadOut:
    siguiente = next((s.id for s in estaciones if s.puede_jugar), None)
    return UnidadOut(
        topic=topic, numero=reglas.numero_de(topic, posicion),
        titulo=reglas.titulo_de(topic, estaciones[0].title), estado=e.estado, acceso=a.acceso,
        recomendada=es_recomendada, atascada=a.atascada, estaciones_total=len(estaciones),
        estaciones_jugadas=e.jugadas, preguntas=e.preguntas, aciertos=e.aciertos,
        porcentaje=e.porcentaje, empezada_en=e.empezada_en, completada_en=e.completada_en,
        se_abre_el=a.se_abre_el, siguiente_reto=UUID(siguiente) if siguiente else None,
        estaciones=[EstacionOut(id=UUID(s.id), title=s.title, skill=s.skill,
                                challenge_type=s.tipo, preguntas=s.preguntas, jugada=s.jugada,
                                ganada=s.ganada, aciertos=s.mejor) for s in estaciones])


async def leer(db: AsyncSession, *, tenant_id: UUID, profile_id: UUID,
               group_code: str | None) -> CaminoOut:
    """El camino del estudiante: las unidades de su nivel de práctica, en orden. NO escribe."""
    u = umbrales()
    nivel_practica, ancla = await practica_service.nivel_vigente(db, tenant_id, profile_id)
    por_nivel: dict[str, list[Any]] = defaultdict(list)
    for fila in await _retos_visibles(db, tenant_id, group_code):
        base = practica_reglas.base(fila.cefr_level)
        if base is not None:
            por_nivel[base].append(fila)
    nivel, prestado = _nivel_a_mostrar(por_nivel, nivel_practica)
    filas = sorted(por_nivel.get(nivel, []), key=_orden)
    intentos = await _intentos(db, tenant_id, profile_id, [f.id for f in filas])
    por_topic: dict[str, list[Estacion]] = defaultdict(list)
    for fila in filas:
        por_topic[fila.topic].append(_estacion(fila, intentos.get(fila.id, [])))
    topics = sorted(por_topic)
    demoradas = await _demoradas(db, tenant_id, profile_id, topics)
    estados = [reglas.estado_de(por_topic[t], demoradas.get(t, []), u) for t in topics]
    acc = reglas.accesos(estados, _instante(), u)
    indice = reglas.recomendada(estados, acc)
    return CaminoOut(
        nivel=nivel, nivel_de_practica=nivel_practica, con_nivel_de_set=ancla is not None,
        prestado=prestado, umbral_completada=u.completada, umbral_dominada=u.dominada,
        dias_atasco=u.dias_atasco, recomendada=None if indice is None else topics[indice],
        unidades=[_unidad(t, i + 1, por_topic[t], estados[i], acc[i], i == indice)
                  for i, t in enumerate(topics)])
