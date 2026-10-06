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
  ZP9   la ruta de M3 con `documento_id: str` (sin `pattern`)    -> AP11

ZP9 no puede parchear el módulo: el modelo del cuerpo queda fijado al
decorar la ruta. Reemplaza la `APIRoute` de M3 en `app.router.routes` (como
`ESPEC_bug16.md` §3, pero con `setattr` de la lista, porque `setitem` no
sirve para listas): mismo path, método,
`status_code` y `response_model`; su endpoint llama al ORIGINAL del router.

ZP7 y ZP20 (no-integ) viven en `test_tramposos_login_piloto_unit.py`.

ZP14 y ZP15 no reemplazan `validate_jwt`: reemplazan el `jwt` de python-jose
que usa `src/auth/service.py` por uno que apaga UNA verificación. Así el
tramposo alcanza a todo el que llama a `validate_jwt`, también a los tests
que la importan por nombre (`tests/auth/test_validate_jwt.py`).

Los tramposos ZP1, ZP11-ZP13 y ZP16-ZP19 llegan con sus pasos (ESPEC §6).
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from typing import Any
from uuid import UUID

import pytest
from fastapi import Depends, HTTPException, Response
from fastapi.routing import APIRoute
from jose import jwt as jose_jwt
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import router as auth_router
from src.auth import service as auth_service
from src.auth.schemas import AuthContext
from src.main import app
from src.shared import deps as deps_mod
from src.shared.db import get_db
from src.shared.deps import require_admin
from src.shared.models import Membership, Profile
from src.teachers import admin_router
from src.teachers.schemas import StudentEnrollIn, StudentEnrollOut
from tests.auth import test_login_piloto as lp
from tests.auth import test_login_piloto_clave as lpc
from tests.teachers import test_m3_documento as m3d
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


class _M3SinPatron(StudentEnrollIn):
    """ZP9: el cuerpo de M3 como antes de D1: `documento_id` sin `pattern`."""

    documento_id: str


_M3_BUENO = admin_router.enroll_student
_RUTA_M3 = "/admin/groups/{gid}/students"


async def _m3_sin_patron(
    gid: UUID,
    payload: _M3SinPatron,
    response: Response,
    auth: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> StudentEnrollOut:
    return await _M3_BUENO(gid, payload, response, auth, db)


def _ruta_m3_sin_patron(_integ: Any, mp: pytest.MonkeyPatch) -> AbstractContextManager[Any]:
    # `monkeypatch.setitem` no sirve con una lista (usa `.get`): se reemplaza
    # la lista entera por una copia con la ruta cambiada, y `undo` la devuelve.
    rutas = list(app.router.routes)
    i = next(i for i, r in enumerate(rutas) if isinstance(r, APIRoute)
             and r.path == _RUTA_M3 and r.methods == {"POST"})
    # Sin `dependency_overrides_provider`, la ruta nueva ignoraría el `get_db`
    # de la fixture (iría a la base por defecto).
    rutas[i] = APIRoute(_RUTA_M3, _m3_sin_patron, methods=["POST"],
                        response_model=StudentEnrollOut, status_code=201,
                        dependency_overrides_provider=app.router.dependency_overrides_provider)
    mp.setattr(app.router, "routes", rutas)
    return nullcontext()


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
    # H-10 (ESPEC_endurecimiento_piloto): `validate_jwt` ahora pide `require_exp`, y
    # python-jose vuelve a encender `verify_exp` cuando un claim es obligatorio. Para
    # seguir siendo "sin verificar exp", el tramposo apaga las dos.
    "ZP15": (_parche(auth_service, "jwt", _JoseSin(verify_exp=False, require_exp=False)), [
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
    "ZP9": (_ruta_m3_sin_patron, [
        (m3d.test_ap11_m3_valida_documento, r"'12\.345\.678': \(201, None\)"),
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
