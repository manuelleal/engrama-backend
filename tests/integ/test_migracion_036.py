"""MG36: la migración 036 (solicitudes sobre datos) sube, baja y vuelve a subir idéntica.

`docs/ESPEC_solicitud_datos.md` §1.7 y C7. Usa las funciones de
`test_migracion_035.py`: el SQL de la migración (las tuplas `SQL_SUBIR` y
`SQL_BAJAR` de su archivo) dentro de una transacción que SIEMPRE se deshace, y
la comparación con los campos enumerados (ERR-24), sin `ordinal_position`.
"""
from __future__ import annotations

import pytest

from tests.integ.test_migracion_035 import cargar, resumen, sube_baja_sube

pytestmark = pytest.mark.integ

TABLAS = ("solicitudes_datos",)
M036 = cargar("036_solicitudes_datos.py")


def test_mg36_sube_baja_y_vuelve_a_subir_identica(integ) -> None:
    """MG36 (C7): up/down/up con el mismo esquema, y subir dos veces no falla."""
    visto = sube_baja_sube(integ, M036, TABLAS)
    observado = resumen(visto, TABLAS)
    assert observado == {
        "con_rls_y_sin_politicas": {"solicitudes_datos": (True, True, 0)},
        "restricciones": {"solicitudes_datos": [
            "solicitudes_datos_estado_check", "solicitudes_datos_mensaje_check",
            "solicitudes_datos_pkey", "solicitudes_datos_profile_id_fkey",
            "solicitudes_datos_respondida_por_fkey", "solicitudes_datos_respuesta_check",
            "solicitudes_datos_tenant_id_fkey", "solicitudes_datos_tipo_check",
            "solicitudes_datos_traza_check"]},
        "indices": {"solicitudes_datos": [
            "idx_solicitudes_datos_perfil", "idx_solicitudes_datos_tenant",
            "solicitudes_datos_pkey"]},
        "tras_bajar": {"solicitudes_datos": {"existe": False}},
        "segunda_igual_a_la_primera": True, "repetida_igual_a_la_primera": True,
    }, f"MG36: {observado}\nprimera: {visto['primera']}\nsegunda: {visto['segunda']}"
