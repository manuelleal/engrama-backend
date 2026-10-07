"""MG40: la migración 040 (el foco del grupo) sube, baja y vuelve a subir idéntica.

`docs/ESPEC_foco_grupo.md` §1.5 y C7. Usa las funciones de
`test_migracion_035.py` (ERR-24: los campos enumerados). Aquí hay una tabla
nueva (`group_focus`) y una columna nueva en una tabla que YA existía
(`challenge_questions.nodes`): de esta se compara que las dos subidas den lo
mismo, que al bajar la columna y su índice desaparezcan, y que lo demás siga.
"""
from __future__ import annotations

from typing import Any

import pytest

from tests.integ.test_migracion_035 import cargar, sube_baja_sube

pytestmark = pytest.mark.integ

TABLAS = ("group_focus", "challenge_questions")
M040 = cargar("040_foco_grupo.py")


def _columnas(esquema: dict[str, Any]) -> list[str]:
    return [c[0] for c in esquema.get("columnas", [])]


def _indices(esquema: dict[str, Any]) -> list[str]:
    return [i[0] for i in esquema.get("indices", [])]


def test_mg40_sube_baja_y_vuelve_a_subir_identica(integ) -> None:
    """MG40 (C7): up/down/up con el mismo esquema, y subir dos veces no falla."""
    visto = sube_baja_sube(integ, M040, TABLAS)
    primera, bajada = visto["primera"], visto["tras_bajar"]
    foco, preguntas = primera["group_focus"], primera["challenge_questions"]
    observado = {
        "foco_con_rls_y_sin_politicas": (foco.get("existe"), foco.get("rls"),
                                         foco.get("politicas")),
        "restricciones_del_foco": [r[0] for r in foco.get("restricciones", [])],
        "indices_del_foco": _indices(foco),
        "la_pregunta_tiene_nodes": "nodes" in _columnas(preguntas),
        "el_indice_de_nodes": "idx_challenge_questions_nodes" in _indices(preguntas),
        "tras_bajar": {
            "foco": bajada["group_focus"],
            "la_pregunta_sigue": bajada["challenge_questions"].get("existe"),
            "sin_nodes": "nodes" not in _columnas(bajada["challenge_questions"]),
            "sin_el_indice": "idx_challenge_questions_nodes" not in _indices(
                bajada["challenge_questions"]),
            "sus_politicas_siguen": bajada["challenge_questions"].get("politicas")
            == preguntas.get("politicas"),
            "las_demas_columnas_siguen": sorted(_columnas(bajada["challenge_questions"]))
            == sorted(c for c in _columnas(preguntas) if c != "nodes"),
        },
        "segunda_igual_a_la_primera": visto["segunda"] == primera,
        "repetida_igual_a_la_primera": visto["repetida"] == primera,
    }
    assert observado == {
        "foco_con_rls_y_sin_politicas": (True, True, 0),
        "restricciones_del_foco": [
            "group_focus_dates_check", "group_focus_group_id_fkey",
            "group_focus_group_start_key", "group_focus_nodes_check", "group_focus_pkey",
            "group_focus_set_by_fkey", "group_focus_tenant_id_fkey"],
        "indices_del_foco": ["group_focus_group_start_key", "group_focus_pkey"],
        "la_pregunta_tiene_nodes": True, "el_indice_de_nodes": True,
        "tras_bajar": {"foco": {"existe": False}, "la_pregunta_sigue": True, "sin_nodes": True,
                       "sin_el_indice": True, "sus_politicas_siguen": True,
                       "las_demas_columnas_siguen": True},
        "segunda_igual_a_la_primera": True, "repetida_igual_a_la_primera": True,
    }, f"MG40: {observado}\nprimera: {primera}\nsegunda: {visto['segunda']}"
