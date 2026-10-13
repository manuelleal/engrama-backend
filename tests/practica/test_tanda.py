"""TD1 a TD6: el nivel de práctica y la tanda de hoy, por HTTP.

`docs/ESPEC_practica_y_tanda.md` §2. Lo observado va en un dict que se compara
ENTERO. Tramposos: `tests/tramposos/test_tramposos_practica.py`.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.shared.models import Membership
from tests.curriculo import _ayuda as cat
from tests.grader import _ayuda as gr
from tests.practica import _ayuda as ay
from tests.racha import _ayuda as ra
from tests.refuerzo import _ayuda as rf

pytestmark = pytest.mark.integ

P = "pendiente"


def test_td1_la_tanda_sale_del_nivel_de_practica(integ, monkeypatch) -> None:
    """TD1 (C4): sin SET sale del A2, en orden fijo, sin la clave, y el POST es idempotente."""
    ra.fijar_dia(monkeypatch, ra.dia(0))
    ay.sin_escalera(monkeypatch)
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    otro_grupo = integ.crear_grupo(c.tenant, "9B")
    # Sembrados en desorden a propósito: el orden lo pone la regla, no la fecha.
    ay.reto(integ, c.profe, "u2-gra", 3, grupo=c.grupo, topic="a2-u02")
    ay.reto(integ, c.profe, "u1-lec", 3, grupo=c.grupo, skill=None)
    ay.reto(integ, c.profe, "u1-voc", 3, grupo=c.grupo, skill="vocabulary")
    ay.reto(integ, c.profe, "u1-gra", 2, grupo=c.grupo)
    ay.reto(integ, c.profe, "de-b1", 3, grupo=c.grupo, nivel="B1", topic="a0")
    ay.reto(integ, c.profe, "de-otro-grupo", 3, grupo=otro_grupo, topic="a0")
    ay.reto(integ, c.profe, "sin-nivel", 3, grupo=c.grupo, nivel=None, topic="a0")
    inactivo, _ = ay.reto(integ, c.profe, "inactivo", 3, grupo=c.grupo, topic="a0")
    ganado, q = ay.reto(integ, c.profe, "ya-ganado", 2, grupo=c.grupo, topic="a0")
    apagar = ay.client.patch(f"/challenges/{inactivo}/status", headers=integ.headers(c.profe),
                             json={"status": "inactive"})
    gana = ra.jugar(integ, ana, ganado, q, "AA")
    antes = ay.tanda(integ, ana, "GET")
    tras_el_get = ay.tandas_en_la_base(integ)
    primera = ay.tanda(integ, ana)
    otra_vez = ay.tanda(integ, ana)
    observado: dict[str, Any] = {
        "preparacion": (apagar.status_code, gana),
        "antes": ay.corta(antes), "el_get_no_escribe": tras_el_get,
        "primera": ay.corta(primera),
        "sin_la_clave": "correct_answer" not in str(primera),
        "trae_las_preguntas": [len(r["reto"]["questions"]) for r in primera["tanda"]["retos"]],
        "repetir_devuelve_la_misma": otra_vez == primera,
        "el_get_la_muestra": ay.tanda(integ, ana, "GET") == primera,
        "tandas_en_la_base": ay.tandas_en_la_base(integ),
    }
    assert observado == {
        "preparacion": (200, (200, (True, 10))),
        "antes": ("A2", False, None, 0, True, False, False), "el_get_no_escribe": 0,
        "primera": ("A2", False,
                    (1, "nuevo", "A2", [("u1-gra", P, 10), ("u1-voc", P, 10), ("u1-lec", P, 10)],
                     8, 0, False), 1, False, False, False),
        "sin_la_clave": True, "trae_las_preguntas": [2, 3, 3],
        "repetir_devuelve_la_misma": True, "el_get_la_muestra": True, "tandas_en_la_base": 1,
    }, f"TD1: {observado}"


def test_td2_el_tope_de_dos_tandas_al_dia(integ, monkeypatch) -> None:
    """TD2 (C5): completa la 1 → la 2 (retos distintos) → listo por hoy; mañana hay más."""
    ra.fijar_dia(monkeypatch, ra.dia(0))
    ay.sin_escalera(monkeypatch)
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    retos = {t: ay.reto(integ, c.profe, t, 3, grupo=c.grupo, topic=f"a2-u0{i}")
             for i, t in enumerate(("t1", "t2", "t3", "t4"), start=1)}
    visto: dict[str, Any] = {"la_1": ay.corta(ay.tanda(integ, ana))}
    ra.jugar(integ, ana, *retos["t1"], "ABB")  # la juega y no la gana
    visto["a_medias"] = ay.corta(ay.tanda(integ, ana))
    ra.jugar(integ, ana, *retos["t2"], "AAA")
    visto["la_1_completa"] = ay.corta(ay.tanda(integ, ana, "GET"))
    visto["la_2"] = ay.corta(ay.tanda(integ, ana))
    ra.jugar(integ, ana, *retos["t3"], "AAA")
    ra.jugar(integ, ana, *retos["t4"], "BBB")
    visto["tras_la_2"] = ay.corta(ay.tanda(integ, ana))
    visto["tandas_hoy_en_la_base"] = ay.tandas_en_la_base(integ)
    ra.fijar_dia(monkeypatch, ra.dia(1))
    visto["manana_antes"] = ay.corta(ay.tanda(integ, ana, "GET"))
    visto["manana"] = ay.corta(ay.tanda(integ, ana))
    assert visto == {
        "la_1": ("A2", False, (1, "nuevo", "A2", [("t1", P, 10), ("t2", P, 10)], 6, 0, False),
                 1, False, False, False),
        "a_medias": ("A2", False, (1, "nuevo", "A2", [("t1", "jugado", 10), ("t2", P, 10)],
                                   6, 0, False), 1, False, False, False),
        "la_1_completa": ("A2", False,
                          (1, "nuevo", "A2", [("t1", "jugado", 10), ("t2", "ganado", 0)],
                           6, 0, True), 1, True, False, False),
        "la_2": ("A2", False, (2, "nuevo", "A2", [("t3", P, 10), ("t4", P, 10)], 6, 0, False),
                 2, False, False, False),
        "tras_la_2": ("A2", False,
                      (2, "nuevo", "A2", [("t3", "ganado", 0), ("t4", "jugado", 10)],
                       6, 0, True), 2, False, True, False),
        "tandas_hoy_en_la_base": 2,
        "manana_antes": ("A2", False, None, 0, True, False, False),
        "manana": ("A2", False, (1, "nuevo", "A2", [("t1", P, 10), ("t4", P, 10)], 6, 0, False),
                   1, False, False, False),
    }, f"TD2: {visto}"


def test_td3_el_repaso_va_primero_y_no_paga(integ, monkeypatch) -> None:
    """TD3 (C6): hasta 3 repasos que tocan, con 0 monedas; el respondido no vuelve hoy."""
    ra.fijar_dia(monkeypatch, ra.dia(0))
    rf.fijar_ahora(monkeypatch)
    ay.sin_escalera(monkeypatch)
    cat.cargar(integ, cat.mapa_v1())
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    nodos = (rf.UNO, rf.DOS, rf.TRES, rf.CUATRO)
    examen, q = rf.sembrar_reto(integ, c.profe, "originales", [
        rf.forma([n], f"f{i}-1", f"f{i}", "original") for i, n in enumerate(nodos)],
        grupo=c.grupo)
    rf.sembrar_reto(integ, c.profe, "paralelas", [
        rf.forma([n], f"f{i}-{k}", f"f{i}", rol) for i, n in enumerate(nodos)
        for k, rol in ((2, "gemela"), (3, "repaso"))], grupo=c.grupo)
    ay.reto(integ, c.profe, "nuevo", 6, grupo=c.grupo)
    fallo = rf.jugar(integ, ana, examen, dict.fromkeys(q.values(), "B"))
    dinero = rf.dinero(integ, c.tenant, ana)
    primera = ay.tanda(integ, ana)
    repaso = primera["tanda"]["repaso"]
    assert len(repaso) == 3, f"TD3: la tanda no trae los 3 repasos: {ay.corta(primera)}"
    bien = rf.responder(integ, ana, repaso[0]["entrada_id"], repaso[0]["pregunta"]["id"], "A")
    mal = rf.responder(integ, ana, repaso[1]["entrada_id"], repaso[1]["pregunta"]["id"], "B")
    despues = ay.tanda(integ, ana, "GET")
    observado = {
        "falla_los_cuatro": (fallo, len(rf.cola(integ, ana))),
        "primera": ay.corta(primera),
        "los_tres_mas_viejos": [(p["etapa"], p["nodo"]["id"]) for p in repaso],
        "el_repaso_no_trae_la_clave": "correct_answer" not in str(repaso),
        "responde_dos": (bien[1][0], bien[1][5], mal[1][0], mal[1][5]),
        "quedan_en_la_tanda": [p["nodo"]["id"] for p in despues["tanda"]["repaso"]],
        "la_cola_si_sirve_otra_forma_del_fallado": rf.DOS in [n for _e, n, _p in
                                                              rf.leer(integ, ana)[1][0]],
        "dinero_identico": rf.dinero(integ, c.tenant, ana) == dinero,
    }
    assert observado == {
        "falla_los_cuatro": ((200, (False, 0)), 4),
        "primera": ("A2", False, (1, "nuevo", "A2", [("nuevo", P, 10)], 6, 3, False),
                    1, False, False, False),
        "los_tres_mas_viejos": [("refuerzo", rf.TRES), ("refuerzo", rf.DOS),
                                ("refuerzo", rf.UNO)],
        "el_repaso_no_trae_la_clave": True,
        "responde_dos": (True, 0, False, 0),
        "quedan_en_la_tanda": [rf.UNO],
        "la_cola_si_sirve_otra_forma_del_fallado": True,
        "dinero_identico": True,
    }, f"TD3: {observado}"


def test_td4_la_escalera_solo_mira_el_primer_intento(integ, monkeypatch) -> None:
    """TD4 (C7): sube, baja y respeta el ancla de SET; nunca escribe el nivel confirmado."""
    ra.fijar_dia(monkeypatch, ra.dia(0))
    c = gr.colegio(integ, "9A", n=3)
    sube, baja, con_set = c.estudiantes
    ay.confirmar_con_set(integ, c.tenant, con_set, "B1")
    confirmados = ay.niveles_confirmados(integ)
    a2 = [ay.reto(integ, c.profe, f"a2-{i}", 3, grupo=c.grupo, topic=f"a2-u0{i}")
          for i in (1, 2)]
    b1 = [ay.reto(integ, c.profe, f"b1-{i}", 3, grupo=c.grupo, nivel="B1", topic=f"b1-u0{i}")
          for i in (1, 2, 3, 4)]
    b2 = [ay.reto(integ, c.profe, f"b2-{i}", 3, grupo=c.grupo, nivel="B2", topic=f"b2-u0{i}")
          for i in (1, 2, 3, 4)]
    visto: dict[str, Any] = {"arranque": [ay.nivel(integ, e) for e in c.estudiantes]}
    # `sube`: 5 de 6 en sus primeros intentos (ventana rápida, sin SET).
    ra.jugar(integ, sube, *a2[0], "AAA")
    visto["sube_con_3_de_3"] = ay.nivel(integ, sube)
    ra.jugar(integ, sube, *a2[1], "AAB")
    visto["sube_con_5_de_6"] = ay.nivel(integ, sube)
    # `baja`: 1 de 6 al primer intento; los segundos intentos (ya vio la clave) no cuentan.
    ra.jugar(integ, baja, *a2[0], "BBB")
    ra.jugar(integ, baja, *a2[0], "AAA")
    ra.jugar(integ, baja, *a2[1], "BBA")
    visto["baja_antes_del_segundo_intento"] = ay.nivel(integ, baja)
    ra.jugar(integ, baja, *a2[1], "AAA")
    visto["baja_tras_copiar_la_clave"] = ay.nivel(integ, baja)
    # `con_set`: ancla B1; 12 de 12 sube a B2 y de ahí no pasa.
    for reto, q in b1:
        ra.jugar(integ, con_set, reto, q, "AAA")
    visto["con_set_tras_12_de_12"] = ay.nivel(integ, con_set)
    for reto, q in b2:
        ra.jugar(integ, con_set, reto, q, "AAA")
    visto["con_set_no_pasa_de_b2"] = ay.nivel(integ, con_set)
    visto["nivel_confirmado_intacto"] = ay.niveles_confirmados(integ) == confirmados
    visto["confirmados"] = ay.niveles_confirmados(integ)
    assert visto == {
        "arranque": [("A2", False), ("A2", False), ("B1", True)],
        "sube_con_3_de_3": ("A2", False), "sube_con_5_de_6": ("B1", False),
        "baja_antes_del_segundo_intento": ("A1", False),
        "baja_tras_copiar_la_clave": ("A1", False),
        "con_set_tras_12_de_12": ("B2", True), "con_set_no_pasa_de_b2": ("B2", True),
        "nivel_confirmado_intacto": True, "confirmados": [("B1", "set")],
    }, f"TD4: {visto}"


def test_td5_cuando_el_nivel_se_agota(integ, monkeypatch) -> None:
    """TD5 (C8): sin retos nuevos sube si puede; si no, vuelve a jugar lo ganado, con paga 0."""
    ra.fijar_dia(monkeypatch, ra.dia(0))
    ay.sin_escalera(monkeypatch)
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    de_a2 = ay.reto(integ, c.profe, "de-a2", 3, grupo=c.grupo)
    de_b1 = ay.reto(integ, c.profe, "de-b1", 3, grupo=c.grupo, nivel="B1", topic="b1-u01")
    visto: dict[str, Any] = {"hoy_la_1": ay.corta(ay.tanda(integ, ana))}
    ra.jugar(integ, ana, *de_a2, "AAA")
    visto["hoy_la_2_sube_de_nivel"] = ay.corta(ay.tanda(integ, ana))
    visto["gana_la_de_b1"] = ra.jugar(integ, ana, *de_b1, "AAA")
    ra.fijar_dia(monkeypatch, ra.dia(1))
    visto["manana_solo_queda_repetir"] = ay.corta(ay.tanda(integ, ana))
    visto["repetir_paga_cero"] = ra.jugar(integ, ana, *de_b1, "AAA")
    visto["manana_completa"] = ay.corta(ay.tanda(integ, ana, "GET"))
    visto["dia_activo_por_repetir"] = ra.hoy(integ, ana)
    visto["huecos"] = [tuple(f) for f in _huecos(integ)]
    assert visto == {
        "hoy_la_1": ("A2", False, (1, "nuevo", "A2", [("de-a2", P, 10)], 3, 0, False),
                     1, False, False, False),
        "hoy_la_2_sube_de_nivel": ("B1", False, (2, "nuevo", "B1", [("de-b1", P, 10)], 3, 0,
                                                 False), 2, False, False, False),
        "gana_la_de_b1": (200, (True, 10)),
        "manana_solo_queda_repetir": ("B1", False,
                                      (1, "repetir", "B1", [("de-b1", P, 0)], 3, 0, False),
                                      1, False, False, True),
        "repetir_paga_cero": (200, (True, 0)),
        "manana_completa": ("B1", False, (1, "repetir", "B1", [("de-b1", "jugado", 0)], 3, 0,
                                          True), 1, True, False, True),
        "dia_activo_por_repetir": (3, 3, False),
        "huecos": [("A2", 1), ("B1", 1)],
    }, f"TD5: {visto}"


def _huecos(integ: Any) -> list[Any]:
    """El hueco de contenido: (nivel agotado, estudiantes sin contenido nuevo)."""
    from sqlalchemy import text

    async def _q() -> list[Any]:
        async with integ.Session() as db:
            return list((await db.execute(text(
                "select nivel_agotado, count(distinct profile_id) from practice_tandas "
                "where nivel_agotado is not null group by nivel_agotado order by 1"))).all())

    return list(integ.run(_q()))


def test_td6_el_nivel_y_la_tanda_son_por_institucion(integ, monkeypatch) -> None:
    """TD6 (C9): lo que pasa en una institución no se ve en la otra."""
    ra.fijar_dia(monkeypatch, ra.dia(0))
    a, b = gr.colegio(integ, "9A", n=1), gr.colegio(integ, "9B", n=1)
    doble = a.estudiantes[0]
    integ._insertar(Membership(tenant_id=b.tenant, profile_id=doble, role="student",
                               group_code="9B", is_active=True, full_name="Persona doble"))
    en_a, en_b = {"X-Tenant-ID": str(a.tenant)}, {"X-Tenant-ID": str(b.tenant)}
    de_a = [ay.reto(integ, a.profe, f"de-a-{i}", 3, grupo=a.grupo, topic=f"a2-u0{i}")
            for i in (1, 2)]
    ay.reto(integ, b.profe, "de-b", 3, grupo=b.grupo)
    ay.reto(integ, a.profe, "de-a-b1", 6, grupo=a.grupo, nivel="B1", topic="b1-u01")
    for reto, q in de_a:  # 6 de 6 en A: sube a B1 en A
        ra.jugar(integ, doble, reto, q, "AAA")
    observado = {
        "en_a": ay.nivel(integ, doble, **en_a),
        "en_b_antes": ay.nivel(integ, doble, **en_b),
        "tanda_en_b": ay.corta(ay.tanda(integ, doble, **en_b)),
        "tanda_en_a": ay.corta(ay.tanda(integ, doble, **en_a)),
        "en_b_despues": ay.nivel(integ, doble, **en_b),
        "filas_de_nivel": int(integ.valor("select count(*) from practice_levels")),
    }
    assert observado == {
        "en_a": ("B1", False), "en_b_antes": ("A2", False),
        "tanda_en_b": ("A2", False, (1, "nuevo", "A2", [("de-b", P, 10)], 3, 0, False),
                       1, False, False, False),
        "tanda_en_a": ("B1", False, (1, "nuevo", "B1", [("de-a-b1", P, 10)], 6, 0, False),
                       1, False, False, False),
        "en_b_despues": ("A2", False), "filas_de_nivel": 2,
    }, f"TD6: {observado}"
