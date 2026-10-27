"""El ÚNICO módulo del proceso web que usa la clave de servicio de GoTrue.

`docs/ESPEC_autorregistro.md` §1.9 (errata a `ESPEC_login_piloto.md` §1.7).
La usa para estas llamadas de la API admin y ninguna más:
  - crear la cuenta de quien se registra, con `id = profiles.id`;
  - borrarla (compensación de un registro que no terminó, o rechazo del profe);
  - invitar a un profe (`docs/ESPEC_invitar_profe.md` §3.4): mirar su cuenta por
    id, crearla sin contraseña y pedir el correo de invitación o de recuperar.
    La invitación usa la clave por este mismo módulo: la cerca (SR1) no cambia.

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


class CuentasDeInvitacion(Protocol):
    """Lo que la invitación de profes necesita de GoTrue (ESPEC_invitar_profe §3.4)."""

    async def estado_de_cuenta(self, id: UUID) -> tuple[str, bool] | None:
        """(correo, confirmada) de la cuenta `id`, o `None` si no existe."""
        ...

    async def crear_invitado(self, id: UUID, correo: str) -> str:
        """Crea la cuenta sin contraseña y sin confirmar: `creada` o `correo_en_uso`."""
        ...

    async def invitar(self, correo: str) -> str:
        """Pide el correo de invitación: `enviada`, `limite_de_correos` o `ya_confirmada`."""
        ...

    async def recuperar(self, correo: str) -> str:
        """Pide el correo de recuperar: `enviada` o `limite_de_correos`."""
        ...

    async def borrar(self, id: UUID) -> None:
        """Borra la cuenta `id` (solo al cancelar una invitación propia sin confirmar)."""
        ...


class FachadaDeInvitacion:
    """La puerta de la invitación hacia GoTrue: SOLO lo que la invitación usa (auditoría H-6).

    Envuelve el adaptador admin, que sabe más (crear con contraseña, cambiar la
    clave de cualquiera...). La ruta de invitar recibe esta fachada y no el
    adaptador: los cuatro métodos de la espec (§3.4) más `borrar`, que pide
    "Cancelar invitación" (H-4). `tests/invitar/test_adaptador.py` UI6 se pone
    rojo si expone algo más.
    """

    __slots__ = ("_admin",)

    def __init__(self, admin: GoTrueAdmin) -> None:
        self._admin = admin

    async def estado_de_cuenta(self, id: UUID) -> tuple[str, bool] | None:
        return await self._admin.estado_de_cuenta(id)

    async def crear_invitado(self, id: UUID, correo: str) -> str:
        return await self._admin.crear_invitado(id, correo)

    async def invitar(self, correo: str) -> str:
        return await self._admin.invitar(correo)

    async def recuperar(self, correo: str) -> str:
        return await self._admin.recuperar(correo)

    async def borrar(self, id: UUID) -> None:
        await self._admin.borrar(id)


def get_cuentas_de_invitacion() -> CuentasDeInvitacion | None:
    """Dependencia: la fachada sobre el adaptador real, o `None` sin URL o sin clave (-> 503)."""
    url = url_de_gotrue(settings)
    clave = settings.supabase_service_role_key
    if not url or not clave:
        return None
    return FachadaDeInvitacion(GoTrueAdmin(url, clave, timeout=TIEMPO_MAXIMO_S))
