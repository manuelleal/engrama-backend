"""El ÚNICO módulo del proceso web que usa la clave de servicio de GoTrue.

`docs/ESPEC_autorregistro.md` §1.9 (errata a `ESPEC_login_piloto.md` §1.7).
La usa para dos llamadas de la API admin y ninguna más:
  - crear la cuenta de quien se registra, con `id = profiles.id`;
  - borrarla (compensación de un registro que no terminó, o rechazo del profe).

`tests/registro/test_unit.py` (SR1) falla si la clave o el adaptador admin
aparecen en cualquier otro módulo de `src/`, salvo la CLI del operador. La
clave nunca va a una respuesta, a un error ni a un log.
"""
from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.auth.cuentas import url_de_gotrue
from src.onboarding.cuentas import GoTrueAdmin
from src.shared.config import settings

TIEMPO_MAXIMO_S = 8.0


class CuentasDeRegistro(Protocol):
    async def crear(self, id: UUID | None, correo: str, clave: str) -> str:
        """Crea la cuenta con ESE `id`. Devuelve `creada` o `correo_en_uso`."""
        ...

    async def borrar(self, id: UUID) -> None:
        """Borra la cuenta `id`. Si no existe, no es un error."""
        ...


def get_cuentas_de_registro() -> CuentasDeRegistro | None:
    """Dependencia: el adaptador real, o `None` si falta la URL o la clave (-> 503)."""
    url = url_de_gotrue(settings)
    clave = settings.supabase_service_role_key
    if not url or not clave:
        return None
    return GoTrueAdmin(url, clave, timeout=TIEMPO_MAXIMO_S)
