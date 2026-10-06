"""El nivel MCER CONFIRMADO de una persona en una institución — ESPEC_eventos_anillo §1.7.

Este módulo es la ÚNICA puerta para escribir el nivel confirmado (ERR-26: una
barrera, una fuente). Lo confirma quien MIDE: hoy SET (`source = "set"`);
después el Grader y el profe, con su propia `source`.

El juego, las monedas y la clase en vivo NO llaman a `record_confirmed_level`
(decisión 007 §6 y regla 7 de ENGRAMA: el juego no infla el nivel). Además, la
base no admite `live` ni `game` como `source` (CHECK de la 037).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.models import ConfirmedLevel


async def record_confirmed_level(
    db: AsyncSession, *, tenant_id: UUID, profile_id: UUID, cefr: str, source: str,
    provisional: bool, score: int | None, assessed_at: datetime, event_row_id: int | None,
) -> bool:
    """Guarda el nivel si esta medición es la más reciente (o igual). No hace commit.

    Devuelve True si quedó guardado y False si ya había uno MÁS NUEVO (el nivel
    no retrocede). "O igual": el evento con la escritura ya calificada reemplaza
    al provisional del mismo intento, que trae la misma fecha.

    Es UNA sentencia (`ON CONFLICT ... DO UPDATE ... WHERE`): dos mediciones a
    la vez no se pisan a medias.
    """
    nueva = pg_insert(ConfirmedLevel).values(
        tenant_id=tenant_id, profile_id=profile_id, cefr=cefr, source=source,
        provisional=provisional, score=score, assessed_at=assessed_at, event_id=event_row_id)
    sentencia = nueva.on_conflict_do_update(
        constraint="confirmed_levels_tenant_profile_key",
        set_={"cefr": nueva.excluded.cefr, "source": nueva.excluded.source,
              "provisional": nueva.excluded.provisional, "score": nueva.excluded.score,
              "assessed_at": nueva.excluded.assessed_at, "event_id": nueva.excluded.event_id,
              "updated_at": func.now()},
        where=ConfirmedLevel.assessed_at <= nueva.excluded.assessed_at,
    ).returning(ConfirmedLevel.id)
    return (await db.execute(sentencia)).scalar_one_or_none() is not None


async def read_confirmed_level(db: AsyncSession, profile_id: UUID,
                               tenant_id: UUID) -> ConfirmedLevel | None:
    """El nivel confirmado de esa persona EN esa institución, o `None`."""
    return (await db.execute(
        select(ConfirmedLevel)
        .where(ConfirmedLevel.profile_id == profile_id, ConfirmedLevel.tenant_id == tenant_id)
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
