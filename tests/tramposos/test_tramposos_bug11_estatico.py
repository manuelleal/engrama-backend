"""Tramposo Y8 (no-integ) de BUG-11 — `docs/ESPEC_bug11.md` §3.

Tramposo de validador (ERR-17): se prueba que U1 de verdad detecta una
lectura del nombre global. `_fuentes()` devuelve lo real MÁS un `falso.py`
sintético (no existe en disco) con `select(Profile.id, Profile.full_name)`;
U1 debe caer nombrándolo.
"""
from __future__ import annotations

import pytest

from tests.teachers import test_bug11_estatico as u1

_FUENTES_ORIGINAL = u1._fuentes

FALSO = (
    "from sqlalchemy import select\n"
    "from src.shared.models import Profile\n"
    "stmt = select(Profile.id, Profile.full_name)\n"
)


def _fuentes_con_falso() -> dict[str, str]:
    """Y8: las fuentes reales más `falso.py`, que lee `Profile.full_name` en la línea 3."""
    return {**_FUENTES_ORIGINAL(), "falso.py": FALSO}


def test_y8_u1_detecta_una_lectura_del_nombre_global(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(u1, "_fuentes", _fuentes_con_falso)
    with pytest.raises(AssertionError, match=r"lee el nombre global \(BUG-11\): \['falso\.py:3'\]"):
        u1.test_u1_teachers_no_lee_el_nombre_global()
