"""Schemas de la tienda, la mochila y la subasta — ESPEC_ola1_economia, ADENDA 1 §A.2 y §A.4.

Campos del contrato de la web (en español). Escalones, tipos y palabras
prohibidas NO van en el schema: los aplica `reglas.py` con su mensaje y un
tramposo puede romperlos (§3).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.bolsillo.schemas import LLAVE_PATRON

_ENTRADA = ConfigDict(extra="forbid")
_SALIDA = ConfigDict(strict=True, extra="forbid")

# Los estados internos de `inventory` y lo que ve la persona.
ESTADOS = {"pending_delivery": "por_entregar", "delivered": "entregado", "expired": "devuelto",
           "available": "por_entregar", "archived": "devuelto"}
ORIGENES = {"shop": "tienda", "auction": "subasta", "reward": "tienda"}


class ObjetoIn(BaseModel):
    model_config = _ENTRADA

    nombre: str = Field(min_length=3, max_length=60)
    descripcion: str | None = Field(default=None, max_length=200)
    tipo: str = Field(max_length=20)
    precio: int = Field(strict=True)
    existencias: int = Field(strict=True, ge=0, le=1000)
    activo: bool = True


class ObjetoPatch(BaseModel):
    model_config = _ENTRADA

    nombre: str | None = Field(default=None, min_length=3, max_length=60)
    descripcion: str | None = Field(default=None, max_length=200)
    tipo: str | None = Field(default=None, max_length=20)
    precio: int | None = Field(default=None, strict=True)
    existencias: int | None = Field(default=None, strict=True, ge=0, le=1000)
    activo: bool | None = None


class ObjetoOut(BaseModel):
    model_config = _SALIDA

    id: UUID
    nombre: str
    descripcion: str | None
    tipo: str
    precio: int
    existencias: int | None
    activo: bool
    creado_por: UUID | None


class CompraIn(BaseModel):
    model_config = _ENTRADA

    llave: str | None = Field(default=None, pattern=LLAVE_PATRON)


class ItemMochilaOut(BaseModel):
    """Una fila de la mochila. `devuelto` = no se entregó a tiempo y se devolvió lo pagado."""

    model_config = _SALIDA

    id: UUID
    objeto_id: UUID
    nombre: str
    tipo: str
    origen: str
    precio_pagado: int | None
    estado: str
    comprado_en: datetime
    entregar_antes_de: datetime
    resuelto_en: datetime | None
    estudiante_id: UUID
    estudiante_nombre: str


# ------------------------------------------------------------------ la subasta
class SubastaIn(BaseModel):
    model_config = _ENTRADA

    grupo_id: UUID
    objeto_id: UUID | None = None
    titulo: str | None = Field(default=None, min_length=3, max_length=60)
    descripcion: str | None = Field(default=None, max_length=200)
    duracion_segundos: int = Field(default=90, strict=True, ge=30, le=600)
    puja_minima: int = Field(strict=True, ge=1, le=600)


class PujaIn(BaseModel):
    model_config = _ENTRADA

    monto: int = Field(strict=True, ge=1, le=1_000_000)
    llave: str | None = Field(default=None, pattern=LLAVE_PATRON)


class SubastaOut(BaseModel):
    model_config = _SALIDA

    id: UUID
    grupo_id: UUID | None
    objeto_id: UUID | None
    titulo: str
    descripcion: str | None
    puja_minima: int
    puja_actual: int
    lider_id: UUID | None
    lider_nombre: str | None
    termina_en: datetime | None
    segundos_restantes: int
    extensiones: int
    estado: str
    ganador_id: UUID | None
    incrementos: list[int]
    creada_en: datetime
