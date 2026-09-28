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

import pytest

from src.main import app
from src.shared.deps import get_current_user, require_teacher
from src.teachers.service import access as access_mod
from tests.teachers import test_t1_groups as t1

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
    """X3: cambia la Depends para TODAS las rutas que la usan."""
    app.dependency_overrides[original] = reemplazo
    try:
        yield
    finally:
        app.dependency_overrides.pop(original, None)


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
