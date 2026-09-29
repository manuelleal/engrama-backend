"""Tramposos (integ) del login piloto — `docs/ESPEC_login_piloto.md` §3.

Mismo patrón que `test_tramposos_bug15.py`: una versión ROTA a propósito, se
inyecta con monkeypatch en el módulo donde se USA, se corre el cuerpo del test
real y se exige `AssertionError` con el mensaje del mecanismo. Aquí se
automatiza la DIAGONAL (la negrita de §3); la matriz completa se mide aparte
(ERR-15, 19 y 23).

  ZP2   `deps.get_profile` = el respaldo viejo (`get_or_create_profile`, que
        crea el stub con `documento_id = sub[:8]`)          -> AP3 y AP4
  ZP14  `validate_jwt` sin verificar la firma               -> AP1
  ZP15  `validate_jwt` sin verificar `exp`                  -> AP2
  ZP3   el `full_name` de `/auth/me` sale del perfil          -> AP8
  ZP4   `get_memberships` con ORDER BY `created_at` DESC      -> AP7
  ZP5   `build_auth_context` ignora un `X-Tenant-ID` ajeno y usa la
        primera membresía                                      -> AP6
  ZP6   la bandera se lee del JWT (`user_metadata`), no de la BD -> AP9
  ZP8   `/auth/contrasena` llama a GoTrue y NO limpia la bandera -> AP10

ZP7 y ZP20 (no-integ) viven en `test_tramposos_login_piloto_unit.py`.

ZP14 y ZP15 no reemplazan `validate_jwt`: reemplazan el `jwt` de python-jose
que usa `src/auth/service.py` por uno que apaga UNA verificación. Así el
tramposo alcanza a todo el que llama a `validate_jwt`, también a los tests
que la importan por nombre (`tests/auth/test_validate_jwt.py`).

Los tramposos ZP1, ZP9-ZP13 y ZP16-ZP19 llegan con sus pasos (ESPEC §6).
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from typing import Any
from uuid import UUID

import pytest
from fastapi import HTTPException
from jose import jwt as jose_jwt
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import router as auth_router
from src.auth import service as auth_service
from src.shared import deps as deps_mod
from src.shared.models import Membership, Profile
from tests.auth import test_login_piloto as lp
from tests.auth import test_login_piloto_clave as lpc
from tests.tramposos.test_tramposos_bug13 import correr

pytestmark = pytest.mark.integ

Aplicar = Callable[[Any, pytest.MonkeyPatch], AbstractContextManager[Any]]

_GET_PROFILE_BUENO = auth_service.get_profile
_CONTEXTO_BUENO = auth_service.build_auth_context


async def _get_profile_viejo(db: AsyncSession, profile_id: UUID) -> Profile:
    """ZP2: el respaldo "solo desarrollo" de antes del paso 2 (hasta `b81d373`).

    Si el `sub` no tiene perfil, crea un stub con `documento_id = sub[:8]`.
    """
    perfil = await _GET_PROFILE_BUENO(db, profile_id)
    if perfil is not None:
        return perfil
    corto = str(profile_id).replace("-", "")[:8]
    perfil = Profile(id=profile_id, documento_id=corto, full_name=f"User {corto}", pin_hash="")
    db.add(perfil)
    await db.commit()
    await db.refresh(perfil)
    return perfil


class _JoseSin:
    """El `jwt` de python-jose con una verificación apagada (ZP14, ZP15)."""

    def __init__(self, **apagadas: bool) -> None:
        self.apagadas = apagadas

    def decode(self, token: str, key: str, **kw: Any) -> dict[str, Any]:
        opciones = {**(kw.pop("options", None) or {}), **self.apagadas}
        datos: dict[str, Any] = jose_jwt.decode(token, key, options=opciones, **kw)
        return datos


def _nombre_del_perfil(profile: Profile, _membresias: Any) -> str:
    """ZP3: el nombre de siempre, el del perfil (M3 lo deja en '')."""
    return profile.full_name


def _orden_desc() -> tuple[Any, ...]:
    """ZP4: la membresía MÁS NUEVA primero."""
    return (Membership.created_at.desc(), Membership.id.desc())


def _contexto_ignora_ajeno(profile: Any, memberships: list[Any],
                           tenant_id_header: str | None = None) -> Any:
    """ZP5: con un `X-Tenant-ID` del que no es miembro, usa la primera membresía."""
    try:
        return _CONTEXTO_BUENO(profile, memberships, tenant_id_header)
    except HTTPException as exc:
        if exc.status_code == 403 and memberships and tenant_id_header:
            return _CONTEXTO_BUENO(profile, memberships, None)
        raise


def _bandera_del_jwt(_profile: Profile) -> bool:
    """ZP6: la bandera sale de `user_metadata.must_change_password` del JWT.

    Los tokens de prueba no traen metadatos (`integ.headers`) o los traen en
    false (AP9): para todos ellos esa lectura da False. El tramposo devuelve
    exactamente eso, sin mirar `profiles.force_password_reset`.
    """
    return False


async def _no_limpia(_db: AsyncSession, _profile_id: UUID) -> None:
    """ZP8: GoTrue aceptó la clave, pero la bandera queda como estaba."""


def _parche(objetivo: Any, nombre: str, valor: Any) -> Aplicar:
    def aplicar(_integ: Any, mp: pytest.MonkeyPatch) -> AbstractContextManager[Any]:
        mp.setattr(objetivo, nombre, valor)
        return nullcontext()
    return aplicar


# =============================================================================
# Registro: id -> (cómo romper, [(test real, mensaje con el que debe caer)])
# =============================================================================
TRAMPOSOS: dict[str, tuple[Aplicar, list[tuple[Callable[..., None], str]]]] = {
    "ZP2": (_parche(deps_mod, "get_profile", _get_profile_viejo), [
        (lp.test_ap3_sin_perfil_da_403_sin_crear_filas, r"'profiles': 1\}"),
        (lp.test_ap4_choque_de_documento_da_403_no_500, r"\(500, None\)"),
    ]),
    "ZP14": (_parche(auth_service, "jwt", _JoseSin(verify_signature=False)), [
        (lp.test_ap1_jwt_de_otro_proyecto_da_401,
         r"/auth/me con el token de otro proyecto: 200"),
    ]),
    "ZP15": (_parche(auth_service, "jwt", _JoseSin(verify_exp=False)), [
        (lp.test_ap2_jwt_vencido_da_401, r"/auth/me con el token vencido: 200"),
    ]),
    "ZP3": (_parche(auth_service, "nombre_visible", _nombre_del_perfil), [
        (lp.test_ap8_nombre_de_la_membresia, r"\{'full_name': ''\}"),
    ]),
    # El diff de un dict puede salir truncado y sus ítems no tienen orden fijo:
    # se busca el comienzo de CUALQUIERA de las dos listas observadas con B
    # primero (lo esperado siempre empieza por A).
    "ZP4": (_parche(auth_service, "orden_membresias", _orden_desc), [
        (lp.test_ap7_docente_en_dos_instituciones,
         r"\[\(200, '[0-9a-f-]{36}', 'Profe Beta'\)|\[\('[0-9a-f-]{36}', 'Profe Beta'\)"),
    ]),
    "ZP5": (_parche(deps_mod, "build_auth_context", _contexto_ignora_ajeno), [
        (lp.test_ap6_tres_instituciones_aisladas, r"estudiante de A en /auth/me con B: 200"),
    ]),
    "ZP6": (_parche(auth_service, "debe_cambiar_clave", _bandera_del_jwt), [
        (lpc.test_ap9_contrasena_temporal_bloquea_menos_cuatro_rutas, r"'me': \(200, False\)"),
    ]),
    "ZP8": (_parche(auth_router, "quitar_contrasena_temporal", _no_limpia), [
        # El diff ordena las claves: 'bandera' sale antes que 'llamadas' (el token).
        (lpc.test_ap10_cambio_de_contrasena,
         r"\{'valida': \{'bandera': True, 'llamadas': .*'mismo_token': 403"),
    ]),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    aplicar, diagonal = TRAMPOSOS[clave]
    with aplicar(integ, monkeypatch):
        for i, (test_real, motivo) in enumerate(diagonal):
            if i:
                integ.truncar_todo()  # cada test real arranca con la base vacía, como en pytest
            with pytest.raises(AssertionError, match=motivo):
                correr(test_real, integ, monkeypatch)
