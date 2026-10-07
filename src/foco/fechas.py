"""Fechas del foco, PURAS — ESPEC_foco_grupo §1.2.

El foco va por días de calendario de la institución, no por instantes UTC: a
las 23:30 de Bogotá sigue siendo "hoy" aunque en UTC ya sea mañana.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

MAX_DIAS = 62  # lo más que puede durar un periodo (hasta − desde)
DIAS_POR_DEFECTO = 6  # sin `hasta`: una semana


def hoy(ahora_utc: datetime, desfase_horas: int) -> date:
    """El día de calendario en la hora de la institución (UTC + desfase)."""
    return (ahora_utc + timedelta(hours=desfase_horas)).date()


def se_solapan(a_desde: date, a_hasta: date, b_desde: date, b_hasta: date) -> bool:
    """Dos periodos cerrados [desde, hasta] comparten al menos un día."""
    return a_desde <= b_hasta and b_desde <= a_hasta


def hasta_por_defecto(desde: date) -> date:
    return desde + timedelta(days=DIAS_POR_DEFECTO)


def duracion_valida(desde: date, hasta: date) -> bool:
    return hasta >= desde and (hasta - desde).days <= MAX_DIAS
