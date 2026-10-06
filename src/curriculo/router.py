"""`GET /teachers/curriculo/nodos`: el catálogo para el selector del profe.

ESPEC_catalogo_nodos §1.4. El catálogo es el mismo para todas las
instituciones y no lleva datos de nadie; aun así pide ser docente.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.curriculo import service
from src.shared.db import get_db
from src.shared.deps import require_teacher
from src.shared.models import CurriculumNode

router = APIRouter()
_STRICT = ConfigDict(strict=True, extra="forbid")


class NodoOut(BaseModel):
    model_config = _STRICT

    id: str
    tipo: str
    nivel: str
    nombre_es: str


class CatalogoOut(BaseModel):
    model_config = _STRICT

    version: str | None
    nodos: list[NodoOut]


def nodo_a_esquema(nodo: CurriculumNode) -> NodoOut:
    return NodoOut(id=nodo.id, tipo=nodo.kind, nivel=nodo.level, nombre_es=nodo.name_es)


@router.get("/curriculo/nodos", response_model=CatalogoOut, status_code=status.HTTP_200_OK)
async def leer_catalogo(
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> CatalogoOut:
    """Los nodos vigentes del mapa cargado, ordenados por id."""
    nodos = await service.vigentes(db)
    return CatalogoOut(version=await service.version(db),
                       nodos=[nodo_a_esquema(n) for n in nodos])
