"""La racha semanal contra la base — ESPEC_racha_semanal §1.1 a §1.5.

Tres ganchos de escritura (ninguno hace `commit`: van en la transacción de
quien los llama) y una lectura:
  - `anotar_respuestas`: retos, repaso y EVA cuentan preguntas del día.
  - `anotar_asistencia`: el check-in marca el día.
  - `leer`: el estado para la llama. No escribe.

Toda consulta filtra por `tenant_id` Y `profile_id`: la racha es por
institución (BUG-12). La fila de `streak_state` se bloquea al escribir: dos
respuestas a la vez del mismo estudiante se serializan.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.engrama_core.service import coins as coins_service
from src.foco import fechas
from src.racha import reglas
from src.racha.reglas import Dia, Racha, Umbrales
from src.racha.schemas import BonoOut, DiaOut, HoyOut, RachaOut, SemanaOut, SemanaPasadaOut
from src.shared.config import settings
from src.shared.models import ActivityDay, CoinLedger, Membership, StreakState

ACCION_BONO = "streak_week"


def _ahora() -> datetime:
    """El instante del SERVIDOR; costura para que los tests muevan el calendario."""
    return datetime.now(UTC)


def umbrales() -> Umbrales:
    """Los siete números, de la configuración (se leen en cada llamada)."""
    return Umbrales(
        dias_por_semana=settings.racha_dias_por_semana,
        dias_protector=settings.racha_dias_protector,
        respuestas_dia=settings.racha_respuestas_dia,
        correctas_dia=settings.racha_correctas_dia,
        protector_inicial=settings.racha_protector_inicial,
        protector_tope=settings.racha_protector_tope,
        bono_semana=settings.racha_bono_semana)


def hoy() -> date:
    """El día de la institución, con la hora del servidor (nunca la del celular)."""
    return fechas.hoy(_ahora(), settings.engrama_utc_offset_hours)


def _del_dueno(modelo: type[ActivityDay] | type[StreakState], tenant_id: UUID,
               profile_id: UUID) -> ColumnElement[bool]:
    """La ÚNICA fuente del filtro por dueño: institución Y estudiante (BUG-12)."""
    return and_(modelo.tenant_id == tenant_id, modelo.profile_id == profile_id)


# ------------------------------------------------------------------ lecturas
def _a_regla(fila: StreakState) -> Racha:
    return Racha(fila.racha_semanas, fila.mejor_racha, fila.semanas_cumplidas,
                 fila.protectores, fila.ultima_semana_cerrada)


def _a_dia(fila: ActivityDay | None) -> Dia:
    if fila is None:
        return reglas.DIA_VACIO
    return Dia(fila.via_asistencia, fila.respuestas, fila.correctas, fila.primeras_correctas,
               dict(fila.preguntas or {}), dict(fila.por_origen or {}))


async def _dias(db: AsyncSession, tenant_id: UUID, profile_id: UUID, desde: date,
                hasta: date) -> list[ActivityDay]:
    return list((await db.execute(
        select(ActivityDay)
        .where(_del_dueno(ActivityDay, tenant_id, profile_id),
               ActivityDay.local_date >= desde, ActivityDay.local_date <= hasta)
        .order_by(ActivityDay.local_date)
        .execution_options(populate_existing=True))).scalars().all())


def _activos_por_semana(dias: Iterable[ActivityDay]) -> Counter[date]:
    return Counter(reglas.lunes_de(d.local_date) for d in dias if d.activo)


def _semanas_sin_contenido(dias: Iterable[ActivityDay]) -> set[date]:
    """Los lunes de las semanas con un día en que no hubo qué servir: no rompen nada."""
    return {reglas.lunes_de(d.local_date) for d in dias if d.sin_contenido}


async def _semana_exenta(db: AsyncSession, tenant_id: UUID, profile_id: UUID) -> date | None:
    """El lunes de la semana en que se creó la membresía: esa no rompe nada."""
    creada = (await db.execute(
        select(Membership.created_at).where(
            Membership.tenant_id == tenant_id,
            Membership.profile_id == profile_id))).scalar_one_or_none()
    if creada is None:
        return None
    return reglas.lunes_de(fechas.hoy(creada, settings.engrama_utc_offset_hours))


async def _cerrada(db: AsyncSession, tenant_id: UUID, profile_id: UUID, racha: Racha,
                   lunes: date, u: Umbrales) -> Racha:
    """La racha con las semanas terminadas ya cerradas (el cierre perezoso)."""
    if racha.ultima_semana_cerrada + reglas.SEMANA >= lunes:
        return racha  # nada que cerrar: ni una consulta
    pasados = await _dias(db, tenant_id, profile_id,
                          racha.ultima_semana_cerrada + reglas.SEMANA,
                          lunes - timedelta(days=1))
    exentas = _semanas_sin_contenido(pasados)
    de_la_membresia = await _semana_exenta(db, tenant_id, profile_id)
    if de_la_membresia is not None:
        exentas.add(de_la_membresia)
    return reglas.cerrar(racha, lunes, _activos_por_semana(pasados), exentas, u)


# ----------------------------------------------------------------- escrituras
async def _tomar_estado(db: AsyncSession, tenant_id: UUID, profile_id: UUID, lunes: date,
                        u: Umbrales) -> StreakState:
    """La fila de la racha, creada si falta y BLOQUEADA hasta el commit."""
    nueva = reglas.inicial(lunes, u)
    await db.execute(pg_insert(StreakState).values(
        tenant_id=tenant_id, profile_id=profile_id, racha_semanas=0, mejor_racha=0,
        semanas_cumplidas=0, protectores=nueva.protectores,
        ultima_semana_cerrada=nueva.ultima_semana_cerrada,
    ).on_conflict_do_nothing(constraint="streak_state_owner_key"))
    return (await db.execute(
        select(StreakState).where(_del_dueno(StreakState, tenant_id, profile_id))
        .with_for_update().execution_options(populate_existing=True))).scalar_one()


async def _tomar_dia(db: AsyncSession, tenant_id: UUID, profile_id: UUID,
                     fecha: date) -> ActivityDay:
    await db.execute(pg_insert(ActivityDay).values(
        tenant_id=tenant_id, profile_id=profile_id, local_date=fecha,
    ).on_conflict_do_nothing(constraint="activity_days_owner_date_key"))
    return (await db.execute(
        select(ActivityDay)
        .where(_del_dueno(ActivityDay, tenant_id, profile_id), ActivityDay.local_date == fecha)
        .execution_options(populate_existing=True))).scalar_one()


async def _pagar_bono(db: AsyncSession, tenant_id: UUID, profile_id: UUID, lunes: date,
                      monto: int) -> None:
    """El bono de la semana cumplida, UNA vez (la llave) y sin tumbar nada.

    En un SAVEPOINT: si la bolsa de la institución no alcanza (402), se deshace
    solo la paga y la semana cuenta igual. Nunca sale un 402 de aquí.
    """
    if monto <= 0:
        return
    try:
        async with db.begin_nested():
            await coins_service.award_coins(
                db, student_id=profile_id, tenant_id=tenant_id, amount=monto,
                action=ACCION_BONO, metadata={"semana": lunes.isoformat()},
                idempotency_key=reglas.llave_bono(tenant_id, profile_id, lunes))
    except HTTPException as exc:
        if exc.status_code != status.HTTP_402_PAYMENT_REQUIRED:
            raise


def _guardar(estado: StreakState, racha: Racha) -> None:
    estado.racha_semanas, estado.mejor_racha = racha.racha_semanas, racha.mejor_racha
    estado.semanas_cumplidas, estado.protectores = racha.semanas_cumplidas, racha.protectores
    estado.ultima_semana_cerrada = racha.ultima_semana_cerrada
    estado.updated_at = _ahora()


async def _aplicar(db: AsyncSession, tenant_id: UUID, profile_id: UUID,
                   respuestas: Iterable[tuple[str, bool, str]], asistencia: bool) -> None:
    """El único camino de escritura: cierra lo pendiente, cuenta el día y, si el día
    pasa a activo, mueve la racha (y paga el bono si la semana se cumplió)."""
    u, fecha = umbrales(), hoy()
    lunes = reglas.lunes_de(fecha)
    estado = await _tomar_estado(db, tenant_id, profile_id, lunes, u)
    racha = await _cerrada(db, tenant_id, profile_id, _a_regla(estado), lunes, u)
    fila = await _tomar_dia(db, tenant_id, profile_id, fecha)
    dia = _a_dia(fila)
    if asistencia:
        dia = Dia(True, dia.respuestas, dia.correctas, dia.primeras_correctas,
                  dia.preguntas, dia.por_origen)
    for clave, acerto, origen in respuestas:
        dia = reglas.anotar_respuesta(dia, clave, acerto, origen)
    fila.via_asistencia, fila.respuestas, fila.correctas = (
        dia.via_asistencia, dia.respuestas, dia.correctas)
    fila.primeras_correctas = dia.primeras_correctas
    fila.preguntas, fila.por_origen = dict(dia.preguntas), dict(dia.por_origen)
    fila.updated_at = _ahora()
    se_activa = not fila.activo and reglas.dia_activo(dia, u)
    cumplida = False
    if se_activa:
        fila.activo = True
        await db.flush()
        semana = await _dias(db, tenant_id, profile_id, lunes, lunes + timedelta(days=6))
        racha, cumplida = reglas.al_activarse_un_dia(racha, sum(1 for d in semana if d.activo), u)
    _guardar(estado, racha)
    await db.flush()
    if cumplida:
        await _pagar_bono(db, tenant_id, profile_id, lunes, u.bono_semana)


async def anotar_respuestas(db: AsyncSession, *, tenant_id: UUID, profile_id: UUID,
                            respuestas: Iterable[tuple[str, bool]], origen: str) -> None:
    """Gancho de retos, repaso y EVA: `(identidad de la pregunta, ¿acertó?)` de hoy."""
    lote = [(clave, acerto, origen) for clave, acerto in respuestas]
    if lote:
        await _aplicar(db, tenant_id, profile_id, lote, asistencia=False)


async def anotar_asistencia(db: AsyncSession, *, tenant_id: UUID, profile_id: UUID) -> None:
    """Gancho del check-in: hoy asistió. Un día ya activo no cambia (L4-c)."""
    await _aplicar(db, tenant_id, profile_id, [], asistencia=True)


async def reservar(db: AsyncSession, *, tenant_id: UUID, profile_id: UUID) -> None:
    """Toma el candado de la racha SIN cambiar nada (la fila nace si falta).

    Lo pide la tanda antes de su propio candado: así todos los caminos toman
    los candados en el mismo orden (racha y después nivel de práctica) y la
    tanda y un `/submit` del mismo estudiante no se bloquean entre sí.
    """
    await _tomar_estado(db, tenant_id, profile_id, reglas.lunes_de(hoy()), umbrales())


async def anotar_sin_contenido(db: AsyncSession, *, tenant_id: UUID, profile_id: UUID) -> None:
    """Hoy pidió practicar y no había qué servirle: la semana no romperá su racha.

    Solo marca el día (ESPEC_solo_refuerzo §1.5): no lo vuelve activo ni mueve
    la racha. Quien llama ya tiene el candado (`reservar`).
    """
    fila = await _tomar_dia(db, tenant_id, profile_id, hoy())
    if not fila.sin_contenido:
        fila.sin_contenido = True
        fila.updated_at = _ahora()
        await db.flush()


async def sin_contenido_hoy(db: AsyncSession, *, tenant_id: UUID, profile_id: UUID) -> bool:
    """¿Hoy quedó marcado sin contenido? No escribe."""
    return bool((await db.execute(
        select(ActivityDay.sin_contenido).where(
            _del_dueno(ActivityDay, tenant_id, profile_id),
            ActivityDay.local_date == hoy()))).scalar_one_or_none())


# -------------------------------------------------------------------- la llama
async def _bono_pagado(db: AsyncSession, tenant_id: UUID, profile_id: UUID, lunes: date) -> bool:
    return (await db.execute(select(CoinLedger.id).where(
        CoinLedger.tenant_id == tenant_id,
        CoinLedger.idempotency_key == reglas.llave_bono(tenant_id, profile_id, lunes),
    ))).scalar_one_or_none() is not None


async def leer(db: AsyncSession, *, tenant_id: UUID, profile_id: UUID) -> RachaOut:
    """El estado de la racha, con el cierre calculado. NO escribe nada."""
    u, fecha = umbrales(), hoy()
    lunes = reglas.lunes_de(fecha)
    fila = (await db.execute(
        select(StreakState).where(_del_dueno(StreakState, tenant_id, profile_id))
        .execution_options(populate_existing=True))).scalar_one_or_none()
    racha = reglas.inicial(lunes, u) if fila is None else _a_regla(fila)
    racha = await _cerrada(db, tenant_id, profile_id, racha, lunes, u)
    dias = {d.local_date: d for d in await _dias(
        db, tenant_id, profile_id, lunes - reglas.SEMANA, lunes + timedelta(days=6))}
    semana = [lunes + timedelta(days=i) for i in range(7)]
    activos = sum(1 for f in semana if f in dias and dias[f].activo)
    pasada = sum(1 for i in range(7)
                 if (d := dias.get(lunes - reglas.SEMANA + timedelta(days=i))) and d.activo)
    de_hoy = _a_dia(dias.get(fecha))
    return RachaOut(
        racha_semanas=racha.racha_semanas, mejor_racha=racha.mejor_racha,
        semanas_cumplidas=racha.semanas_cumplidas, protectores=racha.protectores,
        protectores_tope=u.protector_tope,
        semana=SemanaOut(
            desde=lunes, hasta=semana[-1], dias_activos=activos, meta_dias=u.dias_por_semana,
            cumplida=activos >= u.dias_por_semana, dias_para_protector=u.dias_protector,
            dias=[DiaOut(fecha=f, activo=bool(dias[f].activo) if f in dias else False,
                         via_asistencia=bool(dias[f].via_asistencia) if f in dias else False,
                         respuestas=dias[f].respuestas if f in dias else 0,
                         correctas=dias[f].correctas if f in dias else 0) for f in semana]),
        hoy=HoyOut(fecha=fecha, activo=bool(fecha in dias and dias[fecha].activo),
                   respuestas=de_hoy.respuestas, correctas=de_hoy.correctas,
                   meta_respuestas=u.respuestas_dia, meta_correctas=u.correctas_dia),
        semana_pasada=SemanaPasadaOut(dias_activos=pasada,
                                      cumplida=pasada >= u.dias_por_semana),
        bono_semana=BonoOut(monedas=u.bono_semana,
                            pagado=await _bono_pagado(db, tenant_id, profile_id, lunes)))
