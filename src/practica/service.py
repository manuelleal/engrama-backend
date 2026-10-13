"""El nivel de práctica y la tanda de hoy contra la base — ESPEC_practica_y_tanda.

  - `tras_intento`: el gancho de `/submit`; mueve la escalera. No hace `commit`.
  - `ver_tanda`: la tanda de hoy. NO escribe.
  - `pedir_tanda`: crea la de hoy (o la siguiente). No hace `commit`.

Toda consulta filtra por `tenant_id` Y `profile_id`. El nivel de SET solo se
LEE (como ancla): este módulo no escribe el nivel confirmado.

Dos relojes, a propósito: el DÍA de la tanda es el de la racha (`racha.hoy()`,
la costura de los tests); los instantes que se comparan con `completed_at` de
los intentos son del reloj real de este proceso (`_instante`), nunca el de la
base, que en el contenedor de pruebas se desfasa.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import ColumnElement, and_, exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.challenge_engine.service import challenges as challenges_service
from src.engrama_core.service import economia, level
from src.practica import reglas
from src.practica.reglas import Candidato, Escalera, Tamano
from src.practica.schemas import PracticaOut, RetoDeTandaOut, TandaDeHoyOut, TandaOut
from src.racha import service as racha_service
from src.refuerzo import service as refuerzo_service
from src.refuerzo.schemas import PendienteOut
from src.shared.config import settings
from src.shared.models import (
    Challenge,
    ChallengeAttempt,
    ChallengeQuestion,
    PracticeLevel,
    PracticeTanda,
    ReinforcementAnswer,
)

PENDIENTE, JUGADO, GANADO = "pendiente", "jugado", "ganado"
TIPOS_FUERA = ("open",)  # no se autocalifican: no entran a la tanda
# Quien empieza no ha cambiado de nivel: su ventana mira todo lo que ya respondió
# (también el intento que hizo nacer la fila). Solo un CAMBIO de nivel la vacía.
VENTANA_ABIERTA = datetime(2000, 1, 1, tzinfo=UTC)


def _instante() -> datetime:
    """El reloj real del proceso (el mismo que pone `completed_at` en `/submit`)."""
    return datetime.now(UTC)


def escalera() -> Escalera:
    return Escalera(
        ventana=settings.practica_ventana, sube=settings.practica_sube,
        baja=settings.practica_baja, ventana_rapida=settings.practica_ventana_rapida,
        sube_rapida=settings.practica_sube_rapida, baja_rapida=settings.practica_baja_rapida,
        decisiones_rapidas=settings.practica_decisiones_rapidas)


def tamano() -> Tamano:
    return Tamano(preguntas_min=settings.tanda_preguntas_min, retos_max=settings.tanda_retos_max)


def _del_dueno(modelo: type[PracticeLevel] | type[PracticeTanda], tenant_id: UUID,
               profile_id: UUID) -> ColumnElement[bool]:
    """La ÚNICA fuente del filtro por dueño: institución Y estudiante."""
    return and_(modelo.tenant_id == tenant_id, modelo.profile_id == profile_id)


def _visibles(tenant_id: UUID, group_code: str | None) -> ColumnElement[bool]:
    """Qué retos ve el estudiante: la MISMA regla del feed (BUG-15; una sola fuente)."""
    return challenges_service.filtro_grupo_estudiante(tenant_id, group_code)


def _del_nivel(nivel: str) -> ColumnElement[bool]:
    """Los retos de ese nivel de práctica: `B1+` y `B1-` son B1. Nada del nivel de arriba."""
    return func.left(Challenge.cefr_level, 2) == nivel


# ------------------------------------------------------------- el nivel de práctica
async def _nivel_de_set(db: AsyncSession, tenant_id: UUID, profile_id: UUID) -> str | None:
    """El nivel confirmado, SOLO leído: es el ancla. Aquí nadie lo escribe."""
    confirmado = await level.read_confirmed_level(db, profile_id, tenant_id)
    return None if confirmado is None else confirmado.cefr


async def _fila(db: AsyncSession, tenant_id: UUID, profile_id: UUID, *,
                bloquear: bool = False) -> PracticeLevel | None:
    stmt = select(PracticeLevel).where(_del_dueno(PracticeLevel, tenant_id, profile_id))
    if bloquear:
        stmt = stmt.with_for_update()
    return (await db.execute(
        stmt.execution_options(populate_existing=True))).scalar_one_or_none()


async def nivel_vigente(db: AsyncSession, tenant_id: UUID,
                        profile_id: UUID) -> tuple[str, str | None]:
    """`(nivel de práctica, ancla)` sin escribir: lo guardado, o el arranque, o el reancla."""
    de_set = reglas.base(await _nivel_de_set(db, tenant_id, profile_id))
    fila = await _fila(db, tenant_id, profile_id)
    if fila is None or (de_set is not None and fila.ancla != de_set):
        return reglas.inicial(de_set, settings.practica_nivel_inicial)
    return fila.nivel, fila.ancla


async def tomar(db: AsyncSession, tenant_id: UUID, profile_id: UUID) -> PracticeLevel:
    """La fila del nivel de práctica, creada si falta, reanclada si SET cambió, y BLOQUEADA."""
    de_set = reglas.base(await _nivel_de_set(db, tenant_id, profile_id))
    nivel, ancla = reglas.inicial(de_set, settings.practica_nivel_inicial)
    await db.execute(pg_insert(PracticeLevel).values(
        tenant_id=tenant_id, profile_id=profile_id, nivel=nivel, ancla=ancla, decisiones=0,
        ventana_desde=VENTANA_ABIERTA,
    ).on_conflict_do_nothing(constraint="practice_levels_owner_key"))
    fila = await _fila(db, tenant_id, profile_id, bloquear=True)
    assert fila is not None  # recién insertada o ya existente
    if de_set is not None and fila.ancla != de_set:  # SET midió después: manda SET
        fila.nivel, fila.ancla, fila.ventana_desde = de_set, de_set, _instante()
        fila.updated_at = _instante()
        await db.flush()  # la sesión no hace autoflush: que la próxima lectura lo vea
    return fila


async def _primeros_intentos(db: AsyncSession, tenant_id: UUID, profile_id: UUID, nivel: str,
                             desde: datetime, cuantas: int) -> list[bool]:
    """Los aciertos de los PRIMEROS intentos en retos de ese nivel, del más viejo al más nuevo.

    Primer intento = el primer intento completado de ese estudiante en ese
    reto: el segundo ya vio la clave y no cuenta (`_es_el_primero`).
    """
    filas = (await db.execute(
        select(ChallengeAttempt.answers)
        .join(Challenge, Challenge.id == ChallengeAttempt.challenge_id)
        .where(ChallengeAttempt.tenant_id == tenant_id,
               ChallengeAttempt.student_id == profile_id,
               ChallengeAttempt.status == "completed",
               ChallengeAttempt.completed_at > desde,
               _del_nivel(nivel), _es_el_primero())
        .order_by(ChallengeAttempt.completed_at.desc(), ChallengeAttempt.id)
        .limit(cuantas))).scalars().all()
    resultados: list[bool] = []
    for respuestas in reversed(filas):  # del más viejo al más nuevo
        resultados.extend(bool(r.get("is_correct")) for r in respuestas or []
                          if isinstance(r, dict))
    return resultados


def _es_el_primero() -> ColumnElement[bool]:
    """No hay otro intento completado ANTES de este, del mismo estudiante y reto."""
    antes = aliased(ChallengeAttempt)
    return ~exists().where(
        antes.challenge_id == ChallengeAttempt.challenge_id,
        antes.student_id == ChallengeAttempt.student_id,
        antes.tenant_id == ChallengeAttempt.tenant_id,
        antes.status == "completed", antes.completed_at < ChallengeAttempt.completed_at)


async def tras_intento(db: AsyncSession, *, tenant_id: UUID, student_id: UUID,
                       challenge: Challenge) -> None:
    """Gancho de `/submit`, DESPUÉS de guardar el intento: mueve la escalera si toca.

    Un reto sin nivel (los que crea un profe a mano) no cuesta ni una consulta.
    """
    del_reto = reglas.base(challenge.cefr_level)
    if del_reto is None:
        return
    fila = await tomar(db, tenant_id, student_id)
    if del_reto != fila.nivel:
        return
    e = escalera()
    resultados = await _primeros_intentos(
        db, tenant_id, student_id, fila.nivel, fila.ventana_desde, max(e.ventana, 1))
    nuevo = reglas.decidir(fila.nivel, resultados, fila.ancla, fila.decisiones, e)
    if nuevo != fila.nivel:
        fila.nivel, fila.decisiones = nuevo, fila.decisiones + 1
        fila.ventana_desde = fila.updated_at = _instante()  # al cambiar, la ventana se vacía
    await db.flush()


# ----------------------------------------------------------------------- la tanda
def _ganado_por(profile_id: UUID) -> ColumnElement[bool]:
    return exists().where(
        ChallengeAttempt.challenge_id == Challenge.id,
        ChallengeAttempt.student_id == profile_id,
        ChallengeAttempt.status == "completed", ChallengeAttempt.is_correct.is_(True))


async def _candidatos(db: AsyncSession, tenant_id: UUID, profile_id: UUID,
                      group_code: str | None, nivel: str, fuera: Sequence[UUID], *,
                      ganados: bool) -> list[Candidato]:
    """Los retos del nivel que podrían entrar: no ganados (nuevos) o ya ganados (repetir)."""
    intentos = (select(func.count()).select_from(ChallengeAttempt)
                .where(ChallengeAttempt.challenge_id == Challenge.id,
                       ChallengeAttempt.student_id == profile_id)
                .correlate(Challenge).scalar_subquery())
    preguntas = (select(func.count()).select_from(ChallengeQuestion)
                 .where(ChallengeQuestion.challenge_id == Challenge.id)
                 .correlate(Challenge).scalar_subquery())
    ganado = _ganado_por(profile_id)
    stmt = select(Challenge.id, Challenge.topic, Challenge.skill, Challenge.title,
                  preguntas).where(
        Challenge.tenant_id == tenant_id, Challenge.status == "active",
        _visibles(tenant_id, group_code), _del_nivel(nivel),
        Challenge.challenge_type.not_in(TIPOS_FUERA), intentos < Challenge.max_attempts,
        ganado if ganados else and_(~ganado, Challenge.current_winners < Challenge.max_winners))
    if fuera:
        stmt = stmt.where(Challenge.id.not_in(list(fuera)))
    return [Candidato(str(i), topic, skill, title, int(n))
            for i, topic, skill, title, n in (await db.execute(stmt)).all() if n]


async def _tandas_de_hoy(db: AsyncSession, tenant_id: UUID, profile_id: UUID,
                         fecha: date) -> list[PracticeTanda]:
    return list((await db.execute(
        select(PracticeTanda)
        .where(_del_dueno(PracticeTanda, tenant_id, profile_id),
               PracticeTanda.local_date == fecha)
        .order_by(PracticeTanda.numero)
        .execution_options(populate_existing=True))).scalars().all())


async def _estados(db: AsyncSession, tenant_id: UUID, profile_id: UUID,
                   tanda: PracticeTanda) -> dict[UUID, str]:
    """`{reto: pendiente | jugado | ganado}` de los retos de esa tanda."""
    estados: dict[UUID, str] = {r: PENDIENTE for r in tanda.retos}
    if not tanda.retos:
        return estados
    filas = (await db.execute(
        select(ChallengeAttempt.challenge_id, ChallengeAttempt.is_correct,
               ChallengeAttempt.completed_at)
        .where(ChallengeAttempt.tenant_id == tenant_id,
               ChallengeAttempt.student_id == profile_id,
               ChallengeAttempt.status == "completed",
               ChallengeAttempt.challenge_id.in_(list(tanda.retos))))).all()
    for reto, gano, cuando in filas:
        if gano:
            estados[reto] = GANADO
        elif estados[reto] != GANADO and cuando is not None and cuando >= tanda.created_at:
            estados[reto] = JUGADO
    if tanda.modo == reglas.MODO_REPETIR:  # ya estaban ganados: cuenta volver a jugarlos
        de_la_tanda = {reto for reto, _gano, cuando in filas
                       if cuando is not None and cuando >= tanda.created_at}
        estados = {r: (JUGADO if r in de_la_tanda else PENDIENTE) for r in tanda.retos}
    return estados


def _completa(estados: dict[UUID, str]) -> bool:
    return all(e != PENDIENTE for e in estados.values())


async def _repaso_que_toca(db: AsyncSession, tenant_id: UUID, profile_id: UUID,
                           group_code: str | None) -> list[PendienteOut]:
    """Bloque 1: lo que la cola serviría ahora (cada entrada con su forma no vista)."""
    return (await refuerzo_service.leer(
        db, tenant_id=tenant_id, profile_id=profile_id, group_code=group_code)).pendientes


async def _repaso_de(db: AsyncSession, tenant_id: UUID, profile_id: UUID,
                     group_code: str | None, tanda: PracticeTanda) -> list[PendienteOut]:
    """Las entradas de repaso de la tanda que siguen sin responder EN esta tanda."""
    if not tanda.repasos:
        return []
    respondidas = set((await db.execute(
        select(ReinforcementAnswer.queue_id)
        .where(ReinforcementAnswer.tenant_id == tenant_id,
               ReinforcementAnswer.profile_id == profile_id,
               ReinforcementAnswer.queue_id.in_(list(tanda.repasos)),
               ReinforcementAnswer.id > tanda.repaso_desde))).scalars().all())
    return [p for p in await _repaso_que_toca(db, tenant_id, profile_id, group_code)
            if p.entrada_id in tanda.repasos and p.entrada_id not in respondidas]


async def _salida(db: AsyncSession, tenant_id: UUID, profile_id: UUID, group_code: str | None,
                  fecha: date, tandas: list[PracticeTanda]) -> TandaDeHoyOut:
    nivel, ancla = await nivel_vigente(db, tenant_id, profile_id)
    tope = settings.tanda_max_al_dia
    practica = PracticaOut(nivel=nivel, con_nivel_de_set=ancla is not None)
    if not tandas:
        return TandaDeHoyOut(fecha=fecha, practica=practica, tanda=None, tandas_hoy=0,
                             tope_al_dia=tope, puede_pedir_otra=tope > 0, listo_por_hoy=False,
                             sin_contenido_nuevo=False)
    ultima = tandas[-1]
    estados = await _estados(db, tenant_id, profile_id, ultima)
    retos = []
    for reto_id in ultima.retos:
        reto = await db.get(Challenge, reto_id)
        if reto is None or reto.tenant_id != tenant_id:
            continue
        ganado = estados[reto_id] == GANADO or ultima.modo == reglas.MODO_REPETIR
        retos.append(RetoDeTandaOut(
            estado=estados[reto_id],
            paga=0 if ganado else economia.recompensa_del_reto(
                reto.coins_reward, settings.reto_monedas_tope),
            reto=await challenges_service.hydrate(db, reto)))
    completa = _completa(estados)
    return TandaDeHoyOut(
        fecha=fecha, practica=practica,
        tanda=TandaOut(numero=ultima.numero, modo=ultima.modo, nivel=ultima.nivel,
                       preguntas=ultima.preguntas, completa=completa, retos=retos,
                       repaso=await _repaso_de(db, tenant_id, profile_id, group_code, ultima)),
        tandas_hoy=len(tandas), tope_al_dia=tope,
        puede_pedir_otra=completa and len(tandas) < tope,
        listo_por_hoy=completa and len(tandas) >= tope,
        sin_contenido_nuevo=ultima.modo != reglas.MODO_NUEVO)


async def ver_tanda(db: AsyncSession, *, tenant_id: UUID, profile_id: UUID,
                    group_code: str | None) -> TandaDeHoyOut:
    """La tanda de hoy (o `tanda: null` si no se ha pedido). NO escribe nada."""
    fecha = racha_service.hoy()
    tandas = await _tandas_de_hoy(db, tenant_id, profile_id, fecha)
    return await _salida(db, tenant_id, profile_id, group_code, fecha, tandas)


async def _elegir(db: AsyncSession, fila: PracticeLevel, tenant_id: UUID, profile_id: UUID,
                  group_code: str | None, fuera: Sequence[UUID],
                  ) -> tuple[str, list[Candidato], str | None]:
    """`(modo, retos, nivel agotado)` de una tanda nueva, con lo que pasa si el nivel se agota."""
    nuevos = await _candidatos(db, tenant_id, profile_id, group_code, fila.nivel, fuera,
                               ganados=False)
    if nuevos:
        return reglas.MODO_NUEVO, reglas.armar(nuevos, tamano()), None
    agotado = fila.nivel
    arriba = reglas.mover(fila.nivel, +1, fila.ancla)
    if arriba != fila.nivel:  # la escalera lo permite: ¿hay algo nuevo arriba?
        nuevos = await _candidatos(db, tenant_id, profile_id, group_code, arriba, fuera,
                                   ganados=False)
        if nuevos:
            fila.nivel, fila.ventana_desde = arriba, _instante()
            fila.updated_at = _instante()
            await db.flush()
            return reglas.MODO_NUEVO, reglas.armar(nuevos, tamano()), agotado
    ganados = await _candidatos(db, tenant_id, profile_id, group_code, fila.nivel, fuera,
                                ganados=True)
    return reglas.MODO_REPETIR, reglas.armar(ganados, tamano()), agotado


async def pedir_tanda(db: AsyncSession, *, tenant_id: UUID, profile_id: UUID,
                      group_code: str | None) -> TandaDeHoyOut:
    """"Dame la tanda de hoy": la que está sin terminar, o una nueva si el tope lo deja."""
    fecha = racha_service.hoy()
    fila = await tomar(db, tenant_id, profile_id)  # bloquea: dos toques no crean dos tandas
    tandas = await _tandas_de_hoy(db, tenant_id, profile_id, fecha)
    if tandas:
        completa = _completa(await _estados(db, tenant_id, profile_id, tandas[-1]))
        if not completa or len(tandas) >= settings.tanda_max_al_dia:
            return await _salida(db, tenant_id, profile_id, group_code, fecha, tandas)
    elif settings.tanda_max_al_dia <= 0:
        return await _salida(db, tenant_id, profile_id, group_code, fecha, tandas)
    fuera = [r for t in tandas for r in t.retos]
    modo, retos, agotado = await _elegir(db, fila, tenant_id, profile_id, group_code, fuera)
    repasos = reglas.primeros(
        await _repaso_que_toca(db, tenant_id, profile_id, group_code),
        settings.tanda_repasos_max)
    if retos or repasos:
        desde = (await db.execute(select(func.coalesce(func.max(ReinforcementAnswer.id), 0))
                                  )).scalar_one()
        tanda = PracticeTanda(
            tenant_id=tenant_id, profile_id=profile_id, local_date=fecha,
            numero=len(tandas) + 1, modo=modo, nivel=fila.nivel, nivel_agotado=agotado,
            retos=[UUID(c.id) for c in retos], repasos=[p.entrada_id for p in repasos],
            repaso_desde=int(desde), preguntas=sum(c.preguntas for c in retos),
            created_at=_instante())
        db.add(tanda)
        await db.flush()
        tandas.append(tanda)
    salida = await _salida(db, tenant_id, profile_id, group_code, fecha, tandas)
    if not tandas:  # no hay NADA que servir: se dice, y no se gasta el tope
        return salida.model_copy(update={"sin_contenido_nuevo": True})
    return salida
