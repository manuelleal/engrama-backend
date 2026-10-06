"""Esquemas de la puerta de eventos — `docs/ESPEC_eventos_anillo.md` §1.3 a §1.5.

Estrictos y con `extra="forbid"`. La raíz se valida entera (422 si no cumple);
cada evento se valida POR SEPARADO, para que uno malo sea un `invalid_event`
y no tumbe el lote.
"""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

_STRICT = ConfigDict(strict=True, extra="forbid")
_SUELTO = ConfigDict(strict=True, extra="allow")

MAX_EVENTOS = 200
MAX_BYTES = 262_144


def _uno(valor: int) -> int:
    """La única versión del esquema que existe."""
    if valor != 1:
        raise ValueError("schema_version debe ser 1")
    return valor


class LoteIn(BaseModel):
    """La raíz del lote. `events` se deja crudo: cada uno se lee aparte."""

    model_config = _STRICT

    schema_version: int
    batch_id: str = Field(min_length=1, max_length=128)
    instance: str = Field(min_length=1, max_length=64)
    session_id: str | None = Field(default=None, max_length=128)  # SET no tiene sesión
    events: list[Any] = Field(min_length=1)

    @field_validator("schema_version")
    @classmethod
    def _version_uno(cls, valor: int) -> int:
        return _uno(valor)


class EventoIn(BaseModel):
    """Los 9 campos de un evento. Ninguno es opcional (aunque dos admiten `null`)."""

    model_config = _STRICT

    event_id: str = Field(min_length=1, max_length=256)
    tenant_id: UUID
    subject_id: UUID | None
    source: str = Field(min_length=1, max_length=32)
    type: str = Field(min_length=1, max_length=64)
    item_ref: str | None = Field(min_length=1, max_length=128)
    payload: dict[str, Any]
    occurred_at: AwareDatetime
    schema_version: int

    @field_validator("schema_version")
    @classmethod
    def _version_uno(cls, valor: int) -> int:
        return _uno(valor)


class SesionPayload(BaseModel):
    """Lo mínimo de los eventos que solo se guardan: un objeto con su `session_id`."""

    model_config = _SUELTO

    session_id: str = Field(min_length=1, max_length=128)


class MonedasPayload(BaseModel):
    """`coins.granted`: todo lo que usa el efecto."""

    model_config = _STRICT

    session_id: str = Field(min_length=1, max_length=128)
    amount: int = Field(ge=1, le=20)
    reason: Literal["correct", "twin", "group_goal"]


class EvidenciaPayload(BaseModel):
    model_config = _SUELTO

    intento_id: str = Field(min_length=1, max_length=128)


class NivelPayload(BaseModel):
    """`level.assessed`: lo que usa el efecto; `cortes` y `destrezas` se guardan como llegan."""

    model_config = _SUELTO

    estado: Literal["confirmado_por_set"]
    nivel_global: Literal["A1", "A2", "B1", "B2", "C1", "C2"]
    score_total: int = Field(ge=0, le=100)
    provisional: bool
    evidencia: EvidenciaPayload


class RechazoOut(BaseModel):
    model_config = _STRICT

    event_id: str
    reason: str


class ResumenOut(BaseModel):
    """`accepted + duplicates + len(rejected) == len(events)`, siempre."""

    model_config = _STRICT

    accepted: int = 0
    duplicates: int = 0
    rejected: list[RechazoOut] = Field(default_factory=list)
    # Eventos `coins.granted` ACEPTADOS cuyas monedas no se acreditaron.
    not_credited: list[RechazoOut] = Field(default_factory=list)
