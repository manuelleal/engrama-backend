"""MG39: la migración 039 (la puerta del Grader) sube, baja y vuelve a subir idéntica.

`docs/ESPEC_grader_anillo.md` §9.4 y C10. Usa las funciones de
`test_migracion_035.py` (ERR-24: los campos enumerados).
"""
from __future__ import annotations

import pytest

from tests.integ.test_migracion_035 import cargar, resumen, sube_baja_sube

pytestmark = pytest.mark.integ

TABLAS = ("grader_list_numbers", "grader_exams", "grader_exam_items", "grader_sheets",
          "grader_sheet_items")
M039 = cargar("039_grader.py")


def test_mg39_sube_baja_y_vuelve_a_subir_identica(integ) -> None:
    """MG39 (C10): up/down/up con el mismo esquema, y subir dos veces no falla."""
    visto = sube_baja_sube(integ, M039, TABLAS)
    observado = resumen(visto, TABLAS)
    assert observado == {
        "con_rls_y_sin_politicas": dict.fromkeys(TABLAS, (True, True, 0)),
        "restricciones": {
            "grader_list_numbers": [
                "grader_list_numbers_group_id_fkey", "grader_list_numbers_group_numero_key",
                "grader_list_numbers_group_profile_key", "grader_list_numbers_numero_check",
                "grader_list_numbers_pkey", "grader_list_numbers_profile_id_fkey",
                "grader_list_numbers_tenant_id_fkey"],
            "grader_exams": [
                "grader_exams_created_by_fkey", "grader_exams_group_id_fkey",
                "grader_exams_huella_check", "grader_exams_n_items_check", "grader_exams_pkey",
                "grader_exams_tenant_codigo_key", "grader_exams_tenant_id_fkey"],
            "grader_exam_items": [
                "grader_exam_items_exam_id_fkey", "grader_exam_items_exam_item_key",
                "grader_exam_items_origen_check", "grader_exam_items_pkey"],
            "grader_sheets": [
                "grader_sheets_aciertos_check", "grader_sheets_enviada_por_fkey",
                "grader_sheets_exam_id_fkey", "grader_sheets_exam_numero_key",
                "grader_sheets_pkey", "grader_sheets_profile_id_fkey",
                "grader_sheets_tenant_id_fkey"],
            "grader_sheet_items": [
                "grader_sheet_items_correcta_check", "grader_sheet_items_estado_check",
                "grader_sheet_items_pkey", "grader_sheet_items_resuelta_por_fkey",
                "grader_sheet_items_sheet_id_fkey", "grader_sheet_items_sheet_item_key"],
        },
        "indices": {
            "grader_list_numbers": [
                "grader_list_numbers_group_numero_key", "grader_list_numbers_group_profile_key",
                "grader_list_numbers_pkey"],
            "grader_exams": ["grader_exams_pkey", "grader_exams_tenant_codigo_key"],
            "grader_exam_items": ["grader_exam_items_exam_item_key", "grader_exam_items_pkey",
                                  "idx_grader_exam_items_nodos"],
            "grader_sheets": ["grader_sheets_exam_numero_key", "grader_sheets_pkey",
                              "idx_grader_sheets_profile"],
            "grader_sheet_items": ["grader_sheet_items_pkey",
                                   "grader_sheet_items_sheet_item_key"],
        },
        "tras_bajar": dict.fromkeys(TABLAS, {"existe": False}),
        "segunda_igual_a_la_primera": True, "repetida_igual_a_la_primera": True,
    }, f"MG39: {observado}\nprimera: {visto['primera']}\nsegunda: {visto['segunda']}"
