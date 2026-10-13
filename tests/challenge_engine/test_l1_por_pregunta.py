"""L1-A1 a L1-A6: responder pregunta por pregunta, por HTTP.

`docs/ESPEC_l1_correccion_por_pregunta.md` §10.6 (C6 a C11). Lo observado va en
un dict que se compara ENTERO. Tramposos: `tests/tramposos/test_tramposos_l1.py`.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.challenge_engine.schemas import AttemptSubmitOut, ChallengeQuestionOut
from src.refuerzo import formas as refuerzo_formas
from src.shared.config import settings
from tests.challenge_engine import _l1 as l1
from tests.curriculo import _ayuda as cat
from tests.grader import _ayuda as gr
from tests.practica import _ayuda as ay
from tests.racha import _ayuda as ra
from tests.refuerzo import _ayuda as rf

pytestmark = pytest.mark.integ

REGLA = "Con he, she, it el verbo lleva -s."
EN_INGLES = {"regla": "Use had + past participle for the earlier action.",
             "por_opcion": {"B": "Has started is for now, not for the past."},
             "ejemplo": "When I called, she had left."}


def test_l1a1_la_respuesta_por_pregunta(integ) -> None:
    """L1-A1 (C6): tras cada respuesta, si acertó, la oración correcta y la explicación."""
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    _reto, q = l1.reto(integ, c.profe, "a2", [
        l1.pregunta(explanation=l1.EXPLICACION),
        l1.pregunta("He ___ football on Sundays.", "B",
                    opciones={"A": "play", "B": "plays"}, explanation=l1.EXPLICACION),
        l1.pregunta("I ____ like fish.", "don't", tipo="fill_blank")], grupo=c.grupo)
    b1, qb = l1.reto(integ, c.profe, "b1", [
        l1.pregunta("By the time we arrived, the film ___.", "A",
                    opciones={"A": "had started", "B": "has started"}, explanation=EN_INGLES)],
        grupo=c.grupo, nivel="B1")
    sin, qs = l1.reto(integ, c.profe, "sin", [l1.pregunta()], grupo=c.grupo)
    intento, _ = l1.intento(integ, ana, _reto)
    observado: dict[str, Any] = {
        "falla_la_primera": l1.responder(integ, ana, intento, q[0], "B"),
        "acierta_por_el_texto_de_la_opcion": l1.responder(integ, ana, intento, q[1], "plays"),
        "escrita_con_apostrofo_curvo": l1.responder(integ, ana, intento, q[2], "Don’t."),
        "b1_en_ingles": l1.responder(integ, ana, l1.intento(integ, ana, b1)[0], qb[0], "B"),
        "sin_explicacion": l1.responder(integ, ana, l1.intento(integ, ana, sin)[0], qs[0], "C"),
        "no_paga_ni_cierra": (int(integ.valor("select count(*) from coin_ledger")),
                              integ.saldo("profile", ana),
                              sorted(str(s) for (s,) in l1.filas(
                                  integ, "select status from challenge_attempts"))),
    }
    assert observado == {
        "falla_la_primera": (200, (False, "B", "A", "She goes to school every day.", {
            "idioma": "es", "regla": REGLA, "por_opcion": "Go es para I, you, we, they.",
            "ejemplo": "He plays football."}, False, 1, 3)),
        "acierta_por_el_texto_de_la_opcion": (
            200, (True, "plays", "B", "He plays football on Sundays.", {
                "idioma": "es", "regla": REGLA, "por_opcion": None,
                "ejemplo": "He plays football."}, False, 2, 3)),
        "escrita_con_apostrofo_curvo": (
            200, (True, "Don’t.", "don't", "I don't like fish.", None, False, 3, 3)),
        "b1_en_ingles": (200, (False, "B", "A", "By the time we arrived, the film had started.", {
            "idioma": "en", "regla": "Use had + past participle for the earlier action.",
            "por_opcion": "Has started is for now, not for the past.",
            "ejemplo": "When I called, she had left."}, False, 1, 1)),
        "sin_explicacion": (200, (False, "C", "A", "She goes to school every day.", None,
                                  False, 1, 1)),
        "no_paga_ni_cierra": (0, None, ["in_progress", "in_progress", "in_progress"]),
    }, f"L1-A1: {observado}"


def test_l1a2_gana_la_primera_respuesta(integ) -> None:
    """L1-A2 (C7): repetir devuelve lo guardado; dos a la vez dejan una fila; el GET retoma."""
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    reto, q = l1.reto(integ, c.profe, "r", [l1.pregunta(), l1.pregunta("He ___ too.")],
                      grupo=c.grupo)
    intento, _ = l1.intento(integ, ana, reto)
    antes = l1.retomar(integ, ana, intento)
    primera = l1.corta(l1.responder(integ, ana, intento, q[0], "B"))
    otra = l1.corta(l1.responder(integ, ana, intento, q[0], "A"))
    juntas = [r.json() if r.status_code == 200 else r.status_code for r in l1.a_la_vez(
        lambda cl: l1.responder_crudo(integ, ana, intento, q[1], "A", cl),
        lambda cl: l1.responder_crudo(integ, ana, intento, q[1], "B", cl))]
    despues = l1.retomar(integ, ana, intento)
    todo_json = all(isinstance(j, dict) for j in juntas)
    observado = {
        "antes": antes,
        "la_primera": primera, "otra_respuesta_devuelve_la_primera": otra,
        "dos_a_la_vez": {
            "las_dos_200": todo_json,
            "la_misma_guardada": todo_json and len({j["answer"] for j in juntas}) == 1,
            "el_mismo_veredicto": todo_json and len({j["is_correct"] for j in juntas}) == 1,
            "una_sola_es_nueva": todo_json and sorted(j["repetida"] for j in juntas),
        },
        "filas": l1.filas(integ, "select count(*), count(distinct question_id) "
                                 "from challenge_attempt_answers"),
        "retomar": (despues["status"], despues["total"], despues["pistas"],
                    [(r["question_id"] == p, r["repetida"], r["respondidas"])
                     for r, p in zip(despues["respondidas"], q, strict=True)]),
        "la_primera_sigue_igual": (despues["respondidas"][0]["answer"],
                                   despues["respondidas"][0]["is_correct"]),
    }
    assert observado == {
        "antes": {"status": "in_progress", "total": 2, "pistas": {}, "respondidas": []},
        "la_primera": (200, False, "B", False),
        "otra_respuesta_devuelve_la_primera": (200, False, "B", True),
        "dos_a_la_vez": {"las_dos_200": True, "la_misma_guardada": True,
                         "el_mismo_veredicto": True, "una_sola_es_nueva": [False, True]},
        "filas": [(2, 2)],
        "retomar": ("in_progress", 2, {}, [(True, True, 2), (True, True, 2)]),
        "la_primera_sigue_igual": ("B", False),
    }, f"L1-A2: {observado}"


def test_l1a3_cada_quien_responde_solo_su_intento(integ) -> None:
    """L1-A3 (C8): intento ajeno o de otra institución, 404; terminado, 409."""
    a, b = gr.colegio(integ, "9A", n=2), gr.colegio(integ, "9B", n=1)
    ana, beto = a.estudiantes
    carla = b.estudiantes[0]
    reto, q = l1.reto(integ, a.profe, "r", [l1.pregunta(), l1.pregunta("He ___ too.")],
                      grupo=a.grupo)
    _otro, q_otro = l1.reto(integ, a.profe, "otro", [l1.pregunta("It ___.")], grupo=a.grupo)
    intento, _ = l1.intento(integ, ana, reto)
    observado: dict[str, Any] = {
        "beto_responde_el_de_ana": l1.responder(integ, beto, intento, q[0], "A")[0],
        "carla_desde_otra_institucion": l1.responder(integ, carla, intento, q[0], "A")[0],
        "beto_lo_retoma": l1.retomar(integ, beto, intento),
        "beto_lo_termina": l1.terminar(integ, beto, intento),
        "pregunta_de_otro_reto": l1.responder(integ, ana, intento, q_otro[0], "A"),
        "ana_si": l1.corta(l1.responder(integ, ana, intento, q[0], "A")),
        "ana_termina": l1.terminar(integ, ana, intento),
        "responder_ya_terminado": l1.responder(integ, ana, intento, q[1], "A"),
        "terminar_otra_vez": l1.terminar(integ, ana, intento),
        "las_filas_son_de_ana_en_su_institucion": [
            (t == a.tenant, p == ana) for t, p in l1.filas(
                integ, "select tenant_id, profile_id from challenge_attempt_answers")],
    }
    assert observado == {
        "beto_responde_el_de_ana": 404, "carla_desde_otra_institucion": 404,
        "beto_lo_retoma": (404, "Attempt not found"),
        "beto_lo_termina": (404, "Attempt not found"),
        "pregunta_de_otro_reto": (404, "Question not found in this attempt"),
        "ana_si": (200, True, "A", False),
        "ana_termina": (200, (False, 0)),
        "responder_ya_terminado": (409, "Attempt already completed or abandoned"),
        "terminar_otra_vez": (409, "Attempt already completed or abandoned"),
        "las_filas_son_de_ana_en_su_institucion": [(True, True)],
    }, f"L1-A3: {observado}"


def _limpio(cuerpo: Any) -> bool:
    """¿Ese JSON no trae la clave, la explicación ni cómo se califica?"""
    texto = str(cuerpo)
    return not any(palabra in texto for palabra in (
        "CENTINELA", "correct_answer", "explanation", "accepted_answers", "tolerancia",
        "tolerance", "oracion_correcta", "pista_inicial", "hint_initial"))


def test_l1a4_nada_sale_antes_de_responder(integ, monkeypatch) -> None:
    """L1-A4 (C9): la clave y la explicación de una pregunta solo salen al responder ESA."""
    ra.fijar_dia(monkeypatch, ra.dia(0))
    ay.sin_escalera(monkeypatch)
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    con = lambda n: {"regla": f"REGLA-CENTINELA-{n}", "ejemplo": f"EJEMPLO-CENTINELA-{n}",  # noqa: E731
                     "por_opcion": {"B": f"PORQUE-CENTINELA-{n}", "C": f"PORQUE-C-CENTINELA-{n}"},
                     "oracion_correcta": f"ORACION-CENTINELA-{n}"}
    reto, q = l1.reto(integ, c.profe, "r", [
        l1.pregunta(explanation=con(1)), l1.pregunta("He ___ too.", explanation=con(2)),
        l1.pregunta("We ___ too.", explanation=con(3))], grupo=c.grupo)
    h = integ.headers(ana)
    feed = l1.client.get("/challenges/", headers=h).json()
    detalle = l1.client.get(f"/challenges/{reto}", headers=h).json()
    tanda = ay.tanda(integ, ana)
    inicio = l1.abrir(integ, ana, reto)
    intento = inicio["attempt_id"]
    sin_responder = l1.retomar(integ, ana, intento)
    una = l1.responder_crudo(integ, ana, intento, q[0], "B").json()
    retomado = l1.retomar(integ, ana, intento)
    observado = {
        "sin_fugas": {"feed": _limpio(feed), "detalle": _limpio(detalle),
                      "tanda": _limpio(tanda), "attempt": _limpio(inicio),
                      "retomar_sin_responder": "CENTINELA" not in str(sin_responder)},
        "trae_las_preguntas": (len(feed[0]["questions"]), len(detalle["questions"]),
                               len(inicio["challenge"]["questions"])),
        "la_respuesta_habla_solo_de_esa": sorted(
            n for n in ("1", "2", "3") if f"CENTINELA-{n}" in str(una)),
        "y_solo_de_la_opcion_elegida": "PORQUE-C-CENTINELA" not in str(una),
        "la_oracion_del_banco": una["oracion_correcta"],
        "retomar_solo_lo_respondido": sorted(
            n for n in ("1", "2", "3") if f"CENTINELA-{n}" in str(retomado)),
        "campos_de_la_pregunta_del_estudiante": sorted(ChallengeQuestionOut.model_fields),
    }
    assert observado == {
        "sin_fugas": {"feed": True, "detalle": True, "tanda": True, "attempt": True,
                      "retomar_sin_responder": True},
        "trae_las_preguntas": (3, 3, 3),
        "la_respuesta_habla_solo_de_esa": ["1"], "y_solo_de_la_opcion_elegida": True,
        "la_oracion_del_banco": "ORACION-CENTINELA-1",
        "retomar_solo_lo_respondido": ["1"],
        "campos_de_la_pregunta_del_estudiante": ["id", "options_json", "order_index",
                                                 "question_text", "question_type"],
    }, f"L1-A4: {observado}"


def test_l1a5_terminar_cierra_como_submit(integ, monkeypatch) -> None:
    """L1-A5 (C10): califica lo guardado, paga una vez, y deja todo como lo deja `/submit`."""
    ra.fijar_dia(monkeypatch, ra.dia(0))
    ay.sin_escalera(monkeypatch)
    cat.cargar(integ, cat.mapa_v1())
    c = gr.colegio(integ, "9A", n=2)
    ana, beto = c.estudiantes
    reto, q = l1.reto(integ, c.profe, "r", [
        l1.pregunta(nodos=[rf.UNO], item_ref="i-1"), l1.pregunta("He ___ too.", item_ref="i-2"),
        l1.pregunta("We ___ too.", item_ref="i-3")], grupo=c.grupo)
    intento, _ = l1.intento(integ, ana, reto)
    l1.responder(integ, ana, intento, q[0], "B")
    l1.responder(integ, ana, intento, q[1], "A")  # la tercera queda sin responder
    visto: dict[str, Any] = {
        "submit_con_respuestas_guardadas": l1.enviar(integ, ana, intento,
                                                     dict.fromkeys(q, "A")),
    }
    cierre = l1.terminar_crudo(integ, ana, intento)
    cuerpo = cierre.json() if cierre.status_code == 200 else {}
    visto["termina_con_una_fallada_y_una_en_blanco"] = (
        cierre.status_code, cuerpo.get("is_correct"), cuerpo.get("coins_earned"),
        round(float(cuerpo.get("score_percent", -1)), 1),
        len(cuerpo.get("correct_answers", [])), cuerpo.get("total_attempts_used"))
    visto["la_misma_forma_de_submit"] = sorted(cuerpo) == sorted(AttemptSubmitOut.model_fields)
    guardado = integ.valor("select answers from challenge_attempts where id = :i", i=intento)
    visto["answers_como_los_deja_submit"] = [
        (d["question_id"] == p, d["given_answer"], d["correct_answer"], d["is_correct"],
         sorted(d)) for d, p in zip(guardado, q, strict=True)]
    visto["lo_fallado_entra_a_la_cola"] = rf.cola(integ, ana)
    visto["cuenta_para_la_racha"] = ra.hoy(integ, ana)
    visto["segundo_intento_lo_gana"] = l1.jugar(integ, ana, reto, "AAA")
    visto["tercero_por_submit_no_paga_otra_vez"] = ra.jugar(integ, ana, reto, q, "AAA")
    visto["cuarto_por_finish_tampoco"] = l1.jugar(integ, ana, reto, "AAA")
    visto["beto_al_primer_intento"] = l1.jugar(integ, beto, reto, "AAA")
    visto["pagas_del_reto"] = l1.pagas(integ, reto)
    assert visto == {
        "submit_con_respuestas_guardadas": (409, "intento_con_respuestas"),
        "termina_con_una_fallada_y_una_en_blanco": (200, False, 0, 33.3, 3, 1),
        "la_misma_forma_de_submit": True,
        "answers_como_los_deja_submit": [
            (True, g, "A", ok, ["correct_answer", "given_answer", "is_correct", "question_id"])
            for g, ok in (("B", False), ("A", True), ("", False))],
        "lo_fallado_entra_a_la_cola": {rf.UNO: ("en_refuerzo", 1, "reto", 0)},
        "cuenta_para_la_racha": (2, 1, False),
        "segundo_intento_lo_gana": (200, (True, 10)),
        "tercero_por_submit_no_paga_otra_vez": (200, (True, 0)),
        "cuarto_por_finish_tampoco": (200, (True, 0)),
        "beto_al_primer_intento": (200, (True, 10)),
        "pagas_del_reto": [10, 10],
    }, f"L1-A5: {visto}"


def _vio(integ: Any, tenant: Any, quien: Any, item: str) -> bool:
    """¿Ese ítem cuenta como VISTO para la cola de repaso y la segunda vuelta?"""
    async def _q() -> bool:
        async with integ.Session() as db:
            return item in (await refuerzo_formas.vistas(db, tenant, [quien]))[quien]

    return bool(integ.run(_q()))


def test_l1a6_el_segundo_intento(integ, monkeypatch) -> None:
    """L1-A6 (C11): el reintento usa la gemela si existe; si no, paga según la variable."""
    c = gr.colegio(integ, "9A", n=6)
    ana, beto, eva, carla, fito, dora = c.estudiantes
    solo, _ = l1.reto(integ, c.profe, "solo", [l1.pregunta(), l1.pregunta("He ___ too.")],
                      grupo=c.grupo)
    fam, qf = l1.reto(integ, c.profe, "fam", [
        l1.pregunta(item_ref="fa-1", familia="fa", rol="original"),
        l1.pregunta("He ___ too.", item_ref="fb-1", familia="fb", rol="original")],
        grupo=c.grupo)
    _gem, qg = l1.reto(integ, c.profe, "gem", [
        l1.pregunta("It ___ well.", item_ref="fa-2", familia="fa", rol="gemela")],
        grupo=c.grupo, solo_refuerzo=True)
    visto: dict[str, Any] = {}
    # Sin gemelas y sin la variable: el segundo intento repite las preguntas y paga como hoy.
    visto["ana_falla"] = l1.jugar(integ, ana, solo, "BA")
    visto["ana_copia_la_clave"] = l1.jugar(integ, ana, solo, "AA")
    # Con la variable en 5: el segundo intento paga 5; el primero, lo de siempre.
    monkeypatch.setattr(settings, "segundo_intento_paga", 5)
    visto["beto_falla"] = l1.jugar(integ, beto, solo, "BA")
    visto["beto_copia_con_la_variable_en_5"] = l1.jugar(integ, beto, solo, "AA")
    visto["eva_gana_al_primero_con_la_variable_en_5"] = l1.jugar(integ, eva, solo, "AA")
    monkeypatch.setattr(settings, "segundo_intento_paga", None)
    # Con gemela: el reintento trae OTRA pregunta donde la hay.
    visto["carla_falla"] = l1.jugar(integ, carla, fam, "BA")
    intento, servidas = l1.intento(integ, carla, fam)
    visto["carla_reintenta"] = {
        "trae_la_gemela_de_fa": servidas[0] == qg[0],
        "fb_no_tiene_y_se_repite": servidas[1] == qf[1],
        "la_clave_vieja_ya_no_es_de_este_intento": l1.responder(integ, carla, intento,
                                                                qf[0], "A"),
        "responde_las_suyas": [l1.corta(l1.responder(integ, carla, intento, p, "A"))
                               for p in servidas],
        "termina": l1.terminar(integ, carla, intento),
    }
    # Quien ya respondió por pregunta no gana mandando las claves viejas por /submit.
    l1.jugar(integ, fito, fam, "BA")
    intento_fito, _ = l1.intento(integ, fito, fam)
    visto["fito_manda_las_claves_viejas_por_submit"] = l1.enviar(
        integ, fito, intento_fito, dict.fromkeys(qf, "A"))
    # La web de hoy (nunca usó /answers): su segundo intento es el de siempre.
    visto["dora_falla_por_submit"] = ra.jugar(integ, dora, fam, qf, "BA")
    visto["dora_recibe_las_de_siempre"] = l1.intento(integ, dora, fam)[1] == qf
    visto["dora_gana_como_hoy"] = l1.enviar(
        integ, dora, l1.intento(integ, dora, fam)[0], dict.fromkeys(qf, "A"))
    # La gemela que se le sirvió a Carla ya no le sirve de repaso; a Dora nadie se la sirvió.
    visto["la_gemela_servida_queda_vista"] = (_vio(integ, c.tenant, carla, "fa-2"),
                                              _vio(integ, c.tenant, dora, "fa-2"))
    visto["pagas"] = {"solo": l1.pagas(integ, solo), "fam": l1.pagas(integ, fam)}
    assert visto == {
        "ana_falla": (200, (False, 0)), "ana_copia_la_clave": (200, (True, 10)),
        "beto_falla": (200, (False, 0)),
        "beto_copia_con_la_variable_en_5": (200, (True, 5)),
        "eva_gana_al_primero_con_la_variable_en_5": (200, (True, 10)),
        "carla_falla": (200, (False, 0)),
        "carla_reintenta": {
            "trae_la_gemela_de_fa": True, "fb_no_tiene_y_se_repite": True,
            "la_clave_vieja_ya_no_es_de_este_intento": (
                404, "Question not found in this attempt"),
            "responde_las_suyas": [(200, True, "A", False), (200, True, "A", False)],
            "termina": (200, (True, 10)),
        },
        "fito_manda_las_claves_viejas_por_submit": (200, (False, 0)),
        "dora_falla_por_submit": (200, (False, 0)),
        "dora_recibe_las_de_siempre": True,
        "dora_gana_como_hoy": (200, (True, 10)),
        "la_gemela_servida_queda_vista": (True, False),
        "pagas": {"solo": [5, 10, 10], "fam": [10, 10]},
    }, f"L1-A6: {visto}"
