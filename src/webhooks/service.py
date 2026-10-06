"""Procesar un lote de eventos, uno por uno — `docs/ESPEC_eventos_anillo.md` §1.4.

El lote NO es todo o nada: cada evento aceptado y su efecto van en su propia
transacción, para que uno malo no tapone la cola del satélite.

La idempotencia la garantiza la base (UNIQUE `(tenant_id, event_id)`), no este
código: el INSERT lleva `ON CONFLICT DO NOTHING`, y un evento que no insertó
fila NO tiene efecto. Así, reenviar un lote, o mandarlo dos veces a la vez, no
paga dos veces ni mueve nada.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared import events
from src.shared.models import LearningEvent, Membership, Tenant
from src.webhooks import efectos
from src.webhooks.schemas import (
    EventoIn,
    LoteIn,
    MonedasPayload,
    NivelPayload,
    RechazoOut,
    ResumenOut,
    SesionPayload,
)

logger = logging.getLogger("engrama.eventos")

ACEPTADO, DUPLICADO, RECHAZADO = "accepted", "duplicate", "rejected"
INVALIDO, TIPO, INSTITUCION, SUJETO, CONFLICTO = (
    "invalid_event", "unknown_type", "unknown_tenant", "unknown_subject", "conflict")
FUTURO_TOLERADO = timedelta(minutes=10)
_PAYLOADS: dict[str, type[BaseModel]] = {
    events.COINS_GRANTED: MonedasPayload, events.LEVEL_ASSESSED: NivelPayload}
_ROLES = {events.ESTUDIANTE: ("student",), events.STAFF: ("teacher", "admin")}


@dataclass(frozen=True)
class Resultado:
    """Qué pasó con UN evento."""

    que: str
    event_id: str
    motivo: str | None = None       # si fue rechazado
    efecto: str = efectos.SIN_EFECTO  # si fue aceptado


def _id_crudo(crudo: Any) -> str:
    valor = crudo.get("event_id") if isinstance(crudo, dict) else None
    return valor if isinstance(valor, str) else ""


def _leer(crudo: Any) -> EventoIn | None:
    """El evento validado, o `None` si le falta o le sobra algo."""
    if not isinstance(crudo, dict):
        return None
    try:
        # Por JSON y en modo estricto: un UUID o una fecha llegan como texto, pero
        # un número no pasa por texto ni un booleano por número.
        return EventoIn.model_validate_json(json.dumps(crudo))
    except (ValidationError, ValueError):
        return None


def _payload(evento: EventoIn) -> BaseModel | None:
    """El `payload` validado según el tipo, o `None` si no cumple."""
    modelo = _PAYLOADS.get(evento.type, SesionPayload)
    try:
        return modelo.model_validate(evento.payload)
    except ValidationError:
        return None


def _motivo_de_forma(origen: str, evento: EventoIn) -> str | None:
    """`unknown_type` o `invalid_event` por lo que el evento DICE (sin tocar la base)."""
    regla = events.regla_de(origen, evento.type)
    con_sujeto = evento.subject_id is not None
    if (regla is None or regla.source != evento.source
            or con_sujeto != (regla.sujeto != events.SIN_SUJETO)):
        return TIPO
    if evento.occurred_at > datetime.now(UTC) + FUTURO_TOLERADO:
        return INVALIDO
    return None


async def _sujeto_valido(db: AsyncSession, tenant_id: UUID, subject_id: UUID | None,
                         sujeto: str) -> bool:
    """¿Es un perfil con membresía ACTIVA, del rol que el tipo pide, en ESA institución?"""
    if sujeto == events.SIN_SUJETO:
        return subject_id is None
    rol = (await db.execute(
        select(Membership.role).where(
            Membership.tenant_id == tenant_id, Membership.profile_id == subject_id,
            Membership.is_active.is_(True))
    )).scalar_one_or_none()
    return rol in _ROLES[sujeto]


async def _motivo_de_base(db: AsyncSession, origen: str, evento: EventoIn) -> str | None:
    """`unknown_tenant` o `unknown_subject`."""
    existe = (await db.execute(
        select(Tenant.id).where(Tenant.id == evento.tenant_id))).scalar_one_or_none()
    if existe is None:
        return INSTITUCION
    regla = events.regla_de(origen, evento.type)
    assert regla is not None  # `_motivo_de_forma` ya lo exigió
    if not await _sujeto_valido(db, evento.tenant_id, evento.subject_id, regla.sujeto):
        return SUJETO
    return None


async def _guardar(db: AsyncSession, origen: str, lote: LoteIn, evento: EventoIn,
                   huella: str, session_id: str | None) -> int | None:
    """Inserta la fila. `None` si ese `(tenant_id, event_id)` ya existía."""
    fila = (await db.execute(
        pg_insert(LearningEvent).values(
            tenant_id=evento.tenant_id, event_id=evento.event_id, origin=origen,
            source=evento.source, type=evento.type, subject_id=evento.subject_id,
            item_ref=evento.item_ref, payload=evento.payload, occurred_at=evento.occurred_at,
            schema_version=evento.schema_version, body_hash=huella, batch_id=lote.batch_id,
            instance=lote.instance, session_id=session_id)
        .on_conflict_do_nothing(constraint="learning_events_tenant_event_key")
        .returning(LearningEvent.id)
    )).scalar_one_or_none()
    return None if fila is None else int(fila)


async def _ya_estaba(db: AsyncSession, evento: EventoIn, huella: str) -> Resultado:
    """El `event_id` ya existía: duplicado si el contenido es el mismo; si no, conflicto."""
    guardada = (await db.execute(
        select(LearningEvent.body_hash).where(
            LearningEvent.tenant_id == evento.tenant_id,
            LearningEvent.event_id == evento.event_id))).scalar_one_or_none()
    if guardada == huella:
        return Resultado(DUPLICADO, evento.event_id)
    return Resultado(RECHAZADO, evento.event_id, CONFLICTO)


async def _aceptar(db: AsyncSession, origen: str, lote: LoteIn, evento: EventoIn,
                   payload: BaseModel, huella: str) -> Resultado:
    """Guarda el evento y, SOLO si es nuevo, aplica su efecto. No hace commit."""
    session_id = getattr(payload, "session_id", None)
    fila_id = await _guardar(db, origen, lote, evento, huella, session_id)
    if fila_id is None:
        return await _ya_estaba(db, evento, huella)
    efecto, monedas = await efectos.aplicar(db, evento, payload, fila_id)
    await db.execute(update(LearningEvent).where(LearningEvent.id == fila_id)
                     .values(effect=efecto, coins=monedas))
    return Resultado(ACEPTADO, evento.event_id, efecto=efecto)


async def procesar_evento(db: AsyncSession, origen: str, lote: LoteIn, crudo: Any) -> Resultado:
    """UN evento, en SU transacción (commit si se aceptó; rollback si no o si algo falla)."""
    evento = _leer(crudo)
    if evento is None:
        return Resultado(RECHAZADO, _id_crudo(crudo), INVALIDO)
    payload = None
    motivo = _motivo_de_forma(origen, evento)
    if motivo is None:
        payload = _payload(evento)
        motivo = INVALIDO if payload is None else await _motivo_de_base(db, origen, evento)
    if motivo is not None or payload is None:
        await db.rollback()
        return Resultado(RECHAZADO, evento.event_id, motivo)
    try:
        resultado = await _aceptar(db, origen, lote, evento, payload,
                                   events.huella_del_evento(crudo))
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        # La sesión sigue viva para el evento siguiente: lo que quedó cargado
        # (billeteras) se relee de la base, no de la memoria.
        db.expire_all()
    return resultado


def resumir(resultados: list[Resultado]) -> ResumenOut:
    resumen = ResumenOut()
    for r in resultados:
        if r.que == ACEPTADO:
            resumen.accepted += 1
            if r.efecto in efectos.NO_ACREDITADOS:
                resumen.not_credited.append(RechazoOut(event_id=r.event_id, reason=r.efecto))
        elif r.que == DUPLICADO:
            resumen.duplicates += 1
        else:
            resumen.rejected.append(RechazoOut(event_id=r.event_id, reason=r.motivo or INVALIDO))
    return resumen


async def procesar_lote(db: AsyncSession, origen: str, lote: LoteIn) -> ResumenOut:
    """Cada evento por separado; la respuesta dice qué pasó con cada uno."""
    resultados = [await procesar_evento(db, origen, lote, crudo) for crudo in lote.events]
    resumen = resumir(resultados)
    logger.info("eventos: origen=%s lote=%s aceptados=%d duplicados=%d rechazados=%d",
                origen, lote.batch_id, resumen.accepted, resumen.duplicates,
                len(resumen.rejected))
    return resumen
