"""Las reglas de la economía de monedas, PURAS — ESPEC_economia_oleada0.

Este módulo no lee la base de datos ni la configuración: recibe los números
que usa y devuelve un entero. Así cada regla se prueba sola y la casa tiene UN
lugar donde mirar cuánto vale algo (REGLAS §4: `attendance.py` ya pasa de 400
líneas y no puede crecer; las reglas nuevas viven aquí).

Regla de la casa: todo monto de monedas sale de una función de este módulo.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import NamedTuple
from uuid import UUID


class DesgloseAsistencia(NamedTuple):
    """Cuánto paga un check-in y de dónde sale (el asiento lo guarda en metadata)."""

    base: int  # por asistir
    puntualidad: int  # 0, o el bono si llegó a tiempo
    puntual: bool

    @property
    def total(self) -> int:
        return self.base + self.puntualidad


def es_puntual(llegada: datetime, apertura: datetime, minutos: int) -> bool:
    """¿Llegó a `minutos` minutos o menos de que el profe abrió la sesión?

    El límite es INCLUSIVO: a los 5:00 exactos es puntual, a los 5:01 no. Un
    check-in anterior a la apertura (relojes desajustados) cuenta como puntual.
    """
    return llegada - apertura <= timedelta(minutes=minutos)


def desglose_asistencia(
    llegada: datetime, apertura: datetime, *, base: int, bono: int, minutos: int
) -> DesgloseAsistencia:
    """5 por asistir + 5 por puntualidad (los números llegan por parámetro).

    A propósito NO recibe la racha: la racha no multiplica nada (§1.1). Para que
    algún día multiplique habría que cambiar esta firma, y ese cambio se vería.
    """
    puntual = es_puntual(llegada, apertura, minutos)
    return DesgloseAsistencia(base=base, puntualidad=bono if puntual else 0, puntual=puntual)


def llave_asistencia(group_id: UUID, student_id: UUID, dia: date) -> str:
    """La llave de idempotencia de la paga de asistencia: un pago por estudiante, grupo y día.

    `dia` es el día de la INSTITUCIÓN (no el UTC). La garantía real es el UNIQUE
    `(tenant_id, idempotency_key)` de la migración 033; esta función solo fija
    qué cuenta como "el mismo pago".
    """
    return f"attendance:{group_id}:{student_id}:{dia.isoformat()}"
