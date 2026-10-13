"""RW1 a RW7: la racha semanal por institución, por HTTP — `docs/ESPEC_racha_semanal.md` §2.

Lo observado va en un dict que se compara ENTERO y sale en el mensaje.
Tramposos: `tests/tramposos/test_tramposos_racha.py`.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.shared.models import Membership
from tests.curriculo import _ayuda as cat
from tests.grader import _ayuda as gr
from tests.racha import _ayuda as ay
from tests.refuerzo import _ayuda as rf
from tests.seguridad.veredictos import sembrar
from tests.webhooks import _ayuda as ev

pytestmark = pytest.mark.integ

CUATRO_DE_SEIS = "AAAABB"  # día activo sin ganar el reto: no hay paga que estorbe


def _dias_activos(integ: Any, mp: pytest.MonkeyPatch, estudiante: Any, reto: str,
                  preguntas: list[str], dias: list[int]) -> None:
    """Hace activo cada uno de esos días con 6 respuestas y 4 correctas."""
    for n in dias:
        ay.fijar_dia(mp, ay.dia(n))
        assert ay.jugar(integ, estudiante, reto, preguntas, CUATRO_DE_SEIS) == (200, (False, 0))


def test_rw1_el_dia_activo_por_respuestas(integ, monkeypatch) -> None:
    """RW1 (C4): 6 preguntas con 4 correctas; cada pregunta una vez; el repaso suma."""
    ay.fijar_dia(monkeypatch, ay.dia(0))
    rf.fijar_ahora(monkeypatch)
    cat.cargar(integ, cat.mapa_v1())
    c = gr.colegio(integ, "9A", n=3)
    ana, beto, caro = c.estudiantes
    r1, q1 = ay.sembrar(integ, c.profe, "r1", 3, grupo=c.grupo)
    r2, q2 = ay.sembrar(integ, c.profe, "r2", 3, grupo=c.grupo)
    r6, q6 = ay.sembrar(integ, c.profe, "r6", 6, grupo=c.grupo)
    rn, qn = ay.sembrar(integ, c.profe, "rn", 1, grupo=c.grupo, nodos=[rf.UNO])
    ay.sembrar(integ, c.profe, "gemela", 1, grupo=c.grupo, nodos=[rf.UNO])
    pasos_ana = {
        "gana_r1": (ay.jugar(integ, ana, r1, q1, "AAA"), ay.hoy(integ, ana)),
        "repite_r1": (ay.jugar(integ, ana, r1, q1, "AAA"), ay.hoy(integ, ana)),
        "r2_una_bien_una_mal_una_en_blanco": (ay.jugar(integ, ana, r2, q2, "AB-"),
                                              ay.hoy(integ, ana)),
        "r2_responde_mal_la_que_faltaba": (ay.jugar(integ, ana, r2, q2, "ABB"),
                                           ay.hoy(integ, ana)),
    }
    pasos_beto = {
        "seis_con_tres_correctas": (ay.jugar(integ, beto, r6, q6, "AAABBB"), ay.hoy(integ, beto)),
        "reintenta_y_acierta_una_mas": (ay.jugar(integ, beto, r6, q6, "BBBABB"),
                                        ay.hoy(integ, beto)),
    }
    falla = ay.jugar(integ, caro, rn, qn, "B")
    pendiente = rf.pendientes(integ, caro)[0]
    repaso = rf.responder(integ, caro, pendiente["entrada_id"], pendiente["pregunta"]["id"])[0]
    observado = {
        "ana": pasos_ana, "beto": pasos_beto,
        "caro_falla_y_repasa": (falla, repaso, ay.hoy(integ, caro),
                                ay.por_origen(integ, caro, ay.dia(0))),
        "origen_de_ana": ay.por_origen(integ, ana, ay.dia(0)),
        "racha_de_ana": ay.corta(integ, ana),
    }
    assert observado == {
        "ana": {
            "gana_r1": ((200, (True, 10)), (3, 3, False)),
            "repite_r1": ((200, (True, 0)), (3, 3, False)),
            "r2_una_bien_una_mal_una_en_blanco": ((200, (False, 0)), (5, 4, False)),
            "r2_responde_mal_la_que_faltaba": ((200, (False, 0)), (6, 4, True)),
        },
        "beto": {
            "seis_con_tres_correctas": ((200, (False, 0)), (6, 3, False)),
            "reintenta_y_acierta_una_mas": ((200, (False, 0)), (6, 4, True)),
        },
        "caro_falla_y_repasa": ((200, (False, 0)), 200, (2, 1, False), {"reto": 1, "repaso": 1}),
        "origen_de_ana": {"reto": 6},
        "racha_de_ana": (0, 0, 0, 1, 1, False),
    }, f"RW1: {observado}"


def test_rw2_la_asistencia_marca_el_dia_y_el_checkin_no_cambia(integ, monkeypatch) -> None:
    """RW2 (C5): asistir hace activo el día; la segunda sesión no cambia nada (L4-c)."""
    ay.fijar_dia(monkeypatch, ay.dia(1))
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    antes = ay.leer(integ, ana)
    primero = ay.asistir(integ, c.tenant, c.grupo, c.profe, ana)
    tras_uno = ay.leer(integ, ana)
    segundo = ay.asistir(integ, c.tenant, c.grupo, c.profe, ana)
    martes = tras_uno["semana"]["dias"][1] if isinstance(tras_uno, dict) else tras_uno
    observado = {
        "antes": (antes["racha_semanas"], antes["protectores"], antes["semana"]["dias_activos"],
                  len(antes["semana"]["dias"]), antes["hoy"]["activo"]),
        "checkin": (primero.status_code, sorted(primero.json())),
        "el_martes": martes,
        "tras_uno": ay.corta(integ, ana),
        "segunda_sesion": (segundo.status_code, segundo.json().get("ya_cobrada_hoy")),
        "la_segunda_no_cambia_nada": ay.leer(integ, ana) == tras_uno,
        "la_racha_vieja_sigue_igual": integ.valor(
            "select current_streak from profiles where id = :p", p=ana),
        "filas_del_dia": int(integ.valor("select count(*) from activity_days")),
    }
    assert observado == {
        "antes": (0, 1, 0, 7, False),
        "checkin": (200, ["base", "coins_awarded", "message", "puntual", "puntualidad",
                          "streak", "success", "ya_cobrada_hoy"]),
        "el_martes": {"fecha": "2026-10-13", "activo": True, "via_asistencia": True,
                      "respuestas": 0, "correctas": 0},
        "tras_uno": (0, 0, 0, 1, 1, False),
        "segunda_sesion": (200, True),
        "la_segunda_no_cambia_nada": True,
        "la_racha_vieja_sigue_igual": 1,
        "filas_del_dia": 1,
    }, f"RW2: {observado}"


def test_rw3_la_semana_cumplida_y_su_bono(integ, monkeypatch) -> None:
    """RW3 (C6): al 3.er día racha 1 y 5 monedas, una vez; sin bolsa, la semana cuenta igual."""
    rico, pobre = gr.colegio(integ, "9A", n=1), gr.colegio(integ, "9B", n=1)
    sembrar(integ, "update coin_wallets set balance = 0 where owner_type = 'tenant' "
                   "and owner_id = :t", t=pobre.tenant)
    visto: dict[str, Any] = {}
    for nombre, c in (("con_bolsa", rico), ("sin_bolsa", pobre)):
        ana = c.estudiantes[0]
        reto, q = ay.sembrar(integ, c.profe, f"r-{nombre}", 6, grupo=c.grupo)
        pasos = []
        for n in (0, 1, 2, 3):
            ay.fijar_dia(monkeypatch, ay.dia(n))
            envio = ay.jugar(integ, ana, reto, q, CUATRO_DE_SEIS)
            c_ = ay.leer(integ, ana)
            pasos.append((envio[0], ay.corta(integ, ana), c_["bono_semana"]))
        visto[nombre] = {"dia_a_dia": pasos, "bonos": ay.bonos(integ, ana),
                         "saldo": integ.saldo("profile", ana) or 0}
    assert visto == {
        "con_bolsa": {
            "dia_a_dia": [(200, (0, 0, 0, 1, 1, False), {"monedas": 5, "pagado": False}),
                          (200, (0, 0, 0, 1, 2, False), {"monedas": 5, "pagado": False}),
                          (200, (1, 1, 1, 1, 3, True), {"monedas": 5, "pagado": True}),
                          (200, (1, 1, 1, 1, 4, True), {"monedas": 5, "pagado": True})],
            "bonos": [("2026-W42", 5)], "saldo": 5},
        "sin_bolsa": {
            "dia_a_dia": [(200, (0, 0, 0, 1, 1, False), {"monedas": 5, "pagado": False}),
                          (200, (0, 0, 0, 1, 2, False), {"monedas": 5, "pagado": False}),
                          (200, (1, 1, 1, 1, 3, True), {"monedas": 5, "pagado": False}),
                          (200, (1, 1, 1, 1, 4, True), {"monedas": 5, "pagado": False})],
            "bonos": [], "saldo": 0},
    }, f"RW3: {visto}"


def test_rw4_el_cierre_perezoso_por_http(integ, monkeypatch) -> None:
    """RW4 (C7): no cumplir gasta el protector; después rompe; el récord y el total quedan."""
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    reto, q = ay.sembrar(integ, c.profe, "r", 6, grupo=c.grupo)
    _dias_activos(integ, monkeypatch, ana, reto, q, [0, 1, 2])  # semana 1 cumplida
    visto: dict[str, Any] = {"semana_1": (ay.corta(integ, ana), ay.en_la_base(integ, ana))}
    ay.fijar_dia(monkeypatch, ay.dia(7))  # semana 2: no hace nada
    visto["semana_2_en_curso"] = ay.corta(integ, ana)
    ay.fijar_dia(monkeypatch, ay.dia(14))  # semana 3: se cierra la 2 sin cumplir
    visto["semana_3_gasto_el_protector"] = (ay.corta(integ, ana), ay.en_la_base(integ, ana),
                                            ay.leer(integ, ana)["semana_pasada"])
    ay.fijar_dia(monkeypatch, ay.dia(21))  # semana 4: se cierra la 3 sin cumplir
    visto["semana_4_semana_nueva"] = (ay.corta(integ, ana), ay.en_la_base(integ, ana))
    assert ay.jugar(integ, ana, reto, q, CUATRO_DE_SEIS)[0] == 200
    visto["al_escribir_se_guarda"] = (ay.corta(integ, ana), ay.en_la_base(integ, ana))
    assert visto == {
        "semana_1": ((1, 1, 1, 1, 3, True), (1, 1, 1, 1)),
        "semana_2_en_curso": (1, 1, 1, 1, 0, False),
        # La lectura calcula el cierre y NO escribe: la base sigue como estaba.
        "semana_3_gasto_el_protector": ((1, 1, 1, 0, 0, False), (1, 1, 1, 1),
                                        {"dias_activos": 0, "cumplida": False}),
        "semana_4_semana_nueva": ((0, 1, 1, 0, 0, False), (1, 1, 1, 1)),
        "al_escribir_se_guarda": ((0, 1, 1, 0, 1, False), (0, 1, 1, 0)),
    }, f"RW4: {visto}"


def test_rw5_la_racha_es_por_institucion(integ, monkeypatch) -> None:
    """RW5 (C8, BUG-12): con actividad en una institución, en la otra la racha es 0."""
    a, b = gr.colegio(integ, "9A", n=2), gr.colegio(integ, "9B", n=1)
    doble, vecina = a.estudiantes
    integ._insertar(Membership(tenant_id=b.tenant, profile_id=doble, role="student",
                               group_code="9B", is_active=True, full_name="Persona doble"))
    reto, q = ay.sembrar(integ, a.profe, "r", 6, grupo=a.grupo)
    _dias_activos(integ, monkeypatch, doble, reto, q, [0, 1, 2])
    en_b = {"X-Tenant-ID": str(b.tenant)}
    observado = {
        "en_a": ay.corta(integ, doble, **{"X-Tenant-ID": str(a.tenant)}),
        "en_b": ay.corta(integ, doble, **en_b),
        "hoy_en_b": ay.leer(integ, doble, **en_b)["hoy"]["respuestas"],
        "la_vecina_de_a": ay.corta(integ, vecina),
        "filas_de_racha_en_b": int(integ.valor(
            "select count(*) from streak_state where tenant_id = :t", t=b.tenant)),
        "dias_en_b": int(integ.valor(
            "select count(*) from activity_days where tenant_id = :t", t=b.tenant)),
    }
    assert observado == {
        "en_a": (1, 1, 1, 1, 3, True), "en_b": (0, 0, 0, 1, 0, False), "hoy_en_b": 0,
        "la_vecina_de_a": (0, 0, 0, 1, 0, False), "filas_de_racha_en_b": 0, "dias_en_b": 0,
    }, f"RW5: {observado}"


def _respuesta_de_eva(c: ev.Clase, item: str | None, correcta: bool, n: int) -> dict[str, Any]:
    evento = c.de_eva("answer.submitted", sufijo=f"-{n}", correct=correcta)
    evento["item_ref"] = item
    return evento


def test_rw6_las_respuestas_de_eva_cuentan(integ, monkeypatch) -> None:
    """RW6 (C9): 6 respuestas de EVA con 4 correctas hacen el día; reenviar no suma."""
    ay.fijar_dia(monkeypatch, ay.dia(2))
    ev.preparar()
    try:
        c = ev.clase(integ)
        ana = c.estudiantes[0]
        cinco = [_respuesta_de_eva(c, f"it-{i}", i <= 3, i) for i in range(1, 6)]
        primero = ev.cortos(ev.enviar("live", ev.lote(cinco)))
        tras_cinco = ay.hoy(integ, ana)
        otra_vez = ev.cortos(ev.enviar("live", ev.lote(cinco)))
        # El mismo ítem con OTRO evento (segundo intento en clase): no es otra pregunta.
        mismo_item = ev.cortos(ev.enviar("live", ev.lote(
            [_respuesta_de_eva(c, "it-1", True, 7), _respuesta_de_eva(c, None, True, 8)],
            batch_id="lote-2")))
        sin_sumar = ay.hoy(integ, ana)
        sexta = ev.cortos(ev.enviar("live", ev.lote(
            [_respuesta_de_eva(c, "it-6", True, 9)], batch_id="lote-3")))
        observado = {
            "primero": primero, "tras_cinco": tras_cinco, "reenviado": otra_vez,
            "mismo_item_y_uno_sin_item": mismo_item, "sin_sumar": sin_sumar, "sexta": sexta,
            "al_final": ay.hoy(integ, ana), "origen": ay.por_origen(integ, ana, ay.dia(2)),
            "efectos": integ.valor("select string_agg(distinct effect, ',') from learning_events"),
            "nivel_escrito": int(integ.valor("select count(*) from confirmed_levels")),
            "filas_en_el_libro": int(integ.valor("select count(*) from coin_ledger")),
        }
    finally:
        ev.soltar()
    assert observado == {
        "primero": (200, 5, 0, [], []), "tras_cinco": (5, 3, False),
        "reenviado": (200, 0, 5, [], []),
        "mismo_item_y_uno_sin_item": (200, 2, 0, [], []), "sin_sumar": (5, 3, False),
        "sexta": (200, 1, 0, [], []), "al_final": (6, 4, True), "origen": {"eva": 6},
        "efectos": "none", "nivel_escrito": 0, "filas_en_el_libro": 0,
    }, f"RW6: {observado}"


def test_rw7_el_protector_se_gana_al_quinto_dia_con_tope(integ, monkeypatch) -> None:
    """RW7 (C10): el 5.º día activo de una semana gana un protector; nunca pasa de 2."""
    c = gr.colegio(integ, "9A", n=1)
    ana = c.estudiantes[0]
    reto, q = ay.sembrar(integ, c.profe, "r", 6, grupo=c.grupo)
    visto = {}
    _dias_activos(integ, monkeypatch, ana, reto, q, [0, 1, 2, 3])
    visto["cuatro_dias"] = ay.corta(integ, ana)
    _dias_activos(integ, monkeypatch, ana, reto, q, [4])
    visto["quinto_dia"] = ay.corta(integ, ana)
    _dias_activos(integ, monkeypatch, ana, reto, q, [5, 6])
    visto["siete_dias"] = ay.corta(integ, ana)
    _dias_activos(integ, monkeypatch, ana, reto, q, [7, 8, 9, 10, 11])
    visto["otra_semana_de_cinco"] = ay.corta(integ, ana)
    assert visto == {
        "cuatro_dias": (1, 1, 1, 1, 4, True), "quinto_dia": (1, 1, 1, 2, 5, True),
        "siete_dias": (1, 1, 1, 2, 7, True), "otra_semana_de_cinco": (2, 2, 2, 2, 5, True),
    }, f"RW7: {visto}"
