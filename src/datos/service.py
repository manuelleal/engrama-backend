"""Registrar y responder solicitudes sobre datos personales — `docs/ESPEC_solicitud_datos.md`.

Dos barreras, cada una en UNA función (ERR-26):
  - la del usuario: solo ve y crea las suyas (`_titular`, `del_usuario`);
  - la del admin: solo las de su institución activa (`de_la_institucion`,
    `_buscar_en_la_institucion`).

Responder NO ejecuta nada: suprimir datos es un trámite manual del operador.
Aquí solo queda quién respondió, qué y cuándo. Ninguna función hace commit.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.datos.schemas import (
    RespuestaIn,
    SolicitanteOut,
    SolicitudDatosAdminOut,
    SolicitudDatosIn,
    SolicitudDatosOut,
)
from src.shared.models import Membership, Profile, SolicitudDatos

TOPE_SIN_CERRAR = 5
SIN_CERRAR = ("abierta", "en_tramite")
DEMASIADAS = "demasiadas_solicitudes_abiertas"
CERRADA = "solicitud_cerrada"
NO_ENCONTRADA = "Solicitud not found"


def a_schema(fila: SolicitudDatos) -> SolicitudDatosOut:
    return SolicitudDatosOut(
        id=fila.id, tipo=fila.tipo, mensaje=fila.mensaje, estado=fila.estado,
        creada_en=fila.created_at, respuesta=fila.respuesta, respondida_en=fila.respondida_en)


async def _auditar(db: AsyncSession, auth: AuthContext, accion: str, solicitud_id: int,
                   clave: str, valor: str) -> None:
    """Una fila en `audit_logs`. El mensaje y la respuesta NO van a la auditoría."""
    await db.execute(
        text("""
            INSERT INTO audit_logs (tenant_id, user_id, action_type, result, metadata)
            VALUES (:tenant, :quien, :accion, 'success',
                    jsonb_build_object('solicitud_id', CAST(:solicitud AS bigint),
                                       CAST(:clave AS text), CAST(:valor AS text)))
        """),
        {"tenant": auth.tenant_id, "quien": auth.profile_id, "accion": accion,
         "solicitud": solicitud_id, "clave": clave, "valor": valor})


# =============================================================================
# El usuario
# =============================================================================
def _titular(auth: AuthContext) -> UUID:
    """A nombre de quién queda la solicitud: SIEMPRE la persona del token."""
    return auth.profile_id


async def crear(db: AsyncSession, auth: AuthContext, datos: SolicitudDatosIn) -> SolicitudDatos:
    """Registra la solicitud en `abierta`, con la institución activa y la fecha de la base.

    409 si la persona ya tiene `TOPE_SIN_CERRAR` sin cerrar. El perfil se
    bloquea antes de contar: dos envíos a la vez no pasan el tope.
    """
    titular = _titular(auth)
    await db.execute(select(Profile.id).where(Profile.id == titular).with_for_update())
    sin_cerrar = (await db.execute(
        select(func.count()).select_from(SolicitudDatos)
        .where(SolicitudDatos.profile_id == titular, SolicitudDatos.estado.in_(SIN_CERRAR))
    )).scalar_one()
    if sin_cerrar >= TOPE_SIN_CERRAR:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=DEMASIADAS)
    fila = SolicitudDatos(profile_id=titular, tenant_id=auth.tenant_id, tipo=datos.tipo,
                          mensaje=datos.mensaje)
    db.add(fila)
    await db.flush()
    await db.refresh(fila)
    await _auditar(db, auth, "datos_solicitud_creada", fila.id, "tipo", fila.tipo)
    return fila


async def del_usuario(db: AsyncSession, auth: AuthContext) -> list[SolicitudDatos]:
    """Las solicitudes de la persona del token, de la más nueva a la más vieja.

    De todas sus instituciones: el derecho es de la persona.
    """
    filas = await db.execute(
        select(SolicitudDatos).where(SolicitudDatos.profile_id == auth.profile_id)
        .order_by(SolicitudDatos.id.desc()))
    return list(filas.scalars().all())


# =============================================================================
# El admin de la institución
# =============================================================================
async def de_la_institucion(db: AsyncSession, auth: AuthContext,
                            estado: str | None = None) -> list[SolicitudDatosAdminOut]:
    """Las solicitudes de la institución ACTIVA del admin, con su solicitante."""
    consulta = (
        select(SolicitudDatos, Profile.documento_id, Membership.full_name)
        .outerjoin(Profile, Profile.id == SolicitudDatos.profile_id)
        .outerjoin(Membership, (Membership.profile_id == SolicitudDatos.profile_id)
                   & (Membership.tenant_id == SolicitudDatos.tenant_id))
        .where(SolicitudDatos.tenant_id == auth.tenant_id)
        .order_by(SolicitudDatos.id.desc())
    )
    if estado is not None:
        consulta = consulta.where(SolicitudDatos.estado == estado)
    return [con_solicitante(fila, documento, nombre)
            for fila, documento, nombre in (await db.execute(consulta)).all()]


def con_solicitante(fila: SolicitudDatos, documento: str | None,
                    nombre: str | None) -> SolicitudDatosAdminOut:
    solicitante = None
    if fila.profile_id is not None and documento is not None:
        solicitante = SolicitanteOut(profile_id=fila.profile_id, nombre=nombre,
                                     documento_id=documento)
    return SolicitudDatosAdminOut(**a_schema(fila).model_dump(), solicitante=solicitante)


async def _buscar_en_la_institucion(db: AsyncSession, tenant_id: UUID,
                                    solicitud_id: int) -> SolicitudDatos | None:
    """La solicitud, BLOQUEADA, solo si es de esa institución."""
    return (await db.execute(
        select(SolicitudDatos)
        .where(SolicitudDatos.id == solicitud_id, SolicitudDatos.tenant_id == tenant_id)
        .with_for_update()
    )).scalar_one_or_none()


def _anotar_respuesta(fila: SolicitudDatos, auth: AuthContext, datos: RespuestaIn) -> None:
    """El estado, la respuesta y la traza: quién (el admin del token) y cuándo (la base)."""
    fila.estado = datos.estado
    fila.respuesta = datos.respuesta
    fila.respondida_por = auth.profile_id
    fila.respondida_en = func.now()


async def responder(db: AsyncSession, auth: AuthContext, solicitud_id: int,
                    datos: RespuestaIn) -> SolicitudDatos:
    """Guarda la respuesta del admin. No toca NINGÚN otro dato.

    404 si no es de su institución (igual que si no existe); 409 si ya estaba
    cerrada: una respuesta dada no se reescribe.
    """
    fila = await _buscar_en_la_institucion(db, auth.tenant_id, solicitud_id)
    if fila is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_ENCONTRADA)
    if fila.estado not in SIN_CERRAR:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CERRADA)
    _anotar_respuesta(fila, auth, datos)
    await db.flush()
    await db.refresh(fila)
    await _auditar(db, auth, "datos_solicitud_respondida", fila.id, "estado", fila.estado)
    return fila
