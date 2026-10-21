"""CU1 a CU5: las reglas puras del camino — docs/ESPEC_camino_progreso.md §2.

Sin base. Lo observado va en un dict que se compara ENTERO; el mensaje lleva el
dict para que los tramposos (`tests/tramposos/test_tramposos_camino.py`) digan
por qué se pusieron rojos.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from src.camino import reglas
from src.camino.reglas import Demorada, Estacion, Intento, Umbrales

U = Umbrales(completada=70, dominada=80, dias_atasco=7, dias_dominio=7, minimo_demoradas=3)
T0 = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)


def dia(n: float) -> datetime:
    return T0 + timedelta(days=n)


def cerrado(aciertos: int, cuando: float = 0, gano: bool = False) -> Intento:
    return Intento("completed", dia(cuando), dia(cuando), aciertos, gano)


def estacion(nombre: str, preguntas: int, *intentos: Intento, escrita: bool = False,
             max_intentos: int = 2) -> Estacion:
    return Estacion(nombre, nombre, "grammar", "fill_blank" if escrita else "multiple_choice",
                    preguntas, max_intentos, escrita, tuple(intentos))


def estado(*estaciones: Estacion, demoradas: tuple[Demorada, ...] = ()) -> str:
    return reglas.estado_de(estaciones, demoradas, U).estado


def test_cu1_los_estados() -> None:
    """CU1: sin empezar, en curso, completada (todas jugadas y ≥ 70 %); el mejor intento manda."""
    e = reglas.estado_de([estacion("a", 3, cerrado(1), cerrado(3, 1))], [], U)
    observado: dict[str, Any] = {
        "sin_intentos": estado(estacion("a", 5), estacion("b", 5)),
        "una_de_dos": estado(estacion("a", 5, cerrado(5)), estacion("b", 5)),
        "abierto_sin_cerrar": estado(estacion("a", 5, Intento("in_progress", T0, None, 0, False)),
                                     estacion("b", 5)),
        "todas_7_de_10": estado(estacion("a", 5, cerrado(4)), estacion("b", 5, cerrado(3))),
        "todas_6_de_10": estado(estacion("a", 5, cerrado(3)), estacion("b", 5, cerrado(3))),
        "una_jugada_al_100_y_otra_sin_jugar": estado(estacion("a", 9, cerrado(9)),
                                                     estacion("b", 1)),
        "mejor_intento": (e.estado, e.aciertos, e.porcentaje, e.completada_en == dia(1)),
        "porcentaje_de_lo_jugado": reglas.estado_de(
            [estacion("a", 4, cerrado(3)), estacion("b", 6)], [], U).porcentaje,
    }
    assert observado == {
        "sin_intentos": "sin_empezar", "una_de_dos": "en_curso", "abierto_sin_cerrar": "en_curso",
        "todas_7_de_10": "completada", "todas_6_de_10": "en_curso",
        "una_jugada_al_100_y_otra_sin_jugar": "en_curso",
        "mejor_intento": ("completada", 3, 100, True), "porcentaje_de_lo_jugado": 75,
    }, f"CU1: {observado}"


def _demoradas(dias: float, *aciertos: bool, escrita: bool = False) -> tuple[Demorada, ...]:
    return tuple(Demorada(dia(dias), a, escrita) for a in aciertos)


def test_cu2_dominada_solo_con_evidencia_demorada() -> None:
    """CU2: completada + 3 demoradas a 7 días o más, ≥ 80 %, y una escrita acertada si hay escritas."""
    mc = estacion("a", 3, cerrado(3, 0))
    con_escrita = (estacion("a", 3, cerrado(3, 0)), estacion("w", 2, cerrado(2, 0), escrita=True))
    observado: dict[str, Any] = {
        "tres_a_7_dias": estado(mc, demoradas=_demoradas(7, True, True, True)),
        "tres_a_6_dias_23_h": estado(mc, demoradas=_demoradas(7 - 1 / 24, True, True, True)),
        "solo_dos": estado(mc, demoradas=_demoradas(8, True, True)),
        "cuatro_de_cinco": estado(mc, demoradas=_demoradas(9, True, True, True, True, False)),
        "tres_de_cinco": estado(mc, demoradas=_demoradas(9, True, True, True, False, False)),
        "las_tempranas_no_cuentan": estado(
            mc, demoradas=_demoradas(1, True, True, True) + _demoradas(8, True, False)),
        "escritas_sin_escrita_acertada": estado(*con_escrita,
                                                demoradas=_demoradas(8, True, True, True)),
        "escritas_con_escrita_acertada": estado(
            *con_escrita, demoradas=_demoradas(8, True, True) + _demoradas(8, True, escrita=True)),
        "en_curso_no_se_domina": estado(estacion("a", 3, cerrado(1)),
                                        demoradas=_demoradas(9, True, True, True)),
    }
    assert observado == {
        "tres_a_7_dias": "dominada", "tres_a_6_dias_23_h": "completada", "solo_dos": "completada",
        "cuatro_de_cinco": "dominada", "tres_de_cinco": "completada",
        "las_tempranas_no_cuentan": "completada",
        "escritas_sin_escrita_acertada": "completada",
        "escritas_con_escrita_acertada": "dominada", "en_curso_no_se_domina": "en_curso",
    }, f"CU2: {observado}"


def _camino(unidades: list[list[Estacion]], ahora: datetime) -> tuple[list[tuple[str, str]], Any]:
    estados = [reglas.estado_de(u, [], U) for u in unidades]
    acc = reglas.accesos(estados, ahora, U)
    return [(e.estado, a.acceso) for e, a in zip(estados, acc, strict=True)], (
        reglas.recomendada(estados, acc), [a.se_abre_el for a in acc], [a.atascada for a in acc])


def test_cu3_el_bloqueo_suave() -> None:
    """CU3: la 2 se abre al completar la 1, o sola a los 7 días de la 1 en curso (con apoyo)."""
    en_curso = [estacion("a", 5, cerrado(1, 0)), estacion("b", 5)]
    completa = [estacion("a", 5, cerrado(5, 0))]
    nada = [estacion("c", 5)]
    observado: dict[str, Any] = {
        "al_empezar": _camino([[estacion("a", 5)], nada, nada], dia(0)),
        "en_curso_3_dias": _camino([en_curso, nada, nada], dia(3)),
        "en_curso_6_dias_23_h": _camino([en_curso, nada, nada], dia(7 - 1 / 24))[0],
        "en_curso_7_dias": _camino([en_curso, nada, nada], dia(7)),
        "completada_abre_la_2": _camino([completa, nada, nada], dia(1)),
        "empezada_nunca_bloqueada": _camino([en_curso, [estacion("d", 2, cerrado(0, 1))], nada],
                                            dia(2))[0],
    }
    se_abre = dia(7)
    assert observado == {
        "al_empezar": ([("sin_empezar", "abierta"), ("sin_empezar", "bloqueada"),
                        ("sin_empezar", "bloqueada")], (0, [None, None, None], [False] * 3)),
        "en_curso_3_dias": ([("en_curso", "abierta"), ("sin_empezar", "bloqueada"),
                             ("sin_empezar", "bloqueada")],
                            (0, [None, se_abre, None], [False] * 3)),
        "en_curso_6_dias_23_h": [("en_curso", "abierta"), ("sin_empezar", "bloqueada"),
                                 ("sin_empezar", "bloqueada")],
        "en_curso_7_dias": ([("en_curso", "abierta"), ("sin_empezar", "abierta_con_apoyo"),
                             ("sin_empezar", "bloqueada")],
                            (1, [None, None, None], [True, False, False])),
        "completada_abre_la_2": ([("completada", "abierta"), ("sin_empezar", "abierta"),
                                  ("sin_empezar", "bloqueada")],
                                 (1, [None, None, None], [False] * 3)),
        "empezada_nunca_bloqueada": [("en_curso", "abierta"), ("en_curso", "abierta"),
                                     ("sin_empezar", "bloqueada")],
    }, f"CU3: {observado}"


def test_cu4_la_recomendada() -> None:
    """CU4: la primera abierta sin completar; nada si todo está completo; la atascada cede."""
    completa = [estacion("a", 2, cerrado(2, 0))]
    en_curso_viejo = [estacion("a", 5, cerrado(1, 0)), estacion("b", 5)]
    empezada_luego = [estacion("d", 2, cerrado(0, 5))]
    observado: dict[str, Any] = {
        "todo_completo": _camino([completa, completa], dia(1))[1][0],
        "la_primera_sin_completar": _camino([completa, [estacion("b", 2)]], dia(1))[1][0],
        "atascada_cede_a_la_empezada": _camino([en_curso_viejo, empezada_luego], dia(10))[1],
        "la_ultima_no_se_atasca": _camino([completa, en_curso_viejo], dia(30))[1],
    }
    assert observado == {
        "todo_completo": None, "la_primera_sin_completar": 1,
        "atascada_cede_a_la_empezada": (1, [None, None], [True, False]),
        "la_ultima_no_se_atasca": (1, [None, None], [False, False]),
    }, f"CU4: {observado}"


def test_cu5_titulo_y_numero() -> None:
    """CU5: el título humano y el número salen del topic y del título del sembrador; sin calce, nada."""
    t = "a1-u03-daily-routine"
    observado = {
        "sembrado": (reglas.numero_de(t, 9),
                     reglas.titulo_de(t, f"{t} · Daily Routine · Gramática 1 · original")),
        "borrador": reglas.titulo_de(t, f"[BORRADOR] {t} · Daily Routine · Lectura 1"),
        "otro_topic": reglas.titulo_de(t, "a1-u04 · Otra · Gramática 1 · original"),
        "a_mano": reglas.titulo_de(t, "Reto del lunes"),
        "sin_numero": reglas.numero_de("unidad-libre", 4),
        "corto": reglas.numero_de("a2-u12", 1),
    }
    assert observado == {
        "sembrado": (3, "Daily Routine"), "borrador": "Daily Routine", "otro_topic": None,
        "a_mano": None, "sin_numero": 4, "corto": 12,
    }, f"CU5: {observado}"


def test_cu6_puede_jugar() -> None:
    """La estación que sigue: no ganada y con intentos, o con uno abierto para retomar."""
    abierto = Intento("in_progress", T0, None, 0, False)
    observado = {
        "nueva": estacion("a", 2).puede_jugar,
        "ganada": estacion("a", 2, cerrado(2, gano=True)).puede_jugar,
        "sin_intentos": estacion("a", 2, cerrado(0), cerrado(1)).puede_jugar,
        "uno_abierto_sin_intentos": estacion("a", 2, cerrado(0), abierto).puede_jugar,
    }
    assert observado == {"nueva": True, "ganada": False, "sin_intentos": False,
                         "uno_abierto_sin_intentos": True}, f"CU6: {observado}"
