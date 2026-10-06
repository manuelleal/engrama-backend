"""La lista del profe, aprobar y rechazar — `docs/ESPEC_autorregistro.md` §1.7.

El grupo ya viene autorizado por `access.authorize_group` (la única fuente de
la barrera de grupo, ERR-26). Aquí la barrera es otra: la solicitud tiene que
ser DE ESE grupo.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.onboarding.cuentas import ErrorCuenta
from src.registro.cuentas import CuentasDeRegistro
from src.registro.schemas import SolicitudOut
from src.registro.service import RegistroNoDisponible, _borrar_cuenta
from src.shared.models import Group, Membership, Profile, SolicitudInscripcion

NO_ENCONTRADA = "Solicitud not found"


def _no_encontrada() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_ENCONTRADA)


async def listar(db: AsyncSession, group: Group) -> list[SolicitudOut]:
    """Las solicitudes `pendiente` del grupo, en orden de llegada (`id`).

    Las `creando` no salen: son registros que no terminaron y no tienen cuenta.
    """
    filas = (await db.execute(
        select(SolicitudInscripcion, Membership.full_name, Profile.documento_id)
        .join(Profile, Profile.id == SolicitudInscripcion.profile_id)
        .join(Membership, (Membership.profile_id == SolicitudInscripcion.profile_id)
              & (Membership.tenant_id == SolicitudInscripcion.tenant_id))
        .where(SolicitudInscripcion.group_id == group.id,
               SolicitudInscripcion.tenant_id == group.tenant_id,
               SolicitudInscripcion.estado == "pendiente")
        .order_by(SolicitudInscripcion.id)
    )).all()
    return [SolicitudOut(id=s.id, nombre=nombre or "", codigo_estudiantil=documento,
                         creada_en=s.created_at)
            for s, nombre, documento in filas]


async def _solicitud_del_grupo(db: AsyncSession, group: Group,
                               solicitud_id: int) -> SolicitudInscripcion | None:
    """La solicitud, BLOQUEADA, solo si es de ese grupo y de esa institución."""
    return (await db.execute(
        select(SolicitudInscripcion)
        .where(SolicitudInscripcion.id == solicitud_id,
               SolicitudInscripcion.group_id == group.id,
               SolicitudInscripcion.tenant_id == group.tenant_id)
        .with_for_update()
    )).scalar_one_or_none()


async def _auditar(db: AsyncSession, auth: AuthContext, accion: str, solicitud_id: int,
                   group_id: UUID) -> None:
    await db.execute(
        text("""
            INSERT INTO audit_logs (tenant_id, user_id, action_type, result, metadata)
            VALUES (:tenant, :quien, :accion, 'success',
                    jsonb_build_object('solicitud_id', CAST(:solicitud AS bigint),
                                       'group_id', CAST(:grupo AS text)))
        """),
        {"tenant": auth.tenant_id, "quien": auth.profile_id, "accion": accion,
         "solicitud": solicitud_id, "grupo": str(group_id)})


async def aprobar(db: AsyncSession, auth: AuthContext, group: Group, solicitud_id: int) -> None:
    """Activa la membresía y deja quién aprobó y cuándo. Repetirlo no cambia nada.

    404 si la solicitud no es de ese grupo o todavía está `creando`. No hace commit.
    """
    solicitud = await _solicitud_del_grupo(db, group, solicitud_id)
    if solicitud is None or solicitud.estado == "creando":
        raise _no_encontrada()
    if solicitud.estado == "aprobada":
        return
    await db.execute(update(Membership).where(
        Membership.tenant_id == solicitud.tenant_id,
        Membership.profile_id == solicitud.profile_id).values(is_active=True))
    await db.execute(update(SolicitudInscripcion)
                     .where(SolicitudInscripcion.id == solicitud.id)
                     .values(estado="aprobada", decidida_por=auth.profile_id,
                             decidida_en=func.now()))
    await _auditar(db, auth, "registro_aprobado", solicitud.id, group.id)


async def rechazar(db: AsyncSession, cuentas: CuentasDeRegistro, auth: AuthContext,
                   group: Group, solicitud_id: int) -> None:
    """Borra la cuenta de GoTrue y después el perfil con todo lo suyo. No hace commit.

    La cuenta va PRIMERO. Si quedara viva, quien se registró con el código
    estudiantil de un compañero conservaría la cuenta de ese documento, y el
    alta del operador no la tocaría al matricular al verdadero. Si GoTrue no
    responde -> 502 y nada cambia.
    """
    solicitud = await _solicitud_del_grupo(db, group, solicitud_id)
    if solicitud is None or solicitud.estado != "pendiente":
        raise _no_encontrada()
    try:
        await _borrar_cuenta(cuentas, solicitud.profile_id)
    except ErrorCuenta as exc:
        raise RegistroNoDisponible() from exc
    await db.execute(delete(Profile).where(Profile.id == solicitud.profile_id))
    await _auditar(db, auth, "registro_rechazado", solicitud_id, group.id)
