"""Comprar y la mochila — ESPEC_ola1_economia §1.4 y ADENDA 1 §A.2.

Comprar es el primer sumidero de ENGRAMA: el precio sale del saldo del
estudiante y VUELVE A LA BOLSA de la institución (en Lingo se destruía y la
bolsa solo se gastaba). El objeto entra a la mochila "por entregar"; si el profe
no lo entrega en 14 días, se devuelve solo (`entregas.devolver_vencidas`).

Orden de bloqueo: bolsa (`tenant`) → estudiante (`profile`) → objeto
(`shop_items`): el mismo de toda la ola (libro.py). Cada ayuda (`_objeto_de`,
`_verificar_stock`, `_cobrar`) es un punto que un tramposo rompe por separado.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.bolsillo.reglas import rechazo
from src.engrama_core.service import libro
from src.shared.config import settings
from src.shared.models import CoinLedger, CoinWallet, Group, Inventory, Membership, ShopItem
from src.shop import reglas
from src.shop.schemas import ESTADOS, ORIGENES, ItemMochilaOut
from src.teachers.service import access as access_service

COMPRA = "shop_purchase"
DEVOLUCION = "shop_refund"


def exigir_estudiante(auth: AuthContext) -> None:
    """Solo una membresía de estudiante compra, puja y tiene mochila."""
    if auth.role != "student":
        raise rechazo(status.HTTP_403_FORBIDDEN, "solo_estudiantes")


def mochila_out(fila: Inventory, objeto: ShopItem, nombre: str | None) -> ItemMochilaOut:
    return ItemMochilaOut(
        id=fila.id, objeto_id=objeto.id, nombre=objeto.name, tipo=objeto.item_type,
        origen=ORIGENES.get(fila.source, fila.source), precio_pagado=fila.price_paid,
        estado=ESTADOS.get(fila.status, fila.status), comprado_en=fila.purchased_at,
        entregar_antes_de=reglas.vence_el(fila.purchased_at, settings.tienda_entrega_plazo_dias),
        resuelto_en=fila.resolved_at, estudiante_id=fila.student_id,
        estudiante_nombre=nombre or "")


def consulta_mochila() -> Any:
    """Mochila + objeto + nombre del estudiante en ESA institución (BUG-11)."""
    return (select(Inventory, ShopItem, Membership.full_name)
            .join(ShopItem, ShopItem.id == Inventory.item_id)
            .outerjoin(Membership, (Membership.tenant_id == Inventory.tenant_id)
                       & (Membership.profile_id == Inventory.student_id)))


async def _objeto_de(db: AsyncSession, tenant_id: UUID, item_id: UUID) -> ShopItem | None:
    """El objeto de ESA institución, bloqueado (dos compras del último no pasan juntas)."""
    stmt = select(ShopItem).where(ShopItem.id == item_id, ShopItem.tenant_id == tenant_id)
    return (await db.execute(stmt.with_for_update())).scalar_one_or_none()


def _verificar_stock(objeto: ShopItem) -> None:
    """Sin existencias, 409. `stock NULL` (heredado de antes de la ola) = ilimitado."""
    if objeto.stock is not None and objeto.stock <= 0:
        raise rechazo(status.HTTP_409_CONFLICT, "agotado")


async def _cobrar(db: AsyncSession, *, tenant_id: UUID, alumno: CoinWallet, bolsa: CoinWallet,
                  monto: int, llave: str, creado_por: UUID, item_id: UUID) -> CoinLedger:
    """El precio va del estudiante a la bolsa (vuelve, no se destruye)."""
    try:
        asiento, _ = await libro.transferir(
            db, tenant_id=tenant_id, desde=alumno, hacia=bolsa, monto=monto, accion=COMPRA,
            creado_por=creado_por, metadata={"item_id": str(item_id)}, llave=llave)
    except libro.SaldoInsuficiente as exc:
        raise rechazo(status.HTTP_402_PAYMENT_REQUIRED, "saldo_insuficiente",
                      saldo=exc.saldo, precio=monto) from exc
    return asiento


async def _repeticion(db: AsyncSession, asiento: CoinLedger, item_id: UUID) -> ItemMochilaOut:
    """La misma llave otra vez: la misma fila de la mochila, sin cobrar de nuevo."""
    fila = (await db.execute(consulta_mochila()
                             .where(Inventory.purchase_ledger_id == asiento.id))).first()
    if fila is None or fila[1].id != item_id:
        raise rechazo(status.HTTP_409_CONFLICT, "llave_reutilizada")
    return mochila_out(*fila)


async def comprar(db: AsyncSession, auth: AuthContext, item_id: UUID,
                  llave_cliente: str | None) -> tuple[ItemMochilaOut, bool]:
    """Compra un objeto de la tienda de SU institución. Devuelve (mochila, ¿nueva?)."""
    exigir_estudiante(auth)
    bolsa = await libro.billetera(db, "tenant", auth.tenant_id, auth.tenant_id, bloquear=True)
    alumno = await libro.billetera(db, "profile", auth.profile_id, auth.tenant_id, bloquear=True)
    if bolsa is None or alumno is None:
        raise RuntimeError("billetera sin crear")
    llave = f"{COMPRA}:{auth.profile_id}:{llave_cliente or uuid4().hex}"
    previo = await libro.asiento_por_llave(db, auth.tenant_id, llave)
    if previo is not None:
        return await _repeticion(db, previo, item_id), False
    objeto = await _objeto_de(db, auth.tenant_id, item_id)
    if objeto is None:
        raise rechazo(status.HTTP_404_NOT_FOUND, "objeto_no_encontrado")
    if not objeto.is_active:
        raise rechazo(status.HTTP_409_CONFLICT, "inactivo")
    _verificar_stock(objeto)
    precio = int(objeto.price_coins)
    asiento = await _cobrar(db, tenant_id=auth.tenant_id, alumno=alumno, bolsa=bolsa,
                            monto=precio, llave=llave, creado_por=auth.profile_id,
                            item_id=objeto.id)
    if objeto.stock is not None:
        objeto.stock = objeto.stock - 1
    await nueva_fila(db, auth.tenant_id, auth.profile_id, objeto, precio, asiento, origen="shop")
    return await _repeticion(db, asiento, objeto.id), True


async def nueva_fila(db: AsyncSession, tenant_id: UUID, alumno: UUID, objeto: ShopItem,
                     precio: int, asiento: CoinLedger, *, origen: str) -> Inventory:
    """La fila "por entregar" de la mochila (compra o subasta ganada)."""
    fila = Inventory(tenant_id=tenant_id, student_id=alumno, item_id=objeto.id, source=origen,
                     status="pending_delivery", price_paid=precio, purchase_ledger_id=asiento.id)
    db.add(fila)
    await db.flush()
    await db.refresh(fila)  # trae `purchased_at` (lo pone la base)
    return fila


async def mochila(db: AsyncSession, auth: AuthContext) -> list[ItemMochilaOut]:
    """La mochila del estudiante, lo más nuevo primero (ya barrida, ver router)."""
    exigir_estudiante(auth)
    filas = (await db.execute(consulta_mochila().where(
        Inventory.tenant_id == auth.tenant_id, Inventory.student_id == auth.profile_id)
        .order_by(Inventory.purchased_at.desc(), Inventory.id))).all()
    return [mochila_out(*f) for f in filas]


async def mochila_grupo(db: AsyncSession, auth: AuthContext, gid: UUID) -> list[ItemMochilaOut]:
    """`GET /economia/grupo/{gid}/mochila`: lo de los estudiantes del grupo, todos los estados."""
    grupo: Group = await access_service.authorize_group(db, auth, gid)
    del_grupo = select(Membership.profile_id).where(
        Membership.tenant_id == grupo.tenant_id, Membership.group_code == grupo.group_code,
        Membership.role == "student", Membership.is_active.is_(True))
    filas = (await db.execute(consulta_mochila().where(
        Inventory.tenant_id == auth.tenant_id, Inventory.student_id.in_(del_grupo))
        .order_by(Inventory.purchased_at.desc(), Inventory.id))).all()
    return [mochila_out(*f) for f in filas]
