"""UF1: las piezas puras del foco del grupo — `docs/ESPEC_foco_grupo.md` §2, C1. No-integ."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from src.challenge_engine.schemas import ChallengeQuestionOut
from src.foco import fechas, logro
from src.foco import service as foco_service


@dataclass(frozen=True)
class _Reto:
    id: UUID
    nombre: str


def _dia(texto: str) -> date:
    return date.fromisoformat(texto)


def _solapan(a: tuple[str, str], b: tuple[str, str]) -> bool:
    return fechas.se_solapan(_dia(a[0]), _dia(a[1]), _dia(b[0]), _dia(b[1]))


def test_uf1_piezas_puras_del_foco() -> None:
    """UF1 (C1): el estado de un nodo en sus bordes, el solape, "hoy" y priorizar."""
    retos = [_Reto(uuid4(), n) for n in "abcde"]
    en_foco = {retos[1].id, retos[3].id, uuid4()}
    priorizados: list[Any] = foco_service.priorizar(retos, en_foco)  # type: ignore[arg-type]
    sin_foco: list[Any] = foco_service.priorizar(retos, set())  # type: ignore[arg-type]
    semana = ("2026-10-05", "2026-10-11")
    observado = {
        "estado": {
            "4_estudiantes": logro.estado_del_nodo(4, 40, 40),
            "5_estudiantes_7_items": logro.estado_del_nodo(5, 7, 7),
            "80_por_ciento": logro.estado_del_nodo(5, 10, 8),
            "79_por_ciento": logro.estado_del_nodo(5, 100, 79),
            "60_por_ciento": logro.estado_del_nodo(5, 10, 6),
            "59_por_ciento": logro.estado_del_nodo(5, 100, 59),
            "sin_nada": logro.estado_del_nodo(0, 0, 0),
        },
        "solape": {
            "el_dia_despues": _solapan(semana, ("2026-10-12", "2026-10-18")),
            "el_ultimo_dia": _solapan(semana, ("2026-10-11", "2026-10-12")),
            "el_primer_dia": _solapan(semana, ("2026-10-01", "2026-10-05")),
            "el_dia_antes": _solapan(semana, ("2026-10-01", "2026-10-04")),
            "contenido": _solapan(semana, ("2026-10-07", "2026-10-07")),
        },
        "hoy": {
            # 23:30 en Bogotá del 6 son las 04:30 UTC del 7: sigue siendo el 6.
            "bogota_a_las_23_30": str(fechas.hoy(datetime(2026, 10, 7, 4, 30, tzinfo=UTC), -5)),
            "bogota_a_las_00_30": str(fechas.hoy(datetime(2026, 10, 7, 5, 30, tzinfo=UTC), -5)),
            "sin_desfase": str(fechas.hoy(datetime(2026, 10, 7, 4, 30, tzinfo=UTC), 0)),
        },
        "duracion": {
            "62_dias": fechas.duracion_valida(_dia("2027-01-01"), _dia("2027-03-04")),
            "63_dias": fechas.duracion_valida(_dia("2027-01-01"), _dia("2027-03-05")),
            "al_reves": fechas.duracion_valida(_dia("2027-01-02"), _dia("2027-01-01")),
            "un_dia": fechas.duracion_valida(_dia("2027-01-01"), _dia("2027-01-01")),
            "por_defecto": str(fechas.hasta_por_defecto(_dia("2026-10-05"))),
        },
        "priorizar": {
            "orden": "".join(r.nombre for r in priorizados),
            "sin_foco": "".join(r.nombre for r in sin_foco),
            "mismos": sorted(r.nombre for r in priorizados) == list("abcde"),
        },
        "campos_de_la_pregunta_del_estudiante": sorted(ChallengeQuestionOut.model_fields),
    }
    assert observado == {
        "estado": {"4_estudiantes": "datos_insuficientes",
                   "5_estudiantes_7_items": "datos_insuficientes",
                   "80_por_ciento": "logrado", "79_por_ciento": "en_desarrollo",
                   "60_por_ciento": "en_desarrollo", "59_por_ciento": "a_reforzar",
                   "sin_nada": "datos_insuficientes"},
        "solape": {"el_dia_despues": False, "el_ultimo_dia": True, "el_primer_dia": True,
                   "el_dia_antes": False, "contenido": True},
        "hoy": {"bogota_a_las_23_30": "2026-10-06", "bogota_a_las_00_30": "2026-10-07",
                "sin_desfase": "2026-10-07"},
        "duracion": {"62_dias": True, "63_dias": False, "al_reves": False, "un_dia": True,
                     "por_defecto": "2026-10-11"},
        "priorizar": {"orden": "bdace", "sin_foco": "abcde", "mismos": True},
        "campos_de_la_pregunta_del_estudiante": [
            "id", "options_json", "order_index", "question_text", "question_type"],
    }, f"UF1: {observado}"
