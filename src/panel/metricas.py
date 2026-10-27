"""Las consultas del panel: SOLO LECTURA, siempre por `tenant_id` explícito (ESPEC_panel_super_admin §1.3).

El backend se conecta sin RLS (`src/shared/db.py`), así que el aislamiento entre
clientes es ESTE `WHERE tenant_id IN (...)`: cada consulta lo lleva, y la
actividad y las monedas se cuentan en el tenant de la FILA (el asiento, el
intento, la asistencia), no en el de la persona.

Cada función recibe la lista de tenants y devuelve un dict por tenant, con UNA
consulta agrupada (sin N+1: el super admin pide todos los clientes a la vez).
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Date, and_, case, cast, func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.shared.models import (
    Attendance,
    ChallengeAttempt,
    CoinLedger,
    CoinWallet,
    Group,
    LearningEvent,
    Membership,
)

DEVOLUCION_DE_COMPRA = "shop_refund"  # src/shop/compras.py: DEVOLUCION
Ids = Sequence[UUID]


def _dia_local(columna: Any, desfase_horas: int) -> Any:
    """La fecha LOCAL de un `timestamptz`: se corre el desfase y se lee en UTC."""
    return cast(func.timezone("UTC", columna + timedelta(hours=desfase_horas)), Date)


async def conteo_por_rol(db: AsyncSession, ids: Ids) -> dict[UUID, dict[str, int]]:
    """Membresías ACTIVAS por tenant y rol."""
    stmt = (
        select(Membership.tenant_id, Membership.role, func.count())
        .where(Membership.tenant_id.in_(ids), Membership.is_active.is_(True))
        .group_by(Membership.tenant_id, Membership.role)
    )
    salida: dict[UUID, dict[str, int]] = defaultdict(dict)
    for tid, rol, n in (await db.execute(stmt)).all():
        salida[tid][rol] = int(n)
    return salida


async def grupos_por_tenant(db: AsyncSession, ids: Ids) -> dict[UUID, int]:
    stmt = (select(Group.tenant_id, func.count()).where(Group.tenant_id.in_(ids))
            .group_by(Group.tenant_id))
    return {tid: int(n) for tid, n in (await db.execute(stmt)).all()}


def _actividad(ids: Ids, desde: datetime) -> Any:
    """(tenant, persona) de todo lo que cuenta como "jugó" desde `desde`, en ESE tenant."""
    return union_all(
        select(ChallengeAttempt.tenant_id.label("tid"), ChallengeAttempt.student_id.label("pid"))
        .where(ChallengeAttempt.tenant_id.in_(ids), ChallengeAttempt.started_at >= desde),
        select(Attendance.tenant_id, Attendance.student_id)
        .where(Attendance.tenant_id.in_(ids), Attendance.created_at >= desde),
        select(LearningEvent.tenant_id, LearningEvent.subject_id)
        .where(LearningEvent.tenant_id.in_(ids), LearningEvent.subject_id.is_not(None),
               LearningEvent.occurred_at >= desde),
    ).subquery()


async def activos_por_tenant(db: AsyncSession, ids: Ids, desde: datetime) -> dict[UUID, int]:
    """Estudiantes con membresía activa que jugaron en ESE tenant desde `desde` (distintos).

    El cruce es por (tenant, persona): jugar en el cliente B no hace activo en A
    a quien también es estudiante de A.
    """
    act = _actividad(ids, desde)
    stmt = (
        select(Membership.tenant_id, func.count(func.distinct(Membership.profile_id)))
        .join(act, and_(act.c.tid == Membership.tenant_id, act.c.pid == Membership.profile_id))
        .where(Membership.tenant_id.in_(ids), Membership.role == "student",
               Membership.is_active.is_(True))
        .group_by(Membership.tenant_id)
    )
    return {tid: int(n) for tid, n in (await db.execute(stmt)).all()}


async def registros_por_tenant(
    db: AsyncSession, ids: Ids, desde: datetime, desfase_horas: int
) -> dict[UUID, dict[date, int]]:
    """Altas de estudiantes (membresías `student`, activas o no) por tenant y día local."""
    dia = _dia_local(Membership.created_at, desfase_horas)
    stmt = (
        select(Membership.tenant_id, dia, func.count())
        .where(Membership.tenant_id.in_(ids), Membership.role == "student",
               Membership.created_at >= desde)
        .group_by(Membership.tenant_id, dia)
    )
    salida: dict[UUID, dict[date, int]] = defaultdict(dict)
    for tid, d, n in (await db.execute(stmt)).all():
        salida[tid][d] = int(n)
    return salida


async def bolsa_por_tenant(db: AsyncSession, ids: Ids) -> dict[UUID, int]:
    """El saldo de la billetera `tenant` (la bolsa de la institución)."""
    stmt = select(CoinWallet.tenant_id, CoinWallet.balance).where(
        CoinWallet.tenant_id.in_(ids), CoinWallet.owner_type == "tenant",
        CoinWallet.owner_id == CoinWallet.tenant_id, CoinWallet.currency == "COIN",
    )
    return {tid: int(saldo) for tid, saldo in (await db.execute(stmt)).all()}


# -----------------------------------------------------------------------------
# Monedas: por la DIRECCIÓN de la billetera (§1.3), no por el nombre de la acción
# -----------------------------------------------------------------------------
def emitidas_expr(origen: Any, destino: Any) -> Any:
    """Institución (bolsa o bolsillo) → estudiante, salvo la devolución de una compra;
    menos estudiante → bolsillo (la corrección del profe)."""
    return case(
        (and_(origen.in_(("tenant", "membership")), destino == "profile",
              CoinLedger.action != DEVOLUCION_DE_COMPRA), CoinLedger.amount),
        (and_(origen == "profile", destino == "membership"), -CoinLedger.amount),
        else_=0,
    )


def gastadas_expr(origen: Any, destino: Any) -> Any:
    """Estudiante → bolsa (compra) + retenido → bolsa (puja liquidada); menos la devolución."""
    return case(
        (and_(origen == "profile", destino == "tenant"), CoinLedger.amount),
        (and_(origen == "auction", destino == "tenant"), CoinLedger.amount),
        (and_(origen == "tenant", destino == "profile",
              CoinLedger.action == DEVOLUCION_DE_COMPRA), -CoinLedger.amount),
        else_=0,
    )


def _sumas_de_monedas(*agrupar: Any) -> Any:
    """SELECT agrupar..., Σ emitidas, Σ gastadas FROM coin_ledger con sus dos billeteras."""
    desde_w, hacia_w = aliased(CoinWallet), aliased(CoinWallet)
    emit = emitidas_expr(desde_w.owner_type, hacia_w.owner_type)
    gast = gastadas_expr(desde_w.owner_type, hacia_w.owner_type)
    return (
        select(*agrupar, func.coalesce(func.sum(emit), 0), func.coalesce(func.sum(gast), 0))
        .select_from(CoinLedger)
        .outerjoin(desde_w, desde_w.id == CoinLedger.from_wallet_id)  # NULL = recarga
        .outerjoin(hacia_w, hacia_w.id == CoinLedger.to_wallet_id)
    )


async def monedas_por_tenant(db: AsyncSession, ids: Ids) -> dict[UUID, tuple[int, int]]:
    """(emitidas, gastadas) de siempre, por tenant."""
    stmt = (_sumas_de_monedas(CoinLedger.tenant_id)
            .where(CoinLedger.tenant_id.in_(ids)).group_by(CoinLedger.tenant_id))
    return {tid: (int(e), int(g)) for tid, e, g in (await db.execute(stmt)).all()}


async def monedas_por_semana(
    db: AsyncSession, ids: Ids, desde: datetime, desfase_horas: int
) -> dict[date, tuple[int, int]]:
    """(emitidas, gastadas) por lunes local, sumando los tenants de `ids`."""
    local = func.timezone("UTC", CoinLedger.created_at + timedelta(hours=desfase_horas))
    semana = cast(func.date_trunc("week", local), Date)  # date_trunc('week') = lunes
    stmt = (_sumas_de_monedas(semana)
            .where(CoinLedger.tenant_id.in_(ids), CoinLedger.created_at >= desde)
            .group_by(semana))
    return {s: (int(e), int(g)) for s, e, g in (await db.execute(stmt)).all()}
