"""Las ventanas de tiempo del panel y el código neutro de un cliente. Todo puro.

Los días y las semanas son LOCALES (`settings.engrama_utc_offset_hours`, −5 en
Bogotá), como la racha y el bolsillo: el registro de las 22:00 del lunes en
Bogotá es del lunes aunque en UTC ya sea martes.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

DIAS_DE_REGISTROS = 30
SEMANAS_DE_MONEDAS = 8
HORAS_DE_ACTIVIDAD = 7 * 24


def ahora() -> datetime:
    """El reloj del panel, en un solo lugar (los tests lo pueden fijar)."""
    return datetime.now(UTC)


def hoy_local(ahora_utc: datetime, desfase_horas: int) -> date:
    return (ahora_utc + timedelta(hours=desfase_horas)).date()


def dias_de_la_ventana(hoy: date, n: int = DIAS_DE_REGISTROS) -> list[date]:
    """Los `n` días que terminan HOY, del más viejo al de hoy (hoy cuenta)."""
    return [hoy - timedelta(days=n - 1 - i) for i in range(n)]


def lunes_de(dia: date) -> date:
    return dia - timedelta(days=dia.weekday())


def semanas_de_la_ventana(hoy: date, n: int = SEMANAS_DE_MONEDAS) -> list[date]:
    """Los lunes de las `n` semanas que terminan en la actual, del más viejo al actual."""
    actual = lunes_de(hoy)
    return [actual - timedelta(weeks=n - 1 - i) for i in range(n)]


def inicio_utc(dia: date, desfase_horas: int) -> datetime:
    """El instante UTC en que empieza ese día local."""
    return datetime.combine(dia, time(0), tzinfo=UTC) - timedelta(hours=desfase_horas)


def codigo_de(puesto: int) -> str:
    """'Cliente 01': el puesto del tenant por fecha de creación. Nunca su nombre."""
    return f"Cliente {puesto:02d}"
