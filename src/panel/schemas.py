"""Respuestas del panel (ESPEC_panel_super_admin §1.4). Solo salida: nada entra por aquí.

`extra="forbid"` para que un campo de más (p. ej. el nombre del tenant en la
respuesta del admin) reviente al construir la respuesta en vez de salir.
"""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

_CERRADO = ConfigDict(extra="forbid")


class Monedas(BaseModel):
    model_config = _CERRADO

    bolsa: int  # saldo actual de la bolsa de la institución
    emitidas: int  # de la institución a los estudiantes, menos correcciones (§1.3)
    gastadas: int  # compras y pujas liquidadas, menos devoluciones (§1.3)


class Metricas(BaseModel):
    model_config = _CERRADO

    profes: int
    admins: int
    grupos: int
    estudiantes: int
    activos_7d: int
    registros_30d: int
    monedas: Monedas


class DiaRegistros(BaseModel):
    model_config = _CERRADO

    dia: date
    n: int


class SemanaMonedas(BaseModel):
    model_config = _CERRADO

    semana: date  # el lunes local
    emitidas: int
    gastadas: int


class Series(BaseModel):
    model_config = _CERRADO

    registros_por_dia: list[DiaRegistros]
    monedas_por_semana: list[SemanaMonedas]


class ClienteResumen(BaseModel):
    """Un cliente visto por el super admin. `etiqueta` es PRIVADA: solo sale en /super/*."""

    model_config = _CERRADO

    id: UUID
    codigo: str
    etiqueta: str
    suspendido: bool
    creado: datetime
    metricas: Metricas


class ClienteDetalle(ClienteResumen):
    registros_por_dia: list[DiaRegistros]
    monedas_por_semana: list[SemanaMonedas]


class PanelSuper(BaseModel):
    model_config = _CERRADO

    hoy: date
    totales: Metricas
    registros_por_dia: list[DiaRegistros]
    monedas_por_semana: list[SemanaMonedas]
    clientes: list[ClienteResumen]


class PanelAdmin(BaseModel):
    """El tablero del admin: SU institución, sin ningún campo de nombre ni id (§1.2)."""

    model_config = _CERRADO

    hoy: date
    metricas: Metricas
    registros_por_dia: list[DiaRegistros]
    monedas_por_semana: list[SemanaMonedas]
