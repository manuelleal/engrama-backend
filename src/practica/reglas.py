"""Reglas PURAS del nivel de práctica y de la tanda — ESPEC_practica_y_tanda §1.1 y §1.2.

No toca la base, el reloj ni la configuración: los números llegan en
`Escalera` y `Tamano`. Todos son juicio del pedagogo (dictamen 04 §1.3).

El nivel de práctica NO es el nivel del estudiante: aquí no hay nada que
escriba ni lea el nivel confirmado; solo se recibe, como `ancla`.
"""
from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypeVar

NIVELES: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1")

MODO_NUEVO, MODO_SEGUNDA_VUELTA, MODO_REPETIR = "nuevo", "segunda_vuelta", "repetir"

# El orden fijo dentro de una unidad: gramática, vocabulario y lo demás (la lectura).
_ORDEN_DESTREZA = {"grammar": 0, "vocabulary": 1}
_OTRA_DESTREZA = 2


@dataclass(frozen=True)
class Escalera:
    """Los números de la escalera. Salen de la configuración."""

    ventana: int
    sube: int
    baja: int
    ventana_rapida: int
    sube_rapida: int
    baja_rapida: int
    decisiones_rapidas: int


@dataclass(frozen=True)
class Tamano:
    """Cuánto cabe en una tanda."""

    preguntas_min: int
    retos_max: int


@dataclass(frozen=True)
class Candidato:
    """Un micro-reto que podría entrar a la tanda."""

    id: str
    topic: str | None
    skill: str | None
    title: str
    preguntas: int
    nivel: str | None = None  # de qué nivel salió (lo prestado no es del de práctica)


def base(cefr: str | None) -> str | None:
    """El nivel de práctica al que pertenece un `cefr_level` (`B1+` y `B1-` son B1; C2 es C1)."""
    if not cefr:
        return None
    nivel = cefr[:2].upper()
    if nivel == "C2":
        return "C1"
    return nivel if nivel in NIVELES else None


def limites(ancla: str | None) -> tuple[int, int]:
    """Los índices mínimo y máximo permitidos: con ancla de SET, solo ±1; siempre A1 a C1."""
    if ancla is None or ancla not in NIVELES:
        return 0, len(NIVELES) - 1
    i = NIVELES.index(ancla)
    return max(0, i - 1), min(len(NIVELES) - 1, i + 1)


def inicial(nivel_de_set: str | None, por_defecto: str) -> tuple[str, str | None]:
    """`(nivel de práctica, ancla)` de quien empieza: el de SET si existe; si no, el por defecto."""
    ancla = base(nivel_de_set)
    if ancla is not None:
        return ancla, ancla
    return (por_defecto if por_defecto in NIVELES else "A2"), None


def mover(nivel: str, pasos: int, ancla: str | None) -> str:
    """El nivel a `pasos` escalones, sin salirse de los límites."""
    minimo, maximo = limites(ancla)
    return NIVELES[max(minimo, min(maximo, NIVELES.index(nivel) + pasos))]


def otros_niveles(nivel: str) -> list[str]:
    """De dónde se PRESTA cuando el nivel no tiene nada: el más cercano primero,
    hacia abajo antes que hacia arriba (B1 → A2, A1, B2, C1)."""
    i = NIVELES.index(nivel)
    return [*reversed(NIVELES[:i]), *NIVELES[i + 1:]]


@dataclass(frozen=True)
class FormaDeReto:
    """Una pregunta de un reto `solo_refuerzo`, para decidir la segunda vuelta."""

    clave: str  # su identidad (la misma de la cola de repaso)
    familia: str | None
    rol: str | None


def elegible_segunda_vuelta(formas: Sequence[FormaDeReto], vistas: Collection[str],
                            original_jugado: Mapping[str, datetime], ahora: datetime,
                            dias: int) -> bool:
    """¿Ese reto entra a la segunda vuelta de ese estudiante? (ESPEC_solo_refuerzo §1.3)

    Todas sus preguntas son gemelas que NO ha visto, y el original de cada
    familia lo jugó (la última vez) hace `dias` o más. `original_jugado` es
    `{familia: último intento completado del original}`.
    """
    if not formas:
        return False
    for f in formas:
        if f.rol != "gemela" or f.familia is None or f.clave in vistas:
            return False
        jugado = original_jugado.get(f.familia)
        if jugado is None or ahora - jugado < timedelta(days=dias):
            return False
    return True


def ventana_vigente(ancla: str | None, decisiones: int, e: Escalera) -> tuple[int, int, int]:
    """`(tamaño, sube con, baja con)`: la rápida solo sin SET y en las primeras decisiones."""
    if ancla is None and decisiones < e.decisiones_rapidas:
        return e.ventana_rapida, e.sube_rapida, e.baja_rapida
    return e.ventana, e.sube, e.baja


def decidir(nivel: str, resultados: Sequence[bool], ancla: str | None, decisiones: int,
            e: Escalera) -> str:
    """El nivel tras mirar la ventana. `resultados`: primeros intentos, del más viejo al más nuevo.

    Solo deciden las ÚLTIMAS `ventana` respuestas, y solo con la ventana llena.
    Devuelve el mismo nivel si no hay cambio (o si el límite no lo deja).
    """
    tamano, sube, baja = ventana_vigente(ancla, decisiones, e)
    if len(resultados) < tamano:
        return nivel
    correctas = sum(1 for acerto in resultados[-tamano:] if acerto)
    if correctas >= sube:
        return mover(nivel, +1, ancla)
    if correctas <= baja:
        return mover(nivel, -1, ancla)
    return nivel


def orden_fijo(c: Candidato) -> tuple[str, int, str, str]:
    """Unidad; dentro, gramática → vocabulario → lectura; después el título."""
    return (c.topic or "", _ORDEN_DESTREZA.get(c.skill or "", _OTRA_DESTREZA), c.title, c.id)


def armar(candidatos: Iterable[Candidato], t: Tamano) -> list[Candidato]:
    """Los retos de la tanda: en orden fijo hasta sumar las preguntas mínimas, sin pasar del tope."""
    elegidos: list[Candidato] = []
    preguntas = 0
    for c in sorted(candidatos, key=orden_fijo):
        if preguntas >= t.preguntas_min or len(elegidos) >= t.retos_max:
            break
        elegidos.append(c)
        preguntas += c.preguntas
    return elegidos


T = TypeVar("T")


def primeros(cosas: Sequence[T], n: int) -> list[T]:
    """Los primeros `n` (el tope de repasos de la tanda)."""
    return list(cosas[:max(0, n)])
