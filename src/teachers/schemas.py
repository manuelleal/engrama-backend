"""Schemas Pydantic de `/teachers` y `/admin` — ESPEC §2.

Pydantic v2 estricto con `extra="forbid"`, mismo patrón que los demás
dominios (WINDSURF §4). Se agrega un schema por ruta, en el orden de los
commits de la espec (§7); no se reordena entre commits.
"""
from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict

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
