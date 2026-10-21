"""Entregar lo comprado y la devolución sola de los 14 días — ESPEC_ola1_economia §1.4.

El profe marca "entregado" (un toque). Si no lo hace en `tienda_entrega_plazo_dias`
(14), la compra se devuelve: el precio pagado vuelve de la bolsa al estudiante,
UNA sola vez (la llave `shop_refund:<inventario>`), la fila queda `expired` y el
objeto recupera su existencia. El estudiante nunca pierde monedas porque el
profe se olvidó.

La devolución es PEREZOSA (no hay tarea programada): corre al leer la mochila
(solo las del estudiante), al listar entregas (toda la institución) y al
intentar entregar una vencida. Toma la fila de la mochila con `FOR UPDATE SKIP
LOCKED` y después bolsa → estudiante → objeto: nadie que tenga la bolsa espera
por una fila de la mochila, así que no hay ciclo de bloqueos con la compra.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.bolsillo import consultas
from src.bolsillo.reglas import rechazo
from src.engrama_core.service import libro
from src.shared.config import settings
from src.shared.models import Group, Inventory, Membership, ShopItem, TeacherGroup
from src.shop import reglas
from src.shop.compras import DEVOLUCION, mochila_out
from src.shop.schemas import ItemMochilaOut

logger_economia = logging.getLogger("engrama.economia")

Resultado = Literal["entregada", "ya_entregada", "vencida"]


def _llave_devolucion(fila: Inventory) -> str | None:
    return f"{DEVOLUCION}:{fila.id}"


def _marcar_devuelta(fila: Inventory, ahora: datetime) -> None:
    fila.status = "expired"
    fila.resolved_at = ahora


def _corte() -> datetime:
    return reglas.corte_devolucion(consultas.ahora(), settings.tienda_entrega_plazo_dias)


async def _devolver_una(db: AsyncSession, fila: Inventory) -> bool:
    """Devuelve UNA compra vencida (la fila ya viene bloqueada). False si no pudo."""
    if fila.price_paid is None:  # filas de antes de la ola 1: no hay qué devolver
        return False
    bolsa = await libro.billetera(db, "tenant", fila.tenant_id, fila.tenant_id, bloquear=True)
    alumno = await libro.billetera(db, "profile", fila.student_id, fila.tenant_id, bloquear=True)
    if bolsa is None or alumno is None:
        raise RuntimeError("billetera sin crear")
    if int(bolsa.balance) < fila.price_paid:
        logger_economia.warning("devolucion_sin_fondos institucion=%s inventario=%s precio=%s",
                                fila.tenant_id, fila.id, fila.price_paid)
        return False
    await libro.transferir(db, tenant_id=fila.tenant_id, desde=bolsa, hacia=alumno,
                           monto=fila.price_paid, accion=DEVOLUCION, creado_por=None,
                           metadata={"inventory_id": str(fila.id)},
                           llave=_llave_devolucion(fila))
    _marcar_devuelta(fila, consultas.ahora())
    objeto = (await db.execute(select(ShopItem).where(ShopItem.id == fila.item_id)
                               .with_for_update()
                               .execution_options(populate_existing=True))).scalar_one()
    if objeto.stock is not None:
        objeto.stock = objeto.stock + 1
    await db.flush()
    return True


async def devolver_vencidas(db: AsyncSession, tenant_id: UUID, *,
                            alumno: UUID | None = None) -> int:
    """Devuelve las compras sin entregar de 14 días o más. Cuántas devolvió."""
    stmt = select(Inventory).where(
        Inventory.tenant_id == tenant_id,
        Inventory.status == "pending_delivery",
        Inventory.purchased_at <= _corte(),
    )
    if alumno is not None:
        stmt = stmt.where(Inventory.student_id == alumno)
    filas = (await db.execute(stmt.with_for_update(skip_locked=True))).scalars().all()
    return sum([await _devolver_una(db, f) for f in filas])


async def _puede_entregar(db: AsyncSession, auth: AuthContext, fila: Inventory,
                          objeto: ShopItem) -> bool:
    """El admin, quien publicó el objeto o un profe asignado a un grupo del estudiante."""
    if auth.is_admin or objeto.created_by == auth.profile_id:
        return True
    grupos_del_alumno = select(Membership.group_code).where(
        Membership.tenant_id == fila.tenant_id, Membership.profile_id == fila.student_id,
        Membership.role == "student", Membership.is_active.is_(True))
    stmt = (select(TeacherGroup.id).join(Group, Group.id == TeacherGroup.group_id)
            .where(Group.tenant_id == fila.tenant_id,
                   TeacherGroup.teacher_id == auth.profile_id,
                   Group.group_code.in_(grupos_del_alumno)).limit(1))
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def entregar(db: AsyncSession, auth: AuthContext,
                   inventory_id: UUID) -> tuple[Resultado, ItemMochilaOut]:
    """Marca entregada una compra. Una vencida se devuelve (el router responde 409)."""
    fila = (await db.execute(select(Inventory).where(
        Inventory.id == inventory_id, Inventory.tenant_id == auth.tenant_id)
        .with_for_update())).scalar_one_or_none()
    objeto = (await db.get(ShopItem, fila.item_id)) if fila is not None else None
    if fila is None or objeto is None or not await _puede_entregar(db, auth, fila, objeto):
        raise rechazo(status.HTTP_404_NOT_FOUND, "compra_no_encontrada")
    nombre = (await db.execute(select(Membership.full_name).where(
        Membership.tenant_id == fila.tenant_id,
        Membership.profile_id == fila.student_id))).scalar_one_or_none()
    if fila.status == "delivered":
        return "ya_entregada", mochila_out(fila, objeto, nombre)
    if fila.status != "pending_delivery":
        raise rechazo(status.HTTP_409_CONFLICT, "ya_devuelta")
    if fila.purchased_at <= _corte():
        if not await _devolver_una(db, fila):  # la bolsa no alcanzó: sigue pendiente
            raise rechazo(status.HTTP_409_CONFLICT, "plazo_vencido_sin_fondos")
        return "vencida", mochila_out(fila, objeto, nombre)
    fila.status = "delivered"
    fila.resolved_by = auth.profile_id
    fila.resolved_at = consultas.ahora()
    await db.flush()
    return "entregada", mochila_out(fila, objeto, nombre)
