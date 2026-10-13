"""MG42: la migración 042 (la racha semanal) sube, baja y vuelve a subir idéntica.

`docs/ESPEC_racha_semanal.md` §1.4 y C11. Usa las funciones de
`test_migracion_035.py` (ERR-24). Dos tablas nuevas; nada existente cambia.

Desde la 044 (`docs/ESPEC_solo_refuerzo.md` §4) `activity_days` tiene una
columna más (`sin_contenido`), así que lo que sube, baja y vuelve a subir
idéntico es la CADENA 042 + 044: bajar la 042 sola y subirla dejaría la tabla
sin esa columna, que es justo lo que hace Alembic si se salta la 044.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.integ.test_migracion_035 import cargar, resumen, sube_baja_sube

pytestmark = pytest.mark.integ

TABLAS = ("activity_days", "streak_state")
M042 = cargar("042_racha_semanal.py")
M044 = cargar("044_solo_refuerzo.py")
CADENA = SimpleNamespace(SQL_SUBIR=(*M042.SQL_SUBIR, *M044.SQL_SUBIR),
                         SQL_BAJAR=(*M044.SQL_BAJAR, *M042.SQL_BAJAR))


def test_mg42_sube_baja_y_vuelve_a_subir_identica(integ) -> None:
    """MG42 (C11): up/down/up con el mismo esquema, y subir dos veces no falla."""
    observado = resumen(sube_baja_sube(integ, CADENA, TABLAS), TABLAS)
    assert observado == {
        "con_rls_y_sin_politicas": dict.fromkeys(TABLAS, (True, True, 0)),
        "restricciones": {
            "activity_days": [
                "activity_days_counts_check", "activity_days_owner_date_key",
                "activity_days_pkey", "activity_days_profile_id_fkey",
                "activity_days_tenant_id_fkey"],
            "streak_state": [
                "streak_state_counts_check", "streak_state_owner_key", "streak_state_pkey",
                "streak_state_profile_id_fkey", "streak_state_tenant_id_fkey"],
        },
        "indices": {
            "activity_days": ["activity_days_owner_date_key", "activity_days_pkey"],
            "streak_state": ["streak_state_owner_key", "streak_state_pkey"],
        },
        "tras_bajar": dict.fromkeys(TABLAS, {"existe": False}),
        "segunda_igual_a_la_primera": True, "repetida_igual_a_la_primera": True,
    }, f"MG42: {observado}"
