"""Rutas del autorregistro — `docs/ESPEC_autorregistro.md` §1.3 y §1.7.

  - `publico` (se monta en `/auth`): `POST /auth/registro`, SIN JWT.
  - `docente` (se monta en `/teachers`): el código del grupo y sus solicitudes,
    con `require_teacher` y `access.authorize_group`.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import consentimiento
from src.auth.schemas import AuthContext
from src.registro import codigos, decision, limite, service
from src.registro.cuentas import CuentasDeRegistro, get_cuentas_de_registro
from src.registro.schemas import (
    CodigoCreadoOut,
    CodigoEstadoOut,
    CodigoIn,
    DecisionOut,
    RegistroIn,
    RegistroOut,
    SolicitudOut,
)
from src.shared.config import settings
from src.shared.db import get_db
from src.shared.deps import require_teacher
from src.teachers.service import access as access_service

publico = APIRouter()
docente = APIRouter()

NO_CONFIGURADO = "registro_no_configurado"
NO_DISPONIBLE = "registro_no_disponible"
DEMASIADOS = "demasiados_intentos"


def _respuesta_uniforme(resultado: str, payload: RegistroIn) -> dict[str, Any]:
    """El cuerpo del 201. NO mira `resultado` ni `payload`, a propósito.

    Creado, código estudiantil ya ocupado o correo ya usado: la respuesta es
    la misma, para que nadie pueda preguntar si un correo tiene cuenta.
    """
    return RegistroOut().model_dump()


def _exigir_cuentas(cuentas: CuentasDeRegistro | None) -> CuentasDeRegistro:
    if cuentas is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=NO_CONFIGURADO)
    return cuentas


def _no_disponible() -> HTTPException:
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=NO_DISPONIBLE)


def _revisar_limite(request: Request, huella: str) -> str:
    """429 si algún tope ya se alcanzó; si no, anota el intento y devuelve la IP."""
    ip = limite.ip_del_visitante(request.client.host if request.client else None,
                                 request.headers.get("x-forwarded-for"),
                                 settings.proxies_de_confianza)
    espera = limite.revisar(ip, huella)
    if espera > 0:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=DEMASIADOS,
                            headers={"Retry-After": str(espera)})
    limite.anotar(ip)
    return ip


# =============================================================================
# POST /auth/registro
# =============================================================================
@publico.post("/registro", response_model=RegistroOut, status_code=status.HTTP_201_CREATED)
async def registrarse(
    payload: RegistroIn,
    request: Request,
    cuentas: CuentasDeRegistro | None = Depends(get_cuentas_de_registro),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Pide la inscripción en el grupo del código. Queda pendiente del profe.

    Orden: cuerpo (422, antes de entrar aquí) -> configuración (503) -> límite
    (429) -> código (403, un solo cuerpo) -> 201 uniforme, o 502 si GoTrue falla.
    """
    # Depende solo del cuerpo y de la configuración: va antes del límite (H-13).
    consentimiento.exigir_version_permitida(payload.aviso_version)
    listas = _exigir_cuentas(cuentas)
    huella = codigos.huella(payload.codigo)
    ip = _revisar_limite(request, huella)
    # Los contadores por código y global solo cuentan si el código de GRUPO
    # servía (auditoría 03, S-3): eso se sabe después de consultar la base.
    codigo_valido = True
    try:
        resultado = await service.registrar(db, listas, payload)
    except service.CodigoNoValido as exc:
        codigo_valido = exc.codigo_de_grupo_valido
        limite.anotar_malo(ip)
        service.logger.info("registro: código no válido (%s)", exc.motivo)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=service.detalle_de_rechazo(exc.motivo)) from exc
    except service.RegistroNoDisponible as exc:
        raise _no_disponible() from exc
    finally:
        limite.anotar_codigo(huella, valido=codigo_valido)
    return JSONResponse(status_code=status.HTTP_201_CREATED,
                        content=_respuesta_uniforme(resultado, payload))


# =============================================================================
# El código del grupo
# =============================================================================
@docente.post("/groups/{gid}/codigo-inscripcion", response_model=CodigoCreadoOut,
              status_code=status.HTTP_201_CREATED)
async def crear_codigo(
    gid: UUID,
    payload: CodigoIn | None = None,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> CodigoCreadoOut:
    """Crea el código del grupo (apaga el anterior). Es la única vez que se ve."""
    group = await access_service.authorize_group(db, auth, gid)
    datos = payload or CodigoIn()
    codigo, fila = await codigos.crear(db, group, auth.profile_id, horas=datos.horas,
                                       cupo=datos.cupo)
    await db.commit()
    return CodigoCreadoOut(codigo=codigos.mostrar(codigo), vence=fila.expires_at,
                           cupo=fila.cupo, usos=fila.usos)


@docente.get("/groups/{gid}/codigo-inscripcion", response_model=CodigoEstadoOut,
             status_code=status.HTTP_200_OK)
async def leer_codigo(
    gid: UUID,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> CodigoEstadoOut:
    """Si hay código vigente, cuándo vence y cuántos lo usaron. Nunca el código."""
    group = await access_service.authorize_group(db, auth, gid)
    actual = await codigos.estado(db, group)
    if actual is None:
        return CodigoEstadoOut(activo=False)
    fila, vigente = actual
    return CodigoEstadoOut(activo=vigente, vence=fila.expires_at, cupo=fila.cupo, usos=fila.usos)


@docente.delete("/groups/{gid}/codigo-inscripcion", status_code=status.HTTP_204_NO_CONTENT,
                response_class=Response)
async def apagar_codigo(
    gid: UUID,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Apaga el código del grupo. 204 también si no había."""
    group = await access_service.authorize_group(db, auth, gid)
    await codigos.apagar(db, group)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =============================================================================
# Las solicitudes
# =============================================================================
@docente.get("/groups/{gid}/solicitudes", response_model=list[SolicitudOut],
             status_code=status.HTTP_200_OK)
async def listar_solicitudes(
    gid: UUID,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> list[SolicitudOut]:
    group = await access_service.authorize_group(db, auth, gid)
    return await decision.listar(db, group)


@docente.post("/groups/{gid}/solicitudes/{sid}/aprobar", response_model=DecisionOut,
              status_code=status.HTTP_200_OK)
async def aprobar_solicitud(
    gid: UUID,
    sid: int,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> DecisionOut:
    group = await access_service.authorize_group(db, auth, gid)
    await decision.aprobar(db, auth, group, sid)
    await db.commit()
    return DecisionOut(id=sid, estado="aprobada")


@docente.post("/groups/{gid}/solicitudes/{sid}/rechazar", response_model=DecisionOut,
              status_code=status.HTTP_200_OK)
async def rechazar_solicitud(
    gid: UUID,
    sid: int,
    auth: AuthContext = Depends(require_teacher),
    cuentas: CuentasDeRegistro | None = Depends(get_cuentas_de_registro),
    db: AsyncSession = Depends(get_db),
) -> DecisionOut:
    group = await access_service.authorize_group(db, auth, gid)
    try:
        await decision.rechazar(db, _exigir_cuentas(cuentas), auth, group, sid)
    except service.RegistroNoDisponible as exc:
        await db.rollback()
        raise _no_disponible() from exc
    await db.commit()
    return DecisionOut(id=sid, estado="rechazada")
