"""Reglas PURAS de la racha semanal — ESPEC_racha_semanal §1.1 a §1.3.

No toca la base, el reloj ni la configuración: recibe las fechas y los
`Umbrales`. Los números los fijó el pedagogo como juicio (dictamen 04): aquí no
hay ninguno escrito.
"""
from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta
from uuid import UUID

SEMANA = timedelta(days=7)

# De dónde vino una respuesta (dato de vigilancia; no decide nada).
ORIGEN_RETO, ORIGEN_RETO_REPETIDO, ORIGEN_REPASO, ORIGEN_EVA = (
    "reto", "reto_repetido", "repaso", "eva")


@dataclass(frozen=True)
class Umbrales:
    """Los siete números de la racha. Salen de la configuración."""

    dias_por_semana: int
    dias_protector: int
    respuestas_dia: int
    correctas_dia: int
    protector_inicial: int
    protector_tope: int
    bono_semana: int


@dataclass(frozen=True)
class Racha:
    """El estado de la racha de un estudiante en una institución."""

    racha_semanas: int
    mejor_racha: int
    semanas_cumplidas: int
    protectores: int
    ultima_semana_cerrada: date


@dataclass(frozen=True)
class Dia:
    """Lo contado en un día. `preguntas` = `{identidad: 0 | 1}` con el mejor resultado."""

    via_asistencia: bool
    respuestas: int
    correctas: int
    primeras_correctas: int
    preguntas: Mapping[str, int]
    por_origen: Mapping[str, int]


DIA_VACIO = Dia(False, 0, 0, 0, {}, {})


def lunes_de(fecha: date) -> date:
    """El lunes de la semana (lunes a domingo) de esa fecha."""
    return fecha - timedelta(days=fecha.weekday())


def llave_bono(tenant_id: UUID, profile_id: UUID, lunes: date) -> str:
    """La llave de la paga del bono: una por institución, estudiante y semana ISO."""
    anio, semana, _ = lunes.isocalendar()
    return f"semana:{tenant_id}:{profile_id}:{anio}-W{semana:02d}"


def dia_activo(dia: Dia, u: Umbrales) -> bool:
    """Asistió, o respondió suficientes preguntas y acertó suficientes. Abrir no cuenta."""
    if dia.via_asistencia:
        return True
    return dia.respuestas >= u.respuestas_dia and dia.correctas >= u.correctas_dia


def anotar_respuesta(dia: Dia, clave: str, acerto: bool, origen: str) -> Dia:
    """El día tras una respuesta. Cada pregunta cuenta UNA vez, con su mejor resultado.

    - Pregunta nueva hoy: suma una respuesta (y un acierto si acertó).
    - Ya respondida y fallada, ahora acertada: pasa a correcta (el reintento
      tras la explicación vale). `primeras_correctas` no cambia.
    - Ya correcta: nada, acierte o falle.
    """
    previa = dia.preguntas.get(clave)
    if previa is None:
        return replace(
            dia, respuestas=dia.respuestas + 1, correctas=dia.correctas + int(acerto),
            primeras_correctas=dia.primeras_correctas + int(acerto),
            preguntas={**dia.preguntas, clave: int(acerto)},
            por_origen={**dia.por_origen, origen: int(dia.por_origen.get(origen, 0)) + 1})
    if not previa and acerto:
        return replace(dia, correctas=dia.correctas + 1, preguntas={**dia.preguntas, clave: 1})
    return dia


def inicial(lunes_actual: date, u: Umbrales) -> Racha:
    """La racha de quien empieza: 0 semanas, su protector, y lo anterior ya cerrado."""
    return Racha(0, 0, 0, min(u.protector_inicial, u.protector_tope), lunes_actual - SEMANA)


def exentas_de(semana_exenta: date | Collection[date] | None) -> frozenset[date]:
    """Los lunes de las semanas que no rompen nada al cerrar: la de la membresía y
    las que tuvieron un día sin contenido (ESPEC_solo_refuerzo §1.5)."""
    if semana_exenta is None:
        return frozenset()
    if isinstance(semana_exenta, date):
        return frozenset({semana_exenta})
    return frozenset(semana_exenta)


def cerrar(racha: Racha, lunes_actual: date, activos_por_semana: Mapping[date, int],
           semana_exenta: date | Collection[date] | None, u: Umbrales) -> Racha:
    """Cierra, en orden, las semanas TERMINADAS que faltan (el cierre perezoso).

    Por cada semana no cumplida: las exentas (la de la membresía y las que
    tuvieron un día sin contenido) no cuentan; con protector se gasta uno y la
    racha queda; sin protector la racha vuelve a 0. `mejor_racha` y
    `semanas_cumplidas` no se tocan: nunca bajan. Cerrar dos veces da lo mismo.
    """
    actual, protectores = racha.racha_semanas, racha.protectores
    exentas = exentas_de(semana_exenta)
    semana = racha.ultima_semana_cerrada + SEMANA
    while semana < lunes_actual:
        cumplida = activos_por_semana.get(semana, 0) >= u.dias_por_semana
        if not cumplida and semana not in exentas:
            if protectores > 0:
                protectores -= 1
            else:
                actual = 0
        semana += SEMANA
    return replace(racha, racha_semanas=actual, protectores=protectores,
                   ultima_semana_cerrada=max(racha.ultima_semana_cerrada, lunes_actual - SEMANA))


def al_activarse_un_dia(racha: Racha, dias_activos: int, u: Umbrales) -> tuple[Racha, bool]:
    """La racha tras pasar un día a activo; `dias_activos` ya lo cuenta.

    Devuelve `(racha, ¿se cumplió la semana justo ahora?)`. Solo el día que
    LLEGA al umbral hace algo: el 4.º y el 6.º no suman nada.
    """
    cumplida = dias_activos == u.dias_por_semana
    if cumplida:
        nueva = racha.racha_semanas + 1
        racha = replace(racha, racha_semanas=nueva, semanas_cumplidas=racha.semanas_cumplidas + 1,
                        mejor_racha=max(racha.mejor_racha, nueva))
    if dias_activos == u.dias_protector:
        racha = replace(racha, protectores=min(max(racha.protectores, u.protector_tope),
                                               racha.protectores + 1))
    return racha, cumplida
