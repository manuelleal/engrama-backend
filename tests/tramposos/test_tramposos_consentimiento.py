"""Tramposos XC1-XC4 del consentimiento — `docs/ESPEC_consentimiento.md` §3.

Una versión ROTA a propósito, inyectada con monkeypatch en el módulo donde se
USA (`src.auth.router`); se corre el cuerpo del test real y se exige
`AssertionError` con el mensaje del mecanismo. Aquí se automatiza la DIAGONAL;
la matriz completa se mide aparte (ERR-15, 19 y 23).

  XC1  el registro se escribe a nombre de OTRO perfil            -> CN2
  XC2  la ruta acepta `version: str` sin límites (APIRoute rota)  -> CN4
  XC3  repetir la versión RENUEVA la fila (borra e inserta)       -> CN3
  XC4  `consent_version` es la PRIMERA fila, no la última         -> CN3

XC2 reemplaza la `APIRoute` (el modelo del cuerpo queda fijado al decorar la
ruta), igual que ZP9 del login piloto e Y16 de BUG-16.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi import Depends
from fastapi.routing import APIRoute
from pydantic import create_model
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import router as auth_router
from src.auth.schemas import AuthContext, ConsentimientoIn, ConsentimientoOut
from src.main import app
from src.shared.db import get_db
from src.shared.deps import get_current_user
from src.shared.models import Consentimiento, Profile
from tests.auth import test_consentimiento as cn

pytestmark = pytest.mark.integ

Aplicar = Callable[[pytest.MonkeyPatch], None]

_REGISTRAR_BUENO = auth_router.registrar_consentimiento
_RUTA = "/auth/consentimiento"


async def _registra_a_otro(db: AsyncSession, *, profile_id: UUID, tenant_id: UUID,
                           version: str) -> datetime:
    """XC1: la aceptación queda a nombre de otro perfil cualquiera, no del que la hizo."""
    otro = (await db.execute(
        select(Profile.id).where(Profile.id != profile_id).order_by(Profile.id).limit(1)
    )).scalar_one()
    return await _REGISTRAR_BUENO(db, profile_id=otro, tenant_id=tenant_id, version=version)


async def _renueva(db: AsyncSession, *, profile_id: UUID, tenant_id: UUID,
                   version: str) -> datetime:
    """XC3: repetir una versión borra la fila y crea otra (fecha y auditoría nuevas)."""
    await db.execute(delete(Consentimiento).where(Consentimiento.profile_id == profile_id,
                                                  Consentimiento.version == version))
    return await _REGISTRAR_BUENO(db, profile_id=profile_id, tenant_id=tenant_id,
                                  version=version)


async def _la_primera(db: AsyncSession, profile_id: UUID) -> str | None:
    """XC4: la versión MÁS VIEJA, no la última."""
    return (await db.execute(
        select(Consentimiento.version).where(Consentimiento.profile_id == profile_id)
        .order_by(Consentimiento.id.asc()).limit(1)
    )).scalar_one_or_none()


_SinLimites = create_model("ConsentimientoSinLimites", __base__=ConsentimientoIn,
                           version=(str, ...))


async def _acepta_cualquier_texto(payload: Any, auth: AuthContext = Depends(get_current_user),
                                  db: AsyncSession = Depends(get_db)) -> Any:
    return await auth_router.aceptar_consentimiento(payload, auth, db)


# Las anotaciones se fijan a mano: con `from __future__ import annotations`
# FastAPI no podría resolver el modelo creado aquí.
_acepta_cualquier_texto.__annotations__ = {
    "payload": _SinLimites, "auth": AuthContext, "db": AsyncSession,
    "return": ConsentimientoOut}


def _ruta_sin_limites(mp: pytest.MonkeyPatch) -> None:
    rutas = list(app.router.routes)
    i = next(i for i, r in enumerate(rutas) if isinstance(r, APIRoute)
             and r.path == _RUTA and r.methods == {"POST"})
    rutas[i] = APIRoute(_RUTA, _acepta_cualquier_texto, methods=["POST"],
                        response_model=ConsentimientoOut, status_code=200,
                        dependency_overrides_provider=app.router.dependency_overrides_provider)
    mp.setattr(app.router, "routes", rutas)


def _parche(nombre: str, valor: Any) -> Aplicar:
    return lambda mp: mp.setattr(auth_router, nombre, valor)


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[..., None], str]] = {
    "XC1": (_parche("registrar_consentimiento", _registra_a_otro),
            cn.test_cn2_nadie_registra_el_consentimiento_de_otro,
            r"'de_a': \(None, \[\]\), 'de_b': \('2026-10-v1', \['2026-10-v1'\], 1\)"),
    "XC2": (_ruta_sin_limites, cn.test_cn4_version_invalida_da_422_sin_escribir,
            r"CN4: \{'invalidos': \{'vacia': 500"),
    "XC3": (_parche("registrar_consentimiento", _renueva),
            cn.test_cn3_idempotente_por_version_y_con_historial,
            r"'repetir': \{'status': 200, 'misma_fecha': False, "
            r"'filas': \['2026-10-v1'\], 'auditorias': 2\}"),
    "XC4": (_parche("ultima_version", _la_primera),
            cn.test_cn3_idempotente_por_version_y_con_historial,
            r"'otra_version': \{'status': 200, 'me': '2026-10-v1'"),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        test_real(integ)
