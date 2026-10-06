"""Rutas de las solicitudes sobre datos personales — `docs/ESPEC_solicitud_datos.md`.

  - `usuario` (se monta en `/auth`): crear la propia y ver las propias.
  - `admin` (se monta en `/admin`): las de su institución, y responderlas.

Con contraseña temporal, las cuatro dan 403 `must_change_password`, como toda
ruta fuera de las 4 permitidas (§1.6 de la espec: una solicitud hecha con una
contraseña que conoce otra persona no prueba que la hizo el titular).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.datos import service
from src.datos.schemas import (
    Estado,
    RespuestaIn,
    SolicitudDatosAdminOut,
    SolicitudDatosIn,
    SolicitudDatosOut,
)
from src.shared.db import get_db
from src.shared.deps import get_current_user, require_admin

usuario = APIRouter()
admin = APIRouter()


@usuario.post("/solicitudes-datos", response_model=SolicitudDatosOut,
              status_code=status.HTTP_201_CREATED)
async def crear_solicitud(
    payload: SolicitudDatosIn,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SolicitudDatosOut:
    """Registra una solicitud sobre los datos de quien llama. Nace `abierta`."""
    fila = await service.crear(db, auth, payload)
    await db.commit()
    return service.a_schema(fila)


@usuario.get("/solicitudes-datos", response_model=list[SolicitudDatosOut],
             status_code=status.HTTP_200_OK)
async def mis_solicitudes(
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SolicitudDatosOut]:
    """Las solicitudes de quien llama, con su estado y la respuesta si la hay."""
    return [service.a_schema(fila) for fila in await service.del_usuario(db, auth)]


@admin.get("/solicitudes-datos", response_model=list[SolicitudDatosAdminOut],
           status_code=status.HTTP_200_OK)
async def solicitudes_de_la_institucion(
    estado: Estado | None = None,
    auth: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[SolicitudDatosAdminOut]:
    """Las solicitudes de la institución activa del admin (opcional: `?estado=`)."""
    return await service.de_la_institucion(db, auth, estado)


@admin.put("/solicitudes-datos/{sid}", response_model=SolicitudDatosOut,
           status_code=status.HTTP_200_OK)
async def responder_solicitud(
    sid: int,
    payload: RespuestaIn,
    auth: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SolicitudDatosOut:
    """Responde una solicitud de su institución. Solo registra: no ejecuta nada."""
    fila = await service.responder(db, auth, sid, payload)
    await db.commit()
    return service.a_schema(fila)
