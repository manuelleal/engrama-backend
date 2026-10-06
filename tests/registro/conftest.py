"""Al terminar cada test del autorregistro se suelta el doble de GoTrue.

`app.dependency_overrides` es global: `tests/teachers/test_access.py`
(`test_h3_sin_overrides_de_dependencias_filtrados`) falla si queda uno puesto.
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.registro import _ayuda as ay


@pytest.fixture(autouse=True)
def _soltar_el_doble_al_terminar() -> Iterator[None]:
    yield
    ay.soltar()
