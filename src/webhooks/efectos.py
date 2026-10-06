"""Los dos efectos de un evento NUEVO — `docs/ESPEC_eventos_anillo.md` §1.6 y §1.7.

  - `coins.granted` (origen `live`): las monedas de la clase salen de la bolsa
    de la institución, por el libro de siempre (`award_coins`), UNA vez.
  - `level.assessed` (origen `set`): el nivel confirmado, por su única puerta
    (`engrama_core/service/level.py`).

Todo lo demás solo se guarda. Nada de origen `live` toca el nivel, el XP ni el
progreso: aquí `coins.granted` mueve billetera y libro, y nada más.

Devuelven el `effect` que queda en la fila. Ninguna hace commit.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.engrama_core.service import coins, level
from src.shared import events
from src.shared.models import LearningEvent
from src.webhooks.schemas import EventoIn, MonedasPayload, NivelPayload

# El tope que el motor de EVA ya aplica, según su encargo. Segunda barrera.
TOPE_POR_SESION = 20
ACREDITADO, BOLSA_AGOTADA, TOPE_SUPERADO = "coins_credited", "pool_exhausted", "session_cap_exceeded"
NIVEL_PUESTO, NIVEL_ANTERIOR, SIN_EFECTO = "level_set", "level_older", "none"
# Los `effect` que van a `not_credited` en la respuesta.
NO_ACREDITADOS = (BOLSA_AGOTADA, TOPE_SUPERADO)


async def _ya_en_la_sesion(db: AsyncSession, evento: EventoIn, session_id: str) -> int:
    """Monedas ya acreditadas a ese estudiante en esa sesión."""
    total = (await db.execute(
        select(func.coalesce(func.sum(LearningEvent.coins), 0))
        .where(LearningEvent.tenant_id == evento.tenant_id,
               LearningEvent.subject_id == evento.subject_id,
               LearningEvent.session_id == session_id,
               LearningEvent.type == events.COINS_GRANTED)
    )).scalar_one()
    return int(total)


async def _pagar(db: AsyncSession, evento: EventoIn, datos: MonedasPayload) -> str:
    """Acredita por el libro. Devuelve el `effect`: acreditado, bolsa agotada o ninguno.

    Va en un SAVEPOINT: si `award_coins` da 402 (la bolsa de la institución no
    alcanza), se deshace SOLO la paga, que ya había reclamado su llave, y el
    evento se queda guardado.

    `award_coins` devuelve `None` si esa llave ya había pagado (la segunda
    barrera, la del libro): entonces aquí no se acreditó nada.
    """
    assert evento.subject_id is not None  # la regla del tipo ya exigió un estudiante
    try:
        async with db.begin_nested():
            fila = await coins.award_coins(
                db, student_id=evento.subject_id, tenant_id=evento.tenant_id,
                amount=datos.amount, action="live",
                metadata={"event_id": evento.event_id, "session_id": datos.session_id,
                          "reason": datos.reason},
                idempotency_key=f"event:{evento.event_id}")
    except HTTPException as exc:
        if exc.status_code != status.HTTP_402_PAYMENT_REQUIRED:
            raise
        return BOLSA_AGOTADA
    return ACREDITADO if fila is not None else SIN_EFECTO


async def acreditar_monedas(db: AsyncSession, evento: EventoIn,
                            datos: MonedasPayload) -> tuple[str, int]:
    """(`effect`, monedas acreditadas) de un `coins.granted` nuevo."""
    # La billetera de la institución, bloqueada ANTES de contar: dos lotes a la
    # vez no pasan el tope (y es el mismo candado que toma `award_coins`).
    await coins.get_wallet(db, "tenant", evento.tenant_id, tenant_id=evento.tenant_id,
                           for_update=True)
    if await _ya_en_la_sesion(db, evento, datos.session_id) + datos.amount > TOPE_POR_SESION:
        return TOPE_SUPERADO, 0
    efecto = await _pagar(db, evento, datos)
    return efecto, (datos.amount if efecto == ACREDITADO else 0)


async def confirmar_nivel(db: AsyncSession, evento: EventoIn, datos: NivelPayload,
                          fila_id: int) -> tuple[str, int]:
    """(`effect`, 0) de un `level.assessed` nuevo: gana la medición más reciente."""
    assert evento.subject_id is not None  # la regla del tipo ya exigió un estudiante
    puesto = await level.record_confirmed_level(
        db, tenant_id=evento.tenant_id, profile_id=evento.subject_id, cefr=datos.nivel_global,
        source=events.ORIGEN_SET, provisional=datos.provisional, score=datos.score_total,
        assessed_at=evento.occurred_at, event_row_id=fila_id)
    return (NIVEL_PUESTO if puesto else NIVEL_ANTERIOR), 0


async def aplicar(db: AsyncSession, evento: EventoIn, payload: Any,
                  fila_id: int) -> tuple[str, int]:
    """El efecto de un evento NUEVO, según su tipo. Para los demás, ninguno."""
    if evento.type == events.COINS_GRANTED:
        return await acreditar_monedas(db, evento, payload)
    if evento.type == events.LEVEL_ASSESSED:
        return await confirmar_nivel(db, evento, payload, fila_id)
    return SIN_EFECTO, 0
