"""La ruta del profe para la cola de refuerzo — ESPEC_refuerzo §1.6.

Montado con prefijo `/teachers`. Las rutas del estudiante (`/challenges/refuerzo`)
viven en el router de retos: deben declararse antes de `/{challenge_id}`.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.refuerzo import panel
from src.refuerzo import service as refuerzo_service
from src.refuerzo.schemas import PanelOut
from src.shared.db import get_db
from src.shared.deps import require_teacher
from src.teachers.service import access as access_service

router = APIRouter()


@router.get("/groups/{gid}/refuerzo", response_model=PanelOut, status_code=status.HTTP_200_OK)
async def leer_refuerzo_del_grupo(
    gid: UUID,
    response: Response,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> PanelOut:
    """Quién refuerza qué. `only_assigned=True`: ni el admin lo ve sin el grupo. Sin caché."""
    grupo = await access_service.authorize_group(db, auth, gid, only_assigned=True)
    response.headers["Cache-Control"] = "no-store"
    return await panel.build_response(db, grupo, ahora=refuerzo_service._ahora())
