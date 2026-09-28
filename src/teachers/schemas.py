"""Schemas Pydantic de `/teachers` y `/admin` — ESPEC §2.

Pydantic v2 estricto con `extra="forbid"`, mismo patrón que los demás
dominios (WINDSURF §4). Se agrega un schema por ruta, en el orden de los
commits de la espec (§7); no se reordena entre commits.
"""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

_STRICT = ConfigDict(strict=True, extra="forbid")


# =============================================================================
# T1 — GET /teachers/groups
# =============================================================================
class GroupSummaryOut(BaseModel):
    """Un grupo visible para el docente/admin, con su cantidad de estudiantes."""

    model_config = _STRICT

    id: UUID
    group_code: str
    student_count: int


# =============================================================================
# T2 — GET /teachers/groups/{gid}/students
# =============================================================================
class ConsistencyOut(BaseModel):
    """La racha, con `label` fijo (ESPEC §2.2): nunca se presenta como desempeño."""

    model_config = _STRICT

    label: str = "constancia"
    current_streak: int


class StudentRosterOut(BaseModel):
    """Una fila del roster. SIN saldo (§2.2), sin `documento_id` ni `pin_hash`."""

    model_config = _STRICT

    profile_id: UUID
    full_name: str
    consistency: ConsistencyOut
    last_attendance_date: date | None = None


# =============================================================================
# T3 — POST /teachers/groups/{gid}/attendance-sessions
# =============================================================================
class SessionDurationIn(BaseModel):
    """Body de T3. El `group_code` NO viaja: sale de `{gid}`, ya autorizado."""

    model_config = _STRICT

    duration_minutes: int = Field(default=15, ge=1, le=180)


# =============================================================================
# M1 — POST /admin/groups
# =============================================================================
class GroupCreateIn(BaseModel):
    """Body de M1. `max_capacity` fuera de alcance más allá de guardarlo (§6)."""

    model_config = _STRICT

    group_code: str
    max_capacity: int | None = Field(default=None, ge=1)


class GroupOut(BaseModel):
    """Respuesta de M1: el grupo recién creado."""

    model_config = _STRICT

    id: UUID
    group_code: str
    max_capacity: int | None = None


# =============================================================================
# M2 — POST /admin/groups/{gid}/teachers
# =============================================================================
class TeacherAssignIn(BaseModel):
    """Body de M2: el docente se identifica por `documento_id`, como M3/M4."""

    model_config = _STRICT

    documento_id: str


class TeacherAssignOut(BaseModel):
    """Respuesta de M2. `resultado`: 'asignado' (201) o 'ya_estaba' (200)."""

    model_config = _STRICT

    teacher_id: UUID
    documento_id: str
    resultado: str


# =============================================================================
# M3 — POST /admin/groups/{gid}/students
# =============================================================================
class StudentEnrollIn(BaseModel):
    """Body de M3/M4: identidad mínima del estudiante (`app.js:3538`)."""

    model_config = _STRICT

    documento_id: str
    nombre_completo: str


class StudentEnrollOut(BaseModel):
    """Respuesta de M3. `resultado`: 'inscrito' (201) o 'ya_estaba' (200).

    Solo `profile_id`, `documento_id` y `resultado` — nada de `pin_hash`
    (ESPEC M3, "solo devuelve...").
    """

    model_config = _STRICT

    profile_id: UUID
    documento_id: str
    resultado: str


# =============================================================================
# M4 — POST /admin/groups/{gid}/students/import
# =============================================================================
class ImportResultOut(BaseModel):
    """Éxito de M4 (todas las filas del CSV, "todo o nada")."""

    model_config = _STRICT

    creados: int
    ya_estaban: int
    total: int


class ImportRowErrorOut(BaseModel):
    """Una fila rechazada — el cuerpo del 422 es `list[ImportRowErrorOut]`."""

    model_config = _STRICT

    fila: int
    motivo: str


# =============================================================================
# T5 — GET /teachers/groups/{gid}/achievement (ESPEC §2.1, corregida ERR-16)
# =============================================================================
class AchievementMethodOut(BaseModel):
    """Constante: los mismos valores en toda respuesta de T5 (§2.1)."""

    model_config = _STRICT

    window_days: int
    first_attempt_only: bool
    min_items: int
    min_challenges: int
    thresholds: dict[str, int]
    excluded_types: list[str]
    axis_mapping: str
    cefr_filter: str
    status_scope: str  # Pedagogo P1: nunca es nivel MCER del estudiante.


class AxisOut(BaseModel):
    """Un eje (Comprehension/Expression/Accuracy) para un estudiante."""

    model_config = _STRICT

    axis: str
    status: str
    label: str
    items: int
    correct: int
    challenges: int
    cefr_levels: dict[str, int]


class SkillDetailOut(BaseModel):
    """Una fila del detalle por skill (§2.1.4)."""

    model_config = _STRICT

    skill: str | None
    axis: str | None
    items: int
    correct: int


class AttemptDetailOut(BaseModel):
    """Un intento `completed` en el alcance, dentro de la ventana (§2.1)."""

    model_config = _STRICT

    challenge_id: UUID
    title: str
    skill: str | None
    score_percent: float
    is_correct: bool
    completed_at: datetime
    first_attempt: bool


class StudentAchievementOut(BaseModel):
    """Un estudiante del roster (mismo orden que T2) con su logro."""

    model_config = _STRICT

    profile_id: UUID
    full_name: str
    axes: list[AxisOut]
    skills: list[SkillDetailOut]
    unmapped_items: int
    attempts: list[AttemptDetailOut]


class AchievementOut(BaseModel):
    """Respuesta completa de T5."""

    model_config = _STRICT

    method: AchievementMethodOut
    students: list[StudentAchievementOut]
