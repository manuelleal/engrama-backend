"""(a) Dar y Corregir monedas (el profe) — ESPEC_ola1_economia §1.3 y ADENDA 1 §A.3.

Dar es el reconocimiento del profe con techo, NO un reemplazo del pago por
aciertos ("la moneda es la respuesta correcta"): una entrega no pasa de 20
(lo que vale el reto más caro), a un estudiante no le llegan de los profes más
de 40 por semana, y sale del bolsillo del profe, que es finito.

Corregir no es castigo: solo deshace una entrega PROPIA, hasta 14 días después,
hasta el monto original y nunca deja al estudiante en negativo. No existe
"quitar" sin una entrega detrás.

Cada función de ayuda (`_grupo_del_alumno`, `_cupo_semanal`, `_entrega_propia`,
`_llave`) es un punto que un tramposo rompe por separado (§3).
"""
from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.bolsillo import consultas, reglas
from src.bolsillo.schemas import CorregirIn, CorregirOut, DarIn, DarOut
from src.engrama_core.service import libro
from src.shared.config import settings
from src.shared.models import CoinLedger, CoinWallet, Group, Membership
from src.teachers.service import access as access_service


def _llave(accion: str, auth: AuthContext, cliente: str | None) -> str | None:
    """La llave del libro: acción + quién + la del cliente (dos profes no chocan).

    Sin llave del cliente, una al azar: cada llamada es nueva (contrato §A.1).
    """
    return f"{accion}:{auth.profile_id}:{cliente or uuid4().hex}"


async def _grupo_del_alumno(db: AsyncSession, auth: AuthContext, sid: UUID) -> Group:
    """Un grupo VISIBLE para `auth` donde `sid` es estudiante activo; si no, 404.

    El profe: solo sus grupos asignados (`access.visible_groups`); el admin: los de
    su institución. Un estudiante de otro grupo u otra institución da el mismo 404.
    """
    codigos = (await db.execute(select(Membership.group_code).where(
        Membership.tenant_id == auth.tenant_id, Membership.profile_id == sid,
        Membership.role == "student", Membership.is_active.is_(True)))).scalars().all()
    for grupo in await access_service.visible_groups(db, auth):
        if grupo.group_code in codigos:
            return grupo
    raise reglas.rechazo(status.HTTP_404_NOT_FOUND, "estudiante_no_encontrado")


async def _cupo_semanal(db: AsyncSession, auth: AuthContext, alumno_wallet: UUID) -> int:
    """Lo que el estudiante ya recibió esta semana de TODOS los profes (neto).

    De `auth` solo se usa la institución: el tope es por estudiante, no por
    profe (el tramposo OT2 cuenta solo lo del mismo profe y deja pasar 60).
    """
    return await consultas.recibido_semana(db, auth.tenant_id, alumno_wallet,
                                           consultas.lunes_actual())


async def _bolsillo_propio(db: AsyncSession, auth: AuthContext) -> CoinWallet:
    m = await consultas.membresia_personal(db, auth.tenant_id, auth.profile_id)
    if m is None:  # require_teacher ya pasó: personal sin membresía activa no debería existir
        raise reglas.rechazo(status.HTTP_403_FORBIDDEN, "sin_bolsillo")
    bolsillo = await libro.billetera(db, "membership", m.id, auth.tenant_id, bloquear=True)
    if bolsillo is None:
        raise RuntimeError("billetera sin crear")
    return bolsillo


def _salida_dar(asiento: CoinLedger, alumno: UUID, bolsillo: CoinWallet,
                recibido: int) -> DarOut:
    meta = asiento.ledger_metadata or {}
    tope = settings.profe_semana_por_estudiante_tope
    return DarOut(entrega_id=asiento.id, estudiante_id=alumno, monto=int(asiento.amount),
                  motivo=str(meta.get("reason", "")), nota=meta.get("note"),
                  creada_en=asiento.created_at, presupuesto_restante=int(bolsillo.balance),
                  recibido_semana=recibido, cupo_semana=max(tope - recibido, 0))


async def dar(db: AsyncSession, auth: AuthContext, datos: DarIn) -> tuple[DarOut, bool]:
    """Del bolsillo del profe a un estudiante de SU grupo. Devuelve (salida, ¿nuevo?)."""
    reglas.validar_motivo(datos.motivo, datos.nota)
    reglas.validar_monto_entrega(datos.monto, settings.profe_entrega_tope)
    sid = datos.student_id
    grupo = await _grupo_del_alumno(db, auth, sid)
    bolsillo = await _bolsillo_propio(db, auth)  # orden: membership → profile
    alumno = await libro.billetera(db, "profile", sid, auth.tenant_id, bloquear=True)
    if alumno is None:
        raise RuntimeError("billetera sin crear")
    llave = _llave(consultas.ENTREGA, auth, datos.llave)
    previo = await libro.asiento_por_llave(db, auth.tenant_id, llave) if llave else None
    if previo is not None:
        if (previo.to_wallet_id, int(previo.amount)) != (alumno.id, datos.monto):
            raise reglas.rechazo(status.HTTP_409_CONFLICT, "llave_reutilizada")
        return _salida_dar(previo, sid, bolsillo, await _cupo_semanal(db, auth, alumno.id)), False
    recibido = await _cupo_semanal(db, auth, alumno.id)
    tope = settings.profe_semana_por_estudiante_tope
    if not reglas.cabe_en_tope(recibido, datos.monto, tope):
        raise reglas.rechazo(status.HTTP_409_CONFLICT, "tope_semanal_estudiante",
                             tope=tope, recibido=recibido)
    try:
        asiento, nuevo = await libro.transferir(
            db, tenant_id=auth.tenant_id, desde=bolsillo, hacia=alumno, monto=datos.monto,
            accion=consultas.ENTREGA, creado_por=auth.profile_id, llave=llave,
            metadata={"reason": datos.motivo, "note": datos.nota, "group_id": str(grupo.id)})
    except libro.SaldoInsuficiente as exc:
        raise reglas.rechazo(status.HTTP_402_PAYMENT_REQUIRED, "presupuesto_insuficiente",
                             saldo=exc.saldo) from exc
    return _salida_dar(asiento, sid, bolsillo, recibido + datos.monto), nuevo


async def _entrega_propia(db: AsyncSession, auth: AuthContext, entry_id: UUID) -> CoinLedger:
    """Una entrega `teacher_award` de ESTE profe en SU institución; si no, 404."""
    stmt = select(CoinLedger).where(
        CoinLedger.id == entry_id,
        CoinLedger.tenant_id == auth.tenant_id,
        CoinLedger.action == consultas.ENTREGA,
        CoinLedger.created_by_profile_id == auth.profile_id,
    )
    entrada = (await db.execute(stmt)).scalar_one_or_none()
    if entrada is None:
        raise reglas.rechazo(status.HTTP_404_NOT_FOUND, "entrega_no_encontrada")
    return entrada


async def _cuanto_corregir(db: AsyncSession, auth: AuthContext, entrada: CoinLedger,
                           pedido: int | None) -> tuple[int, int]:
    """(monto a corregir, lo que quedaría corregible) o el 409 que toque."""
    if not reglas.dentro_del_plazo(entrada.created_at, consultas.ahora(),
                                   settings.corregir_plazo_dias):
        raise reglas.rechazo(status.HTTP_409_CONFLICT, "plazo_vencido",
                             dias=settings.corregir_plazo_dias)
    ya = await consultas.ya_corregido(db, auth.tenant_id, entrada.id)
    restante = reglas.corregible(int(entrada.amount), ya)
    if restante == 0:
        raise reglas.rechazo(status.HTTP_409_CONFLICT, "ya_corregida")
    monto = restante if pedido is None else pedido
    if monto > restante:
        raise reglas.rechazo(status.HTTP_409_CONFLICT, "excede_original", maximo=restante)
    return monto, restante - monto


async def corregir(db: AsyncSession, auth: AuthContext,
                   datos: CorregirIn) -> tuple[CorregirOut, bool]:
    """Asiento inverso de una entrega propia: del estudiante al bolsillo de origen."""
    entrada = await _entrega_propia(db, auth, datos.entrega_id)
    bolsillo = await libro.billetera_por_id(db, entrada.from_wallet_id, bloquear=True)
    alumno = await libro.billetera_por_id(db, entrada.to_wallet_id, bloquear=True)
    llave = _llave(consultas.CORRECCION, auth, datos.llave)
    previo = await libro.asiento_por_llave(db, auth.tenant_id, llave) if llave else None
    if previo is not None:
        if (previo.ledger_metadata or {}).get("original_entry_id") != str(entrada.id):
            raise reglas.rechazo(status.HTTP_409_CONFLICT, "llave_reutilizada")
        restante = reglas.corregible(int(entrada.amount),
                                     await consultas.ya_corregido(db, auth.tenant_id, entrada.id))
        return _salida_corregir(previo, entrada, restante, bolsillo), False
    monto, restante = await _cuanto_corregir(db, auth, entrada, datos.monto)
    try:
        asiento, nuevo = await libro.transferir(
            db, tenant_id=auth.tenant_id, desde=alumno, hacia=bolsillo, monto=monto,
            accion=consultas.CORRECCION, creado_por=auth.profile_id, llave=llave,
            metadata={"original_entry_id": str(entrada.id), "note": datos.nota})
    except libro.SaldoInsuficiente as exc:
        # El estudiante ya gastó esas monedas: nunca queda en negativo.
        raise reglas.rechazo(status.HTTP_409_CONFLICT, "ya_gastado", maximo=exc.saldo) from exc
    return _salida_corregir(asiento, entrada, restante, bolsillo), nuevo


def _salida_corregir(asiento: CoinLedger, entrada: CoinLedger, restante: int,
                     bolsillo: CoinWallet) -> CorregirOut:
    return CorregirOut(correccion_id=asiento.id, entrega_id=entrada.id,
                       monto=int(asiento.amount), corregible_restante=restante,
                       presupuesto_restante=int(bolsillo.balance))
