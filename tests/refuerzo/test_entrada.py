"""CR1, CR2 y CR7: lo que entra a la cola de refuerzo — `docs/ESPEC_refuerzo.md` §2.

  CR1  C2  desde una hoja del Grader: entra el NODO de cada ítem fallado.
  CR2  C3  desde un reto: la pregunta fallada mete sus nodos; `/submit` no cambia.
  CR7  C8  una fusión del mapa reapunta la cola.
"""
from __future__ import annotations

import pytest

from tests.curriculo import _ayuda as cat
from tests.grader import _ayuda as gr
from tests.refuerzo import _ayuda as ay
from tests.refuerzo._ayuda import CUATRO, DOS, TRES, UNO

pytestmark = pytest.mark.integ

ITEMS = [("i1", [UNO]), ("i2", [DOS, TRES]), ("i3", [CUATRO]), ("i4", [])]
IDS = [i for i, _ in ITEMS]


def test_cr1_desde_una_hoja_del_grader(integ, monkeypatch) -> None:
    """CR1 (C2): entran los nodos de lo fallado, una vez; la hoja corregida retira lo intacto."""
    ay.fijar_ahora(monkeypatch)
    cat.cargar(integ, cat.mapa_v1())
    c = gr.colegio(integ, n=3)
    s1, s2, s3 = c.estudiantes
    assert gr.lista(integ, c.profe, c.codigo_grupo)[0] == 200
    assert ay.examen_con(integ, c, ITEMS) == 201
    assert ay.examen_con(integ, c, [("z1", []), ("z2", [])], codigo="SIN-NODOS") == 201
    _reto, q = ay.sembrar_reto(integ, c.profe, "banco", [ay.forma([TRES], "t-1")],
                               grupo=c.grupo)
    original = ay.hoja_con(1, IDS, malas=("i1",), vacias=("i2",), dobles=("i4",))
    primera = gr.enviar(integ, c.profe, c.codigo_grupo,
                        [original, ay.hoja_con(2, IDS)])  # la de s2, todo correcto
    tras_primera = ay.cola(integ, s1)
    reenvio = gr.enviar(integ, c.profe, c.codigo_grupo, [original])
    tras_reenvio = ay.cola(integ, s1)
    trabajada = ay.responder(integ, s1, ay.entrada_de(integ, s1, TRES), q["t-1"], "B")
    corregida = gr.enviar(integ, c.profe, c.codigo_grupo,
                          [ay.hoja_con(1, IDS, malas=("i1",), dobles=("i4",))])
    sin_nodos = gr.enviar(integ, c.profe, c.codigo_grupo,
                          [ay.hoja_con(3, ["z1", "z2"], malas=("z1", "z2"), codigo="SIN-NODOS")],
                          codigo="SIN-NODOS")
    observado = {
        "envios": (primera, reenvio, corregida, sin_nodos),
        "tras_primera": tras_primera, "reenviar_no_cambia_nada": tras_reenvio == tras_primera,
        "trabajo_tres": trabajada[0],
        "tras_corregida": ay.cola(integ, s1),
        "el_que_acerto_todo": ay.cola(integ, s2),
        "el_del_examen_sin_nodos": ay.cola(integ, s3),
    }
    en_cola = ("en_refuerzo", 1, "grader", 0)
    assert observado == {
        "envios": ((200, (2, 0, [])), (200, (1, 1, [])), (200, (1, 1, [])), (200, (1, 0, []))),
        "tras_primera": {UNO: en_cola, DOS: en_cola, TRES: en_cola},
        "reenviar_no_cambia_nada": True, "trabajo_tres": 200,
        # DOS estaba intacta y se retira; TRES ya se trabajó y se queda.
        "tras_corregida": {UNO: en_cola, TRES: en_cola},
        "el_que_acerto_todo": {}, "el_del_examen_sin_nodos": {},
    }, f"CR1: {observado}"


def test_cr2_desde_un_reto(integ, monkeypatch) -> None:
    """CR2 (C3): lo fallado en `/submit` mete sus nodos; el resultado y la paga no cambian."""
    ay.fijar_ahora(monkeypatch)
    cat.cargar(integ, cat.mapa_v1())
    c = gr.colegio(integ, n=2)
    s1, s2 = c.estudiantes
    reto, q = ay.sembrar_reto(integ, c.profe, "reto", [
        ay.forma([UNO], "a"), ay.forma([DOS], "b"), ay.forma([], "c")], grupo=c.grupo)
    sin_nodos, z = ay.sembrar_reto(integ, c.profe, "sin nodos", [ay.forma([], "z")],
                                   grupo=c.grupo)
    primero = ay.jugar(integ, s1, reto, {q["a"]: "B", q["b"]: "A", q["c"]: "B"})
    tras_primero = ay.cola(integ, s1)
    segundo = ay.jugar(integ, s1, reto, {q["a"]: "B", q["b"]: "A", q["c"]: "A"})
    observado = {
        "primero": primero, "tras_primero": tras_primero,
        "segundo": segundo, "tras_segundo": ay.cola(integ, s1),
        "el_que_gana": ay.jugar(integ, s2, reto, {q["a"]: "A", q["b"]: "A", q["c"]: "A"}),
        "su_cola": ay.cola(integ, s2),
        "falla_un_reto_sin_nodos": ay.jugar(integ, s2, sin_nodos, {z["z"]: "B"}),
        "su_cola_despues": ay.cola(integ, s2),
        "monedas_de_quien_gano": integ.saldo("profile", s2),
    }
    assert observado == {
        "primero": (200, (False, 0)), "tras_primero": {UNO: ("en_refuerzo", 1, "reto", 0)},
        "segundo": (200, (False, 0)), "tras_segundo": {UNO: ("en_refuerzo", 2, "reto", 0)},
        "el_que_gana": (200, (True, 10)), "su_cola": {},
        "falla_un_reto_sin_nodos": (200, (False, 0)), "su_cola_despues": {},
        "monedas_de_quien_gano": 10,
    }, f"CR2: {observado}"


def test_cr7_una_fusion_del_mapa_reapunta_la_cola(integ, monkeypatch) -> None:
    """CR7 (C8): el nodo viejo pasa al nuevo; quien tenía los dos se queda con el nuevo."""
    ay.fijar_ahora(monkeypatch)
    cat.cargar(integ, cat.mapa_v1())
    c = gr.colegio(integ, n=2)
    s1, s2 = c.estudiantes
    reto, q = ay.sembrar_reto(integ, c.profe, "reto", [
        ay.forma([DOS], "d"), ay.forma([TRES], "t")], grupo=c.grupo)
    ay.jugar(integ, s1, reto, {q["d"]: "B", q["t"]: "B"})  # s1: DOS y TRES
    ay.jugar(integ, s2, reto, {q["d"]: "B", q["t"]: "A"})  # s2: solo DOS
    antes = (ay.cola(integ, s1), ay.cola(integ, s2))
    fusion = cat.cargar(integ, cat.mapa(
        "v2", [i for i in cat.VIGENTES_V1 if i != DOS], {**cat.REEMPLAZOS_V1, DOS: TRES}))
    observado = {
        "antes": (sorted(antes[0]), sorted(antes[1])),
        "reapuntadas": fusion["reapuntadas"].get("reinforcement_queue")
        if isinstance(fusion, dict) else fusion,
        "despues": (sorted(ay.cola(integ, s1)), sorted(ay.cola(integ, s2))),
    }
    assert observado == {
        "antes": ([TRES, DOS], [DOS]), "reapuntadas": 2, "despues": ([TRES], [TRES]),
    }, f"CR7: {observado}"
