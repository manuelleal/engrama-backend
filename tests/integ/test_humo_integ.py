"""Humo de la fixture de integración (espec §5).

Comprueba que la base que usan los tests `integ` es la que dicen las
migraciones: Alembic en 029, RLS activo en las 26 tablas, las 51 políticas
de la 029 y la función `auth.uid()` de Supabase. El resultado queda escrito en
`tests/_salida/humo_integ.json` (lo escribe la fixture `humo_integ`).
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from tests import integ_db

pytestmark = pytest.mark.integ


def test_humo_escribe_archivo_con_la_base_migrada(humo_integ: dict[str, Any]) -> None:
    """humo_integ.json existe, coincide con lo medido y trae los valores de la espec."""
    assert integ_db.RUTA_HUMO.exists(), f"no se escribió {integ_db.RUTA_HUMO}"
    en_disco = json.loads(integ_db.RUTA_HUMO.read_text(encoding="utf-8"))
    assert en_disco == humo_integ
    assert set(en_disco) == set(integ_db.HUMO_ESPERADO)
    integ_db.afirmar_humo(en_disco)
