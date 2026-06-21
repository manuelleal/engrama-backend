"""Lógica del ranking — SPECS/04-leaderboard.md §3.

Métrica de orden (determinista):
    1. coins  DESC  (balance de la wallet COIN del estudiante)
    2. xp     DESC  (desempate por experiencia)
    3. full_name ASC (desempate final estable)

Reglas de integridad (WINDSURF §3):
  - Solo se rankean estudiantes (`memberships.role = 'student'`, activos).
  - TODA query filtra por `tenant_id` explícito (defensa en profundidad),
    aunque RLS lo cubriría con `user_session`.
  - Solo-lectura: no escribe nada, no hace commit.

La función pura `build_leaderboard` se separa de la query para poder testear
la asignación de ranks / `me` / truncado sin tocar la base de datos.
"""
from __future__ import annotations

from typing import NamedTuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.leaderboard.schemas import LeaderboardEntry, LeaderboardOut
from src.shared.models import CoinWallet, Membership, Profile


class RankRow(NamedTuple):
    """Fila ya ordenada que alimenta `build_leaderboard` (DB-agnóstica)."""

    profile_id: UUID
    full_name: str
    coins: int
    xp: int
    level: int
    current_streak: int


# =============================================================================
# 3.1 build_leaderboard — función pura (unit-testable sin DB)
# =============================================================================
def build_leaderboard(
    rows: list[RankRow],
    *,
    me_profile_id: UUID,
    limit: int,
) -> tuple[list[LeaderboardEntry], LeaderboardEntry | None, int]:
    """Convierte filas ordenadas en (top-N, fila propia, total).

    `rows` DEBE venir ya ordenado por la métrica de ranking. El rank es la
    posición 1-based sobre la lista COMPLETA, así que la fila propia conserva
    su puesto real aunque quede fuera del top-N devuelto en `entries`.
    """
    entries: list[LeaderboardEntry] = []
    me_entry: LeaderboardEntry | None = None

    for index, row in enumerate(rows):
        entry = LeaderboardEntry(
            rank=index + 1,
            profile_id=row.profile_id,
            full_name=row.full_name,
            coins=int(row.coins),
            xp=int(row.xp),
            level=int(row.level),
            current_streak=int(row.current_streak),
            is_me=row.profile_id == me_profile_id,
        )
        if entry.rank <= limit:
            entries.append(entry)
        if entry.is_me:
            me_entry = entry

    return entries, me_entry, len(rows)


# =============================================================================
# 3.2 get_leaderboard — query + ensamblado
# =============================================================================
async def get_leaderboard(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    group_code: str | None,
    me_profile_id: UUID,
    limit: int = 20,
) -> LeaderboardOut:
    """Arma el ranking de estudiantes del tenant (o de un grupo concreto).

    LEFT JOIN con `coin_wallets` para que estudiantes sin wallet aún cuenten
    con 0 coins en vez de desaparecer del ranking.
    """
    coins = func.coalesce(CoinWallet.balance, 0)

    stmt = (
        select(
            Profile.id,
            Profile.full_name,
            coins.label("coins"),
            Profile.xp,
            Profile.level,
            Profile.current_streak,
        )
        .join(Membership, Membership.profile_id == Profile.id)
        .outerjoin(
            CoinWallet,
            (CoinWallet.owner_type == "profile")
            & (CoinWallet.owner_id == Profile.id)
            & (CoinWallet.tenant_id == tenant_id)
            & (CoinWallet.currency == "COIN"),
        )
        .where(
            Membership.tenant_id == tenant_id,
            Membership.is_active.is_(True),
            Membership.role == "student",
        )
        .order_by(coins.desc(), Profile.xp.desc(), Profile.full_name.asc())
    )

    if group_code is not None:
        stmt = stmt.where(Membership.group_code == group_code)

    result = await db.execute(stmt)
    rows = [
        RankRow(
            profile_id=r.id,
            full_name=r.full_name,
            coins=int(r.coins),
            xp=int(r.xp),
            level=int(r.level),
            current_streak=int(r.current_streak),
        )
        for r in result.all()
    ]

    entries, me_entry, total = build_leaderboard(
        rows, me_profile_id=me_profile_id, limit=limit
    )

    return LeaderboardOut(
        scope="group" if group_code is not None else "tenant",
        group_code=group_code,
        entries=entries,
        me=me_entry,
        total=total,
    )
