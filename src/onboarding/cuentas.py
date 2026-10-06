"""Puerto hacia la API ADMIN de GoTrue — `docs/ESPEC_login_piloto.md` §1.1 y §1.7.

El vínculo entre la cuenta y el perfil es el `id`: la cuenta de GoTrue se crea
CON el `id` del perfil (`POST /admin/users {"id": <profiles.id>, ...}`), así
que el `sub` del JWT ES `profiles.id` y no hay nada que enlazar después.
(P0 medido: GoTrue v2.196.0 respeta el `id` que se le pasa.)

`CuentasAdmin` es el protocolo; `GoTrueAdmin`, el adaptador httpx. Los tests
usan el doble `tests/cuentas_falsas.py`.

La clave de servicio (`SUPABASE_SERVICE_ROLE_KEY`) la usa esta CLI, desde el
entorno del operador. En el proceso web la usa UN solo módulo,
`src/registro/cuentas.py`, para el autorregistro (ESPEC_autorregistro §1.9).
Nunca se escribe en un archivo, en el resumen ni en un mensaje de error.
"""
from __future__ import annotations

import os
from typing import Protocol
from uuid import UUID

import httpx

CREADA = "creada"
CORREO_EN_USO = "correo_en_uso"


class ErrorCuenta(Exception):
    """GoTrue no hizo lo pedido. El mensaje NO lleva claves ni contraseñas."""


class ErrorDeConfiguracion(Exception):
    """Falta una variable de entorno que la CLI necesita."""


class CuentasAdmin(Protocol):
    async def buscar(self, id: UUID) -> str | None:
        """El correo de la cuenta con ese `id`, o `None` si no existe."""
        ...

    async def crear(self, id: UUID | None, correo: str, clave: str) -> str:
        """Crea la cuenta con ESE `id`. Devuelve `CREADA` o `CORREO_EN_USO`."""
        ...

    async def cambiar_clave(self, id: UUID, clave: str) -> None:
        """Pone una contraseña nueva a la cuenta `id`."""
        ...


def _codigo_de_error(r: httpx.Response) -> str:
    """El `error_code` de GoTrue si viene; nunca el cuerpo entero."""
    try:
        datos = r.json()
    except ValueError:
        return ""
    return str(datos.get("error_code") or "") if isinstance(datos, dict) else ""


class GoTrueAdmin:
    """Adaptador httpx de la API admin de GoTrue (`/admin/users`)."""

    def __init__(self, url: str, clave_de_servicio: str, *, timeout: float = 15.0) -> None:
        self.url = url.rstrip("/")
        self._cabeceras = {"Authorization": f"Bearer {clave_de_servicio}",
                           "apikey": clave_de_servicio}
        self.timeout = timeout

    async def _pedir(self, metodo: str, ruta: str, cuerpo: dict[str, object] | None = None,
                     ) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as cliente:
                return await cliente.request(metodo, f"{self.url}{ruta}",
                                             headers=self._cabeceras, json=cuerpo)
        except httpx.HTTPError as exc:
            # Solo el tipo: el texto de httpx puede traer la URL, nunca la clave.
            raise ErrorCuenta(f"GoTrue no respondió ({type(exc).__name__})") from exc

    async def buscar(self, id: UUID) -> str | None:
        r = await self._pedir("GET", f"/admin/users/{id}")
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise ErrorCuenta(f"buscar: GoTrue respondió {r.status_code} {_codigo_de_error(r)}")
        return str(r.json().get("email") or "")

    async def crear(self, id: UUID | None, correo: str, clave: str) -> str:
        cuerpo: dict[str, object] = {"email": correo, "password": clave, "email_confirm": True}
        if id is not None:
            cuerpo["id"] = str(id)
        r = await self._pedir("POST", "/admin/users", cuerpo)
        if r.status_code in (200, 201):
            creado = str(r.json().get("id") or "")
            if id is not None and creado != str(id):
                # P0 dejaría de valer: GoTrue ignoró el id. Se dice, no se calla.
                raise ErrorCuenta("crear: GoTrue no respetó el id pedido (P0)")
            return CREADA
        codigo = _codigo_de_error(r)
        if r.status_code == 422 and (codigo == "email_exists"
                                     or "already been registered" in r.text):
            return CORREO_EN_USO
        raise ErrorCuenta(f"crear: GoTrue respondió {r.status_code} {codigo}")

    async def borrar(self, id: UUID) -> None:
        """Borra la cuenta. Un 404 (no existe) cuenta como borrada: es idempotente.

        La usa solo el autorregistro: para deshacer un registro que no terminó
        y cuando el profe rechaza una solicitud (ESPEC_autorregistro §1.5 y §1.7).
        """
        r = await self._pedir("DELETE", f"/admin/users/{id}")
        if r.status_code not in (200, 204, 404):
            raise ErrorCuenta(
                f"borrar: GoTrue respondió {r.status_code} {_codigo_de_error(r)}")

    async def cambiar_clave(self, id: UUID, clave: str) -> None:
        r = await self._pedir("PUT", f"/admin/users/{id}", {"password": clave})
        if r.status_code != 200:
            raise ErrorCuenta(
                f"cambiar_clave: GoTrue respondió {r.status_code} {_codigo_de_error(r)}")


def gotrue_admin_del_entorno() -> GoTrueAdmin:
    """El adaptador real, con `GOTRUE_URL` y `SUPABASE_SERVICE_ROLE_KEY` del entorno."""
    url = os.environ.get("GOTRUE_URL", "").strip()
    clave = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    faltan = [n for n, v in (("GOTRUE_URL", url), ("SUPABASE_SERVICE_ROLE_KEY", clave)) if not v]
    if faltan:
        raise ErrorDeConfiguracion(f"faltan variables de entorno: {', '.join(faltan)}")
    return GoTrueAdmin(url, clave)
