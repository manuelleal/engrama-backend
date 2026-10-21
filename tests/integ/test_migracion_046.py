"""MG46: la migración 046 (el pase acotado) sube, baja y vuelve a subir idéntica.

`docs/ESPEC_pase_acotado.md` §1.5. Usa las funciones de `test_migracion_035.py`
(ERR-24). Una sola tabla nueva: al bajar se va solo ella.
"""
from __future__ import annotations

from typing import Any

import pytest

from tests.integ.test_migracion_035 import cargar, sube_baja_sube

pytestmark = pytest.mark.integ

NUEVA = "anillo_pases"
M046 = cargar("046_anillo_pases.py")


def _nombres(esquema: dict[str, Any], que: str) -> list[str]:
    return [fila[0] for fila in esquema.get(que, [])]


def test_mg46_sube_baja_y_vuelve_a_subir_identica(integ) -> None:
    """MG46: up/down/up con el mismo esquema, y subir dos veces no falla."""
    visto = sube_baja_sube(integ, M046, (NUEVA,))
    primera = visto["primera"][NUEVA]
    observado = {
        "con_rls_y_sin_politicas": (primera.get("existe"), primera.get("rls"),
                                    primera.get("politicas")),
        "restricciones": _nombres(primera, "restricciones"),
        "indices": _nombres(primera, "indices"),
        "tras_bajar": visto["tras_bajar"][NUEVA],
        "segunda_igual_a_la_primera": visto["segunda"][NUEVA] == primera,
        "repetida_igual_a_la_primera": visto["repetida"][NUEVA] == primera,
    }
    assert observado == {
        "con_rls_y_sin_politicas": (True, True, 0),
        "restricciones": [
            "anillo_pases_audiencia_check", "anillo_pases_hash_check", "anillo_pases_hash_key",
            "anillo_pases_pkey", "anillo_pases_profile_id_fkey", "anillo_pases_tenant_id_fkey"],
        "indices": ["anillo_pases_hash_key", "anillo_pases_pkey", "idx_anillo_pases_expira",
                    "idx_anillo_pases_perfil"],
        "tras_bajar": {"existe": False},
        "segunda_igual_a_la_primera": True, "repetida_igual_a_la_primera": True,
    }, f"MG46: {observado}"
