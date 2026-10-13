"""Esquemas de la tanda de hoy — ESPEC_practica_y_tanda §1.2. Solo salida."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from src.challenge_engine.schemas import ChallengeOut
from src.refuerzo.schemas import PendienteOut

_STRICT = ConfigDict(strict=True, extra="forbid")


class PracticaOut(BaseModel):
    """"Practicas en: A2". NO es el nivel del estudiante ni va en el escudo."""

    model_config = _STRICT

    nivel: str
    # Falso = sin examen: la web agrega "Todavía no es tu nivel. Confírmalo con el examen".
    con_nivel_de_set: bool


class RetoDeTandaOut(BaseModel):
    model_config = _STRICT

    estado: str  # pendiente | jugado | ganado
    paga: int  # lo que pagaría ganarlo AHORA (0 si ya lo ganó)
    reto: ChallengeOut  # el esquema de siempre: sin la clave


class TandaOut(BaseModel):
    model_config = _STRICT

    numero: int
    modo: str  # nuevo | segunda_vuelta | repetir
    nivel: str
    preguntas: int
    completa: bool
    repaso: list[PendienteOut]
    retos: list[RetoDeTandaOut]


class TandaDeHoyOut(BaseModel):
    model_config = _STRICT

    fecha: date
    practica: PracticaOut
    tanda: TandaOut | None
    tandas_hoy: int
    tope_al_dia: int
    puede_pedir_otra: bool
    listo_por_hoy: bool
    sin_contenido_nuevo: bool
