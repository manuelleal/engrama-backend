"""Rutas de la tienda, la mochila y la subasta — ESPEC_ola1_economia, ADENDA 1 §A.2 y §A.4.

Dos routers:
  - `economia` (montado en /economia): la tienda, comprar, la mochila y entregar.
  - `subastas` (montado en /subastas): la puja en vivo.

Comprar responde 201 la primera vez y 200 al repetir la misma `llave`. Entregar
una compra vencida, o pujar en una subasta que ya pasó su hora, responde 409
DESPUÉS de commitear lo que eso hizo (la devolución o el cierre): por eso esas
respuestas no salen de un HTTPException, que haría rollback.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.bolsillo.reglas import MENSAJES
from src.shared.config import settings
from src.shared.db import get_db
from src.shared.deps import get_current_user, require_teacher
from src.shop import catalogo, compras, entregas, subastas
from src.shop.schemas import (
    CompraIn,
    ItemMochilaOut,
    ObjetoIn,
    ObjetoOut,
    ObjetoPatch,
    PujaIn,
    SubastaIn,
    SubastaOut,
)

economia = APIRouter()
subasta = APIRouter()


def _conflicto(code: str, **extra: object) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT,
                        content={"detail": MENSAJES[code].format(**extra)})


# ------------------------------------------------------------------ la tienda
@economia.get("/tienda", response_model=list[ObjetoOut])
async def tienda(auth: AuthContext = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)) -> list[ObjetoOut]:
    return await catalogo.listar(db, auth)


@economia.post("/tienda", response_model=ObjetoOut, status_code=status.HTTP_201_CREATED)
async def crear_objeto(payload: ObjetoIn, auth: AuthContext = Depends(require_teacher),
                       db: AsyncSession = Depends(get_db)) -> ObjetoOut:
    objeto = await catalogo.crear(db, auth, payload)
    await db.commit()
    return catalogo.objeto_out(objeto)


@economia.patch("/tienda/{item_id}", response_model=ObjetoOut)
async def editar_objeto(item_id: UUID, payload: ObjetoPatch,
                        auth: AuthContext = Depends(require_teacher),
                        db: AsyncSession = Depends(get_db)) -> ObjetoOut:
    objeto = await catalogo.editar(db, auth, item_id, payload)
    await db.commit()
    return catalogo.objeto_out(objeto)


@economia.post("/tienda/{item_id}/comprar", response_model=ItemMochilaOut,
               status_code=status.HTTP_201_CREATED)
async def comprar(item_id: UUID, response: Response, payload: CompraIn | None = None,
                  auth: AuthContext = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)) -> ItemMochilaOut:
    llave = payload.llave if payload is not None else None
    salida, nueva = await compras.comprar(db, auth, item_id, llave)
    await db.commit()
    response.status_code = status.HTTP_201_CREATED if nueva else status.HTTP_200_OK
    return salida


# ------------------------------------------------------------------ la mochila
@economia.get("/mochila", response_model=list[ItemMochilaOut])
async def mochila(auth: AuthContext = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)) -> list[ItemMochilaOut]:
    compras.exigir_estudiante(auth)
    await entregas.devolver_vencidas(db, auth.tenant_id, alumno=auth.profile_id)
    await db.commit()
    return await compras.mochila(db, auth)


@economia.get("/grupo/{gid}/mochila", response_model=list[ItemMochilaOut])
async def mochila_grupo(gid: UUID, auth: AuthContext = Depends(require_teacher),
                        db: AsyncSession = Depends(get_db)) -> list[ItemMochilaOut]:
    await entregas.devolver_vencidas(db, auth.tenant_id)
    await db.commit()
    return await compras.mochila_grupo(db, auth, gid)


@economia.post("/mochila/{inventory_id}/entregar", response_model=ItemMochilaOut)
async def entregar(inventory_id: UUID, auth: AuthContext = Depends(require_teacher),
                   db: AsyncSession = Depends(get_db)) -> ItemMochilaOut | JSONResponse:
    resultado, salida = await entregas.entregar(db, auth, inventory_id)
    await db.commit()
    if resultado == "vencida":
        return _conflicto("plazo_vencido_devuelto", dias=settings.tienda_entrega_plazo_dias)
    return salida


# ------------------------------------------------------------------ la subasta
@subasta.get("/activa", response_model=SubastaOut | None)
async def activa(grupo: str = Query(..., min_length=1, max_length=64,
                                    description="UUID del grupo o su group_code"),
                 auth: AuthContext = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)) -> SubastaOut | None:
    salida = await subastas.activa(db, auth, grupo)
    await db.commit()  # el cierre perezoso, si hubo
    return salida


@subasta.post("", response_model=SubastaOut, status_code=status.HTTP_201_CREATED)
async def crear_subasta(payload: SubastaIn, auth: AuthContext = Depends(require_teacher),
                        db: AsyncSession = Depends(get_db)) -> SubastaOut:
    salida = await subastas.crear(db, auth, payload)
    await db.commit()
    return salida


@subasta.post("/{aid}/pujar", response_model=SubastaOut)
async def pujar(aid: UUID, payload: PujaIn, auth: AuthContext = Depends(get_current_user),
                db: AsyncSession = Depends(get_db)) -> SubastaOut | JSONResponse:
    resultado, salida = await subastas.pujar(db, auth, aid, payload)
    await db.commit()
    if resultado == "cerrada":
        return _conflicto("subasta_cerrada")
    return salida


@subasta.post("/{aid}/cerrar", response_model=SubastaOut)
async def cerrar_subasta(aid: UUID, auth: AuthContext = Depends(require_teacher),
                         db: AsyncSession = Depends(get_db)) -> SubastaOut:
    salida = await subastas.cerrar_por_profe(db, auth, aid)
    await db.commit()
    return salida
