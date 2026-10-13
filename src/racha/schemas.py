"""Esquemas de la racha semanal — ESPEC_racha_semanal §1.5. Solo salida."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

_STRICT = ConfigDict(strict=True, extra="forbid")


class DiaOut(BaseModel):
    """Un punto de la semana (de lunes a domingo)."""

    model_config = _STRICT

    fecha: date
    activo: bool
    via_asistencia: bool
    respuestas: int
    correctas: int


class SemanaOut(BaseModel):
    model_config = _STRICT

    desde: date
    hasta: date
    dias_activos: int
    meta_dias: int
    cumplida: bool
    dias_para_protector: int
    dias: list[DiaOut]


class HoyOut(BaseModel):
    """Cuánto le falta hoy para que el día cuente por respuestas."""

    model_config = _STRICT

    fecha: date
    activo: bool
    respuestas: int
    correctas: int
    meta_respuestas: int
    meta_correctas: int


class SemanaPasadaOut(BaseModel):
    model_config = _STRICT

    dias_activos: int
    cumplida: bool


class BonoOut(BaseModel):
    """El bono de ESTA semana: cuánto vale y si ya está en el libro."""

    model_config = _STRICT

    monedas: int
    pagado: bool


class RachaOut(BaseModel):
    """La llama: semanas seguidas, récord, total, protectores y la semana en curso."""

    model_config = _STRICT

    racha_semanas: int
    mejor_racha: int
    semanas_cumplidas: int
    protectores: int
    protectores_tope: int
    semana: SemanaOut
    hoy: HoyOut
    semana_pasada: SemanaPasadaOut
    bono_semana: BonoOut
