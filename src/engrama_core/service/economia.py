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


def exigir_tope_del_reto(coins_reward: int, tope: int) -> int:
    """Valida el valor de un reto NUEVO: pasar del tope es un error (el schema lo hace 422)."""
    if coins_reward > tope:
        raise ValueError(f"coins_reward no puede pasar de {tope} monedas por reto")
    return coins_reward


def recompensa_del_reto(coins_reward: int, tope: int) -> int:
    """Lo que un reto paga Y muestra: el menor entre lo guardado y el tope.

    Un reto sembrado antes del tope (o insertado a mano) puede tener más de lo
    permitido en la base; la columna no se reescribe (la casa no tiene castigos
    retroactivos), pero lo que se muestra y se paga es lo mismo: el tope.
    """
    return min(coins_reward, tope)


def cupo_por_defecto(estudiantes_activos: int, piso: int) -> int:
    """`max_winners` de un reto creado SIN indicarlo: el tamaño del grupo, con piso.

    Sin cupo indicado, el reto no debe acabarse antes de que todo el grupo lo
    intente (la moneda premia el dominio, no llegar primero). El piso evita que
    un grupo todavía vacío deje el cupo en 0 o 1.
    """
    return max(estudiantes_activos, piso)


def llave_asistencia(group_id: UUID, student_id: UUID, dia: date) -> str:
    """La llave de idempotencia de la paga de asistencia: un pago por estudiante, grupo y día.

    `dia` es el día de la INSTITUCIÓN (no el UTC). La garantía real es el UNIQUE
    `(tenant_id, idempotency_key)` de la migración 033; esta función solo fija
    qué cuenta como "el mismo pago".
    """
    return f"attendance:{group_id}:{student_id}:{dia.isoformat()}"


def llave_recarga(referencia: str) -> str:
    """La llave de idempotencia de una recarga de la bolsa: una por referencia.

    La referencia la pone el operador (el número de la orden, del recibo...).
    Con el UNIQUE `(tenant_id, idempotency_key)` de la 033, repetir la orden con
    la misma referencia no puede emitir las monedas dos veces.
    """
    return f"topup:{referencia}"


def redondear_monedas(numerador: int, denominador: int) -> int:
    """La ÚNICA forma permitida de pasar de una fracción a monedas.

    El entero más cercano a numerador/denominador, con la MITAD HACIA ARRIBA
    (2,5 -> 3; 0,5 -> 1), usando solo aritmética entera. Python tiene
    `round(2.5) == 2` (redondeo bancario) y JavaScript `Math.round(2.5) == 3`:
    el backend y la web darían monedas distintas por el mismo cálculo. Esta
    función no usa `round` ni `float`, así que da lo mismo en cualquier lenguaje
    (la web debe hacer `Math.floor((2 * n + d) / (2 * d))`).
    """
    if numerador < 0 or denominador <= 0:
        raise ValueError(f"redondear_monedas({numerador}, {denominador}): "
                         "exige numerador >= 0 y denominador > 0")
    return (2 * numerador + denominador) // (2 * denominador)
