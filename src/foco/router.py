"""Las rutas del profe para el foco y las etiquetas — ESPEC_foco_grupo §1.

Montado con prefijo `/teachers`. El grupo se resuelve por
`access.authorize_group`: rol equivocado, 403; grupo ajeno o inexistente, 404.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.foco import etiquetas, logro, service
from src.foco.schemas import EtiquetasIn, EtiquetasOut, FocoIn, FocoOut, FocosOut, LogroOut
from src.shared.db import get_db
from src.shared.deps import require_teacher
from src.teachers.service import access as access_service

router = APIRouter()


@router.get("/challenges/{cid}/nodos", response_model=EtiquetasOut,
            status_code=status.HTTP_200_OK)
async def leer_etiquetas(
    cid: UUID,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> EtiquetasOut:
    """Los nodos de cada pregunta del reto (para quien lo siembra y lo etiqueta)."""
    reto = await etiquetas.reto_etiquetable(db, auth, cid)
    return await etiquetas.leer(db, reto.id)


@router.put("/challenges/{cid}/nodos", response_model=EtiquetasOut,
            status_code=status.HTTP_200_OK)
async def reemplazar_etiquetas(
    cid: UUID,
    datos: EtiquetasIn,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> EtiquetasOut:
    """Reemplaza los nodos de las preguntas nombradas. Todo o nada."""
    reto = await etiquetas.reto_etiquetable(db, auth, cid)
    reto_id = reto.id
    await etiquetas.reetiquetar(db, reto, datos)
    await db.commit()
    return await etiquetas.leer(db, reto_id)


@router.put("/groups/{gid}/foco", response_model=FocoOut, status_code=status.HTTP_200_OK)
async def fijar_foco(
    gid: UUID,
    datos: FocoIn,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> FocoOut:
    """Crea o reemplaza el periodo del foco que empieza en `desde`."""
    grupo = await access_service.authorize_group(db, auth, gid)
    periodo = await service.fijar(db, grupo, auth.profile_id, datos)
    await db.commit()
    return await service.a_esquema(db, periodo, service.hoy())


@router.get("/groups/{gid}/foco", response_model=FocosOut, status_code=status.HTTP_200_OK)
async def leer_foco(
    gid: UUID,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> FocosOut:
    """Los periodos del foco del grupo y cuál está vigente hoy."""
    grupo = await access_service.authorize_group(db, auth, gid)
    dia = service.hoy()
    todos = await service.periodos(db, [grupo.id])
    vigente = service.vigente_entre(todos, dia)
    return FocosOut(
        hoy=dia, vigente=await service.a_esquema(db, vigente, dia) if vigente else None,
        periodos=[await service.a_esquema(db, p, dia) for p in todos])


@router.delete("/groups/{gid}/foco/{desde}", status_code=status.HTTP_204_NO_CONTENT)
async def borrar_foco(
    gid: UUID,
    desde: date,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Borra el periodo que empieza ese día."""
    grupo = await access_service.authorize_group(db, auth, gid)
    await service.borrar(db, grupo, desde)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/groups/{gid}/foco/logro", response_model=LogroOut,
            status_code=status.HTTP_200_OK)
async def leer_logro(
    gid: UUID,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> LogroOut:
    """El logro del grupo por nodo del foco vigente. `only_assigned=True`, como T5 y T7."""
    grupo = await access_service.authorize_group(db, auth, gid, only_assigned=True)
    return await logro.build_response(db, grupo, now=datetime.now(UTC), dia=service.hoy())
