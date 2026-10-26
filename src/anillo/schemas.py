"""Cuerpos de las dos rutas del pase acotado — `docs/ESPEC_pase_acotado.md` §1.2 y §1.3.

Estrictos y con `extra="forbid"` (WINDSURF §4): un campo de más es 422, y el
422 no devuelve lo enviado (manejador global, `src/shared/validacion.py`).
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.auth.schemas import MembershipOut

_STRICT = ConfigDict(strict=True, extra="forbid")

# Las dos piezas del anillo que reciben a alguien desde ENGRAMA.
Audiencia = Literal["eva", "set"]


class PaseIn(BaseModel):
    """`POST /anillo/pases`: para qué pieza es el pase. Nada más."""

    model_config = _STRICT

    audiencia: Audiencia


class PaseOut(BaseModel):
    """El pase y cuánto vive. Va con `Cache-Control: no-store`."""

    model_config = _STRICT

    pase: str
    audiencia: Audiencia
    expira_en_s: int


class CanjeIn(BaseModel):
    """`POST /anillo/canje`: el pase y la audiencia de QUIEN canjea (EVA o SET)."""

    model_config = _STRICT

    # 47 caracteres el bueno. El tope es el mismo que EVA y SET ya aceptan para
    # un pase (4.096): así un token de sesión (más de 200 caracteres) que llegue
    # aquí recibe el mismo 401 que cualquier pase que no existe, no un 422.
    pase: str = Field(min_length=1, max_length=4096)
    audiencia: Audiencia


class CarneOut(BaseModel):
    """La identidad mínima que EVA y SET ya leen de `/auth/me`, con los mismos nombres.

    Es un subconjunto de `ProfileOut`: EVA y SET cambian la llamada, no la lectura.
    No viajan `documento_id`, `xp`, `level`, rachas ni las otras instituciones.
    """

    model_config = _STRICT

    id: UUID
    full_name: str
    is_active: bool
    must_change_password: bool
    consent_version: str | None = None
    active_tenant_id: UUID
    # Solo la membresía de la institución del pase.
    memberships: list[MembershipOut]
    audiencia: Audiencia
    # Solo con audiencia `set` y rol `teacher`: los códigos de sus grupos.
    grupos_docente: list[str] | None = None
