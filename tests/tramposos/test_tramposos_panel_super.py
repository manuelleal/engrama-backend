"""Tramposos del panel del super admin — docs/ESPEC_panel_super_admin.md §2 (TP1-TP7).

Mismo patrón que `test_tramposos_ola1_economia.py`: cada tramposo rompe UNA pieza a
propósito, se corre el cuerpo del test real y se exige `AssertionError` con el
mensaje de su test. Si un tramposo no pone rojo su test, ese test no prueba nada.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from datetime import date, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import and_, case, func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import service as auth_service
from src.main import app
from src.panel import acceso, metricas, servicio, ventanas
from src.panel.schemas import PanelAdmin
from src.shared.models import Attendance, ChallengeAttempt, CoinLedger, LearningEvent, Membership
from tests.panel import test_panel_super as tp
from tests.tramposos.test_tramposos_bug13 import correr

pytestmark = pytest.mark.integ

Aplicar = Callable[[Any, pytest.MonkeyPatch], AbstractContextManager[Any]]


def _parche(objetivo: Any, nombre: str, valor: Any) -> Aplicar:
    def aplicar(_integ: Any, mp: pytest.MonkeyPatch) -> AbstractContextManager[Any]:
        mp.setattr(objetivo, nombre, valor)
        return nullcontext()
    return aplicar


_exigir_super_original = acceso.exigir_super
_dias_originales = ventanas.dias_de_la_ventana


def _acepta_admins_sin_recursion(rol: str) -> None:
    """TP1: el super admin "es" también cualquier admin (como `require_admin`)."""
    if rol not in {"super_admin", "admin"}:
        _exigir_super_original(rol)


def _ventana_de_31(hoy: date, n: int = 30) -> list[date]:
    """TP3: un día de más (el error de borde clásico)."""
    del n
    return _dias_originales(hoy, 31)


async def _activos_sin_tenant(db: AsyncSession, ids: Sequence[UUID],
                              desde: datetime) -> dict[UUID, int]:
    """TP4: la actividad se cruza solo por persona: jugar en B hace activo en A."""
    act = union_all(
        select(ChallengeAttempt.student_id.label("pid")).where(ChallengeAttempt.started_at >= desde),
        select(Attendance.student_id).where(Attendance.created_at >= desde),
        select(LearningEvent.subject_id).where(LearningEvent.occurred_at >= desde),
    ).subquery()
    stmt = (select(Membership.tenant_id, func.count(func.distinct(Membership.profile_id)))
            .join(act, act.c.pid == Membership.profile_id)
            .where(Membership.tenant_id.in_(ids), Membership.role == "student",
                   Membership.is_active.is_(True))
            .group_by(Membership.tenant_id))
    return {tid: int(n) for tid, n in (await db.execute(stmt)).all()}


def _emitidas_ingenuas(origen: Any, destino: Any) -> Any:
    """TP5: todo lo que llega a un estudiante desde la institución es emisión (también la
    devolución de una compra) y las correcciones no restan."""
    return case((and_(origen.in_(("tenant", "membership")), destino == "profile"),
                 CoinLedger.amount), else_=0)


async def _admin_ve_todo(db: AsyncSession, tenant_id: UUID) -> PanelAdmin:
    """TP6: el tablero del admin suma TODOS los tenants (se olvidó el filtro)."""
    del tenant_id
    ids = [t.id for t in await servicio.tenants_en_orden(db)]
    ahora_utc = ventanas.ahora()
    cifras = servicio.sumar(list((await servicio.metricas_por_tenant(db, ids, ahora_utc)).values()))
    series = await servicio.series_de(db, ids, ahora_utc)
    return PanelAdmin(hoy=ventanas.hoy_local(ahora_utc, -5), metricas=cifras,
                      registros_por_dia=series.registros_por_dia,
                      monedas_por_semana=series.monedas_por_semana)


class _PanelAdminConNombre(PanelAdmin):
    etiqueta: str
    id: UUID


def _ruta_del_admin_con_nombre(_integ: Any, mp: pytest.MonkeyPatch) -> AbstractContextManager[Any]:
    """TP7: alguien le agrega la etiqueta y el id al esquema del admin (y el servicio los llena)."""
    async def con_nombre(db: AsyncSession, tenant_id: UUID) -> _PanelAdminConNombre:
        base = await _original_panel_admin(db, tenant_id)
        detalle = await servicio.detalle(db, tenant_id)
        assert detalle is not None
        return _PanelAdminConNombre(**base.model_dump(), etiqueta=detalle.etiqueta, id=tenant_id)

    mp.setattr(servicio, "panel_admin", con_nombre)
    ruta = next(r for r in app.router.routes
                if isinstance(r, APIRoute) and r.path == "/admin/metricas")
    rota = APIRoute(ruta.path, endpoint=ruta.endpoint, methods=["GET"],
                    response_model=_PanelAdminConNombre,
                    dependency_overrides_provider=ruta.dependency_overrides_provider)
    mp.setattr(ruta, "app", rota.app)
    return nullcontext()


_original_panel_admin = servicio.panel_admin

TRAMPOSOS: dict[str, tuple[Aplicar, list[tuple[Callable[..., None], str]]]] = {
    "TP1": (_parche(acceso, "exigir_super", _acepta_admins_sin_recursion), [
        (tp.test_ps2_solo_el_super_admin_entra, r"PS2: \{'admin': \[200, 200\]"),
    ]),
    "TP2": (_parche(acceso, "exigir_cuenta_activa", lambda _p: None), [
        (tp.test_ps3_super_suspendido_o_con_clave_temporal_no_entra,
         r"PS3: \{'suspendido': \(200"),
    ]),
    "TP3": (_parche(ventanas, "dias_de_la_ventana", _ventana_de_31), [
        (tp.test_ps5_registros_por_dia_30_dias_locales_hasta_hoy,
         r"PS5: \{'fechas_ok': False, .*'total': 5\}"),
    ]),
    "TP4": (_parche(metricas, "activos_por_tenant", _activos_sin_tenant), [
        (tp.test_ps6_activos_7d_por_tenant_y_ventana, r"PS6: \{'A': 4, 'B': 1\}"),
    ]),
    "TP5": (_parche(metricas, "emitidas_expr", _emitidas_ingenuas), [
        (tp.test_ps7_monedas_por_direccion, r"PS7: \{'monedas': \{'bolsa': 777, 'emitidas': 63"),
    ]),
    "TP6": (_parche(servicio, "panel_admin", _admin_ve_todo), [
        (tp.test_am1_el_admin_ve_solo_su_institucion, r"AM1: \{'A': \{'profes': 3"),
    ]),
    "TP7": (_ruta_del_admin_con_nombre, [
        (tp.test_am4_la_respuesta_del_admin_no_trae_nombre,
         r"AM4: \{'status': 200, 'claves_prohibidas': \['etiqueta', 'id'\], 'nombre_a': True"),
    ]),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    aplicar, diagonal = TRAMPOSOS[clave]
    with aplicar(integ, monkeypatch):
        for test_real, motivo in diagonal:
            with pytest.raises(AssertionError, match=motivo):
                correr(test_real, integ, monkeypatch)
            integ.truncar_todo()  # cada test real arranca con la base limpia


def test_tp2_parchea_lo_que_usa_acceso() -> None:
    """TP2 parcha `acceso.exigir_cuenta_activa`: debe ser la misma función que la de auth."""
    assert acceso.exigir_cuenta_activa is auth_service.exigir_cuenta_activa
