"""Cuerpos y respuestas de `/admin/invitaciones` — `docs/ESPEC_invitar_profe.md` §3.

Estrictos y con `extra="forbid"` (WINDSURF §4). La institución NO viaja en el
cuerpo: sale siempre del token (`auth.tenant_id`).
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, Strict, field_validator

_STRICT = ConfigDict(strict=True, extra="forbid")
# El id del grupo llega como texto en el JSON: estricto en todo lo demás, no aquí
# (docs/ESPEC_bug1_strict_uuid.md §1, el mismo `UUIDIn` de los otros módulos).
UUIDIn = Annotated[UUID, Strict(False)]
_SIN_ESPACIOS_AL_BORDE = r"^\S(.*\S)?$"
# Correo estricto (auditoría H-8a): la parte local con los caracteres permitidos, sin
# puntos al borde ni dobles (máx. 64); el dominio con etiquetas de 1 a 63 que no
# empiezan ni terminan en guion, y un TLD de 2 o más letras. No es la RFC entera:
# es lo que un correo real de una institución cumple, y deja fuera los errores de
# tecleo más comunes ("a..b@x.co", "a@x", "a@x.c", "a b@x.co").
_LOCAL = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
_ETIQUETA = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_FORMA_DE_CORREO = rf"^{_LOCAL}@(?:{_ETIQUETA}\.)+[A-Za-z]{{2,63}}$"
LOCAL_MAX = 64  # el validador de Pydantic (Rust) no tiene lookahead: el largo va aparte

ENVIADA = "enviada"
ACEPTADA = "aceptada"


class InvitacionIn(BaseModel):
    """Body de `POST /admin/invitaciones`: a quién, con qué correo y a qué grupo."""

    model_config = _STRICT

    nombre: str = Field(min_length=2, max_length=120, pattern=_SIN_ESPACIOS_AL_BORDE)
    correo: str = Field(min_length=3, max_length=254, pattern=_FORMA_DE_CORREO)
    group_id: UUIDIn

    @field_validator("correo")
    @classmethod
    def _parte_local_corta(cls, valor: str) -> str:
        if len(valor.split("@", 1)[0]) > LOCAL_MAX:
            raise ValueError(f"la parte antes de la @ pasa de {LOCAL_MAX} caracteres")
        return valor

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
