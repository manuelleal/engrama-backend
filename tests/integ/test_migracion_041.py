"""MG41: la migración 041 (la cola de refuerzo) sube, baja y vuelve a subir idéntica.

`docs/ESPEC_refuerzo.md` §1.7 y C9. Usa las funciones de `test_migracion_035.py`
(ERR-24). Dos tablas nuevas y tres columnas en `challenge_questions`: de esta
se compara que las dos subidas den lo mismo y que al bajar se vayan solo ellas.
"""
from __future__ import annotations

from typing import Any

import pytest

from tests.integ.test_migracion_035 import cargar, sube_baja_sube

pytestmark = pytest.mark.integ

NUEVAS = ("reinforcement_queue", "reinforcement_answers")
TABLAS = (*NUEVAS, "challenge_questions")
COLUMNAS = {"item_ref", "family_ref", "form_role"}
M041 = cargar("041_refuerzo.py")


def _nombres(esquema: dict[str, Any], que: str) -> list[str]:
    return [fila[0] for fila in esquema.get(que, [])]


def test_mg41_sube_baja_y_vuelve_a_subir_identica(integ) -> None:
    """MG41 (C9): up/down/up con el mismo esquema, y subir dos veces no falla."""
    visto = sube_baja_sube(integ, M041, TABLAS)
    primera, bajada = visto["primera"], visto["tras_bajar"]
    preguntas, sin = primera["challenge_questions"], bajada["challenge_questions"]
    observado = {
        "con_rls_y_sin_politicas": {t: (primera[t].get("existe"), primera[t].get("rls"),
                                        primera[t].get("politicas")) for t in NUEVAS},
        "restricciones": {t: _nombres(primera[t], "restricciones") for t in NUEVAS},
        "indices": {t: _nombres(primera[t], "indices") for t in NUEVAS},
        "la_pregunta_gana": sorted(COLUMNAS & set(_nombres(preguntas, "columnas"))),
        "su_check_y_su_indice": (
            "challenge_questions_form_role_check" in _nombres(preguntas, "restricciones"),
            "idx_challenge_questions_item_ref" in _nombres(preguntas, "indices")),
        "tras_bajar": {
            "nuevas": {t: bajada[t] for t in NUEVAS},
            "la_pregunta_pierde_solo_eso": sorted(_nombres(sin, "columnas")) == sorted(
                c for c in _nombres(preguntas, "columnas") if c not in COLUMNAS),
            "sin_el_check_ni_el_indice": (
                "challenge_questions_form_role_check" not in _nombres(sin, "restricciones"),
                "idx_challenge_questions_item_ref" not in _nombres(sin, "indices")),
            "conserva_nodes": "nodes" in _nombres(sin, "columnas"),
        },
        "segunda_igual_a_la_primera": visto["segunda"] == primera,
        "repetida_igual_a_la_primera": visto["repetida"] == primera,
    }
    assert observado == {
        "con_rls_y_sin_politicas": dict.fromkeys(NUEVAS, (True, True, 0)),
        "restricciones": {
            "reinforcement_queue": [
                "reinforcement_queue_counts_check", "reinforcement_queue_due_check",
                "reinforcement_queue_mastered_check", "reinforcement_queue_origin_check",
                "reinforcement_queue_owner_node_key", "reinforcement_queue_pkey",
                "reinforcement_queue_profile_id_fkey", "reinforcement_queue_status_check",
                "reinforcement_queue_tenant_id_fkey"],
            "reinforcement_answers": [
                "reinforcement_answers_pkey", "reinforcement_answers_profile_id_fkey",
                "reinforcement_answers_question_id_fkey",
                "reinforcement_answers_queue_id_fkey",
                "reinforcement_answers_queue_question_key",
                "reinforcement_answers_stage_check", "reinforcement_answers_tenant_id_fkey"],
        },
        "indices": {
            "reinforcement_queue": ["reinforcement_queue_owner_node_key",
                                    "reinforcement_queue_pkey"],
            "reinforcement_answers": ["idx_reinforcement_answers_profile",
                                      "reinforcement_answers_pkey",
                                      "reinforcement_answers_queue_question_key"],
        },
        "la_pregunta_gana": ["family_ref", "form_role", "item_ref"],
        "su_check_y_su_indice": (True, True),
        "tras_bajar": {"nuevas": dict.fromkeys(NUEVAS, {"existe": False}),
                       "la_pregunta_pierde_solo_eso": True,
                       "sin_el_check_ni_el_indice": (True, True), "conserva_nodes": True},
        "segunda_igual_a_la_primera": True, "repetida_igual_a_la_primera": True,
    }, f"MG41: {observado}\nprimera: {primera}\nsegunda: {visto['segunda']}"
