"""MG44: la migración 044 (retos solo de refuerzo y días sin contenido) sube, baja y sube.

`docs/ESPEC_solo_refuerzo.md` §1.6 y C8. Usa las funciones de
`test_migracion_035.py` (ERR-24). Ninguna tabla nueva: dos columnas, y al bajar
se van solo ellas.
"""
from __future__ import annotations

from typing import Any

import pytest

from tests.integ.test_migracion_035 import cargar, sube_baja_sube

pytestmark = pytest.mark.integ

COLUMNAS = {"challenges": "solo_refuerzo", "activity_days": "sin_contenido"}
TABLAS = tuple(COLUMNAS)
M044 = cargar("044_solo_refuerzo.py")


def _columnas(esquema: dict[str, Any]) -> dict[str, tuple[Any, ...]]:
    return {fila[0]: tuple(fila[1:4]) for fila in esquema.get("columnas", [])}


def test_mg44_sube_baja_y_vuelve_a_subir_identica(integ) -> None:
    """MG44 (C8): up/down/up con el mismo esquema, y subir dos veces no falla."""
    visto = sube_baja_sube(integ, M044, TABLAS)
    primera, bajada = visto["primera"], visto["tras_bajar"]
    observado = {
        # (tipo, ¿acepta NULL?, valor por defecto): los retos y los días de hoy quedan en FALSE.
        "la_columna": {t: _columnas(primera[t]).get(c) for t, c in COLUMNAS.items()},
        "tras_bajar_pierde_solo_eso": {
            t: sorted(_columnas(bajada[t])) == sorted(x for x in _columnas(primera[t]) if x != c)
            for t, c in COLUMNAS.items()},
        "conserva_lo_demas": {t: (bajada[t]["restricciones"] == primera[t]["restricciones"],
                                  bajada[t]["indices"] == primera[t]["indices"],
                                  bajada[t]["rls"]) for t in TABLAS},
        "segunda_igual_a_la_primera": visto["segunda"] == primera,
        "repetida_igual_a_la_primera": visto["repetida"] == primera,
    }
    assert observado == {
        "la_columna": dict.fromkeys(TABLAS, ("boolean", "NO", "false")),
        "tras_bajar_pierde_solo_eso": dict.fromkeys(TABLAS, True),
        "conserva_lo_demas": dict.fromkeys(TABLAS, (True, True, True)),
        "segunda_igual_a_la_primera": True, "repetida_igual_a_la_primera": True,
    }, f"MG44: {observado}"
