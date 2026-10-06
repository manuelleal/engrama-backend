"""MG38: la migración 038 (catálogo de nodos) sube, baja y vuelve a subir idéntica.

`docs/ESPEC_catalogo_nodos.md` §1.5 y C5. Usa las funciones de
`test_migracion_035.py` (ERR-24: los campos enumerados).
"""
from __future__ import annotations

import pytest

from tests.integ.test_migracion_035 import cargar, resumen, sube_baja_sube

pytestmark = pytest.mark.integ

TABLAS = ("curriculum_nodes",)
M038 = cargar("038_catalogo_nodos.py")


def test_mg38_sube_baja_y_vuelve_a_subir_identica(integ) -> None:
    """MG38 (C5): up/down/up con el mismo esquema, y subir dos veces no falla."""
    visto = sube_baja_sube(integ, M038, TABLAS)
    observado = resumen(visto, TABLAS)
    assert observado == {
        "con_rls_y_sin_politicas": dict.fromkeys(TABLAS, (True, True, 0)),
        "restricciones": {"curriculum_nodes": [
            "curriculum_nodes_id_check", "curriculum_nodes_pkey",
            "curriculum_nodes_replaced_by_fkey", "curriculum_nodes_replaced_check"]},
        "indices": {"curriculum_nodes": ["curriculum_nodes_pkey"]},
        "tras_bajar": dict.fromkeys(TABLAS, {"existe": False}),
        "segunda_igual_a_la_primera": True, "repetida_igual_a_la_primera": True,
    }, f"MG38: {observado}\nprimera: {visto['primera']}\nsegunda: {visto['segunda']}"
