"""Esquemas del autorregistro — `docs/ESPEC_autorregistro.md` §1.3 y §1.7.

Pydantic estricto con `extra="forbid"`: un cuerpo con `tenant_id`, `group_id`
o `role` da 422. El grupo y la institución salen SOLO del código.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.auth import politica_clave
from src.auth.schemas import CLAVE_MAX, CLAVE_MIN

_STRICT = ConfigDict(strict=True, extra="forbid")
# bcrypt (el de GoTrue) solo mira los primeros 72 BYTES de una contraseña.
# `CLAVE_MAX` cuenta caracteres: 40 eñes son 40 caracteres y 80 bytes.
CLAVE_MAX_BYTES = CLAVE_MAX
_SIN_ESPACIOS_AL_BORDE = r"^\S(.*\S)?$"


class RegistroIn(BaseModel):
    """Body de `POST /auth/registro`.

    No hay fecha de nacimiento, teléfono ni cédula (dato mínimo). El correo no
    se guarda en la base: solo viaja a GoTrue.
    """

    model_config = _STRICT

    # Lo que no sea un código vigente da 403, no 422: aquí solo se acota el largo.
    codigo: str = Field(min_length=1, max_length=20)
    nombre: str = Field(min_length=1, max_length=120, pattern=_SIN_ESPACIOS_AL_BORDE)
    correo: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    codigo_estudiantil: str = Field(pattern=r"^[A-Za-z0-9-]{1,24}$")
    # La misma política que `POST /auth/contrasena`: una sola fuente.
    contrasena: str = Field(min_length=CLAVE_MIN, max_length=CLAVE_MAX)
    # Una declaración: solo `true`. Los menores entran por la lista de su institución.
    # `bool` estricto y no `Literal[True]`: Pydantic acepta `1` como `Literal[True]`.
    mayor_de_edad: bool
    # La versión del aviso de datos que aceptó ANTES de crear la cuenta.
    aviso_version: str = Field(min_length=1, max_length=32, pattern=_SIN_ESPACIOS_AL_BORDE)

    @field_validator("mayor_de_edad")
    @classmethod
    def _solo_mayores(cls, valor: bool) -> bool:
        if valor is not True:
            raise ValueError("el autorregistro es solo para mayores de edad")
        return valor

    @field_validator("contrasena")
    @classmethod
    def _cabe_en_bytes(cls, valor: str) -> str:
        """422 claro si pasa de 72 bytes (auditoría 03; ESPEC §11.5 a).

        Sin esto, una contraseña con tildes, eñes o emojis podía pasar el tope
        de caracteres y llegar a GoTrue, que la rechaza: el estudiante veía un
        502 ("intenta más tarde") por algo que nunca iba a funcionar.
        """
        if len(valor.encode("utf-8")) > CLAVE_MAX_BYTES:
            raise ValueError(f"la contraseña no puede pasar de {CLAVE_MAX_BYTES} bytes "
                             "(las tildes, la ñ y los emojis ocupan más de uno)")
        return valor

    @field_validator("contrasena")
    @classmethod
    def _tiene_letra_y_numero_o_simbolo(cls, valor: str) -> str:
        """422 claro si es solo letras, solo números o solo símbolos (auditoría 03, S-6).

        GoTrue aplica esta regla al CAMBIAR la contraseña, pero el registro crea
        la cuenta por la API de administración, que no la aplica: sin esto una
        contraseña de solo letras entraba (medido: 201). La regla vive en
        `auth/politica_clave.py`, una sola fuente (ESPEC §12.1). Va después del
        tope en bytes: una contraseña muy larga da primero ese error.
        """
        if not politica_clave.cumple_composicion(valor):
            raise ValueError(politica_clave.MENSAJE_COMPOSICION)
        return valor

    def correo_normalizado(self) -> str:
        return self.correo.lower()


class RegistroOut(BaseModel):
    """La única respuesta con un código válido. No trae id, correo, nombre ni grupo."""

    model_config = _STRICT

    estado: Literal["pendiente"] = "pendiente"


class CodigoIn(BaseModel):
    """Body de crear el código. Los dos campos son opcionales."""

    model_config = _STRICT

    horas: int | None = Field(default=None, ge=1, le=168)
    cupo: int | None = Field(default=None, ge=1, le=200)


class CodigoCreadoOut(BaseModel):
    """La ÚNICA respuesta que trae el código en claro."""

    model_config = _STRICT

    codigo: str
    vence: datetime
    cupo: int
    usos: int


class CodigoEstadoOut(BaseModel):
    """El estado del código del grupo. Nunca trae el código."""

    model_config = _STRICT

    activo: bool
    vence: datetime | None = None
    cupo: int | None = None
    usos: int | None = None


class SolicitudOut(BaseModel):
    """Una solicitud pendiente, como la ve el profe. Sin correo: el backend no lo guarda."""

    model_config = _STRICT

    id: int
    nombre: str
    codigo_estudiantil: str
    creada_en: datetime


class DecisionOut(BaseModel):
    model_config = _STRICT

    id: int
    estado: Literal["aprobada", "rechazada"]
