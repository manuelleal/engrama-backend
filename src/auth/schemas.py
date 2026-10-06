"""Pydantic schemas del módulo auth (request/response + contexto interno).

Siguen las reglas de WINDSURF §4: Pydantic v2 en modo estricto con
`extra="forbid"` para atrapar payloads malformados temprano.

Fuentes de verdad:
  - SPECS/01-auth.md §2.
  - Modelos SQLAlchemy `Profile` y `Membership` en shared/models.py.
"""
from __future__ import annotations

from datetime import date, datetime
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
    # El nombre que escribió ESTA institución (BUG-11, 032). NULL en docentes
    # y admins creados antes de la espec del login piloto.
    full_name: str | None = None


class ProfileOut(BaseModel):
    """Respuesta de /auth/me y /auth/session: perfil + todas sus memberships.

    `full_name` es el de la membresía activa (ESPEC_login_piloto §1.4).
    """

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
    # El colegio que resolvió `build_auth_context` para ESTA request. Con más
    # de una membresía, el cliente manda `X-Tenant-ID` en toda llamada.
    active_tenant_id: UUID
    # `profiles.force_password_reset`: la contraseña es temporal y hay que
    # cambiarla con `POST /auth/contrasena` antes de usar el resto de la API.
    must_change_password: bool
    # La última versión del aviso de datos que aceptó esta persona, o None
    # (docs/ESPEC_consentimiento.md). El cliente la compara con su versión
    # vigente; el servidor no bloquea por esto.
    consent_version: str | None = None


class ConsentimientoIn(BaseModel):
    """Body de `POST /auth/consentimiento`: SOLO la versión del aviso.

    No hay `profile_id` ni `accepted_at` (y `extra="forbid"` los rechaza): la
    persona es la del token y la fecha es la del servidor. 1 a 32 caracteres,
    sin espacios al principio ni al final.
    """

    model_config = _STRICT

    version: str = Field(min_length=1, max_length=32, pattern=r"^\S(.*\S)?$")


class ConsentimientoOut(BaseModel):
    """Respuesta: la versión guardada y cuándo se aceptó por primera vez."""

    model_config = _STRICT

    version: str
    accepted_at: datetime


class CambioDeClaveIn(BaseModel):
    """Body de `POST /auth/contrasena`. 72 es el límite de bcrypt (en GoTrue)."""

    model_config = _STRICT

    nueva: str = Field(min_length=10, max_length=72)


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
