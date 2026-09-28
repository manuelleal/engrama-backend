"""Schemas Pydantic de `/teachers` y `/admin` — ESPEC §2.

Pydantic v2 estricto con `extra="forbid"`, mismo patrón que los demás
dominios (WINDSURF §4). Se agrega un schema por ruta, en el orden de los
commits de la espec (§7); no se reordena entre commits.
"""
from __future__ import annotations

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
