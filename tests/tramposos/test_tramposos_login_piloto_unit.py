"""Tramposos (no-integ) del login piloto — `docs/ESPEC_login_piloto.md` §3.

Mismo patrón que `test_tramposos_login_piloto.py`, sin base: se reemplaza la
función en `src.auth.service` (donde la usan `get_current_user` y UP3), se
corre el cuerpo del test real y se exige `AssertionError` con el mensaje.

  ZP7   `puede_con_contrasena_temporal` siempre verdadera          -> UP3
  ZP20  la lista indexada solo por path, sin el método (H-4)       -> UP3

ZP10 y ZP16 llegan con sus pasos (ESPEC §6).
"""
from __future__ import annotations

from collections.abc import Callable

import pytest

from src.auth import service as auth_service
from tests.auth import test_permitidas_unit as up

_PATHS_PERMITIDOS = frozenset(p for p, _m in auth_service.RUTAS_CON_CONTRASENA_TEMPORAL)


def _solo_por_path(path: str, _metodo: str) -> bool:
    """ZP20: cualquier método de un path permitido pasa (p. ej. `POST /auth/me`)."""
    return path in _PATHS_PERMITIDOS


TRAMPOSOS: dict[str, tuple[Callable[..., bool], Callable[[], None], str]] = {
    "ZP7": (lambda *_: True, up.test_up3_permitidas_por_path_y_metodo,
            r"\('/auth/me', 'POST'\): True"),
    "ZP20": (_solo_por_path, up.test_up3_permitidas_por_path_y_metodo,
             r"\('/auth/me', 'POST'\): True"),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(monkeypatch, clave: str) -> None:
    roto, test_real, motivo = TRAMPOSOS[clave]
    monkeypatch.setattr(auth_service, "puede_con_contrasena_temporal", roto)
    with pytest.raises(AssertionError, match=motivo):
        test_real()
