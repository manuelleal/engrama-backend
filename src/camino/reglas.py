"""Reglas PURAS del camino de nivel — docs/ESPEC_camino_progreso.md §1.2 a §1.4.

No toca la base, el reloj ni la configuración: `ahora` y los números llegan
como argumentos (`Umbrales`). Los umbrales son juicio del pedagogo (ERR-16);
los 7 días del bloqueo suave los decidió Christiam (21-oct).

Lo que aquí se decide, en palabras:
  - una unidad está COMPLETADA cuando jugó todas sus estaciones y acertó el 70 %
    de sus preguntas, contando de cada estación su MEJOR intento (así cuenta la
    forma gemela del reintento: el error corregido también es aprendizaje);
  - está DOMINADA solo con evidencia demorada: respuestas a formas no vistas de
    esa unidad, 7 días o más después de completarla. Nunca por velocidad;
  - BLOQUEO SUAVE: la siguiente se abre al completar la anterior, o sola si la
    anterior lleva 7 días en curso ("abierta con apoyo"). Nadie se queda sin salida.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

SIN_EMPEZAR, EN_CURSO, COMPLETADA, DOMINADA = "sin_empezar", "en_curso", "completada", "dominada"
COMPLETAS = (COMPLETADA, DOMINADA)
ABIERTA, BLOQUEADA, CON_APOYO = "abierta", "bloqueada", "abierta_con_apoyo"
EN_PROGRESO = "in_progress"  # un intento abierto: se puede retomar aunque no queden intentos

_PREFIJO = re.compile(r"^\[[^\]]*\]\s*")  # "[BORRADOR] " delante del título
_NUMERO = re.compile(r"-u(\d+)(?:-|$)")  # "a1-u03-daily-routine" -> 3


@dataclass(frozen=True)
class Umbrales:
    """Los números del camino. Salen de la configuración (`CAMINO_*`)."""

    completada: int  # % de acierto para Completada
    dominada: int  # % de acierto en lo demorado para Dominada
    dias_atasco: int  # días en curso para abrir la siguiente con apoyo
    dias_dominio: int  # días después de completar para que una respuesta sea "demorada"
    minimo_demoradas: int  # cuántas respuestas demoradas hacen falta


@dataclass(frozen=True)
class Intento:
    """Un intento del estudiante en una estación."""

    estado: str  # in_progress | completed | abandoned
    started_at: datetime
    completed_at: datetime | None
    aciertos: int  # preguntas acertadas (solo vale si está completed)
    gano: bool


@dataclass(frozen=True)
class Estacion:
    """Un reto de la unidad, con los intentos de ESE estudiante."""

    id: str
    title: str
    skill: str | None
    tipo: str  # challenge_type
    preguntas: int
    max_intentos: int
    escrita: bool  # sus preguntas se responden escribiendo (tu_palabra)
    intentos: tuple[Intento, ...] = ()

    def _cerrados(self) -> list[Intento]:
        return [i for i in self.intentos if i.estado == "completed" and i.completed_at is not None]

    @property
    def jugada(self) -> bool:
        return bool(self._cerrados())

    @property
    def ganada(self) -> bool:
        return any(i.gano for i in self.intentos)

    @property
    def mejor(self) -> int | None:
        """Lo más que acertó en un intento cerrado (nunca más que sus preguntas); None si no cerró ninguno."""
        cerrados = self._cerrados()
        return min(max(i.aciertos for i in cerrados), self.preguntas) if cerrados else None

    @property
    def mejor_en(self) -> datetime | None:
        """Cuándo alcanzó por primera vez su mejor puntaje."""
        mejor = self.mejor
        cuando = [i.completed_at for i in self._cerrados() if min(i.aciertos, self.preguntas) == mejor]
        return min(c for c in cuando if c is not None) if cuando else None

    @property
    def puede_jugar(self) -> bool:
        """No la ganó y le quedan intentos (o tiene uno abierto para retomar)."""
        if self.ganada:
            return False
        return len(self.intentos) < self.max_intentos or any(
            i.estado == EN_PROGRESO for i in self.intentos)


@dataclass(frozen=True)
class Demorada:
    """Una respuesta a una forma gemela o de repaso de la unidad, con su hora."""

    cuando: datetime
    acerto: bool
    escrita: bool


@dataclass(frozen=True)
class EstadoDeUnidad:
    estado: str
    aciertos: int
    preguntas: int
    jugadas: int
    porcentaje: int | None
    empezada_en: datetime | None
    completada_en: datetime | None


def _alcanza(aciertos: int, total: int, umbral: int) -> bool:
    """¿`aciertos / total ≥ umbral %`? En enteros: sin redondeos de coma flotante."""
    return total > 0 and aciertos * 100 >= umbral * total


def _por_ciento(aciertos: int, total: int) -> int:
    """El porcentaje redondeado (la mitad, hacia arriba), en enteros: la guardia del redondeo
    (`tests/engrama_core/test_economia_unit.py`, UE2) no deja `round(` en `src/`."""
    return (200 * aciertos + total) // (2 * total)


def _empezada_en(estaciones: Sequence[Estacion]) -> datetime | None:
    inicios = [i.started_at for e in estaciones for i in e.intentos]
    return min(inicios) if inicios else None


def _completada(estaciones: Sequence[Estacion], aciertos: int, preguntas: int,
                u: Umbrales) -> bool:
    return bool(estaciones) and all(e.jugada for e in estaciones) and _alcanza(
        aciertos, preguntas, u.completada)


def _dominada(estaciones: Sequence[Estacion], demoradas: Sequence[Demorada],
              completada_en: datetime, u: Umbrales) -> bool:
    """Evidencia demorada (§1.3): 7 días o más después de completarla, en formas no vistas."""
    desde = completada_en + timedelta(days=u.dias_dominio)
    validas = [d for d in demoradas if d.cuando >= desde]
    if len(validas) < u.minimo_demoradas:
        return False
    if not _alcanza(sum(1 for d in validas if d.acerto), len(validas), u.dominada):
        return False
    if any(e.escrita for e in estaciones):  # con escritas en la unidad, el azar no basta
        return any(d.escrita and d.acerto for d in validas)
    return True


def estado_de(estaciones: Sequence[Estacion], demoradas: Sequence[Demorada],
              u: Umbrales) -> EstadoDeUnidad:
    """El estado de UNA unidad con lo que ese estudiante hizo en ella."""
    jugadas = [e for e in estaciones if e.jugada]
    aciertos = sum(e.mejor or 0 for e in jugadas)
    preguntas_jugadas = sum(e.preguntas for e in jugadas)
    preguntas = sum(e.preguntas for e in estaciones)
    porcentaje = _por_ciento(aciertos, preguntas_jugadas) if preguntas_jugadas else None
    empezada = _empezada_en(estaciones)
    if empezada is None:
        return EstadoDeUnidad(SIN_EMPEZAR, 0, preguntas, 0, None, None, None)
    if not _completada(estaciones, aciertos, preguntas, u):
        return EstadoDeUnidad(EN_CURSO, aciertos, preguntas, len(jugadas), porcentaje, empezada,
                              None)
    completada_en = max(e.mejor_en for e in estaciones if e.mejor_en is not None)
    estado = DOMINADA if _dominada(estaciones, demoradas, completada_en, u) else COMPLETADA
    return EstadoDeUnidad(estado, aciertos, preguntas, len(jugadas), porcentaje, empezada,
                          completada_en)


def atascada(e: EstadoDeUnidad, hay_siguiente: bool, ahora: datetime, u: Umbrales) -> bool:
    """En curso hace `dias_atasco` días o más, y con una unidad después a donde seguir."""
    return (hay_siguiente and e.estado == EN_CURSO and e.empezada_en is not None
            and ahora >= e.empezada_en + timedelta(days=u.dias_atasco))


@dataclass(frozen=True)
class Acceso:
    acceso: str
    se_abre_el: datetime | None
    atascada: bool


def accesos(estados: Sequence[EstadoDeUnidad], ahora: datetime, u: Umbrales) -> list[Acceso]:
    """El bloqueo SUAVE (§1.4), unidad por unidad, en orden."""
    salida: list[Acceso] = []
    for i, e in enumerate(estados):
        trabada = atascada(e, i + 1 < len(estados), ahora, u)
        if i == 0 or e.estado != SIN_EMPEZAR:  # la primera, o ya empezada: nunca se bloquea
            salida.append(Acceso(ABIERTA, None, trabada))
            continue
        previa = estados[i - 1]
        if previa.estado in COMPLETAS:
            salida.append(Acceso(ABIERTA, None, trabada))
        elif salida[i - 1].atascada:
            salida.append(Acceso(CON_APOYO, None, trabada))
        elif previa.estado == EN_CURSO and previa.empezada_en is not None:
            salida.append(Acceso(BLOQUEADA, previa.empezada_en + timedelta(days=u.dias_atasco),
                                 trabada))
        else:
            salida.append(Acceso(BLOQUEADA, None, trabada))
    return salida


def recomendada(estados: Sequence[EstadoDeUnidad], acc: Sequence[Acceso]) -> int | None:
    """El índice de la unidad recomendada: la primera abierta, sin completar y no atascada;
    si no hay, la primera abierta sin completar; con todo completo, ninguna."""
    abiertas = [i for i, (e, a) in enumerate(zip(estados, acc, strict=True))
                if a.acceso != BLOQUEADA and e.estado not in COMPLETAS]
    libres = [i for i in abiertas if not acc[i].atascada]
    if libres:
        return libres[0]
    return abiertas[0] if abiertas else None


def numero_de(topic: str, posicion: int) -> int:
    """El número de la unidad (`-uNN` del topic) o, si no lo trae, su posición."""
    m = _NUMERO.search(topic)
    return int(m.group(1)) if m else posicion


def titulo_de(topic: str, titulo_reto: str) -> str | None:
    """El título humano de la unidad, leído del título del reto que armó el sembrador
    (`"<topic> · <título> · <bloque> · <rol>"`). Si no calza, None: no se inventa."""
    segmentos = [s.strip() for s in _PREFIJO.sub("", titulo_reto).split(" · ")]
    if len(segmentos) >= 3 and segmentos[0] == topic and segmentos[1]:
        return segmentos[1]
    return None
