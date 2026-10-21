"""(b) El presupuesto del profe: recargar, devolver y mirar bolsillos — ESPEC §1.2.

El bolsillo es la billetera de la MEMBRESÍA del profe (una por institución,
migración 047). Lo recarga el admin desde la bolsa de la institución, con un
tope semanal por bolsillo (`profe_presupuesto_semanal`, 100); el profe da desde
ahí (`entregas.py`). La bolsa de la institución la sigue recargando solo el
operador por la CLI.
"""
from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.bolsillo import consultas, listas, reglas
from src.bolsillo.schemas import (
    BolsilloAdminOut,
    MovimientoIn,
    MovimientoOut,
    PanelBolsillosOut,
    PresupuestoOut,
)
from src.engrama_core.service import libro
from src.shared.config import settings
from src.shared.models import CoinLedger, CoinWallet, Membership, Profile, Tenant


async def _objetivo(db: AsyncSession, auth: AuthContext, teacher_id: UUID) -> Membership:
    """La membresía de personal de `teacher_id` en la institución del admin; si no, 404."""
    m = await consultas.membresia_personal(db, auth.tenant_id, teacher_id)
    if m is None:
        raise reglas.rechazo(status.HTTP_404_NOT_FOUND, "profe_no_encontrado")
    return m


async def _recargado_semana(db: AsyncSession, tenant_id: UUID, bolsillo_id: UUID) -> int:
    """Lo recargado a ESE bolsillo desde el lunes (las devoluciones no liberan cupo)."""
    return await consultas.suma(db, tenant_id=tenant_id, accion=consultas.RECARGA,
                                desde_fecha=consultas.lunes_actual(), hacia_wallet=bolsillo_id)


async def _billeteras(db: AsyncSession, auth: AuthContext,
                      m: Membership) -> tuple[CoinWallet, CoinWallet]:
    """Bolsa y bolsillo, bloqueados en el orden de la casa (tenant → membership)."""
    bolsa = await libro.billetera(db, "tenant", auth.tenant_id, auth.tenant_id, bloquear=True)
    bolsillo = await libro.billetera(db, "membership", m.id, auth.tenant_id, bloquear=True)
    if bolsa is None or bolsillo is None:  # con crear=True no pasa
        raise RuntimeError("billetera sin crear")
    return bolsa, bolsillo


async def _salida(db: AsyncSession, asiento: CoinLedger, m: Membership, bolsa: CoinWallet,
                  bolsillo: CoinWallet) -> MovimientoOut:
    return MovimientoOut(
        movimiento_id=asiento.id, teacher_id=m.profile_id, monto=int(asiento.amount),
        saldo_bolsillo=int(bolsillo.balance), saldo_bolsa=int(bolsa.balance),
        recargado_semana=await _recargado_semana(db, m.tenant_id, bolsillo.id))


def _exigir_mismo(asiento: CoinLedger, desde: CoinWallet, hacia: CoinWallet, monto: int) -> None:
    """La misma llave con otro destino u otro monto no es un reintento: 409."""
    if (asiento.from_wallet_id, asiento.to_wallet_id, int(asiento.amount)) != (
            desde.id, hacia.id, monto):
        raise reglas.rechazo(status.HTTP_409_CONFLICT, "llave_reutilizada")


async def recargar(db: AsyncSession, auth: AuthContext, teacher_id: UUID,
                   datos: MovimientoIn) -> tuple[MovimientoOut, bool]:
    """De la bolsa al bolsillo, con tope semanal. Devuelve (salida, ¿nuevo?)."""
    m = await _objetivo(db, auth, teacher_id)
    bolsa, bolsillo = await _billeteras(db, auth, m)
    llave = f"{consultas.RECARGA}:{auth.profile_id}:{datos.llave or uuid4().hex}"
    previo = await libro.asiento_por_llave(db, auth.tenant_id, llave)
    if previo is not None:
        _exigir_mismo(previo, bolsa, bolsillo, datos.monto)
        return await _salida(db, previo, m, bolsa, bolsillo), False
    ya = await _recargado_semana(db, auth.tenant_id, bolsillo.id)
    tope = settings.profe_presupuesto_semanal
    if not reglas.cabe_en_tope(ya, datos.monto, tope):
        raise reglas.rechazo(status.HTTP_409_CONFLICT, "tope_semanal_presupuesto",
                             tope=tope, recargado=ya)
    try:
        asiento, nuevo = await libro.transferir(
            db, tenant_id=auth.tenant_id, desde=bolsa, hacia=bolsillo, monto=datos.monto,
            accion=consultas.RECARGA, creado_por=auth.profile_id,
            metadata={"note": datos.nota}, llave=llave)
    except libro.SaldoInsuficiente as exc:
        raise reglas.rechazo(status.HTTP_402_PAYMENT_REQUIRED, "bolsa_insuficiente",
                             saldo=exc.saldo) from exc
    return await _salida(db, asiento, m, bolsa, bolsillo), nuevo


async def devolver(db: AsyncSession, auth: AuthContext, teacher_id: UUID,
                   datos: MovimientoIn) -> tuple[MovimientoOut, bool]:
    """Del bolsillo a la bolsa, hasta el saldo del bolsillo."""
    m = await _objetivo(db, auth, teacher_id)
    bolsa, bolsillo = await _billeteras(db, auth, m)
    llave = f"{consultas.DEVOLUCION}:{auth.profile_id}:{datos.llave or uuid4().hex}"
    previo = await libro.asiento_por_llave(db, auth.tenant_id, llave)
    if previo is not None:
        _exigir_mismo(previo, bolsillo, bolsa, datos.monto)
        return await _salida(db, previo, m, bolsa, bolsillo), False
    try:
        asiento, nuevo = await libro.transferir(
            db, tenant_id=auth.tenant_id, desde=bolsillo, hacia=bolsa, monto=datos.monto,
            accion=consultas.DEVOLUCION, creado_por=auth.profile_id,
            metadata={"note": datos.nota}, llave=llave)
    except libro.SaldoInsuficiente as exc:
        raise reglas.rechazo(status.HTTP_409_CONFLICT, "saldo_bolsillo",
                             saldo=exc.saldo) from exc
    return await _salida(db, asiento, m, bolsa, bolsillo), nuevo


async def _nombre(db: AsyncSession, m: Membership) -> str:
    """El nombre visible: el de la membresía; si no lo tiene (personal anterior a la 032),
    el del perfil (como `nombre_visible` de auth)."""
    if m.full_name:
        return m.full_name
    return (await db.execute(select(Profile.full_name).where(
        Profile.id == m.profile_id))).scalar_one_or_none() or ""


async def _fila(db: AsyncSession, m: Membership) -> BolsilloAdminOut:
    nombre = await _nombre(db, m)
    bolsillo = await libro.billetera(db, "membership", m.id, m.tenant_id, crear=False)
    if bolsillo is None:  # nunca recargado: saldo 0 y nada en la semana
        return BolsilloAdminOut(teacher_id=m.profile_id, nombre=nombre, rol=m.role,
                                saldo=0, recargado_semana=0, entregado_semana=0)
    dado = await consultas.suma(db, tenant_id=m.tenant_id, accion=consultas.ENTREGA,
                                desde_fecha=consultas.lunes_actual(), desde_wallet=bolsillo.id)
    return BolsilloAdminOut(
        teacher_id=m.profile_id, nombre=nombre, rol=m.role,
        saldo=int(bolsillo.balance),
        recargado_semana=await _recargado_semana(db, m.tenant_id, bolsillo.id),
        entregado_semana=dado)


async def mi_presupuesto(db: AsyncSession, auth: AuthContext) -> PresupuestoOut:
    """`GET /economia/presupuesto`: el bolsillo propio, los topes y lo corregible."""
    m = await consultas.membresia_personal(db, auth.tenant_id, auth.profile_id)
    fila = await _fila(db, m) if m is not None else None
    return PresupuestoOut(
        saldo=fila.saldo if fila else 0,
        recargado_semana=fila.recargado_semana if fila else 0,
        entregado_semana=fila.entregado_semana if fila else 0,
        tope_recarga_semanal=settings.profe_presupuesto_semanal,
        tope_por_entrega=settings.profe_entrega_tope,
        tope_semanal_por_estudiante=settings.profe_semana_por_estudiante_tope,
        entregas_recientes=await listas.mis_entregas(db, auth))


async def panel_admin(db: AsyncSession, auth: AuthContext) -> PanelBolsillosOut:
    """`GET /admin/presupuestos`: la bolsa y cada bolsillo de personal de SU institución."""
    bolsa = await libro.billetera(db, "tenant", auth.tenant_id, auth.tenant_id, crear=False)
    emitido = (await db.execute(
        select(Tenant.coin_pool).where(Tenant.id == auth.tenant_id))).scalar_one_or_none()
    personal = (await db.execute(
        select(Membership).where(
            Membership.tenant_id == auth.tenant_id,
            Membership.role.in_(consultas.ROLES_CON_BOLSILLO),
            Membership.is_active.is_(True),
        ).order_by(Membership.created_at, Membership.profile_id))).scalars().all()
    return PanelBolsillosOut(
        bolsa_saldo=int(bolsa.balance) if bolsa else 0, bolsa_emitida=int(emitido or 0),
        profes=[await _fila(db, m) for m in personal])
