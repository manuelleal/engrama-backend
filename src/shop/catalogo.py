"""El catálogo de la tienda: publicar, editar y mirar — ESPEC_ola1_economia §1.4.

Lo publica el admin o un profe de la institución. El profe edita solo lo que
publicó; el admin, todo lo de su institución (y ve todo el catálogo, también lo
inactivo: así se entera si alguien publica algo que no debe).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.bolsillo.reglas import rechazo
from src.shared.config import settings
from src.shared.models import ShopItem
from src.shop import reglas
from src.shop.schemas import ObjetoIn, ObjetoOut, ObjetoPatch


def objeto_out(o: ShopItem) -> ObjetoOut:
    return ObjetoOut(id=o.id, nombre=o.name, descripcion=o.description, tipo=o.item_type,
                     precio=int(o.price_coins), existencias=o.stock, activo=bool(o.is_active),
                     creado_por=o.created_by)


# Del contrato (español) a las columnas de `shop_items`.
_COLUMNAS = {"nombre": "name", "descripcion": "description", "tipo": "item_type",
             "precio": "price_coins", "existencias": "stock", "activo": "is_active"}


def _validar(nombre: str | None, descripcion: str | None, tipo: str | None,
             precio: int | None) -> None:
    """Las reglas de §1.4 sobre lo que viene (en un PATCH, solo lo que cambia)."""
    if tipo is not None:
        reglas.validar_tipo(tipo)
    if precio is not None:
        reglas.validar_precio(precio, settings.tienda_escalones)
    reglas.validar_textos(nombre, descripcion)


async def crear(db: AsyncSession, auth: AuthContext, datos: ObjetoIn) -> ShopItem:
    _validar(datos.nombre, datos.descripcion, datos.tipo, datos.precio)
    objeto = ShopItem(tenant_id=auth.tenant_id, name=datos.nombre.strip(),
                      description=datos.descripcion, item_type=datos.tipo,
                      price_coins=datos.precio, stock=datos.existencias,
                      is_active=datos.activo, created_by=auth.profile_id)
    db.add(objeto)
    await db.flush()
    return objeto


async def _editable(db: AsyncSession, auth: AuthContext, item_id: UUID) -> ShopItem:
    """El objeto si esta persona puede editarlo; si no, 404 (no delata si existe)."""
    stmt = select(ShopItem).where(ShopItem.id == item_id, ShopItem.tenant_id == auth.tenant_id)
    if not auth.is_admin:
        stmt = stmt.where(ShopItem.created_by == auth.profile_id)
    objeto = (await db.execute(stmt.with_for_update())).scalar_one_or_none()
    if objeto is None:
        raise rechazo(status.HTTP_404_NOT_FOUND, "objeto_no_encontrado")
    return objeto


async def editar(db: AsyncSession, auth: AuthContext, item_id: UUID,
                 datos: ObjetoPatch) -> ShopItem:
    objeto = await _editable(db, auth, item_id)
    cambios = datos.model_dump(exclude_unset=True)
    _validar(cambios.get("nombre"), cambios.get("descripcion"), cambios.get("tipo"),
             cambios.get("precio"))
    for campo, valor in cambios.items():
        if valor is None and campo != "descripcion":
            continue  # un null explícito no borra un campo obligatorio
        setattr(objeto, _COLUMNAS[campo], valor)
    await db.flush()
    return objeto


async def listar(db: AsyncSession, auth: AuthContext) -> list[ObjetoOut]:
    """`GET /economia/tienda`. El personal ve todo el catálogo de su institución
    (activo e inactivo); el estudiante, solo lo activo. Los objetos ocultos de las
    subastas de texto libre nacen inactivos y solo los ve el personal."""
    stmt = select(ShopItem).where(ShopItem.tenant_id == auth.tenant_id)
    if not auth.is_teacher:
        stmt = stmt.where(ShopItem.is_active.is_(True))
    filas = (await db.execute(
        stmt.order_by(ShopItem.price_coins, ShopItem.name, ShopItem.id))).scalars().all()
    return [objeto_out(o) for o in filas]
