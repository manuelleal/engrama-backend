"""Tramposos SIN Docker de T5/T7 — ESPEC §3, §4: X11-X16, X19 y X20.

Mismo patrón que `test_tramposos_como.py`: una versión ROTA de una función
pura, se corre el test real (U3*, U5, U6) y se exige `AssertionError`. Ninguno
lleva `pytestmark = pytest.mark.integ` — ni el tramposo ni el test real tocan
la base (§2.1, §2.3 son funciones puras que reciben `now`).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

import pytest

import src.teachers.service.achievement as achievement_mod
import src.teachers.service.item_errors as item_errors_mod
import tests.teachers.test_achievement_unit as u3
import tests.teachers.test_item_errors_unit as u56


# =============================================================================
# X11 — usa el ÚLTIMO intento, no el primero.
# =============================================================================
def _primeros_intentos_ultimo(intentos: list[Any]) -> dict[Any, Any]:
    por_challenge: dict[Any, list[Any]] = defaultdict(list)
    for a in intentos:
        por_challenge[a.challenge_id].append(a)
    return {
        cid: max(lst, key=lambda a: (a.completed_at, a.started_at, str(a.attempt_id)))
        for cid, lst in por_challenge.items()
    }


# =============================================================================
# X12 — aplica la ventana ANTES de elegir el primer intento.
# =============================================================================
def _primeros_en_ventana_ventana_primero(intentos: list[Any], now: Any) -> list[Any]:
    limite = now - timedelta(days=achievement_mod.WINDOW_DAYS)
    en_alcance = [
        a for a in intentos
        if a.challenge_type not in achievement_mod.EXCLUDED_TYPES and a.completed_at >= limite
    ]
    primeros = achievement_mod._primeros_intentos(en_alcance)  # noqa: SLF001
    return list(primeros.values())


# =============================================================================
# X13 — el mínimo, SIN la condición de 3 retos.
# =============================================================================
def _axis_status_sin_min_retos(items: int, correct: int, _n_retos: int) -> str:
    if items >= achievement_mod.MIN_ITEMS:  # BUG: falta `and n_retos >= MIN_CHALLENGES`
        if 100 * correct >= achievement_mod.THRESHOLD_LOGRADO * items:
            return "logrado"
        if 100 * correct >= achievement_mod.THRESHOLD_EN_DESARROLLO * items:
            return "en_desarrollo"
        return "a_reforzar"
    return "datos_insuficientes"


# =============================================================================
# X14 — el umbral de 80, exclusivo (`>` en vez de `>=`).
# =============================================================================
def _axis_status_umbral_exclusivo(items: int, correct: int, n_retos: int) -> str:
    if items >= achievement_mod.MIN_ITEMS and n_retos >= achievement_mod.MIN_CHALLENGES:
        if 100 * correct > achievement_mod.THRESHOLD_LOGRADO * items:  # BUG: `>` no `>=`
            return "logrado"
        if 100 * correct >= achievement_mod.THRESHOLD_EN_DESARROLLO * items:
            return "en_desarrollo"
        return "a_reforzar"
    return "datos_insuficientes"


# =============================================================================
# X15 — una skill desconocida cae en Accuracy (en vez de `unmapped_items`).
# =============================================================================
def _skill_to_axis_todo_a_accuracy(skill: str | None) -> str | None:
    normalizado = achievement_mod.normalize_skill(skill)
    if normalizado is None:
        return None
    return achievement_mod._AXIS_MAP.get(normalizado, "Accuracy")  # noqa: SLF001


# =============================================================================
# X16 — incluye los retos `open`.
# =============================================================================
def _primeros_en_ventana_con_open(intentos: list[Any], now: Any) -> list[Any]:
    limite = now - timedelta(days=achievement_mod.WINDOW_DAYS)
    primeros = achievement_mod._primeros_intentos(intentos)  # noqa: SLF001 — BUG: no excluye 'open'
    return [p for p in primeros.values() if p.completed_at >= limite]


# =============================================================================
# X19 — el distractor cuenta la opción correcta.
# =============================================================================
def _es_la_opcion_correcta_nunca(_opcion: Any, _correct_answer: Any) -> bool:
    return False  # BUG: nunca excluye la opción correcta


# =============================================================================
# X20 — T7 sin la supresión de menos de 5 respondientes.
# =============================================================================
def _compute_item_errors_sin_supresion(
    calificados: Any, preguntas: Any, *, min_respondents: int = 0
) -> Any:
    return item_errors_mod.compute_item_errors(calificados, preguntas, min_respondents=0)


TRAMPOSOS: dict[str, tuple[str, Any, Any, str]] = {
    "X11": ("achievement_mod", "_primeros_intentos", _primeros_intentos_ultimo,
           "u3.test_u3a_primer_intento_manda_no_el_reintento"),
    "X12": ("achievement_mod", "primeros_en_ventana", _primeros_en_ventana_ventana_primero,
           "u3.test_u3b_ventana_de_28_dias"),
    "X13": ("achievement_mod", "_axis_status", _axis_status_sin_min_retos,
           "u3.test_u3c_minimo_8_items_3_retos"),
    "X14": ("achievement_mod", "_axis_status", _axis_status_umbral_exclusivo,
           "u3.test_u3d_umbrales_n_10"),
    "X15": ("achievement_mod", "skill_to_axis", _skill_to_axis_todo_a_accuracy,
           "u3.test_u3e_mapeo_normaliza_y_desconocidas_van_a_unmapped"),
    "X16": ("achievement_mod", "primeros_en_ventana", _primeros_en_ventana_con_open,
           "u3.test_u3g_reto_open_no_aporta_items"),
    "X19": ("item_errors_mod", "_es_la_opcion_correcta", _es_la_opcion_correcta_nunca,
           "u56.test_u5_distractor"),
    # `u56` importó `compute_item_errors` con `from ... import` (nombre propio):
    # parchar el módulo de origen no alcanzaría a su llamada. Se parcha `u56`
    # mismo, igual que `test_tramposos_como.py` parcha el módulo que llama.
    "X20": ("u56", "compute_item_errors", _compute_item_errors_sin_supresion,
           "u56.test_u6_supresion_4_suprime_5_visible"),
}

_MODULOS = {
    "achievement_mod": achievement_mod, "item_errors_mod": item_errors_mod,
    "u3": u3, "u56": u56,
}
_TESTS = {"u3": u3, "u56": u56}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_logro_pone_rojo_su_test(monkeypatch: pytest.MonkeyPatch, clave: str) -> None:
    modulo_nombre, atributo, roto, test_ref = TRAMPOSOS[clave]
    monkeypatch.setattr(_MODULOS[modulo_nombre], atributo, roto)
    mod_test, nombre_test = test_ref.split(".")
    test_real = getattr(_TESTS[mod_test], nombre_test)
    with pytest.raises(AssertionError):
        test_real()
