"""SR1 a SR5: los retos `solo_refuerzo`, la segunda vuelta y el nivel agotado, por HTTP.

`docs/ESPEC_solo_refuerzo.md` §2. Lo observado va en un dict que se compara
ENTERO. Tramposos: `tests/tramposos/test_tramposos_solo_refuerzo.py`.
"""
from __future__ import annotations

from typing import Any

import pytest

from tests.curriculo import _ayuda as cat
from tests.grader import _ayuda as gr
from tests.practica import _ayuda as ay
from tests.racha import _ayuda as ra
from tests.refuerzo import _ayuda as rf

pytestmark = pytest.mark.integ

P = "pendiente"


def _familia(integ: Any, c: Any, nodos: list[str] | None = None) -> dict[str, Any]:
    """El original (feed), la gemela y el repaso (`solo_refuerzo`) de dos familias."""
    n = nodos or []
    return {
        "orig": ay.de_formas(integ, c.profe, "orig", [
            rf.forma(n, "fa-1", "fa", "original"), rf.forma(n, "fb-1", "fb", "original")],
            grupo=c.grupo),
        "gem": ay.de_formas(integ, c.profe, "gem", [
            rf.forma(n, "fa-2", "fa", "gemela"), rf.forma(n, "fb-2", "fb", "gemela")],
            grupo=c.grupo, solo_refuerzo=True),
        "rep": ay.de_formas(integ, c.profe, "rep", [
            rf.forma(n, "fa-3", "fa", "repaso"), rf.forma(n, "fb-3", "fb", "repaso")],
            grupo=c.grupo, solo_refuerzo=True),
    }


def test_sr1_fuera_del_feed_y_de_la_tanda(integ, monkeypatch) -> None:
    """SR1 (C3): la gemela y el repaso no salen, no se abren y no pagan tres veces lo mismo."""
    ra.fijar_dia(monkeypatch, ra.dia(0))
    ay.sin_escalera(monkeypatch)
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    r = _familia(integ, c)
    todos = ay.client.get("/challenges/all", headers=integ.headers(c.profe)).json()
    primera = ay.tanda(integ, ana)
    observado: dict[str, Any] = {
        "feed": ay.feed(integ, ana),
        "tanda": ay.corta(primera),
        "el_estudiante_no_los_ve": [ay.ver(integ, ana, r[t][0]) for t in ("orig", "gem", "rep")],
        "ni_los_abre": [ay.abrir(integ, ana, r[t][0]) for t in ("gem", "rep")],
        "el_profe_si": [ay.ver(integ, c.profe, r[t][0]) for t in ("orig", "gem", "rep")],
        "el_profe_los_lista": sorted((x["title"], x["coins_reward"]) for x in todos),
        "el_esquema_no_cambia": "solo_refuerzo" not in str(todos),
        "gana_el_original": ra.jugar(integ, ana, *r["orig"], "AA"),
        "feed_despues": ay.feed(integ, ana),
        "saldo": integ.saldo("profile", ana),
        "intentos_en_los_de_refuerzo": int(integ.valor(
            "select count(*) from challenge_attempts a join challenges c on c.id = "
            "a.challenge_id where c.solo_refuerzo")),
        "en_la_base": sorted((str(t), bool(s)) for t, s in _marcas(integ)),
    }
    assert observado == {
        "feed": ["orig"],
        "tanda": ("A2", False, (1, "nuevo", "A2", [("orig", P, 10)], 2, 0, False),
                  1, False, False, False),
        "el_estudiante_no_los_ve": [200, 404, 404], "ni_los_abre": [404, 404],
        "el_profe_si": [200, 200, 200],
        "el_profe_los_lista": [("gem", 5), ("orig", 10), ("rep", 5)],
        "el_esquema_no_cambia": True,
        "gana_el_original": (200, (True, 10)), "feed_despues": ["orig"], "saldo": 10,
        "intentos_en_los_de_refuerzo": 0,
        "en_la_base": [("gem", True), ("orig", False), ("rep", True)],
    }, f"SR1: {observado}"


def _marcas(integ: Any) -> list[Any]:
    from sqlalchemy import text

    async def _q() -> list[Any]:
        async with integ.Session() as db:
            return list((await db.execute(text(
                "select title, solo_refuerzo from challenges"))).all())

    return list(integ.run(_q()))


def test_sr2_los_de_refuerzo_alimentan_la_cola(integ, monkeypatch) -> None:
    """SR2 (C4): tras fallar el original, la cola sirve la gemela del reto `solo_refuerzo`."""
    ra.fijar_dia(monkeypatch, ra.dia(0))
    rf.fijar_ahora(monkeypatch)
    ay.sin_escalera(monkeypatch)
    cat.cargar(integ, cat.mapa_v1())
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    r = _familia(integ, c, nodos=[rf.UNO])
    falla = ra.jugar(integ, ana, *r["orig"], "BA")  # falla fa-1
    dinero = rf.dinero(integ, c.tenant, ana)
    estado, (pendientes, _repasar, en_espera, _superados) = rf.leer(integ, ana)
    entrada = rf.entrada_de(integ, ana, rf.UNO)
    responde = rf.responder(integ, ana, entrada, r["gem"][1][0], "A")
    observado = {
        "falla_el_original": falla,
        "la_cola_sirve_la_gemela": (estado, [(e, n, q == r["gem"][1][0])
                                             for e, n, q in pendientes], en_espera),
        "la_responde": (responde[0], responde[1][0], responde[1][2], responde[1][5]),
        "dinero_identico": rf.dinero(integ, c.tenant, ana) == dinero,
        "sigue_sin_poder_abrir_el_reto": ay.abrir(integ, ana, r["gem"][0]),
    }
    assert observado == {
        "falla_el_original": (200, (False, 0)),
        "la_cola_sirve_la_gemela": (200, [("refuerzo", rf.UNO, True)], 0),
        "la_responde": (200, True, "por_repasar", 0),
        "dinero_identico": True, "sigue_sin_poder_abrir_el_reto": 404,
    }, f"SR2: {observado}"


def test_sr3_la_segunda_vuelta(integ, monkeypatch) -> None:
    """SR3 (C5): gemelas no vistas, a 21 días del original, pagando 5 una vez."""
    ra.fijar_dia(monkeypatch, ra.dia(0))
    ay.sin_escalera(monkeypatch)
    cat.cargar(integ, cat.mapa_v1())
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    una = lambda titulo, item, familia, rol, nodos=(), **k: ay.de_formas(  # noqa: E731
        integ, c.profe, titulo, [rf.forma(list(nodos), item, familia, rol)], grupo=c.grupo, **k)
    o1 = una("o1", "f1-1", "f1", "original", [rf.UNO])
    o2, o3 = una("o2", "f2-1", "f2", "original"), una("o3", "f3-1", "f3", "original")
    g1 = una("g1", "f1-2", "f1", "gemela", [rf.UNO], solo_refuerzo=True)
    g2 = una("g2", "f2-2", "f2", "gemela", solo_refuerzo=True)
    una("g3", "f3-2", "f3", "gemela", solo_refuerzo=True)
    una("p2", "f2-3", "f2", "repaso", solo_refuerzo=True)
    visto: dict[str, Any] = {
        "juega_los_originales": [ra.jugar(integ, ana, *o1, "B"), ra.jugar(integ, ana, *o1, "A"),
                                 ra.jugar(integ, ana, *o2, "A"), ra.jugar(integ, ana, *o3, "A")]}
    hoy = ay.tanda(integ, ana)
    visto["hoy_no_hay_segunda_vuelta"] = ay.corta(hoy)
    repaso = hoy["tanda"]["repaso"]
    assert len(repaso) == 1, f"SR3: la tanda no trae el repaso de f1: {ay.corta(hoy)}"
    visto["el_repaso_gasta_la_gemela_de_f1"] = (
        repaso[0]["pregunta"]["id"] == g1[1][0],
        rf.responder(integ, ana, repaso[0]["entrada_id"], g1[1][0], "A")[1][0])
    ay.envejecer(integ, [o1[0], o2[0]], 22)  # o3 se jugó hoy: su gemela no entra
    ra.fijar_dia(monkeypatch, ra.dia(1))
    segunda = ay.tanda(integ, ana)
    visto["a_22_dias"] = ay.corta(segunda)
    visto["acceso"] = (ay.ver(integ, ana, g2[0]), ay.ver(integ, ana, g1[0]))
    visto["la_gana"] = ra.jugar(integ, ana, *g2, "A")
    visto["otra_vez"] = ra.jugar(integ, ana, *g2, "A")
    visto["despues"] = ay.corta(ay.tanda(integ, ana, "GET"))
    visto["pagas_de_g2"] = [int(m) for m in _pagas(integ, g2[0])]
    visto["cuenta_para_el_dia"] = ra.hoy(integ, ana)
    assert visto == {
        "juega_los_originales": [(200, (False, 0)), (200, (True, 10)), (200, (True, 10)),
                                 (200, (True, 10))],
        "hoy_no_hay_segunda_vuelta": (
            "A2", False, (1, "repetir", "A2", [("o1", P, 0), ("o2", P, 0), ("o3", P, 0)],
                          3, 1, False), 1, False, False, True),
        "el_repaso_gasta_la_gemela_de_f1": (True, True),
        "a_22_dias": ("A2", False, (1, "segunda_vuelta", "A2", [("g2", P, 5)], 1, 0, False),
                      1, False, False, True),
        "acceso": (200, 404),
        "la_gana": (200, (True, 5)), "otra_vez": (200, (True, 0)),
        "despues": ("A2", False, (1, "segunda_vuelta", "A2", [("g2", "ganado", 0)], 1, 0, True),
                    1, True, False, True),
        "pagas_de_g2": [5], "cuenta_para_el_dia": (1, 1, False),
    }, f"SR3: {visto}"


def _pagas(integ: Any, reto: str) -> list[Any]:
    from sqlalchemy import text

    async def _q() -> list[Any]:
        async with integ.Session() as db:
            return list((await db.execute(text(
                "select amount from coin_ledger where action = 'challenge' and amount > 0 "
                "and metadata->>'challenge_id' = :r order by id"), {"r": reto})).scalars())

    return list(integ.run(_q()))


def test_sr4_sin_retos_del_nivel_se_presta_de_otro(integ, monkeypatch) -> None:
    """SR4 (C6): una institución sin retos del nivel no deja la tanda vacía."""
    ra.fijar_dia(monkeypatch, ra.dia(0))
    ay.sin_escalera(monkeypatch)
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    a1 = [ay.reto(integ, c.profe, f"a1-{i}", 3, grupo=c.grupo, nivel="A1", topic=f"a1-u0{i}")
          for i in (1, 2)]
    b2 = ay.reto(integ, c.profe, "b2-1", 3, grupo=c.grupo, nivel="B2", topic="b2-u01")
    visto: dict[str, Any] = {"la_1_de_abajo": ay.corta(ay.tanda(integ, ana))}
    visto["paga_como_reto_nuevo"] = [ra.jugar(integ, ana, *r, "AAA") for r in a1]
    visto["la_2_de_arriba"] = ay.corta(ay.tanda(integ, ana))
    visto["gana_el_de_b2"] = ra.jugar(integ, ana, *b2, "AAA")
    ra.fijar_dia(monkeypatch, ra.dia(1))
    visto["manana_repite_lo_prestado"] = ay.corta(ay.tanda(integ, ana))
    visto["el_nivel_de_practica_no_se_movio"] = ay.nivel(integ, ana)
    visto["huecos"] = [tuple(f) for f in _huecos(integ)]
    visto["dias_sin_contenido"] = int(integ.valor(
        "select count(*) from activity_days where sin_contenido"))
    assert visto == {
        "la_1_de_abajo": ("A2", False,
                          (1, "nuevo", "A1", [("a1-1", P, 10), ("a1-2", P, 10)], 6, 0, False),
                          1, False, False, False),
        "paga_como_reto_nuevo": [(200, (True, 10)), (200, (True, 10))],
        "la_2_de_arriba": ("A2", False, (2, "nuevo", "B2", [("b2-1", P, 10)], 3, 0, False),
                           2, False, False, False),
        "gana_el_de_b2": (200, (True, 10)),
        "manana_repite_lo_prestado": (
            "A2", False, (1, "repetir", "A1", [("a1-1", P, 0), ("a1-2", P, 0)], 6, 0, False),
            1, False, False, True),
        "el_nivel_de_practica_no_se_movio": ("A2", False),
        "huecos": [("A2", "A1", 2), ("A2", "B2", 1)],
        "dias_sin_contenido": 0,
    }, f"SR4: {visto}"


def _huecos(integ: Any) -> list[Any]:
    """(nivel agotado, nivel de la tanda, tandas) de las tandas con hueco de contenido."""
    from sqlalchemy import text

    async def _q() -> list[Any]:
        async with integ.Session() as db:
            return list((await db.execute(text(
                "select nivel_agotado, nivel, count(*) from practice_tandas "
                "where nivel_agotado is not null group by 1, 2 order by 1, 2"))).all())

    return list(integ.run(_q()))


def test_sr5_sin_contenido_la_semana_no_rompe_la_racha(integ, monkeypatch) -> None:
    """SR5 (C7): quien pidió practicar y no había nada conserva su racha y su protector."""
    c = gr.colegio(integ, "9A", n=2)
    ana, beto = c.estudiantes
    for d in (0, 1, 2):  # semana 1: los dos la cumplen asistiendo
        ra.fijar_dia(monkeypatch, ra.dia(d))
        for e in (ana, beto):
            assert ra.asistir(integ, c.tenant, c.grupo, c.profe, e).status_code == 200
    visto: dict[str, Any] = {"semana_1": [ra.corta(integ, e) for e in (ana, beto)]}
    ra.fijar_dia(monkeypatch, ra.dia(8))  # semana 2: no hay ni un reto; solo Ana pide
    sin_nada = ay.tanda(integ, ana)
    visto["ana_pide_y_no_hay_nada"] = (ay.corta(sin_nada), ay.protegida(sin_nada),
                                       ay.tandas_en_la_base(integ))
    visto["el_get_lo_dice_y_no_escribe"] = ay.protegida(ay.tanda(integ, ana, "GET"))
    visto["beto_no_pidio"] = ay.protegida(ay.tanda(integ, beto, "GET"))
    ra.fijar_dia(monkeypatch, ra.dia(15))  # semana 3: se cierra la 2
    visto["al_cerrar_la_2"] = [ra.corta(integ, e) for e in (ana, beto)]
    ay.tanda(integ, ana)  # otra semana sin nada: Ana vuelve a pedir
    ra.fijar_dia(monkeypatch, ra.dia(22))  # semana 4: se cierra la 3
    visto["al_cerrar_la_3"] = [ra.corta(integ, e) for e in (ana, beto)]
    ay.reto(integ, c.profe, "por-fin", 6, grupo=c.grupo)  # ya hay contenido
    con_contenido = ay.tanda(integ, ana)
    visto["con_contenido_no_hay_exencion"] = (ay.protegida(con_contenido),
                                              con_contenido["tanda"]["preguntas"])
    ra.fijar_dia(monkeypatch, ra.dia(29))  # semana 5: Ana no practicó la 4, que sí tenía
    visto["al_cerrar_la_4"] = ra.corta(integ, ana)
    visto["dias_marcados"] = int(integ.valor(
        "select count(*) from activity_days where sin_contenido"))
    assert visto == {
        "semana_1": [(1, 1, 1, 1, 3, True), (1, 1, 1, 1, 3, True)],
        "ana_pide_y_no_hay_nada": (("A2", False, None, 0, True, False, True), True, 0),
        "el_get_lo_dice_y_no_escribe": True, "beto_no_pidio": False,
        "al_cerrar_la_2": [(1, 1, 1, 1, 0, False), (1, 1, 1, 0, 0, False)],
        "al_cerrar_la_3": [(1, 1, 1, 1, 0, False), (0, 1, 1, 0, 0, False)],
        "con_contenido_no_hay_exencion": (False, 6),
        "al_cerrar_la_4": (1, 1, 1, 0, 0, False),
        "dias_marcados": 2,
    }, f"SR5: {visto}"
