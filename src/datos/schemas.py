"""Esquemas de las solicitudes sobre datos personales — `docs/ESPEC_solicitud_datos.md`.

Estrictos y con `extra="forbid"`: la persona sale del token, la institución es
la activa y las fechas son del servidor. Un cuerpo con `profile_id`,
`tenant_id`, `estado` o una fecha da 422.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

_STRICT = ConfigDict(strict=True, extra="forbid")

Tipo = Literal["conocer", "actualizar", "rectificar", "suprimir"]
Estado = Literal["abierta", "en_tramite", "resuelta", "rechazada"]
# `abierta` no está: es el estado con que nace, no una respuesta.
EstadoDeRespuesta = Literal["en_tramite", "resuelta", "rechazada"]

TEXTO_MAX = 1000
# Al menos un carácter que no sea espacio (el patrón se busca, no se ancla).
_CON_ALGO = r"\S"


class SolicitudDatosIn(BaseModel):
    """Body de `POST /auth/solicitudes-datos`."""

    model_config = _STRICT

    tipo: Tipo
    mensaje: str = Field(min_length=1, max_length=TEXTO_MAX, pattern=_CON_ALGO)


class RespuestaIn(BaseModel):
    """Body de `PUT /admin/solicitudes-datos/{id}`."""

    model_config = _STRICT

    estado: EstadoDeRespuesta
    respuesta: str = Field(min_length=1, max_length=TEXTO_MAX, pattern=_CON_ALGO)


class SolicitudDatosOut(BaseModel):
    """La solicitud como la ve su dueño. Sin `respondida_por`: eso queda en la base."""

    model_config = _STRICT

    id: int
    tipo: str
    mensaje: str
    estado: str
    creada_en: datetime
    respuesta: str | None = None
    respondida_en: datetime | None = None


class SolicitanteOut(BaseModel):
    """Quién pidió, para el admin. `nombre` es el de SU institución (BUG-11)."""

    model_config = _STRICT

    profile_id: UUID
    nombre: str | None = None
    documento_id: str


class SolicitudDatosAdminOut(SolicitudDatosOut):
    """La solicitud como la ve el admin: con el solicitante (o `null` si ya no existe)."""

    solicitante: SolicitanteOut | None = None
