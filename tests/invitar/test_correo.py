"""UI7 (H-8a): el correo de la invitación se valida de forma estricta — ESPEC §11.

Sin base: el esquema `InvitacionIn`. Los malos son errores de tecleo reales.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from src.invitar import schemas as schemas_mod

BUENOS = ["profe@uis.edu.co", "nombre.apellido+clase@colegio.edu.co", "a_b-c@sub-dominio.ejemplo.org",
          "X9@EJEMPLO.COM"]
MALOS = ["a..b@uis.edu.co", ".ana@uis.edu.co", "ana.@uis.edu.co", "ana@uis", "ana@uis.c",
         "ana@-uis.co", "ana@uis-.co", "ana@uis..co", "ana b@uis.co", "ana@@uis.co", "ana@uis.co.",
         "a" * 65 + "@uis.co", "ana@uis.c0m"]


def _pasa(correo: str) -> bool:
    try:
        schemas_mod.InvitacionIn.model_validate({"nombre": "Ana", "correo": correo,
                                                  "group_id": str(uuid4())})
    except ValidationError:
        return False
    return True


def test_ui7_correo_estricto() -> None:
    observado: dict[str, Any] = {
        "buenos_rechazados": [c for c in BUENOS if not _pasa(c)],
        "malos_aceptados": [c for c in MALOS if _pasa(c)],
    }
    assert observado == {"buenos_rechazados": [], "malos_aceptados": []}, f"UI7: {observado}"
