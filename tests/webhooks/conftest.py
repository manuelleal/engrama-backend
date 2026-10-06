"""Al terminar cada test de la puerta de eventos se apagan los secretos sintéticos."""
from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.webhooks import _ayuda as ay


@pytest.fixture(autouse=True)
def _apagar_los_secretos_al_terminar() -> Iterator[None]:
    yield
    ay.soltar()
