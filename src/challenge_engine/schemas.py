"""Schemas Pydantic del módulo challenge_engine — SPECS/03-challenges.md §2.

Cubre dos sub-dominios: Challenges (CRUD + generación IA) y Attempts
(start/submit/history). Todos estrictos (`extra="forbid"`) per WINDSURF §4.

REGLA CRÍTICA (spec §9):
  `correct_answer` NUNCA sale en respuestas al estudiante. El único
  schema que lo contiene (`ChallengeQuestionIn`) es de entrada. Los
  schemas de salida al estudiante (`ChallengeQuestionOut`) lo omiten.
  Solo se revelan correct_answers en `AttemptSubmitOut.correct_answers`
  DESPUÉS de enviar el intento.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


_STRICT = ConfigDict(strict=True, extra="forbid")

# CEFR levels aceptados por el CHECK constraint de challenges.cefr_level.
_CEFR_LEVELS = (
    "A1", "A1+", "A2", "A2+", "B1-", "B1", "B1+", "B2", "B2+", "C1", "C1+",
)
_CHALLENGE_TYPES = ("multiple_choice", "open", "fill_blank", "listening")
_CHALLENGE_STATUSES = ("active", "inactive", "archived")


# =============================================================================
# CHALLENGES — entrada
# =============================================================================
class ChallengeQuestionIn(BaseModel):
    """Una pregunta para crear dentro de un Challenge.

    `options_json` es lista de dicts `[{label, value}, ...]` para
    multiple_choice; puede ser None en preguntas open/fill_blank.
    """

    model_config = _STRICT

    question_type: str = "multiple_choice"
    question_text: str
    options_json: list[dict[str, Any]] | None = None
    correct_answer: str
    order_index: int = Field(default=1, ge=1)


class ChallengeCreate(BaseModel):
    """Payload manual para POST /challenges/ (teacher crea un challenge)."""

    model_config = _STRICT

    title: str
    description: str
    challenge_type: str = "multiple_choice"
    cefr_level: str | None = None
    skill: str | None = None
    topic: str | None = None
    specific_instructions: str | None = None
    coins_reward: int = Field(default=10, ge=0)
    xp_reward: int = Field(default=10, ge=0)
    max_attempts: int = Field(default=2, ge=1)
    max_winners: int = Field(default=10, ge=1)
    group_id: UUID | None = None  # None = visible a todo el tenant
    questions: list[ChallengeQuestionIn] = Field(min_length=1)


class ChallengeGenerateRequest(BaseModel):
    """Payload para POST /challenges/generate (IA crea y persiste el challenge)."""

    model_config = _STRICT

    cefr_level: str
    skill: str  # grammar | vocabulary | reading | listening | writing
    topic: str
    num_questions: int = Field(default=3, ge=1, le=10)
    group_id: UUID | None = None
    specific_instructions: str | None = None


class ChallengeStatusUpdate(BaseModel):
    """Body de PATCH /challenges/{id}/status."""

    model_config = _STRICT

    status: str


# =============================================================================
# CHALLENGES — salida
# =============================================================================
class ChallengeQuestionOut(BaseModel):
    """Pregunta renderizada para el estudiante — SIN `correct_answer`.

    El valor correcto no viaja al cliente hasta que el intento se
    completa y se devuelve dentro de `AttemptSubmitOut.correct_answers`.
    """

    model_config = _STRICT

    id: UUID
    question_type: str
    question_text: str
    options_json: list[dict[str, Any]] | None = None
    order_index: int


class ChallengeOut(BaseModel):
    """Respuesta estándar de un challenge (lista o detalle)."""

    model_config = _STRICT

    id: UUID
    title: str
    description: str
    challenge_type: str
    cefr_level: str | None = None
    skill: str | None = None
    topic: str | None = None
    coins_reward: int
    xp_reward: int
    max_attempts: int
    max_winners: int
    current_winners: int
    status: str
    questions: list[ChallengeQuestionOut] = Field(default_factory=list)
    created_at: datetime


# =============================================================================
# ATTEMPTS
# =============================================================================
class AnswerSubmit(BaseModel):
    """Una respuesta del estudiante a UNA pregunta dentro de un intento."""

    model_config = _STRICT

    question_id: UUID
    answer: str


class AttemptSubmitRequest(BaseModel):
    """Body de POST /attempts/{id}/submit: todas las respuestas juntas."""

    model_config = _STRICT

    answers: list[AnswerSubmit] = Field(min_length=1)


class AttemptStartOut(BaseModel):
    """Respuesta de POST /challenges/{id}/attempt."""

    model_config = _STRICT

    attempt_id: UUID
    challenge: ChallengeOut
    attempt_number: int  # cuántos intentos lleva este estudiante con este challenge


class CorrectAnswerReveal(BaseModel):
    """Una entrada de `AttemptSubmitOut.correct_answers` (post-grading)."""

    model_config = _STRICT

    question_id: UUID
    correct_answer: str


class AttemptSubmitOut(BaseModel):
    """Resultado del submit: score, premios y revelación de respuestas correctas."""

    model_config = _STRICT

    attempt_id: UUID
    is_correct: bool
    score_percent: float
    coins_earned: int
    xp_earned: int
    streak_bonus: int
    correct_answers: list[CorrectAnswerReveal]
    drako_feedback: str | None = None
    total_attempts_used: int
    attempts_remaining: int


class AttemptHistoryOut(BaseModel):
    """Una fila de historial de intentos del estudiante."""

    model_config = _STRICT

    id: UUID
    challenge_id: UUID
    status: str
    score_percent: float
    is_correct: bool | None = None
    coins_earned: int
    xp_earned: int
    started_at: datetime
    completed_at: datetime | None = None


# Exportados para que otros módulos sepan qué valores son válidos.
CEFR_LEVELS = _CEFR_LEVELS
CHALLENGE_TYPES = _CHALLENGE_TYPES
CHALLENGE_STATUSES = _CHALLENGE_STATUSES
