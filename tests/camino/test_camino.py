"""CM1 a CM7 y el humo: el camino de nivel por HTTP contra Postgres — docs/ESPEC_camino_progreso.md §2.

Lo observado va en un dict que se compara ENTERO y el mensaje lleva el dict
(los tramposos de `tests/tramposos/test_tramposos_camino.py` lo leen). Los retos
se siembran por `POST /challenges/` con `topic`, `cefr_level` y el título del
sembrador ("<topic> · <unidad> · <bloque> · <rol>").
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from tests.grader import _ayuda as gr
from tests.practica import _ayuda as ay
from tests.racha import _ayuda as ra
from tests.refuerzo import _ayuda as rf
from tests.seguridad.veredictos import sembrar as sql

pytestmark = pytest.mark.integ

client = ay.client
RUTA_HUMO = Path(__file__).resolve().parents[1] / "_salida" / "humo_camino.json"
TABLAS_QUE_NO_CAMBIAN = ("coin_ledger", "coin_wallets", "challenge_attempts", "practice_levels",
                         "practice_tandas", "reinforcement_queue", "reinforcement_answers",
                         "challenge_attempt_answers", "confirmed_levels")


def camino(integ: Any, quien: UUID) -> Any:
    """El cuerpo de `GET /challenges/camino`, o `(estado, cuerpo)` si no es 200."""
    r = client.get("/challenges/camino", headers=integ.headers(quien))
    return r.json() if r.status_code == 200 else (r.status_code, r.text)


def corto(c: Any) -> Any:
    """(nivel, prestado, recomendada, [(topic, número, título, estado, acceso, ¿rec?, [títulos])])."""
    if not isinstance(c, dict):
        return c
    return (c["nivel"], c["prestado"], c["recomendada"],
            [(u["topic"], u["numero"], u["titulo"], u["estado"], u["acceso"], u["recomendada"],
              [e["title"].split(" · ")[2] for e in u["estaciones"]]) for u in c["unidades"]])


def estados(c: Any) -> Any:
    """[(topic, estado, acceso, ¿recomendada?, ¿atascada?, porcentaje)]."""
    if not isinstance(c, dict):
        return c
    return [(u["topic"], u["estado"], u["acceso"], u["recomendada"], u["atascada"],
             u["porcentaje"]) for u in c["unidades"]]


def t(topic: str, unidad: str, bloque: str, rol: str | None = "original") -> str:
    return " · ".join(x for x in (topic, unidad, bloque, rol) if x)


def unidades_basicas(integ: Any, c: Any) -> dict[str, tuple[str, list[str]]]:
    """Dos unidades A2: la 1 con 3 estaciones (2, 3 y 2 preguntas) y la 2 con 2; en desorden."""
    r = {}
    r["u2-voc"] = ay.reto(integ, c.profe, t("a2-u02", "Dos", "Vocabulario 1"), 2, grupo=c.grupo,
                          topic="a2-u02", skill="vocabulary")
    r["u1-lec"] = ay.reto(integ, c.profe, t("a2-u01", "Uno", "Lectura 1", None), 2,
                          grupo=c.grupo, skill="reading")
    r["u1-voc"] = ay.reto(integ, c.profe, t("a2-u01", "Uno", "Vocabulario 1"), 3, grupo=c.grupo,
                          skill="vocabulary")
    r["u2-gra"] = ay.reto(integ, c.profe, t("a2-u02", "Dos", "Gramática 1"), 2, grupo=c.grupo,
                          topic="a2-u02")
    r["u1-gra"] = ay.reto(integ, c.profe, t("a2-u01", "Uno", "Gramática 1"), 2, grupo=c.grupo)
    return r


def envejecer(integ: Any, quien: UUID, dias: float) -> None:
    """Todos los intentos de ese estudiante pasan a haber ocurrido `dias` días antes."""
    sql(integ, "update challenge_attempts set started_at = started_at - make_interval(secs => :s),"
               " completed_at = completed_at - make_interval(secs => :s) where student_id = :p",
        s=dias * 86400, p=quien)


def cuentas(integ: Any) -> dict[str, int]:
    return {tabla: int(integ.valor(f"select count(*) from {tabla}"))  # noqa: S608 (nombres fijos)
            for tabla in TABLAS_QUE_NO_CAMBIAN}


def test_cm1_forma_y_orden(integ) -> None:
    """CM1: solo las estaciones visibles del nivel, en orden; sin clave ni monedas; bloqueo suave."""
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    otro = integ.crear_grupo(c.tenant, "9B")
    unidades_basicas(integ, c)
    ay.reto(integ, c.profe, t("a2-u01", "Uno", "Ajeno 1"), 2, grupo=otro)
    ay.reto(integ, c.profe, t("a2-u01", "Uno", "Refuerzo 1", "gemela"), 2, grupo=c.grupo,
            solo_refuerzo=True)
    ay.reto(integ, c.profe, t("a2-u01", "Uno", "Abierta 1"), 2, grupo=c.grupo,
            challenge_type="open")
    ay.reto(integ, c.profe, t("b1-u01", "Otra", "Gramática 1"), 2, grupo=c.grupo, nivel="B1",
            topic="b1-u01")
    inactivo, _ = ay.reto(integ, c.profe, t("a2-u01", "Uno", "Apagado 1"), 2, grupo=c.grupo)
    apagar = client.patch(f"/challenges/{inactivo}/status", headers=integ.headers(c.profe),
                          json={"status": "inactive"}).status_code
    cuerpo = camino(integ, ana)
    texto = json.dumps(cuerpo)
    observado: dict[str, Any] = {
        "apagar": apagar, "camino": corto(cuerpo),
        "sin_clave_ni_monedas": ("correct_answer" not in texto and "coins" not in texto
                                 and "questions" not in texto),
        "umbrales": (cuerpo["umbral_completada"], cuerpo["umbral_dominada"],
                     cuerpo["dias_atasco"]),
        "siguiente_es_la_primera": cuerpo["unidades"][0]["siguiente_reto"]
        == cuerpo["unidades"][0]["estaciones"][0]["id"],
        "se_abre_el": [u["se_abre_el"] for u in cuerpo["unidades"]],
    }
    assert observado == {
        "apagar": 200,
        "camino": ("A2", False, "a2-u01", [
            ("a2-u01", 1, "Uno", "sin_empezar", "abierta", True,
             ["Gramática 1", "Vocabulario 1", "Lectura 1"]),
            ("a2-u02", 2, "Dos", "sin_empezar", "bloqueada", False,
             ["Gramática 1", "Vocabulario 1"])]),
        "sin_clave_ni_monedas": True, "umbrales": (70, 80, 7), "siguiente_es_la_primera": True,
        "se_abre_el": [None, None],
    }, f"CM1: {observado}"


def test_cm2_el_progreso(integ) -> None:
    """CM2: la 1 entera con ≥ 70 % queda completada y abre la 2; con menos, sigue en curso."""
    c = gr.colegio(integ, "9A", n=2)
    ana, beto = c.estudiantes
    r = unidades_basicas(integ, c)
    for quien, respuestas in ((ana, ("AA", "AAB", "AB")), (beto, ("AA", "ABB", "AB"))):
        for clave, resp in zip(("u1-gra", "u1-voc", "u1-lec"), respuestas, strict=True):
            ra.jugar(integ, quien, *r[clave], resp)
    observado = {"ana_5_de_7": estados(camino(integ, ana)),
                 "beto_4_de_7": estados(camino(integ, beto))}
    assert observado == {
        "ana_5_de_7": [("a2-u01", "completada", "abierta", False, False, 71),
                       ("a2-u02", "sin_empezar", "abierta", True, False, None)],
        "beto_4_de_7": [("a2-u01", "en_curso", "abierta", True, False, 57),
                        ("a2-u02", "sin_empezar", "bloqueada", False, False, None)],
    }, f"CM2: {observado}"


def test_cm3_el_atasco_abre_la_siguiente_a_los_7_dias(integ) -> None:
    """CM3: con la 1 en curso, la 2 se abre sola a los 7 días (con apoyo) y pasa a recomendada."""
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    r = unidades_basicas(integ, c)
    ra.jugar(integ, ana, *r["u1-gra"], "AB")
    envejecer(integ, ana, 6)
    a_los_6 = camino(integ, ana)
    inicio = integ.valor("select min(started_at) from challenge_attempts where student_id = :p",
                         p=ana)
    se_abre = datetime.fromisoformat(a_los_6["unidades"][1]["se_abre_el"])
    envejecer(integ, ana, 1)
    observado = {
        "a_los_6": estados(a_los_6),
        "se_abre_a_los_7_de_empezar": abs((se_abre - (inicio + timedelta(days=7)))
                                          .total_seconds()) < 1,
        "a_los_7": estados(camino(integ, ana)),
    }
    assert observado == {
        "a_los_6": [("a2-u01", "en_curso", "abierta", True, False, 50),
                    ("a2-u02", "sin_empezar", "bloqueada", False, False, None)],
        "se_abre_a_los_7_de_empezar": True,
        "a_los_7": [("a2-u01", "en_curso", "abierta", False, True, 50),
                    ("a2-u02", "sin_empezar", "abierta_con_apoyo", True, False, None)],
    }, f"CM3: {observado}"


def _monedas(integ: Any, tenant: UUID) -> tuple[int, int]:
    """(filas, suma) del libro de monedas de la institución."""
    f = integ.fila("select count(*) as n, coalesce(sum(amount), 0) as s from coin_ledger "
                   "where tenant_id = :t", t=tenant)
    assert f is not None
    return int(f["n"]), int(f["s"])


def test_cm4_el_get_no_escribe_y_el_camino_no_paga(integ) -> None:
    """CM4: leer el camino no cambia ninguna tabla; completar la unidad paga solo su reto."""
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    u1, q1 = ay.reto(integ, c.profe, t("a2-u01", "Uno", "Gramática 1"), 2, grupo=c.grupo)
    ay.reto(integ, c.profe, t("a2-u02", "Dos", "Gramática 1"), 2, grupo=c.grupo, topic="a2-u02")
    antes = cuentas(integ)
    camino(integ, ana)
    tras_leer = cuentas(integ)
    libro_antes = _monedas(integ, c.tenant)
    jugada = ra.jugar(integ, ana, u1, q1, "AA")
    libro_tras_jugar = _monedas(integ, c.tenant)
    leido = [estados(camino(integ, ana)) for _ in range(3)]
    observado = {
        "el_get_no_escribe": tras_leer == antes, "jugada": jugada,
        "paga_del_reto": libro_tras_jugar[1] - libro_antes[1],
        "leer_tras_completar": leido[0],
        "leer_tres_veces_no_paga": _monedas(integ, c.tenant) == libro_tras_jugar,
    }
    assert observado == {
        "el_get_no_escribe": True, "jugada": (200, (True, 10)), "paga_del_reto": 10,
        "leer_tras_completar": [("a2-u01", "completada", "abierta", False, False, 100),
                                ("a2-u02", "sin_empezar", "abierta", True, False, None)],
        "leer_tres_veces_no_paga": True,
    }, f"CM4: {observado}"


def test_cm5_por_institucion_y_por_estudiante(integ) -> None:
    """CM5: lo que hace otro estudiante, o lo de otra institución, no mueve el camino de ana."""
    c = gr.colegio(integ, "9A", n=2)
    ana, beto = c.estudiantes
    r = unidades_basicas(integ, c)
    otra = gr.colegio(integ, "9A", n=1)  # otra institución, mismo código de grupo
    ajeno, qa = ay.reto(integ, otra.profe, t("a2-u01", "Uno", "Ajeno 1"), 2, grupo=otra.grupo)
    for clave in ("u1-gra", "u1-voc", "u1-lec"):
        ra.jugar(integ, beto, *r[clave], "AAA"[:len(r[clave][1])])
    ra.jugar(integ, otra.estudiantes[0], ajeno, qa, "AA")
    observado = {"ana": corto(camino(integ, ana)), "beto": estados(camino(integ, beto))[0],
                 "la_otra": corto(camino(integ, otra.estudiantes[0]))}
    assert observado == {
        "ana": ("A2", False, "a2-u01", [
            ("a2-u01", 1, "Uno", "sin_empezar", "abierta", True,
             ["Gramática 1", "Vocabulario 1", "Lectura 1"]),
            ("a2-u02", 2, "Dos", "sin_empezar", "bloqueada", False,
             ["Gramática 1", "Vocabulario 1"])]),
        "beto": ("a2-u01", "completada", "abierta", False, False, 100),
        "la_otra": ("A2", False, None, [
            ("a2-u01", 1, "Uno", "completada", "abierta", False, ["Ajeno 1"])]),
    }, f"CM5: {observado}"


def test_cm6_prestado_y_vacio(integ) -> None:
    """CM6: sin retos del nivel de práctica (A2) sale el más cercano con `prestado`; sin nada, vacío."""
    c = gr.colegio(integ, "9A", n=1)
    vacio = camino(integ, c.estudiantes[0])
    ay.reto(integ, c.profe, t("b1-u01", "Otra", "Gramática 1"), 2, grupo=c.grupo, nivel="B1",
            topic="b1-u01")
    observado = {"vacio": corto(vacio), "prestado": corto(camino(integ, c.estudiantes[0]))}
    assert observado == {
        "vacio": ("A2", False, None, []),
        "prestado": ("B1", True, "b1-u01", [
            ("b1-u01", 1, "Otra", "sin_empezar", "abierta", True, ["Gramática 1"])]),
    }, f"CM6: {observado}"


def _insertar(integ: Any, consulta: str, **params: Any) -> Any:
    """Una escritura de preparación que devuelve un valor (`returning`), confirmada."""
    from sqlalchemy import text

    async def _s() -> Any:
        async with integ.engine.begin() as conn:
            return (await conn.execute(text(consulta), params)).scalar()

    return integ.run(_s())


def responder_gemelas(integ: Any, c: Any, quien: UUID, reto: str, preguntas: list[str],
                      aciertos: tuple[bool, ...]) -> None:
    """Respuestas de HOY a formas gemela: las primeras por `/answers` (un intento de ese reto) y la
    última por el repaso (una entrada de la cola). Escritas en la base: lo que el camino lee."""
    intento = _insertar(
        integ, "insert into challenge_attempts (tenant_id, challenge_id, student_id, status) "
               "values (:t, :r, :p, 'in_progress') returning id", t=c.tenant, r=reto, p=quien)
    for q, acerto in zip(preguntas[:-1], aciertos[:-1], strict=True):
        sql(integ, "insert into challenge_attempt_answers (tenant_id, attempt_id, profile_id, "
                   "question_id, answer, is_correct) values (:t, :a, :p, :q, 'A', :c)",
            t=c.tenant, a=intento, p=quien, q=q, c=acerto)
    cola = _insertar(
        integ, "insert into reinforcement_queue (tenant_id, profile_id, node_id, origin, "
               "origin_ref) values (:t, :p, 'gr.a2.demo', 'reto', 'demo') returning id",
        t=c.tenant, p=quien)
    sql(integ, "insert into reinforcement_answers (queue_id, tenant_id, profile_id, question_id, "
               "form_key, stage, answer, is_correct, status_after) values (:c, :t, :p, :q, "
               "'demo', 'refuerzo', 'A', :ok, 'en_refuerzo')",
        c=cola, t=c.tenant, p=quien, q=preguntas[-1], ok=aciertos[-1])


def test_cm7_dominada_con_evidencia_demorada(integ) -> None:
    """CM7: completada; respuestas a gemelas 3 días después no bastan; 8 días después, dominada."""
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    u1, q1 = ay.reto(integ, c.profe, t("a2-u01", "Uno", "Gramática 1"), 3, grupo=c.grupo)
    ay.reto(integ, c.profe, t("a2-u02", "Dos", "Gramática 1"), 2, grupo=c.grupo, topic="a2-u02")
    gemelas, qg = ay.de_formas(
        integ, c.profe, t("a2-u01", "Uno", "Gramática 1", "gemela"),
        [rf.forma([], f"g{i}", "fam", "gemela") for i in range(3)], grupo=c.grupo,
        solo_refuerzo=True)
    ra.jugar(integ, ana, u1, q1, "AAA")
    envejecer(integ, ana, 3)
    responder_gemelas(integ, c, ana, gemelas, qg, (True, True, True))
    a_los_3 = estados(camino(integ, ana))[0]
    envejecer(integ, ana, 5)
    observado = {"a_los_3": a_los_3, "a_los_8": estados(camino(integ, ana))[0]}
    assert observado == {
        "a_los_3": ("a2-u01", "completada", "abierta", False, False, 100),
        "a_los_8": ("a2-u01", "dominada", "abierta", False, False, 100),
    }, f"CM7: {observado}"


def test_humo_camino_escribe_su_archivo(integ) -> None:
    """Humo (METODO regla 6): un caso chico de punta a punta escribe `tests/_salida/humo_camino.json`."""
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    r = unidades_basicas(integ, c)
    ra.jugar(integ, ana, *r["u1-gra"], "AA")
    cuerpo = camino(integ, ana)
    nombres = {e["id"]: e["title"] for u in cuerpo["unidades"] for e in u["estaciones"]}
    for u in cuerpo["unidades"]:  # sin ids ni horas: el archivo dice lo mismo en dos corridas
        u["siguiente_reto"] = nombres.get(u["siguiente_reto"])
        for campo in ("empezada_en", "completada_en", "se_abre_el"):
            u[campo] = u[campo] is not None
        for e in u["estaciones"]:
            e["id"] = e["title"]
    RUTA_HUMO.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO.write_text(json.dumps(cuerpo, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    leido = json.loads(RUTA_HUMO.read_text(encoding="utf-8"))
    assert (leido["recomendada"], [u["estado"] for u in leido["unidades"]],
            leido["unidades"][0]["estaciones_jugadas"]) == (
        "a2-u01", ["en_curso", "sin_empezar"], 1), f"HUMO: {leido}"
