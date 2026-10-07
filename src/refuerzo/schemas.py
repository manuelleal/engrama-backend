"""Esquemas de la cola de refuerzo — ESPEC_refuerzo §1.3 y §1.6."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, Strict

from src.challenge_engine.schemas import ChallengeQuestionOut
from src.curriculo.router import NodoOut

_STRICT = ConfigDict(strict=True, extra="forbid")
UUIDIn = Annotated[UUID, Strict(False)]


class PendienteOut(BaseModel):
    model_config = _STRICT

    entrada_id: int
    etapa: str
    nodo: NodoOut
    pregunta: ChallengeQuestionOut  # el esquema de siempre: sin clave y sin nodos


class RefuerzoOut(BaseModel):
    model_config = _STRICT

    pendientes: list[PendienteOut]
    por_repasar: int
    en_espera_de_contenido: int
    superados: int


class RespuestaIn(BaseModel):
    model_config = _STRICT

    question_id: UUIDIn
    answer: str = Field(max_length=2000)


class RespuestaOut(BaseModel):
    model_config = _STRICT

    entrada_id: int
    question_id: UUID
    is_correct: bool
    correct_answer: str
    explanation: dict[str, Any] | None = None  # llega con L1; el campo ya es del contrato
    estado: str
    proxima_fecha: datetime | None
    repetida: bool
    coins_earned: int = 0  # siempre 0: el refuerzo no paga


class MetodoOut(BaseModel):
    model_config = _STRICT

    aciertos_para_repaso: int
    dias_para_repaso: int
    pendiente_del_pedagogo: bool
    regla: str


class NodoEnColaOut(BaseModel):
    model_config = _STRICT

    nodo: NodoOut
    estado: str
    etiqueta: str
    origen: str
    fallos: int
    desde: datetime
    proxima_fecha: datetime | None


class EstudianteEnColaOut(BaseModel):
    model_config = _STRICT

    profile_id: UUID
    full_name: str
    nodos: list[NodoEnColaOut]


class PorNodoOut(BaseModel):
    model_config = _STRICT

    nodo: NodoOut
    en_refuerzo: int
    por_repasar: int
    superado: int
    en_espera_de_contenido: int


class HuecoOut(BaseModel):
    model_config = _STRICT

    nodo: NodoOut
    estudiantes_en_espera: int


class PanelOut(BaseModel):
    model_config = _STRICT

    method: MetodoOut
    estudiantes: list[EstudianteEnColaOut]
    por_nodo: list[PorNodoOut]
    huecos: list[HuecoOut]
