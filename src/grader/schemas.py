"""Cuerpos de `/grader` — ESPEC_grader_anillo §1 y §9.3.

Todos estrictos y con `extra="forbid"`: un campo de más (por ejemplo una imagen
en base64) es un 422. El `estado` de un ítem es texto libre A PROPÓSITO: una
`dudosa` no tumba el lote con 422, rechaza SU hoja (`reglas.py`).
"""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, Strict, model_validator

_STRICT = ConfigDict(strict=True, extra="forbid")

# El JSON trae el UUID y la fecha como texto; en modo estricto no entrarían.
UUIDIn = Annotated[UUID, Strict(False)]
FechaIn = Annotated[AwareDatetime, Strict(False)]  # con zona: sin ella, 422

Codigo = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")]
Huella = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Nivel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]
GroupCode = Annotated[str, Field(min_length=1, max_length=64)]
ItemId = Annotated[str, Field(min_length=1, max_length=128)]
NodoId = Annotated[str, Field(min_length=1, max_length=128)]

MAX_ITEMS = 200
MAX_HOJAS = 200
MAX_NODOS_POR_ITEM = 8


class ItemExamenIn(BaseModel):
    model_config = _STRICT

    item_id: ItemId
    origen: Literal["oficial", "docente"]
    nivel: Nivel
    destreza: str = Field(min_length=1, max_length=64)
    tema: str = Field(max_length=256)
    enunciado: str = Field(min_length=1, max_length=4000)
    correcta_texto: str = Field(max_length=4000)
    explicacion: str = Field(max_length=4000)
    # Los nodos del mapa que practica el ítem (decisión 012 §6). Opcional.
    nodos: list[NodoId] = Field(default_factory=list, max_length=MAX_NODOS_POR_ITEM)


class ExamenIn(BaseModel):
    model_config = _STRICT

    codigo: Codigo
    huella: Huella
    titulo: str = Field(min_length=1, max_length=200)
    nivel: Nivel
    group_code: GroupCode
    n_items: int = Field(ge=1, le=MAX_ITEMS)
    items: list[ItemExamenIn] = Field(min_length=1, max_length=MAX_ITEMS)

    @model_validator(mode="after")
    def _items_coherentes(self) -> ExamenIn:
        if self.n_items != len(self.items):
            raise ValueError("n_items no coincide con la cantidad de items")
        ids = [i.item_id for i in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("item_id repetido")
        return self


class ExamenOut(BaseModel):
    model_config = _STRICT

    codigo: str
    huella: str
    group_code: str
    n_items: int
    creado: bool


class EstudianteNumeradoOut(BaseModel):
    model_config = _STRICT

    numero: int
    student_id: UUID
    full_name: str


class ListaOut(BaseModel):
    model_config = _STRICT

    group_code: str
    estudiantes: list[EstudianteNumeradoOut]


class ItemHojaIn(BaseModel):
    model_config = _STRICT

    item_id: ItemId
    estado: str = Field(min_length=1, max_length=16)
    correcta: bool
    elegida_texto: str | None = Field(default=None, max_length=1000)
    resuelta_por: UUIDIn | None = None


class HojaIn(BaseModel):
    model_config = _STRICT

    event_id: str = Field(min_length=1, max_length=128)
    numero: int
    forma: str = Field(min_length=1, max_length=8)
    calificado_en: FechaIn
    items: list[ItemHojaIn] = Field(max_length=MAX_ITEMS)
    aciertos: int
    total: int


class ResultadosIn(BaseModel):
    model_config = _STRICT

    codigo: Codigo
    huella: Huella
    group_code: GroupCode
    hojas: list[HojaIn] = Field(min_length=1, max_length=MAX_HOJAS)


class RechazadaOut(BaseModel):
    model_config = _STRICT

    numero: int
    motivo: str


class ResultadosOut(BaseModel):
    model_config = _STRICT

    recibidas: int
    reemplazadas: int
    rechazadas: list[RechazadaOut]
