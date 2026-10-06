"""`POST /events/batch`: la puerta de entrada del anillo — `docs/ESPEC_eventos_anillo.md` §1.1.

SIN JWT: la autentica la firma HMAC del satélite (EVA es `live`, SET es `set`).
No pasa por `get_current_user`, no mira `Authorization` ni `X-Tenant-ID`: un
estudiante con su sesión no puede escribirse monedas ni nivel.

Orden: tamaño (413) -> firma (401, un solo cuerpo) -> JSON y raíz (422) ->
cantidad de eventos (413) -> cada evento por separado (200 con el resumen).
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared import events
from src.shared.config import settings
from src.shared.db import get_db
from src.webhooks import service
from src.webhooks.schemas import MAX_BYTES, MAX_EVENTOS, LoteIn, ResumenOut

router = APIRouter()

FIRMA_INVALIDA = "invalid_signature"


def _ahora() -> float:
    return time.time()


def _secreto_de(origen: str) -> str:
    """El secreto de ese origen, o '' si el origen no existe o está apagado."""
    return {events.ORIGEN_LIVE: settings.events_secret_live,
            events.ORIGEN_SET: settings.events_secret_set}.get(origen, "")


def _no_autorizado(origen: str) -> HTTPException:
    """El MISMO 401 para todo fallo de firma: no dice cuál fue, ni nada del secreto."""
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=FIRMA_INVALIDA)


async def _leer_cuerpo(request: Request) -> bytes:
    """Los bytes exactos que viajaron; 413 si pasan de `MAX_BYTES`."""
    demasiado = HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                              detail="batch_too_large")
    declarado = request.headers.get("content-length", "")
    if declarado.isdigit() and int(declarado) > MAX_BYTES:
        raise demasiado
    cuerpo = await request.body()
    if len(cuerpo) > MAX_BYTES:
        raise demasiado
    return cuerpo


def _firma_valida(secreto: str, timestamp: str, cuerpo: bytes, firma: str) -> bool:
    return events.verificar(secreto, timestamp, cuerpo, firma, ahora=_ahora())


def _autenticar(request: Request, cuerpo: bytes) -> str:
    """El origen, si la firma es suya para ESOS bytes y dentro de la ventana; si no, 401."""
    origen = request.headers.get("x-engrama-source", "")
    timestamp = request.headers.get("x-engrama-timestamp", "")
    firma = request.headers.get("x-engrama-signature", "")
    if not _firma_valida(_secreto_de(origen), timestamp, cuerpo, firma):
        raise _no_autorizado(origen)
    return origen


def _leer_lote(cuerpo: bytes) -> LoteIn:
    """La raíz validada (422) y con a lo sumo `MAX_EVENTOS` eventos (413)."""
    try:
        lote = LoteIn.model_validate_json(cuerpo)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="invalid_batch") from exc
    if len(lote.events) > MAX_EVENTOS:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="too_many_events")
    return lote


@router.post("/batch", response_model=ResumenOut, status_code=status.HTTP_200_OK)
async def recibir_lote(request: Request, db: AsyncSession = Depends(get_db)) -> ResumenOut:
    """Recibe un lote firmado y responde, evento por evento, qué aceptó y qué no."""
    cuerpo = await _leer_cuerpo(request)
    origen = _autenticar(request, cuerpo)
    lote = _leer_lote(cuerpo)
    return await service.procesar_lote(db, origen, lote)
