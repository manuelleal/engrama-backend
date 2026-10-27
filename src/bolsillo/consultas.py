"""Lecturas comunes del bolsillo: quién es personal, sumas de la semana y el reloj.

ESPEC_ola1_economia §1.2-1.3. Todo filtra por `tenant_id` explícito (defensa en
profundidad, WINDSURF §3): el backend se conecta sin RLS (`src/shared/db.py`).
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import cast, exists, func, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.bolsillo import reglas
from src.shared.config import settings
from src.shared.models import CoinLedger, Group, InvitacionDocente, Membership, Profile

# Las acciones del libro que escribe la ola 1 (§1.1).
RECARGA = "budget_allocation"
DEVOLUCION = "budget_return"
ENTREGA = "teacher_award"
CORRECCION = "teacher_reversal"
ROLES_CON_BOLSILLO = ("teacher", "admin")


def ahora() -> datetime:
    """El reloj de la ola 1, en un solo lugar (los tests lo pueden fijar)."""
    return datetime.now(UTC)


def lunes_actual() -> datetime:
    """El inicio de la semana de hoy (lunes 00:00 local) como instante UTC."""
    return reglas.inicio_semana(ahora(), settings.engrama_utc_offset_hours)


def sin_invitacion_pendiente():  # type: ignore[no-untyped-def]
    """Condición: el perfil NO es un profe invitado que aún no aceptó (invitar profes, H-4b).

    Un invitado sin aceptar (fila en `invitaciones_docente` y la bandera arriba) no
    entra al reparto de monedas: no puede entrar todavía, y con un correo ajeno no
    entrará nunca. Los profes del alta de la CLI con contraseña temporal no tienen
    fila de invitación: siguen igual.
    """
    return ~exists(
        select(InvitacionDocente.id)
        .join(Profile, Profile.id == InvitacionDocente.profile_id)
        .where(InvitacionDocente.profile_id == Membership.profile_id,
               InvitacionDocente.tenant_id == Membership.tenant_id,
               Profile.force_password_reset.is_(True)))


async def membresia_personal(db: AsyncSession, tenant_id: UUID, profile_id: UUID) -> Membership | None:
    """La membresía activa de profe o admin de ese perfil en ESA institución (no un invitado pendiente)."""
    stmt = select(Membership).where(
        Membership.tenant_id == tenant_id,
        Membership.profile_id == profile_id,
        Membership.role.in_(ROLES_CON_BOLSILLO),
        Membership.is_active.is_(True),
        sin_invitacion_pendiente(),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def alumno_del_grupo(db: AsyncSession, group: Group, student_id: UUID) -> Membership | None:
    """La membresía activa de estudiante de `student_id` en ESE grupo (por `group_code`)."""
    stmt = select(Membership).where(
        Membership.tenant_id == group.tenant_id,
        Membership.profile_id == student_id,
        Membership.group_code == group.group_code,
        Membership.role == "student",
        Membership.is_active.is_(True),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def suma(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    accion: str,
    desde_fecha: datetime,
    desde_wallet: UUID | None = None,
    hacia_wallet: UUID | None = None,
) -> int:
    """Suma de los asientos de `accion` desde `desde_fecha`, por origen y/o destino."""
    stmt = select(func.coalesce(func.sum(CoinLedger.amount), 0)).where(
        CoinLedger.tenant_id == tenant_id,
        CoinLedger.action == accion,
        CoinLedger.created_at >= desde_fecha,
    )
    if desde_wallet is not None:
        stmt = stmt.where(CoinLedger.from_wallet_id == desde_wallet)
    if hacia_wallet is not None:
        stmt = stmt.where(CoinLedger.to_wallet_id == hacia_wallet)
    return int((await db.execute(stmt)).scalar_one())


def _id_original():  # type: ignore[no-untyped-def]
    """`metadata->>'original_entry_id'` como UUID (la corrección apunta a su entrega)."""
    return cast(CoinLedger.ledger_metadata["original_entry_id"].astext, PG_UUID(as_uuid=True))


async def recibido_semana(db: AsyncSession, tenant_id: UUID, alumno_wallet: UUID,
                          lunes: datetime) -> int:
    """Lo NETO que un estudiante recibió de todos los profes esta semana.

    Entregas de la semana menos lo corregido DE ESAS entregas: corregir un error
    devuelve cupo; corregir una entrega de la semana pasada no da cupo nuevo.
    """
    entregado = await suma(db, tenant_id=tenant_id, accion=ENTREGA, desde_fecha=lunes,
                           hacia_wallet=alumno_wallet)
    original = aliased(CoinLedger)
    corregido = (await db.execute(
        select(func.coalesce(func.sum(CoinLedger.amount), 0))
        .select_from(CoinLedger)
        .join(original, original.id == _id_original())
        .where(CoinLedger.tenant_id == tenant_id, CoinLedger.action == CORRECCION,
               original.to_wallet_id == alumno_wallet, original.created_at >= lunes)
    )).scalar_one()
    return entregado - int(corregido)


async def ya_corregido(db: AsyncSession, tenant_id: UUID, entrada_id: UUID) -> int:
    """Cuánto se ha corregido ya de una entrega."""
    stmt = select(func.coalesce(func.sum(CoinLedger.amount), 0)).where(
        CoinLedger.tenant_id == tenant_id,
        CoinLedger.action == CORRECCION,
        _id_original() == entrada_id,
    )
    return int((await db.execute(stmt)).scalar_one())
