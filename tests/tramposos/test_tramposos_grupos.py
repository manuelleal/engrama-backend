"""Tramposos (integ) de `/teachers` y `/admin` — ESPEC §3.

Mismo patrón que `test_tramposos_seguridad.py`: una versión ROTA a propósito,
se corre el cuerpo del test real y se exige `AssertionError` con el mensaje
correcto. Cada tramposo aquí apunta a UNA celda representativa de las que
predice el §3 "Rojo esperado"; la matriz COMPLETA (qué OTRAS celdas también
se ponen rojas) se mide aparte y se reporta (ERR-15) — no se automatiza
entera aquí, mismo criterio que el ERR-10 documentado en
`test_tramposos_seguridad.py`.

Los tramposos nacen en el commit que agrega la ruta que rompen (§7):
  X1, X2, X3  -> commit 2 (T1)
  X9          -> commit 3 (T2)
  X5          -> commit 4 (T3/T4)
  X7          -> commit 5 (T6)
  X4          -> commit 6 (M1/M2)
  X8          -> commit 8 (M4)
  X6, X10, X17, X18 -> commit 10 (T5)
  X21         -> commit 11 (T7)
Este archivo se escribe incrementalmente en ese orden (ERR-12: hay versión
intermedia guardada de cada commit que lo toca).
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import pytest
from fastapi import Depends
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.main import app
from src.shared.db import get_db
from src.shared.deps import get_current_user, require_admin, require_teacher
from src.shared.models import AttendanceSession
from src.teachers.service import access as access_mod
from src.teachers.service import panel as panel_mod
from tests.teachers import test_t1_groups as t1
from tests.teachers import test_t2_roster as t2
from tests.teachers import test_t3_t4_attendance as t34
from tests.teachers import test_t6_assign as t6
from tests.teachers import test_m1_m2_admin_groups as m12

pytestmark = pytest.mark.integ

Aplicar = Callable[[Any, pytest.MonkeyPatch], Any]


# =============================================================================
# Versiones rotas
# =============================================================================
def _base_stmt_sin_tenant(auth: Any):  # type: ignore[no-untyped-def]
    """X1: el SELECT de grupos ya no filtra por `tenant_id`."""
    from sqlalchemy import select

    from src.shared.models import Group

    return select(Group)


def _nunca_exige_asignacion(_auth: Any, *, only_assigned: bool) -> bool:  # noqa: ARG001
    """X2: nunca exige `teacher_groups`, ni con `only_assigned=True`."""
    return False


@contextmanager
def _override(original: Any, reemplazo: Any) -> Iterator[None]:
    """X3/X4: cambia la Depends para TODAS las rutas que la usan."""
    app.dependency_overrides[original] = reemplazo
    try:
        yield
    finally:
        app.dependency_overrides.pop(original, None)


async def _t2_con_balance(
    gid: UUID,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """X9: T2 con `balance` — bypassa `response_model` (que lo bloquearía de
    todas formas: `extra='forbid'` no filtra atributos que el propio código
    nunca declaró) devolviendo un JSONResponse crudo, para probar el
    contrato incluso si alguien reescribiera el endpoint entero."""
    group = await access_mod.authorize_group(db, auth, gid)
    filas = await panel_mod.roster(db, group)
    payload = [{**f.model_dump(mode="json"), "balance": 999999} for f in filas]
    return JSONResponse(payload)


async def _close_sin_expirar(db: AsyncSession, auth: AuthContext, session_id: UUID) -> Any:
    """X5: cierra sin cambiar `status` ni `expires_at` (ESPEC T4, §3)."""
    from sqlalchemy import select

    stmt = select(AttendanceSession).where(
        AttendanceSession.id == session_id, AttendanceSession.tenant_id == auth.tenant_id
    )
    session = (await db.execute(stmt)).scalar_one_or_none()
    if session is None:
        from fastapi import HTTPException, status as st
        raise HTTPException(status_code=st.HTTP_404_NOT_FOUND, detail="not found")
    await access_mod.authorize_group(db, auth, session.group_id)
    # BUG a propósito: no toca session.status ni session.expires_at.
    await db.flush()
    return session


async def _assign_sin_revisar_grupo_actual(
    db: AsyncSession, auth: AuthContext, group: Any, challenge_id: UUID
) -> Any:
    """X7: fija `group_id` sin mirar si el actual es visible para `auth`."""
    challenge = await panel_mod.challenges_service.get_challenge(
        db, challenge_id, auth.tenant_id
    )
    # BUG a propósito: se salta el chequeo de "sin grupo o en un grupo visible".
    challenge.group_id = group.id
    await db.flush()
    return challenge


@contextmanager
def _reemplazar_ruta(path: str, metodos: set[str], endpoint: Any) -> Iterator[None]:
    """Reemplaza en sitio el `endpoint`/`dependant.call` de una APIRoute ya
    montada — la única forma de saltarse su `response_model` (§2.2, X9)."""
    objetivo = next(
        r for r in app.routes
        if isinstance(r, APIRoute) and r.path == path and set(r.methods) == metodos
    )
    original_endpoint, original_call = objetivo.endpoint, objetivo.dependant.call
    objetivo.endpoint = endpoint
    objetivo.dependant.call = endpoint
    try:
        yield
    finally:
        objetivo.endpoint = original_endpoint
        objetivo.dependant.call = original_call


# =============================================================================
# Registro: id -> (cómo romper, test real, mensaje con el que debe caer)
# =============================================================================
TRAMPOSOS: dict[str, tuple[Aplicar, Callable[[Any], None], str]] = {
    "X1": (
        lambda _i, mp: mp.setattr(access_mod, "_base_stmt", _base_stmt_sin_tenant),
        t1.test_t1_dm_200_sin_ga,
        r"not in",
    ),
    "X2": (
        lambda _i, mp: mp.setattr(access_mod, "_requiere_asignacion", _nunca_exige_asignacion),
        t1.test_t1_do_200_sin_ga,
        r"not in",
    ),
    "X3": (
        lambda _i, _mp: _override(require_teacher, get_current_user),
        t1.test_t1_e_403,
        r"403",
    ),
    "X9": (
        lambda _i, _mp: _reemplazar_ruta(
            "/teachers/groups/{gid}/students", {"GET"}, _t2_con_balance
        ),
        t2.test_f2_roster_sin_balance,
        r"balance",
    ),
    "X5": (
        lambda _i, mp: mp.setattr(panel_mod, "close_session", _close_sin_expirar),
        t34.test_f4_cerrar_expira_y_bloquea_checkin,
        r"active.*expired",
    ),
    "X7": (
        lambda _i, mp: mp.setattr(panel_mod, "assign_challenge", _assign_sin_revisar_grupo_actual),
        t6.test_f6_no_reasigna_reto_de_grupo_no_visible,
        r"404",
    ),
    "X4": (
        lambda _i, _mp: _override(require_admin, require_teacher),
        m12.test_m1_d_403,
        r"403",
    ),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    resultado = aplicar(integ, monkeypatch)
    ctx = resultado if hasattr(resultado, "__enter__") else _nullctx()
    with ctx, pytest.raises(AssertionError, match=motivo):
        test_real(integ)


@contextmanager
def _nullctx() -> Iterator[None]:
    yield
