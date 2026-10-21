"""Schemas de Dar, Corregir y el presupuesto — ESPEC_ola1_economia, ADENDA 1 §A.3.

Los campos son los del contrato que consume la web (en español). Entradas con
`extra="forbid"` y montos enteros estrictos (un "20" en texto no se convierte).
Los topes NO van en el schema: los aplica `reglas.py` con su mensaje, y un
tramposo puede romperlos (§3).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

_ENTRADA = ConfigDict(extra="forbid")
_SALIDA = ConfigDict(strict=True, extra="forbid")

# La llave de idempotencia que manda el cliente (una por toque de botón).
LLAVE_PATRON = r"^[A-Za-z0-9_-]{8,64}$"


# --------------------------------------------------------------------- entradas
class DarIn(BaseModel):
    model_config = _ENTRADA

    student_id: UUID
    monto: int = Field(strict=True)
    motivo: str = Field(max_length=30)
    nota: str | None = Field(default=None, max_length=80)
    llave: str | None = Field(default=None, pattern=LLAVE_PATRON)


class CorregirIn(BaseModel):
    model_config = _ENTRADA

    entrega_id: UUID
    monto: int | None = Field(default=None, strict=True, ge=1)
    nota: str | None = Field(default=None, max_length=80)
    llave: str | None = Field(default=None, pattern=LLAVE_PATRON)


class MovimientoIn(BaseModel):
    """Recargar o devolver un bolsillo (el admin)."""

    model_config = _ENTRADA

    monto: int = Field(strict=True, ge=1, le=1_000_000)
    nota: str | None = Field(default=None, max_length=80)
    llave: str | None = Field(default=None, pattern=LLAVE_PATRON)


# ---------------------------------------------------------------------- salidas
class DarOut(BaseModel):
    model_config = _SALIDA

    entrega_id: UUID
    estudiante_id: UUID
    monto: int
    motivo: str
    nota: str | None
    creada_en: datetime
    presupuesto_restante: int
    recibido_semana: int
    cupo_semana: int


class CorregirOut(BaseModel):
    model_config = _SALIDA

    correccion_id: UUID
    entrega_id: UUID
    monto: int
    corregible_restante: int
    presupuesto_restante: int


class EntregaRecienteOut(BaseModel):
    model_config = _SALIDA

    entrega_id: UUID
    estudiante_id: UUID
    monto: int
    motivo: str
    creada_en: datetime
    corregible: int
    corregible_hasta: datetime


class PresupuestoOut(BaseModel):
    """`GET /economia/presupuesto`: el bolsillo propio, los topes y lo corregible."""

    model_config = _SALIDA

    saldo: int
    recargado_semana: int
    entregado_semana: int
    tope_recarga_semanal: int
    tope_por_entrega: int
    tope_semanal_por_estudiante: int
    entregas_recientes: list[EntregaRecienteOut]


class MovimientoOut(BaseModel):
    model_config = _SALIDA

    movimiento_id: UUID
    teacher_id: UUID
    monto: int
    saldo_bolsillo: int
    saldo_bolsa: int
    recargado_semana: int


class BolsilloAdminOut(BaseModel):
    model_config = _SALIDA

    teacher_id: UUID
    rol: str
    saldo: int
    recargado_semana: int
    entregado_semana: int


class PanelBolsillosOut(BaseModel):
    """`GET /admin/presupuestos`: la bolsa de la institución y cada bolsillo."""

    model_config = _SALIDA

    bolsa_saldo: int
    bolsa_emitida: int
    profes: list[BolsilloAdminOut]


class SaldoAlumnoOut(BaseModel):
    """Una fila de `GET /economia/grupo/{gid}/saldos` (aparte del roster, que no lleva saldo)."""

    model_config = _SALIDA

    estudiante_id: UUID
    nombre: str
    saldo: int
    recibido_semana: int
    cupo_semana: int
