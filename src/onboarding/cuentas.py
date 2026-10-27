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
# Resultados de `invitar` y `recuperar` (docs/ESPEC_invitar_profe.md §3.4, UI2).
ENVIADA = "enviada"
LIMITE_DE_CORREOS = "limite_de_correos"
YA_CONFIRMADA = "ya_confirmada"


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

    # ---------------------------------------------- invitar profes (ESPEC_invitar_profe §3.4)
    async def estado_de_cuenta(self, id: UUID) -> tuple[str, bool] | None:
        """(correo, confirmada) de la cuenta con ese `id`, o `None` si no existe (UI3).

        "Confirmada" = GoTrue ya tiene `email_confirmed_at`: la persona canjeó un
        enlace (P4). Una cuenta invitada que no lo ha abierto lo tiene nulo (P1).
        """
        r = await self._pedir("GET", f"/admin/users/{id}")
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise ErrorCuenta(
                f"estado: GoTrue respondió {r.status_code} {_codigo_de_error(r)}")
        datos = r.json()
        return str(datos.get("email") or ""), bool(datos.get("email_confirmed_at"))

    async def crear_invitado(self, id: UUID, correo: str) -> str:
        """Crea la cuenta del profe invitado: con ESE `id`, SIN contraseña y SIN confirmar (UI1).

        Sin confirmar a propósito: GoTrue solo manda la invitación a una cuenta
        sin confirmar (P7: a una confirmada responde 422 `email_exists`). Sin
        contraseña: nadie la conoce; la pone el profe con el enlace.
        """
        r = await self._pedir("POST", "/admin/users",
                              {"id": str(id), "email": correo, "email_confirm": False})
        if r.status_code in (200, 201):
            if str(r.json().get("id") or "") != str(id):
                raise ErrorCuenta("crear_invitado: GoTrue no respetó el id pedido (P1)")
            return CREADA
        codigo = _codigo_de_error(r)
        if r.status_code == 422 and (codigo == "email_exists"
                                     or "already been registered" in r.text):
            return CORREO_EN_USO
        raise ErrorCuenta(f"crear_invitado: GoTrue respondió {r.status_code} {codigo}")

    async def invitar(self, correo: str) -> str:
        """`POST /invite`: GoTrue manda el correo de invitación con su plantilla (UI2).

        OJO (P9): a un correo SIN cuenta, `/invite` CREA la cuenta con un id que
        elige GoTrue. Por eso solo se llama después de `crear_invitado` y de
        comprobar por id que la cuenta es la de ESTA invitación (§3.4).
        """
        r = await self._pedir("POST", "/invite", {"email": correo})
        return self._resultado_de_correo(r, "invitar")

    async def recuperar(self, correo: str) -> str:
        """`POST /recover`: el correo de crear contraseña nueva (cuenta ya confirmada)."""
        r = await self._pedir("POST", "/recover", {"email": correo})
        return self._resultado_de_correo(r, "recuperar")

    @staticmethod
    def _resultado_de_correo(r: httpx.Response, que: str) -> str:
        if r.status_code == 200:
            return ENVIADA
        codigo = _codigo_de_error(r)
        if r.status_code == 429:
            return LIMITE_DE_CORREOS  # el cubo de GOTRUE_RATE_LIMIT_EMAIL_SENT (L1)
        if r.status_code == 422 and codigo == "email_exists":
            return YA_CONFIRMADA
        raise ErrorCuenta(f"{que}: GoTrue respondió {r.status_code} {codigo}")

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
