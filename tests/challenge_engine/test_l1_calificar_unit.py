"""L1-U1 a L1-U5: calificar UNA respuesta y armar su explicación, puro.

`docs/ESPEC_l1_correccion_por_pregunta.md` §2 (C1 a C3) y su adenda §10.6 (C4
y C5: la explicación, el idioma y la paga del segundo intento). Sin base.
Tramposos: `tests/tramposos/test_tramposos_l1.py`.
"""
from __future__ import annotations

import unicodedata
from typing import Any

import pytest

from src.challenge_engine.service import calificar as cal
from src.challenge_engine.service.calificar import Pregunta
from src.engrama_core.service import economia
from src.shared.config import Settings

VOCABULARIO = {"fever", "fewer", "shift", "shirt", "receive", "castle", "cat", "car"}


def _escrita(aceptada: str, *, tolerancia: str = cal.EXACTA, pista: bool = False,
             otras: tuple[str, ...] = ()) -> Pregunta:
    return Pregunta("fill_blank", aceptada, accepted_answers=otras, tolerancia=tolerancia,
                    pista_inicial=pista)


def _acierta(p: Pregunta, *respuestas: str) -> dict[str, bool]:
    return {r: cal.calificar(p, r, VOCABULARIO) for r in respuestas}


def test_l1u1_la_normalizacion() -> None:
    """L1-U1 (C1): apóstrofo curvo, espacios, puntuación final y NFC; la interna se queda."""
    cafe_descompuesto = unicodedata.normalize("NFD", "café")
    observado: dict[str, Any] = {
        "normalizar": [cal.normalizar(t) for t in (
            "don’t", "  The   Cat. ", "Really?!", "“Hi”", "it's.", "‘quoted’", "ʼtis")],
        "apostrofo_curvo": cal.calificar(_escrita("don't"), "don’t"),
        "espacios_y_punto": cal.calificar(_escrita("the cat"), "  The   Cat. "),
        "nfc": cal.calificar(_escrita("café"), cafe_descompuesto),
        "la_puntuacion_interna_cuenta": cal.calificar(_escrita("it's"), "its"),
        "alguna_de_las_aceptadas": cal.calificar(_escrita("do not", otras=("don't",)), "Don’t!"),
        "vacia_nunca_acierta": cal.calificar(_escrita("x"), "   "),
    }
    assert observado == {
        "normalizar": ["don't", "the cat", "really", '"hi"', "it's", "'quoted'", "'tis"],
        "apostrofo_curvo": True, "espacios_y_punto": True, "nfc": True,
        "la_puntuacion_interna_cuenta": False, "alguna_de_las_aceptadas": True,
        "vacia_nunca_acierta": False,
    }, f"L1-U1: {observado}"


def test_l1u2_la_tolerancia_de_una_letra() -> None:
    """L1-U2 (C2): un error de tipeo sí; otra palabra válida no; 4 letras o menos, exacta."""
    observado = {
        "receive_1_letra": _acierta(_escrita("receive", tolerancia=cal.UNA_LETRA),
                                    "recive", "receeive", "recieve", "receive", "rceive"),
        "receive_exacta": _acierta(_escrita("receive"), "recive", "receive"),
        "fever_no_es_fewer": _acierta(_escrita("fever", tolerancia=cal.UNA_LETRA),
                                      "fewer", "feve", "fevar"),
        "cat_es_exacta": _acierta(_escrita("cat", tolerancia=cal.UNA_LETRA),
                                  "car", "caat", "cut", "cat"),
        "distancia": [cal.a_distancia_uno(a, b) for a, b in (
            ("abc", "abd"), ("abc", "ab"), ("abc", "abcd"), ("abc", "abc"), ("ab", "ba"),
            ("abc", "a"))],
    }
    assert observado == {
        "receive_1_letra": {"recive": True, "receeive": True, "recieve": False,
                            "receive": True, "rceive": True},
        "receive_exacta": {"recive": False, "receive": True},
        "fever_no_es_fewer": {"fewer": False, "feve": True, "fevar": True},
        "cat_es_exacta": {"car": False, "caat": False, "cut": False, "cat": True},
        "distancia": [True, True, True, False, False, False],
    }, f"L1-U2: {observado}"


def test_l1u3_la_pista_con_inicial() -> None:
    """L1-U3 (C3): vale el resto o la palabra entera; la tolerancia, una sola vez."""
    con_tolerancia = _escrita("castle", tolerancia=cal.UNA_LETRA, pista=True)
    exacta = _escrita("castle", pista=True)
    observado = {
        "con_1_letra": _acierta(con_tolerancia, "astle", "castle", "astlee", "astl", "stl"),
        "exacta": _acierta(exacta, "astle", "castle", "astlee", "astl"),
        "sin_pista_el_resto_no_vale": cal.calificar(_escrita("castle"), "astle"),
        "la_pista_que_ve": [cal.pista_de(con_tolerancia), cal.pista_de(_escrita("castle")),
                            cal.pista_de(Pregunta("multiple_choice", "A", pista_inicial=True))],
    }
    assert observado == {
        "con_1_letra": {"astle": True, "castle": True, "astlee": True, "astl": True,
                        "stl": False},
        "exacta": {"astle": True, "castle": True, "astlee": False, "astl": False},
        "sin_pista_el_resto_no_vale": False,
        "la_pista_que_ve": ["c", None, None],
    }, f"L1-U3: {observado}"


def test_l1u4_opciones_explicacion_y_segundo_intento(monkeypatch: pytest.MonkeyPatch) -> None:
    """L1-U4 (C4): por label o por value; `por_opcion` solo de la elegida y si falló; la paga."""
    monkeypatch.delenv("SEGUNDO_INTENTO_PAGA", raising=False)
    c = Settings(_env_file=None)  # type: ignore[call-arg]
    opciones = [{"label": "A", "value": "goes"}, {"label": "B", "value": "go"}]
    p = Pregunta("multiple_choice", "A", options=opciones)
    explicacion = {"regla": "Con he, she, it el verbo lleva -s.",
                   "por_opcion": {"B": "Go es para I, you, we, they.", "C": "otra"},
                   "ejemplo": "She goes to school."}
    observado = {
        "opcion": {r: cal.calificar(p, r) for r in ("A", "a", "goes", "B", "go", "", "C")},
        "label_de": [cal.label_de(p, r) for r in ("goes", " b ", "zzz")],
        "explicacion_si_fallo": cal.explicacion_para(explicacion, elegida="B", acerto=False),
        "explicacion_si_acerto": cal.explicacion_para(explicacion, elegida="A", acerto=True),
        "sin_explicacion": cal.explicacion_para(None, elegida="A", acerto=False),
        "la_variable_nace_sin_valor": c.segundo_intento_paga,
        "paga_del_intento": {
            "primero, como hoy": economia.paga_del_intento(10, 1, None),
            "segundo, como hoy": economia.paga_del_intento(10, 2, None),
            "segundo con 5": economia.paga_del_intento(10, 2, 5),
            "primero con 5": economia.paga_del_intento(10, 1, 5),
            "tercero con 5": economia.paga_del_intento(10, 3, 5),
            "segundo con 5 y reto de 3": economia.paga_del_intento(3, 2, 5),
            "segundo con 0": economia.paga_del_intento(10, 2, 0),
        },
    }
    assert observado == {
        "opcion": {"A": True, "a": True, "goes": True, "B": False, "go": False, "": False,
                   "C": False},
        "label_de": ["A", "B", "zzz"],
        "explicacion_si_fallo": {"idioma": "es", "regla": "Con he, she, it el verbo lleva -s.",
                                 "por_opcion": "Go es para I, you, we, they.",
                                 "ejemplo": "She goes to school."},
        "explicacion_si_acerto": {"idioma": "es", "regla": "Con he, she, it el verbo lleva -s.",
                                  "por_opcion": None, "ejemplo": "She goes to school."},
        "sin_explicacion": None,
        "la_variable_nace_sin_valor": None,
        "paga_del_intento": {"primero, como hoy": 10, "segundo, como hoy": 10,
                             "segundo con 5": 5, "primero con 5": 10, "tercero con 5": 5,
                             "segundo con 5 y reto de 3": 3, "segundo con 0": 0},
    }, f"L1-U4: {observado}"


def test_l1u5_la_oracion_correcta_y_el_idioma() -> None:
    """L1-U5 (C5): la oración completa, no la letra; español en A1 y A2, inglés desde B1."""
    opciones = [{"label": "A", "value": "faster"}, {"label": "C", "value": "cheaper"}]
    de_opcion = Pregunta("multiple_choice", "C", options=opciones)
    escrita = Pregunta("fill_blank", "don't")
    e = {"regla": "r", "ejemplo": "e"}
    observado = {
        "oracion": {
            "hueco relleno": cal.oracion_correcta("Metrolinea is ___ than a taxi.", de_opcion),
            "escrita": cal.oracion_correcta("I ____ like fish.", escrita),
            "sin hueco, el texto de la correcta": cal.oracion_correcta(
                "Which word means 'costs less'?", de_opcion),
            "dos huecos, el texto de la correcta": cal.oracion_correcta(
                "It is ___ and ___.", de_opcion),
            "la del banco manda": cal.oracion_correcta(
                "Metrolinea is ___ than a taxi.", de_opcion, " The bus is cheaper. "),
            "sin opciones, la clave": cal.oracion_correcta("x ___", Pregunta("multiple_choice",
                                                                             "C")),
        },
        "texto_correcto": [cal.texto_correcto(de_opcion), cal.texto_correcto(escrita)],
        "idioma_por_nivel": {str(n): cal.idioma_de(n) for n in (
            "A1", "A1+", "A2", "A2+", "B1-", "B1", "B1+", "B2", "C1", "C1+", None)},
        "idioma_de_la_explicacion": {
            "A2 sin idioma": cal.explicacion_para(e, elegida="A", acerto=True,
                                                  nivel="A2")["idioma"],  # type: ignore[index]
            "B1 sin idioma": cal.explicacion_para(e, elegida="A", acerto=True,
                                                  nivel="B1")["idioma"],  # type: ignore[index]
            "B1 y el banco dice es": cal.explicacion_para(
                {**e, "idioma": "es"}, elegida="A", acerto=True,
                nivel="B1")["idioma"],  # type: ignore[index]
            "idioma raro, manda el nivel": cal.explicacion_para(
                {**e, "idioma": "fr"}, elegida="A", acerto=True,
                nivel="A1")["idioma"],  # type: ignore[index]
        },
    }
    assert observado == {
        "oracion": {
            "hueco relleno": "Metrolinea is cheaper than a taxi.",
            "escrita": "I don't like fish.",
            "sin hueco, el texto de la correcta": "cheaper",
            "dos huecos, el texto de la correcta": "cheaper",
            "la del banco manda": "The bus is cheaper.",
            "sin opciones, la clave": "x C",
        },
        "texto_correcto": ["cheaper", "don't"],
        "idioma_por_nivel": {"A1": "es", "A1+": "es", "A2": "es", "A2+": "es", "B1-": "en",
                             "B1": "en", "B1+": "en", "B2": "en", "C1": "en", "C1+": "en",
                             "None": "es"},
        "idioma_de_la_explicacion": {"A2 sin idioma": "es", "B1 sin idioma": "en",
                                     "B1 y el banco dice es": "es",
                                     "idioma raro, manda el nivel": "es"},
    }, f"L1-U5: {observado}"
