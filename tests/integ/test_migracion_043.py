"""MG43: la migración 043 (nivel de práctica y tandas) sube, baja y vuelve a subir idéntica.

`docs/ESPEC_practica_y_tanda.md` §1.3 y C10. Usa las funciones de
`test_migracion_035.py` (ERR-24). Dos tablas nuevas; nada existente cambia.
"""
from __future__ import annotations

import pytest

from tests.integ.test_migracion_035 import cargar, resumen, sube_baja_sube

pytestmark = pytest.mark.integ

TABLAS = ("practice_levels", "practice_tandas")
M043 = cargar("043_practica_y_tanda.py")


def test_mg43_sube_baja_y_vuelve_a_subir_identica(integ) -> None:
    """MG43 (C10): up/down/up con el mismo esquema, y subir dos veces no falla."""
    observado = resumen(sube_baja_sube(integ, M043, TABLAS), TABLAS)
    assert observado == {
        "con_rls_y_sin_politicas": dict.fromkeys(TABLAS, (True, True, 0)),
        "restricciones": {
            "practice_levels": [
                "practice_levels_ancla_check", "practice_levels_decisiones_check",
                "practice_levels_nivel_check", "practice_levels_owner_key",
                "practice_levels_pkey", "practice_levels_profile_id_fkey",
                "practice_levels_tenant_id_fkey"],
            "practice_tandas": [
                "practice_tandas_modo_check", "practice_tandas_numero_check",
                "practice_tandas_owner_date_numero_key", "practice_tandas_pkey",
                "practice_tandas_profile_id_fkey", "practice_tandas_tenant_id_fkey"],
        },
        "indices": {
            "practice_levels": ["practice_levels_owner_key", "practice_levels_pkey"],
            "practice_tandas": ["practice_tandas_owner_date_numero_key",
                                "practice_tandas_pkey"],
        },
        "tras_bajar": dict.fromkeys(TABLAS, {"existe": False}),
        "segunda_igual_a_la_primera": True, "repetida_igual_a_la_primera": True,
    }, f"MG43: {observado}"
