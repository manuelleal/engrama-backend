"""MG45: la migración 045 (la corrección por pregunta) sube, baja y vuelve a subir idéntica.

`docs/ESPEC_l1_correccion_por_pregunta.md` §10.5 y C13. Usa las funciones de
`test_migracion_035.py` (ERR-24). Una tabla nueva y cinco columnas en tablas
que ya existían: al bajar se van solo ellas.
"""
from __future__ import annotations

from typing import Any

import pytest

from tests.integ.test_migracion_035 import cargar, sube_baja_sube

pytestmark = pytest.mark.integ

NUEVA = "challenge_attempt_answers"
COLUMNAS = {"challenge_questions": {"explanation", "accepted_answers", "tolerance",
                                    "hint_initial"},
            "challenge_attempts": {"served_questions"}}
TABLAS = (NUEVA, *COLUMNAS)
M045 = cargar("045_correccion_por_pregunta.py")


def _nombres(esquema: dict[str, Any], que: str) -> list[str]:
    return [fila[0] for fila in esquema.get(que, [])]


def _columnas(esquema: dict[str, Any]) -> dict[str, tuple[Any, ...]]:
    return {fila[0]: tuple(fila[1:4]) for fila in esquema.get("columnas", [])}


def test_mg45_sube_baja_y_vuelve_a_subir_identica(integ) -> None:
    """MG45 (C13): up/down/up con el mismo esquema, y subir dos veces no falla."""
    visto = sube_baja_sube(integ, M045, TABLAS)
    primera, bajada = visto["primera"], visto["tras_bajar"]
    observado = {
        "con_rls_y_sin_politicas": (primera[NUEVA].get("existe"), primera[NUEVA].get("rls"),
                                    primera[NUEVA].get("politicas")),
        "restricciones": _nombres(primera[NUEVA], "restricciones"),
        "indices": _nombres(primera[NUEVA], "indices"),
        # (tipo, ¿acepta NULL?, valor por defecto): lo que ya existe queda sin
        # explicación, exacto, sin pista y con las preguntas del reto.
        "las_columnas": {t: {c: _columnas(primera[t]).get(c) for c in sorted(cs)}
                         for t, cs in COLUMNAS.items()},
        "el_check_de_la_tolerancia": "challenge_questions_tolerance_check" in _nombres(
            primera["challenge_questions"], "restricciones"),
        "tras_bajar": {
            "la_tabla": bajada[NUEVA],
            "pierden_solo_eso": {
                t: sorted(_columnas(bajada[t])) == sorted(
                    x for x in _columnas(primera[t]) if x not in cs)
                for t, cs in COLUMNAS.items()},
            "sin_el_check": "challenge_questions_tolerance_check" not in _nombres(
                bajada["challenge_questions"], "restricciones"),
        },
        "segunda_igual_a_la_primera": visto["segunda"] == primera,
        "repetida_igual_a_la_primera": visto["repetida"] == primera,
    }
    assert observado == {
        "con_rls_y_sin_politicas": (True, True, 0),
        "restricciones": [
            "challenge_attempt_answers_attempt_id_fkey",
            "challenge_attempt_answers_attempt_question_key", "challenge_attempt_answers_pkey",
            "challenge_attempt_answers_profile_id_fkey",
            "challenge_attempt_answers_question_id_fkey",
            "challenge_attempt_answers_tenant_id_fkey"],
        "indices": ["challenge_attempt_answers_attempt_question_key",
                    "challenge_attempt_answers_pkey", "idx_challenge_attempt_answers_owner"],
        "las_columnas": {
            "challenge_questions": {
                "accepted_answers": ("ARRAY", "YES", None), "explanation": ("jsonb", "YES", None),
                "hint_initial": ("boolean", "NO", "false"),
                "tolerance": ("text", "NO", "'exacta'::text")},
            "challenge_attempts": {"served_questions": ("ARRAY", "YES", None)},
        },
        "el_check_de_la_tolerancia": True,
        "tras_bajar": {"la_tabla": {"existe": False},
                       "pierden_solo_eso": dict.fromkeys(COLUMNAS, True), "sin_el_check": True},
        "segunda_igual_a_la_primera": True, "repetida_igual_a_la_primera": True,
    }, f"MG45: {observado}"
