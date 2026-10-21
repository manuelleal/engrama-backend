"""La salida de `GET /challenges/camino` — docs/ESPEC_camino_progreso.md §1.5. Solo salida.

Sin ningún campo de monedas, ni la clave, ni las preguntas: el camino dice en
qué va el estudiante, no paga ni revela nada.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

_STRICT = ConfigDict(strict=True, extra="forbid")


class EstacionOut(BaseModel):
    """Un reto de la unidad y lo que el estudiante hizo en él."""

    model_config = _STRICT

    id: UUID
    title: str
    skill: str | None = None
    challenge_type: str
    preguntas: int
    jugada: bool
    ganada: bool
    aciertos: int | None = None  # su mejor intento cerrado; None si no cerró ninguno


class UnidadOut(BaseModel):
    model_config = _STRICT

    topic: str
    numero: int
    titulo: str | None = None  # del título que puso el sembrador; None si no calza
    estado: str  # sin_empezar | en_curso | completada | dominada
    acceso: str  # abierta | bloqueada | abierta_con_apoyo
    recomendada: bool
    atascada: bool
    estaciones_total: int
    estaciones_jugadas: int
    preguntas: int
    aciertos: int
    porcentaje: int | None = None
    empezada_en: datetime | None = None
    completada_en: datetime | None = None
    se_abre_el: datetime | None = None  # bloqueada: cuándo se abre sola si la anterior sigue en curso
    siguiente_reto: UUID | None = None
    estaciones: list[EstacionOut]


class CaminoOut(BaseModel):
    model_config = _STRICT

    nivel: str  # el nivel cuyas unidades se muestran
    nivel_de_practica: str
    con_nivel_de_set: bool
    prestado: bool  # el nivel de práctica no tiene retos y se muestra el más cercano
    umbral_completada: int
    umbral_dominada: int
    dias_atasco: int
    recomendada: str | None = None
    unidades: list[UnidadOut]
