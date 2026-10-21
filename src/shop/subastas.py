"""La subasta (puja) en vivo — ESPEC_ola1_economia, ADENDA 1 §A.4-§A.5 (decisión 017).

El profe lanza una subasta para SU grupo (un objeto de la tienda o un texto
libre), de 90 s por defecto. Cada puja RETIENE las monedas del que puja en la
billetera de la subasta (`owner_type='auction'`) y al líder anterior se le
devuelven al instante: nadie puja con monedas que no tiene ni con las mismas
monedas en dos subastas. Una puja en los últimos 10 s extiende 10 s (máximo 3).
Al cerrar, lo retenido del ganador vuelve a la bolsa de la institución y el
objeto entra a su mochila "por entregar".

Bloqueos: la fila de la subasta primero (serializa las pujas de esa subasta),
después bolsa → retención → estudiantes (en orden de id, para que dos pujas
cruzadas entre dos subastas no se traben).
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.bolsillo import consultas
from src.bolsillo.reglas import rechazo
from src.engrama_core.service import libro
from src.shared.models import Auction, AuctionBid, CoinWallet, Group, Membership, ShopItem
from src.shop import compras, reglas
from src.shop.schemas import PujaIn, SubastaIn, SubastaOut
from src.teachers.service import access as access_service

INCREMENTOS = (5, 10, 25)
VENTANA_S = 10  # una puja en los últimos 10 s...
EXTENSION_S = 10  # ...extiende el cierre 10 s...
MAX_EXTENSIONES = 3  # ...a lo sumo 3 veces
RESULTADO_S = 120  # `activa` muestra la última cerrada durante 2 minutos
RETENCION, REEMBOLSO, LIQUIDACION = "auction_hold", "auction_refund", "auction_settle"
ESTADOS = {"active": "activa", "ended": "cerrada", "cancelled": "cancelada"}

Resultado = Literal["ok", "repetida", "cerrada"]


def subasta_out(a: Auction) -> SubastaOut:
    ahora = consultas.ahora()
    quedan = 0
    if a.status == "active" and a.ends_at is not None:
        quedan = max(0, math.ceil((a.ends_at - ahora).total_seconds()))
    return SubastaOut(
        id=a.id, grupo_id=a.group_id, objeto_id=a.item_id, titulo=a.item_name,
        descripcion=a.description, puja_minima=int(a.base_price), puja_actual=int(a.current_bid),
        lider_id=a.highest_bidder_id, lider_nombre=a.highest_bidder_name, termina_en=a.ends_at,
        segundos_restantes=quedan, extensiones=int(a.extensions or 0),
        estado=ESTADOS.get(a.status, a.status), ganador_id=a.winner_id,
        incrementos=list(INCREMENTOS), creada_en=a.created_at)


async def _grupo_visible(db: AsyncSession, auth: AuthContext, gid: UUID) -> Group:
    """El personal: su grupo (o cualquiera de su institución, el admin). El estudiante:
    solo el suyo. Lo demás, 404."""
    if auth.is_teacher:
        return await access_service.authorize_group(db, auth, gid)
    grupo = (await db.execute(select(Group).where(
        Group.id == gid, Group.tenant_id == auth.tenant_id,
        Group.group_code == auth.group_code))).scalar_one_or_none()
    if grupo is None:
        raise rechazo(status.HTTP_404_NOT_FOUND, "grupo_no_encontrado")
    return grupo


async def _objeto_para(db: AsyncSession, auth: AuthContext, datos: SubastaIn) -> ShopItem:
    """El objeto de la tienda (su existencia queda reservada) o uno oculto de texto libre."""
    if (datos.objeto_id is None) == (datos.titulo is None):
        raise rechazo(status.HTTP_422_UNPROCESSABLE_ENTITY, "objeto_o_titulo")
    if datos.objeto_id is not None:
        objeto = await compras._objeto_de(db, auth.tenant_id, datos.objeto_id)
        if objeto is None:
            raise rechazo(status.HTTP_404_NOT_FOUND, "objeto_no_encontrado")
        if not objeto.is_active:
            raise rechazo(status.HTTP_409_CONFLICT, "inactivo")
        compras._verificar_stock(objeto)
        if objeto.stock is not None:
            objeto.stock = objeto.stock - 1
        return objeto
    reglas.validar_textos(datos.titulo, datos.descripcion)
    # Oculto: precio 0 (ningún objeto de la tienda vale 0: los escalones empiezan
    # en 40), inactivo y sin existencias. Solo existe para la fila de la mochila.
    oculto = ShopItem(tenant_id=auth.tenant_id, name=datos.titulo, description=datos.descripcion,
                      item_type="privilegio", price_coins=0, stock=0, is_active=False,
                      created_by=auth.profile_id)
    db.add(oculto)
    await db.flush()
    return oculto


async def _activa_de(db: AsyncSession, tenant_id: UUID, gid: UUID) -> Auction | None:
    return (await db.execute(select(Auction).where(
        Auction.tenant_id == tenant_id, Auction.group_id == gid, Auction.status == "active")
        .with_for_update())).scalar_one_or_none()


async def crear(db: AsyncSession, auth: AuthContext, datos: SubastaIn) -> SubastaOut:
    grupo = await access_service.authorize_group(db, auth, datos.grupo_id)
    previa = await _activa_de(db, auth.tenant_id, grupo.id)
    if previa is not None:
        await cerrar_si_vencio(db, previa)
        if previa.status == "active":
            raise rechazo(status.HTTP_409_CONFLICT, "grupo_con_subasta")
    objeto = await _objeto_para(db, auth, datos)
    ahora = consultas.ahora()
    subasta = Auction(
        tenant_id=auth.tenant_id, group_id=grupo.id, item_name=objeto.name,
        description=datos.descripcion or objeto.description, base_price=datos.puja_minima,
        current_bid=0, duration_seconds=datos.duracion_segundos, start_at=ahora,
        ends_at=ahora + timedelta(seconds=datos.duracion_segundos), status="active",
        item_id=objeto.id, created_by=auth.profile_id, extensions=0)
    db.add(subasta)
    await db.flush()
    await db.refresh(subasta)
    return subasta_out(subasta)


async def _bloquear_alumnos(db: AsyncSession, tenant_id: UUID,
                            ids: list[UUID]) -> dict[UUID, CoinWallet]:
    """Las billeteras de los estudiantes, bloqueadas en orden de id."""
    salida: dict[UUID, CoinWallet] = {}
    for pid in sorted(set(ids), key=str):
        w = await libro.billetera(db, "profile", pid, tenant_id, bloquear=True)
        if w is None:
            raise RuntimeError("billetera sin crear")
        salida[pid] = w
    return salida


def _validar_monto(a: Auction, monto: int) -> None:
    """Primera puja ≥ mínima; después, sube exactamente 5, 10 o 25."""
    if a.highest_bidder_id is None:
        if monto < int(a.base_price):
            raise rechazo(status.HTTP_409_CONFLICT, "puja_minima", minimo=int(a.base_price))
    elif monto - int(a.current_bid) not in INCREMENTOS:
        raise rechazo(status.HTTP_409_CONFLICT, "incremento_invalido", actual=int(a.current_bid))


def _extender(a: Auction, ahora: datetime) -> None:
    """Puja en los últimos 10 s: el cierre se corre 10 s, máximo 3 veces."""
    if a.ends_at is None or a.ends_at - ahora > timedelta(seconds=VENTANA_S):
        return
    if (a.extensions or 0) < MAX_EXTENSIONES:
        a.ends_at = a.ends_at + timedelta(seconds=EXTENSION_S)
        a.extensions = (a.extensions or 0) + 1


async def _retener(db: AsyncSession, a: Auction, auth: AuthContext, monto: int,
                   llave: str | None) -> bool:
    """Mueve las monedas: retiene al que puja y devuelve al líder anterior. ¿Nuevo?"""
    retenida = await libro.billetera(db, "auction", a.id, a.tenant_id, bloquear=True)
    lider = a.highest_bidder_id
    alumnos = await _bloquear_alumnos(db, a.tenant_id, [auth.profile_id, *([lider] if lider else [])])
    yo = alumnos[auth.profile_id]
    if retenida is None:
        raise RuntimeError("billetera sin crear")
    a_retener = monto - int(a.current_bid) if lider == auth.profile_id else monto
    try:
        _, nuevo = await libro.transferir(
            db, tenant_id=a.tenant_id, desde=yo, hacia=retenida, monto=a_retener,
            accion=RETENCION, creado_por=auth.profile_id, llave=llave,
            metadata={"auction_id": str(a.id), "puja": monto})
    except libro.SaldoInsuficiente as exc:
        raise rechazo(status.HTTP_402_PAYMENT_REQUIRED, "sin_saldo_puja", saldo=exc.saldo) from exc
    if nuevo and lider is not None and lider != auth.profile_id:
        await _devolver_al_superado(db, a, retenida, alumnos[lider])
    return nuevo


async def _devolver_al_superado(db: AsyncSession, a: Auction, retenida: CoinWallet,
                                superado: CoinWallet) -> None:
    """Al líder anterior se le devuelve TODO lo suyo, al instante."""
    await libro.transferir(db, tenant_id=a.tenant_id, desde=retenida, hacia=superado,
                           monto=int(a.current_bid), accion=REEMBOLSO, creado_por=None,
                           metadata={"auction_id": str(a.id)})


async def pujar(db: AsyncSession, auth: AuthContext, aid: UUID,
                datos: PujaIn) -> tuple[Resultado, SubastaOut]:
    compras.exigir_estudiante(auth)
    a = (await db.execute(select(Auction).where(Auction.id == aid, Auction.tenant_id ==
                                                auth.tenant_id).with_for_update())).scalar_one_or_none()
    if a is None or a.group_id is None:
        raise rechazo(status.HTTP_404_NOT_FOUND, "subasta_no_encontrada")
    await _grupo_visible(db, auth, a.group_id)
    llave = f"{RETENCION}:{auth.profile_id}:{datos.llave}" if datos.llave else None
    if llave and await libro.asiento_por_llave(db, auth.tenant_id, llave) is not None:
        return "repetida", subasta_out(a)
    if a.status != "active":
        raise rechazo(status.HTTP_409_CONFLICT, "subasta_cerrada")
    if await cerrar_si_vencio(db, a):
        return "cerrada", subasta_out(a)
    _validar_monto(a, datos.monto)
    await _retener(db, a, auth, datos.monto, llave)
    nombre = (await db.execute(select(Membership.full_name).where(
        Membership.tenant_id == a.tenant_id,
        Membership.profile_id == auth.profile_id))).scalar_one_or_none()
    db.add(AuctionBid(tenant_id=a.tenant_id, auction_id=a.id, bidder_id=auth.profile_id,
                      bid_amount=datos.monto))
    a.current_bid, a.highest_bidder_id, a.highest_bidder_name = datos.monto, auth.profile_id, nombre
    _extender(a, consultas.ahora())
    await db.flush()
    return "ok", subasta_out(a)


async def cerrar(db: AsyncSession, a: Auction) -> None:
    """Cierra una subasta activa (ya bloqueada): al ganador, mochila; lo retenido, a la bolsa."""
    if a.status != "active":
        return
    ahora = consultas.ahora()
    a.status = "ended"
    if a.ends_at is None or a.ends_at > ahora:
        a.ends_at = ahora
    # Orden de la casa: bolsa → retención → objeto (como la compra: bolsa antes que objeto).
    bolsa = await libro.billetera(db, "tenant", a.tenant_id, a.tenant_id, bloquear=True)
    retenida = await libro.billetera(db, "auction", a.id, a.tenant_id, bloquear=True)
    if bolsa is None or retenida is None:
        raise RuntimeError("billetera sin crear")
    objeto = None if a.item_id is None else (await db.execute(
        select(ShopItem).where(ShopItem.id == a.item_id).with_for_update())).scalar_one_or_none()
    if a.highest_bidder_id is None:
        if objeto is not None and objeto.price_coins > 0 and objeto.stock is not None:
            objeto.stock = objeto.stock + 1  # nadie pujó: el objeto vuelve a la tienda
        await db.flush()
        return
    if objeto is None:  # hay puja ganadora pero no hay qué entregar: no se liquida a ciegas
        raise RuntimeError(f"subasta {a.id} con puja y sin objeto")
    asiento, _ = await libro.transferir(
        db, tenant_id=a.tenant_id, desde=retenida, hacia=bolsa, monto=int(a.current_bid),
        accion=LIQUIDACION, creado_por=None, metadata={"auction_id": str(a.id)},
        llave=f"{LIQUIDACION}:{a.id}")
    a.winner_id = a.highest_bidder_id
    await compras.nueva_fila(db, a.tenant_id, a.highest_bidder_id, objeto, int(a.current_bid),
                             asiento, origen="auction")


async def cerrar_si_vencio(db: AsyncSession, a: Auction) -> bool:
    """Cierre perezoso: si ya pasó la hora, la cierra. ¿La cerró?"""
    if a.status == "active" and a.ends_at is not None and consultas.ahora() >= a.ends_at:
        await cerrar(db, a)
        return True
    return False


async def cerrar_por_profe(db: AsyncSession, auth: AuthContext, aid: UUID) -> SubastaOut:
    a = (await db.execute(select(Auction).where(Auction.id == aid, Auction.tenant_id ==
                                                auth.tenant_id).with_for_update())).scalar_one_or_none()
    if a is None or a.group_id is None:
        raise rechazo(status.HTTP_404_NOT_FOUND, "subasta_no_encontrada")
    await access_service.authorize_group(db, auth, a.group_id)
    await cerrar(db, a)
    return subasta_out(a)


async def activa(db: AsyncSession, auth: AuthContext, gid: UUID) -> SubastaOut | None:
    """La activa del grupo (cerrándola si ya venció) o la última cerrada hace < 2 min."""
    grupo = await _grupo_visible(db, auth, gid)
    a = await _activa_de(db, auth.tenant_id, grupo.id)
    if a is not None:
        await cerrar_si_vencio(db, a)
        if a.status == "active":
            return subasta_out(a)
    reciente = (await db.execute(select(Auction).where(
        Auction.tenant_id == auth.tenant_id, Auction.group_id == grupo.id,
        Auction.status == "ended",
        Auction.ends_at >= consultas.ahora() - timedelta(seconds=RESULTADO_S))
        .order_by(Auction.ends_at.desc()).limit(1))).scalar_one_or_none()
    return subasta_out(reciente) if reciente is not None else None
