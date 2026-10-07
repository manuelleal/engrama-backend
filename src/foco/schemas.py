"""Esquemas del foco del grupo y de las etiquetas de nodo — ESPEC_foco_grupo §1."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, Strict, model_validator

from src.curriculo.router import NodoOut

_STRICT = ConfigDict(strict=True, extra="forbid")

# El JSON trae el UUID y la fecha como texto; en modo estricto no entrarían.
UUIDIn = Annotated[UUID, Strict(False)]
DiaIn = Annotated[date, Strict(False)]
NodoId = Annotated[str, Field(min_length=1, max_length=128)]

MAX_NODOS_DEL_FOCO = 12
MAX_NODOS_POR_PREGUNTA = 8


class FocoIn(BaseModel):
    model_config = _STRICT

    desde: DiaIn
    hasta: DiaIn | None = None
    nodos: list[NodoId] = Field(min_length=1, max_length=MAX_NODOS_DEL_FOCO)


class FocoOut(BaseModel):
    model_config = _STRICT

    desde: date
    hasta: date
    vigente: bool
    nodos: list[NodoOut]


class FocosOut(BaseModel):
    model_config = _STRICT

    hoy: date
    vigente: FocoOut | None
    periodos: list[FocoOut]


class FocoVigenteOut(BaseModel):
    """El foco vigente tal como lo ve el estudiante (sin `vigente`: lo es)."""

    model_config = _STRICT

    desde: date
    hasta: date
    nodos: list[NodoOut]


class FocoEstudianteOut(BaseModel):
    model_config = _STRICT

    vigente: FocoVigenteOut | None
    retos_en_foco: list[UUID]


class PreguntaNodosIn(BaseModel):
    model_config = _STRICT

    question_id: UUIDIn
    nodos: list[NodoId] = Field(max_length=MAX_NODOS_POR_PREGUNTA)
    # ESPEC_refuerzo §1.2. Solo se cambian los que VIENEN en el cuerpo.
    item_ref: str | None = Field(default=None, min_length=1, max_length=128)
    familia: str | None = Field(default=None, min_length=1, max_length=128)
    rol: Literal["original", "gemela", "repaso"] | None = None


class EtiquetasIn(BaseModel):
    model_config = _STRICT

    preguntas: list[PreguntaNodosIn] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _sin_repetir(self) -> EtiquetasIn:
        ids = [p.question_id for p in self.preguntas]
        if len(set(ids)) != len(ids):
            raise ValueError("question_id repetido")
        return self


class PreguntaNodosOut(BaseModel):
    model_config = _STRICT

    question_id: UUID
    order_index: int
    nodos: list[str]
    item_ref: str | None = None
    familia: str | None = None
    rol: str | None = None


class EtiquetasOut(BaseModel):
    model_config = _STRICT

    challenge_id: UUID
    preguntas: list[PreguntaNodosOut]


class LogroMetodoOut(BaseModel):
    model_config = _STRICT

    window_days: int
    first_attempt_only: bool
    min_students: int
    min_items: int
    thresholds: dict[str, int]
    excluded_types: list[str]
    scope: str


class PeriodoOut(BaseModel):
    model_config = _STRICT

    desde: date
    hasta: date


class LogroNodoOut(BaseModel):
    model_config = _STRICT

    nodo: NodoOut
    students: int
    items: int
    correct: int
    challenges: int
    status: str
    label: str


class LogroOut(BaseModel):
    model_config = _STRICT

    method: LogroMetodoOut
    foco: PeriodoOut | None
    group_students: int
    nodos: list[LogroNodoOut]
