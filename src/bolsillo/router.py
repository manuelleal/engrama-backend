"""Rutas del bolsillo — ESPEC_ola1_economia, ADENDA 1 §A.3 (contrato de la web).

Dos routers: `economia` (montado en /economia, `require_teacher`: profe o admin)
y `admin` (montado en /admin, `require_admin`). El estudiante recibe 403 en
todas. Lo ajeno (grupo, estudiante, entrega o profe de otra institución) da 404,
no 403: no se delata si existe.

Las rutas que mueven monedas responden 201 la primera vez y 200 al repetir la
misma `llave` (el mismo asiento, sin mover nada).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.bolsillo import entregas, listas, presupuesto
from src.bolsillo.schemas import (
    CorregirIn,
    CorregirOut,
    DarIn,
    DarOut,
    MovimientoIn,
    MovimientoOut,
    PanelBolsillosOut,
    PresupuestoOut,
    SaldoAlumnoOut,
)
from src.shared.db import get_db
from src.shared.deps import require_admin, require_teacher

economia = APIRouter()
admin = APIRouter()


def _codigo(response: Response, nuevo: bool) -> None:
    """201 si se movió algo; 200 si era la repetición de una llave ya usada."""
    response.status_code = status.HTTP_201_CREATED if nuevo else status.HTTP_200_OK


# ------------------------------------------------------------------ el profe
@economia.get("/presupuesto", response_model=PresupuestoOut)
async def presupuesto_propio(auth: AuthContext = Depends(require_teacher),
                             db: AsyncSession = Depends(get_db)) -> PresupuestoOut:
    return await presupuesto.mi_presupuesto(db, auth)


@economia.get("/grupo/{gid}/saldos", response_model=list[SaldoAlumnoOut])
async def saldos_grupo(gid: UUID, auth: AuthContext = Depends(require_teacher),
                       db: AsyncSession = Depends(get_db)) -> list[SaldoAlumnoOut]:
    return await listas.saldos_grupo(db, auth, gid)


@economia.post("/dar", response_model=DarOut, status_code=status.HTTP_201_CREATED)
async def dar(payload: DarIn, response: Response,
              auth: AuthContext = Depends(require_teacher),
              db: AsyncSession = Depends(get_db)) -> DarOut:
    salida, nuevo = await entregas.dar(db, auth, payload)
    await db.commit()
    _codigo(response, nuevo)
    return salida


@economia.post("/corregir", response_model=CorregirOut, status_code=status.HTTP_201_CREATED)
async def corregir(payload: CorregirIn, response: Response,
                   auth: AuthContext = Depends(require_teacher),
                   db: AsyncSession = Depends(get_db)) -> CorregirOut:
    salida, nuevo = await entregas.corregir(db, auth, payload)
    await db.commit()
    _codigo(response, nuevo)
    return salida


# ------------------------------------------------------------------ el admin
@admin.get("/presupuestos", response_model=PanelBolsillosOut)
async def presupuestos(auth: AuthContext = Depends(require_admin),
                       db: AsyncSession = Depends(get_db)) -> PanelBolsillosOut:
    return await presupuesto.panel_admin(db, auth)


@admin.post("/presupuestos/{teacher_id}/recargar", response_model=MovimientoOut,
            status_code=status.HTTP_201_CREATED)
async def recargar(teacher_id: UUID, payload: MovimientoIn, response: Response,
                   auth: AuthContext = Depends(require_admin),
                   db: AsyncSession = Depends(get_db)) -> MovimientoOut:
    salida, nuevo = await presupuesto.recargar(db, auth, teacher_id, payload)
    await db.commit()
    _codigo(response, nuevo)
    return salida


@admin.post("/presupuestos/{teacher_id}/devolver", response_model=MovimientoOut,
            status_code=status.HTTP_201_CREATED)
async def devolver(teacher_id: UUID, payload: MovimientoIn, response: Response,
                   auth: AuthContext = Depends(require_admin),
                   db: AsyncSession = Depends(get_db)) -> MovimientoOut:
    salida, nuevo = await presupuesto.devolver(db, auth, teacher_id, payload)
    await db.commit()
    _codigo(response, nuevo)
    return salida
