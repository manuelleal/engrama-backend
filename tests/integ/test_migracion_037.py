"""MG37: la migración 037 (eventos del anillo) sube, baja y vuelve a subir idéntica.

`docs/ESPEC_eventos_anillo.md` §1.9 y C18. Usa las funciones de
`test_migracion_035.py`: el SQL de la migración dentro de una transacción que
SIEMPRE se deshace, y la comparación con los campos enumerados (ERR-24).
"""
from __future__ import annotations

import pytest

from tests.integ.test_migracion_035 import cargar, resumen, sube_baja_sube

pytestmark = pytest.mark.integ

TABLAS = ("learning_events", "confirmed_levels")
M037 = cargar("037_eventos_anillo.py")


def test_mg37_sube_baja_y_vuelve_a_subir_identica(integ) -> None:
    """MG37 (C18): up/down/up con el mismo esquema, y subir dos veces no falla."""
    visto = sube_baja_sube(integ, M037, TABLAS)
    observado = resumen(visto, TABLAS)
    assert observado == {
        "con_rls_y_sin_politicas": dict.fromkeys(TABLAS, (True, True, 0)),
        "restricciones": {
            "learning_events": [
                "learning_events_coins_check", "learning_events_effect_check",
                "learning_events_event_id_check", "learning_events_pkey",
                "learning_events_subject_id_fkey", "learning_events_tenant_event_key",
                "learning_events_tenant_id_fkey"],
            "confirmed_levels": [
                "confirmed_levels_cefr_check", "confirmed_levels_event_id_fkey",
                "confirmed_levels_pkey", "confirmed_levels_profile_id_fkey",
                "confirmed_levels_score_check", "confirmed_levels_source_check",
                "confirmed_levels_tenant_id_fkey", "confirmed_levels_tenant_profile_key"],
        },
        "indices": {
            "learning_events": ["idx_learning_events_session", "idx_learning_events_subject",
                                "learning_events_pkey", "learning_events_tenant_event_key"],
            "confirmed_levels": ["confirmed_levels_pkey", "confirmed_levels_tenant_profile_key"],
        },
        "tras_bajar": dict.fromkeys(TABLAS, {"existe": False}),
        "segunda_igual_a_la_primera": True, "repetida_igual_a_la_primera": True,
    }, f"MG37: {observado}\nprimera: {visto['primera']}\nsegunda: {visto['segunda']}"
