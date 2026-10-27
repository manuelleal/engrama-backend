"""Cancelar una invitación que no se aceptó — `docs/ESPEC_invitar_profe.md` §11 (H-4a).

El admin se equivocó de correo, o el profe ya no viene. Se borra todo lo que
nació con la invitación: la asignación al grupo, la membresía, el perfil y la
fila de la invitación (el UNIQUE por institución y correo queda libre).

La cuenta de GoTrue se borra SOLO si es nuestra: existe con el id del perfil de
ESTA invitación, su correo es el de la invitación y no está confirmada. Con un
correo que ya tenía cuenta en otra institución no hay cuenta con ese id: no se
toca nada en GoTrue. Si GoTrue no responde, no se borra nada (502): se reintenta.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.invitar import service
from src.onboarding.cuentas import ErrorCuenta
from src.registro.cuentas import CuentasDeInvitacion
from src.shared.models import InvitacionDocente, Profile, TeacherGroup

logger = logging.getLogger("engrama.invitar")
GOTRUE_NO_DISPONIBLE = "gotrue_no_disponible"
ACCION_CANCELAR = "invitacion_cancelada"  # otra acción: cancelar no cuenta para el tope


async def _borrar_cuenta_si_es_nuestra(cuentas: CuentasDeInvitacion, inv: InvitacionDocente) -> bool:
    """True si borró la cuenta. Nunca toca una cuenta ajena ni una ya confirmada."""
    estado = await cuentas.estado_de_cuenta(inv.profile_id)
    if estado is None:
        return False
    correo, confirmada = estado
    if correo.lower() != inv.correo or confirmada:
        return False
    await cuentas.borrar(inv.profile_id)
    return True


async def cancelar(db: AsyncSession, auth: AuthContext, invitacion_id: int,
                   cuentas: CuentasDeInvitacion) -> None:
    """404, 409 `ya_aceptada`, 502 si GoTrue falla; si no, borra todo. No hace commit."""
    actual = await service.una(db, auth, invitacion_id, para_actualizar=True)
    if actual.estado == service.ACEPTADA:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=service.YA_ACEPTADA)
    inv = (await db.execute(select(InvitacionDocente).where(
        InvitacionDocente.id == invitacion_id,
        InvitacionDocente.tenant_id == auth.tenant_id))).scalar_one()
    try:
        borro = await _borrar_cuenta_si_es_nuestra(cuentas, inv)
    except ErrorCuenta as exc:
        await db.rollback()
        logger.error("invitar: invitacion=%s no se canceló, GoTrue falló (%s)", invitacion_id, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=GOTRUE_NO_DISPONIBLE) from exc
    perfil = inv.profile_id
    await db.execute(delete(TeacherGroup).where(TeacherGroup.teacher_id == perfil,
                                                TeacherGroup.tenant_id == auth.tenant_id))
    # La membresía y la invitación caen en cascada con el perfil.
    await db.execute(delete(Profile).where(Profile.id == perfil))
    await db.execute(text("""
        INSERT INTO audit_logs (tenant_id, user_id, action_type, result, metadata)
        VALUES (:tenant, :admin, :accion, 'success',
                jsonb_build_object('invitacion_id', CAST(:inv AS bigint)))
    """), {"tenant": auth.tenant_id, "admin": auth.profile_id, "accion": ACCION_CANCELAR,
           "inv": invitacion_id})
    logger.info("invitar: invitacion=%s cancelada (cuenta borrada: %s)", invitacion_id, borro)
