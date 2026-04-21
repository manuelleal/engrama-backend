"""Pydantic schemas del módulo auth (request/response + contexto interno).

Siguen las reglas de WINDSURF §4: Pydantic v2 en modo estricto con
`extra="forbid"` para atrapar payloads malformados temprano.

Fuentes de verdad:
  - SPECS/01-auth.md §2.
  - Modelos SQLAlchemy `Profile` y `Membership` en shared/models.py.
"""
from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


_STRICT = ConfigDict(strict=True, extra="forbid")


class MembershipOut(BaseModel):
    """Una membresía activa del usuario en un tenant específico."""

    model_config = _STRICT

    tenant_id: UUID
    tenant_name: str
    tenant_slug: str
    role: str = Field(description="'student' | 'teacher' | 'admin' | 'super_admin'")
    group_code: str | None = None
    is_active: bool


class ProfileOut(BaseModel):
    """Respuesta de /auth/me y /auth/session: perfil + todas sus memberships."""

    model_config = _STRICT

    id: UUID
    documento_id: str
    full_name: str
    role: str
    current_streak: int
    longest_streak: int
    xp: int
    level: int
    is_active: bool
    last_attendance_date: date | None = None
    memberships: list[MembershipOut] = Field(default_factory=list)


class AuthContext(BaseModel):
    """Contexto interno inyectado en cada request autenticado.

    NO se expone vía HTTP — es el objeto que los services reciben como
    primer argumento. Contiene el tenant "activo" resuelto en `build_auth_context`.
    """

    model_config = _STRICT

    profile_id: UUID
    role: str
    tenant_id: UUID
    group_code: str | None = None
    is_teacher: bool = False
    is_admin: bool = False
