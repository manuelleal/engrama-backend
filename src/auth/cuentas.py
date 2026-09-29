"""Puerto hacia GoTrue para que el USUARIO cambie su contraseña — ESPEC_login_piloto §1.5.

`POST /auth/contrasena` no habla HTTP con GoTrue directamente: pide un
`CambioDeClave` por la dependencia `get_cambio_de_clave`. En producción es el
adaptador httpx `GoTrueCambioDeClave`; en los tests, un doble que registra las
llamadas (`app.dependency_overrides`).

Menor privilegio: se llama a `PUT /user` de GoTrue con el MISMO Bearer del
usuario (y `apikey: supabase_anon_key` si está configurada). GoTrue valida el
token por su cuenta. La clave de servicio NO se usa aquí: el proceso web no la
necesita (solo la CLI del operador, §1.7).
"""
from __future__ import annotations

from typing import Protocol

import httpx

from src.shared.config import Settings, settings


class ClaveRechazada(Exception):
    """GoTrue respondió 422: clave débil o igual a la anterior."""


class CambioFallido(Exception):
    """GoTrue no respondió, dio 5xx u otra respuesta que no es 200 ni 422."""


class CambioDeClave(Protocol):
    async def cambiar(self, token: str, nueva: str) -> None:
        """Cambia la clave del dueño de `token`. Lanza `ClaveRechazada` o `CambioFallido`."""
        ...


class GoTrueCambioDeClave:
    """Adaptador httpx: `PUT {gotrue}/user {"password": nueva}` con el Bearer del usuario."""

    def __init__(self, url: str, anon_key: str = "", *, timeout: float = 10.0) -> None:
        self.url = url.rstrip("/")
        self.anon_key = anon_key
        self.timeout = timeout

    async def cambiar(self, token: str, nueva: str) -> None:
        headers = {"Authorization": f"Bearer {token}"}
        if self.anon_key:
            headers["apikey"] = self.anon_key
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as cliente:
                r = await cliente.put(f"{self.url}/user", headers=headers,
                                      json={"password": nueva})
        except httpx.HTTPError as exc:
            raise CambioFallido(type(exc).__name__) from exc
        if r.status_code == 200:
            return
        if r.status_code == 422:
            raise ClaveRechazada()
        # 5xx, y también un 4xx inesperado (p. ej. 401 si GoTrue no reconoce
        # el token): la clave no cambió, así que la bandera tampoco.
        raise CambioFallido(str(r.status_code))


def url_de_gotrue(config: Settings) -> str:
    """`GOTRUE_URL`; si está vacía, `SUPABASE_URL + "/auth/v1"`; si también, ''."""
    if config.gotrue_url:
        return config.gotrue_url.rstrip("/")
    if config.supabase_url:
        return config.supabase_url.rstrip("/") + "/auth/v1"
    return ""


def get_cambio_de_clave() -> CambioDeClave | None:
    """Dependencia: el adaptador real, o `None` si no hay URL de GoTrue (-> 503)."""
    url = url_de_gotrue(settings)
    if not url:
        return None
    return GoTrueCambioDeClave(url, settings.supabase_anon_key)
