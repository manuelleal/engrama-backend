"""Cuerpos y respuestas de `/admin/invitaciones` — `docs/ESPEC_invitar_profe.md` §3.

Estrictos y con `extra="forbid"` (WINDSURF §4). La institución NO viaja en el
cuerpo: sale siempre del token (`auth.tenant_id`).
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, Strict

_STRICT = ConfigDict(strict=True, extra="forbid")
# El id del grupo llega como texto en el JSON: estricto en todo lo demás, no aquí
# (docs/ESPEC_bug1_strict_uuid.md §1, el mismo `UUIDIn` de los otros módulos).
UUIDIn = Annotated[UUID, Strict(False)]
_SIN_ESPACIOS_AL_BORDE = r"^\S(.*\S)?$"
_FORMA_DE_CORREO = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

ENVIADA = "enviada"
ACEPTADA = "aceptada"


class InvitacionIn(BaseModel):
    """Body de `POST /admin/invitaciones`: a quién, con qué correo y a qué grupo."""

    model_config = _STRICT

    nombre: str = Field(min_length=2, max_length=120, pattern=_SIN_ESPACIOS_AL_BORDE)
    correo: str = Field(min_length=3, max_length=254, pattern=_FORMA_DE_CORREO)
    group_id: UUIDIn

    def correo_normalizado(self) -> str:
        """En minúsculas: `Profe@X.co` y `profe@x.co` son la misma invitación (GoTrue también, P8)."""
        return self.correo.lower()


class InvitacionOut(BaseModel):
    """Una invitación, como la ve el admin de SU institución (§3.2).

    No trae el id del perfil ni nada de GoTrue: el mismo cuerpo sale para un
    correo nuevo y para uno que ya tenía cuenta en otra parte (§1.3).
    """

    model_config = _STRICT

    id: int
    nombre: str
    correo: str
    group_id: UUID
    group_code: str
    estado: Literal["enviada", "aceptada"]
    enviada_en: datetime
    envios: int
