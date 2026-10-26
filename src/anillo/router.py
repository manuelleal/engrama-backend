"""Las dos rutas del pase acotado — `docs/ESPEC_pase_acotado.md` §1.2 y §1.3.

  - POST /anillo/pases : la web pide un pase al tocar «Clase en vivo», «Examen de
    nivel» o una herramienta de clase (guarda `user`).
  - POST /anillo/canje : EVA o SET lo cambian por el carné (sin JWT: lo autentica
    el propio pase). En el despliegue, Caddy la cierra desde afuera (404, como a
    `/events`): EVA y SET la llaman por la red interna.

Las dos respuestas llevan `Cache-Control: no-store`: un pase o un carné no se
guardan en ninguna caché.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.shared.config import settings
from src.shared.db import get_db
from src.shared.deps import get_current_user

from . import service
from .schemas import CanjeIn, CarneOut, PaseIn, PaseOut

router = APIRouter()

SIN_CACHE = "no-store"


@router.post("/pases", response_model=PaseOut, status_code=status.HTTP_201_CREATED)
async def emitir_pase(
    payload: PaseIn,
    response: Response,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaseOut:
    """Un pase de un solo uso para EVA o SET, atado a la institución activa."""
    pase = await service.emitir(db, auth, payload.audiencia)
    await db.commit()
    response.headers["Cache-Control"] = SIN_CACHE
    return PaseOut(pase=pase, audiencia=payload.audiencia,
                   expira_en_s=settings.anillo_pase_ttl_s)


@router.post("/canje", response_model=CarneOut, status_code=status.HTTP_200_OK)
async def canjear_pase(
    payload: CanjeIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> CarneOut:
    """Gasta el pase (primero, con commit) y devuelve el carné de su dueño."""
    gastado = await service.gastar(db, payload.pase, payload.audiencia)
    carne = await service.carne(db, gastado)
    response.headers["Cache-Control"] = SIN_CACHE
    return carne
