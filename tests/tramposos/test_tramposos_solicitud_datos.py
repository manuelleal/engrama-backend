"""Tramposos XS1-XS9 de las solicitudes sobre datos — `docs/ESPEC_solicitud_datos.md` §3.

Una versión ROTA a propósito, inyectada con monkeypatch en el módulo donde se
USA (`src.datos.service`, al que el router llama por el módulo); se corre el
cuerpo del test real y se exige `AssertionError` con el mensaje del mecanismo.
Aquí se automatiza la DIAGONAL; la matriz completa se mide aparte.

XS5 y XS6 reemplazan la `APIRoute` (el modelo del cuerpo queda fijado al
decorar la ruta), igual que XC2 del consentimiento.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi import Depends
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.datos import router as router_mod
from src.datos import service as service_mod
from src.datos.schemas import RespuestaIn, SolicitudDatosAdminOut, SolicitudDatosOut
from src.main import app
from src.shared.db import get_db
from src.shared.deps import get_current_user
from src.shared.models import Profile, SolicitudDatos
from tests.datos import test_solicitudes_datos as sd

pytestmark = pytest.mark.integ

Aplicar = Callable[[pytest.MonkeyPatch], None]
_RUTA = "/auth/solicitudes-datos"
_RESPONDER_BUENO = service_mod.responder
_BUSCAR_BUENO = service_mod._buscar_en_la_institucion


# --- XS1: la lista del usuario trae las de todos ------------------------------
async def _lista_de_todos(db: AsyncSession, auth: AuthContext) -> list[SolicitudDatos]:
    filas = await db.execute(select(SolicitudDatos).order_by(SolicitudDatos.id.desc()))
    return list(filas.scalars().all())


# --- XS2: la solicitud queda a nombre de OTRO perfil --------------------------
_OTRO: dict[str, UUID] = {}


def _a_nombre_de_otro(auth: AuthContext) -> UUID:
    """El perfil que el arnés dejó en `_OTRO`; si no hay, uno que no existe (FK -> 500)."""
    return _OTRO.get("perfil", UUID(int=7))


def _otro_titular(mp: pytest.MonkeyPatch) -> None:
    """Antes de crear, se elige "otro" perfil cualquiera de la base (no el que llama)."""
    async def crear_a_otro(db: AsyncSession, auth: AuthContext, datos: Any) -> SolicitudDatos:
        otro = (await db.execute(select(Profile.id).where(Profile.id != auth.profile_id)
                                 .order_by(Profile.id).limit(1))).scalar_one_or_none()
        if otro is not None:
            _OTRO["perfil"] = otro
        else:
            _OTRO.pop("perfil", None)
        return await _CREAR_BUENO(db, auth, datos)

    mp.setattr(service_mod, "_titular", _a_nombre_de_otro)
    mp.setattr(service_mod, "crear", crear_a_otro)


_CREAR_BUENO = service_mod.crear


# --- XS3 y XS4: el admin sin la barrera de institución ------------------------
async def _lista_de_todas_las_instituciones(db: AsyncSession, auth: AuthContext,
                                            estado: str | None = None,
                                            ) -> list[SolicitudDatosAdminOut]:
    filas = await db.execute(select(SolicitudDatos).order_by(SolicitudDatos.id.desc()))
    return [service_mod.con_solicitante(f, "sintetico", None) for f in filas.scalars().all()]


async def _buscar_en_cualquier_institucion(db: AsyncSession, tenant_id: UUID,
                                           solicitud_id: int) -> SolicitudDatos | None:
    return (await db.execute(select(SolicitudDatos).where(
        SolicitudDatos.id == solicitud_id))).scalar_one_or_none()


# --- XS5 y XS6: la ruta sin sus límites ---------------------------------------
class _SinTope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: Any = None
    mensaje: Any = None


async def _crea_lo_que_llegue(payload: Any, auth: AuthContext = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)) -> Any:
    return await router_mod.crear_solicitud(payload, auth, db)


_crea_lo_que_llegue.__annotations__ = {
    "payload": _SinTope, "auth": AuthContext, "db": AsyncSession, "return": SolicitudDatosOut}


def _ruta_sin_limites(validar: Callable[[Any], bool]) -> Aplicar:
    """La ruta de crear, que solo conserva la validación que `validar` deja pasar."""
    from fastapi import HTTPException

    async def endpoint(payload: Any, auth: AuthContext = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)) -> Any:
        if not validar(payload):
            raise HTTPException(status_code=422, detail="invalido")
        return await router_mod.crear_solicitud(payload, auth, db)

    endpoint.__annotations__ = dict(_crea_lo_que_llegue.__annotations__)

    def aplicar(mp: pytest.MonkeyPatch) -> None:
        rutas = list(app.router.routes)
        i = next(i for i, r in enumerate(rutas) if isinstance(r, APIRoute)
                 and r.path == _RUTA and r.methods == {"POST"})
        rutas[i] = APIRoute(_RUTA, endpoint, methods=["POST"],
                            response_model=SolicitudDatosOut, status_code=201,
                            dependency_overrides_provider=app.router.dependency_overrides_provider)
        mp.setattr(app.router, "routes", rutas)

    return aplicar


_TIPOS = ("conocer", "actualizar", "rectificar", "suprimir")


def _solo_valida_el_tipo(p: Any) -> bool:
    """XS5: el mensaje pasa con cualquier largo (si es texto no vacío)."""
    return p.tipo in _TIPOS and isinstance(p.mensaje, str) and p.mensaje.strip() != ""


def _solo_valida_el_mensaje(p: Any) -> bool:
    """XS6: el tipo es texto libre."""
    return (isinstance(p.tipo, str) and isinstance(p.mensaje, str)
            and 0 < len(p.mensaje) <= 1000 and p.mensaje.strip() != "")


# --- XS8: resolver un `suprimir` EJECUTA algo (desactiva el perfil) ------------------------------
async def _responde_y_ejecuta(db: AsyncSession, auth: AuthContext, solicitud_id: int,
                              datos: RespuestaIn) -> SolicitudDatos:
    fila = await _RESPONDER_BUENO(db, auth, solicitud_id, datos)
    if fila.tipo == "suprimir" and datos.estado == "resuelta":
        # Desactiva en vez de borrar: `audit_logs.user_id` no tiene ON DELETE, y un
        # DELETE del perfil lo frena la base (500) antes de que el test lo vea.
        await db.execute(update(Profile).where(Profile.id == fila.profile_id)
                         .values(is_active=False))
    return fila


# --- XS9: la respuesta no deja quién -----------------------------------------
def _sin_quien(fila: SolicitudDatos, auth: AuthContext, datos: RespuestaIn) -> None:
    from sqlalchemy import func

    fila.estado = datos.estado
    fila.respuesta = datos.respuesta
    fila.respondida_en = func.now()


def _parche(nombre: str, valor: Any) -> Aplicar:
    return lambda mp: mp.setattr(service_mod, nombre, valor)


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[..., None], str]] = {
    "XS1": (_parche("del_usuario", _lista_de_todos), sd.test_sd2_nadie_lee_ni_crea_por_otro,
            r"'lista_de_b': \[\{'id': "),
    "XS2": (_otro_titular, sd.test_sd2_nadie_lee_ni_crea_por_otro,
            r"'lista_de_a': 0, 'filas_de_a': 0, 'filas_de_b': 2"),
    "XS3": (_parche("de_la_institucion", _lista_de_todas_las_instituciones),
            sd.test_sd5_el_admin_solo_su_institucion_y_con_traza,
            r"SD5: \{'ve': \{'admin_a': \[\(2, "),
    "XS4": (_parche("_buscar_en_la_institucion", _buscar_en_cualquier_institucion),
            sd.test_sd5_el_admin_solo_su_institucion_y_con_traza,
            r"'admin_b_responde_la_de_a': \(200, 'resuelta'\)"),
    "XS5": (_ruta_sin_limites(_solo_valida_el_tipo), sd.test_sd3_tipo_o_mensaje_invalido_da_422,
            r"'mensaje_de_1001': 500"),
    "XS6": (_ruta_sin_limites(_solo_valida_el_mensaje),
            sd.test_sd3_tipo_o_mensaje_invalido_da_422, r"'tipo_inventado': 500"),
    "XS7": (_parche("TOPE_SIN_CERRAR", 10**6), sd.test_sd4_a_lo_sumo_cinco_sin_cerrar,
            r"'la_sexta': \(201, None\)"),
    "XS8": (_parche("responder", _responde_y_ejecuta), sd.test_sd6_barreras_y_no_ejecuta_nada,
            r"'nada_cambio': \(\(1, 1, 1, 30\), False\)"),
    "XS9": (_parche("_anotar_respuesta", _sin_quien),
            sd.test_sd5_el_admin_solo_su_institucion_y_con_traza,
            r"'quien_y_cuando': \(False, True\)"),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        test_real(integ)
