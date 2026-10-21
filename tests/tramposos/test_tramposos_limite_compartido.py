"""Tramposos del límite compartido — `docs/ESPEC_limites_registro.md` §3.

Una versión ROTA a propósito; se corre el cuerpo del test real y se exige
`AssertionError` con el mensaje del mecanismo (la diagonal).

  ZR43  la bajada de 046 no hace nada                               -> MG46
"""
from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from tests.integ import test_migracion_046 as mg

pytestmark = pytest.mark.integ

Correr = Callable[[Any, pytest.MonkeyPatch], None]


def _zr43(integ: Any, mp: pytest.MonkeyPatch) -> None:
    """La migración cuya bajada no borra nada."""
    mg.cuerpo_mg46(integ, SimpleNamespace(SQL_SUBIR=mg.M046.SQL_SUBIR, SQL_BAJAR=()))


TRAMPOSOS: dict[str, tuple[Correr, str]] = {
    "ZR43": (_zr43, r"'tras_bajar': \{'la_tabla': \{'existe': True"),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    correr, motivo = TRAMPOSOS[clave]
    with pytest.raises(AssertionError, match=motivo):
        correr(integ, monkeypatch)
