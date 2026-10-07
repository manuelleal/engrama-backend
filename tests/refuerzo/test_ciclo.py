"""CR3-CR6: el ciclo del refuerzo, la espera de contenido y quién ve qué.

`docs/ESPEC_refuerzo.md` §2.

  CR3  C4  se sirve una forma no vista, nunca la misma; acierto + repaso = superado; 0 monedas.
  CR4  C5  sin forma no vista: en espera de contenido, y hueco para el profe.
  CR5  C6  los retrocesos y la configuración.
  CR6  C7  el panel es solo del profe del grupo; nadie toca la cola de otro.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest

from src.challenge_engine.schemas import ChallengeQuestionOut
from src.refuerzo import service as refuerzo_service
from src.shared.models import TeacherGroup
from tests.curriculo import _ayuda as cat
from tests.grader import _ayuda as gr
from tests.refuerzo import _ayuda as ay
from tests.refuerzo._ayuda import DOS, T0, UNO
from tests.seguridad.veredictos import sembrar
from tests.teachers._actores import armar, prohibidos_t

pytestmark = pytest.mark.integ


def _fallar_en_examen(integ: Any, c: gr.Colegio, numero: int, item: str, nodos: list[str],
                      codigo: str = gr.CODIGO) -> None:
    """Un examen de un ítem con esos nodos, y la hoja de ese número fallándolo."""
    if gr.lista(integ, c.profe, c.codigo_grupo)[0] != 200:
        raise AssertionError("no hay lista")
    assert ay.examen_con(integ, c, [(item, nodos)], codigo=codigo) == 201
    envio = gr.enviar(integ, c.profe, c.codigo_grupo,
                      [ay.hoja_con(numero, [item], malas=(item,), codigo=codigo)], codigo=codigo)
    assert envio == (200, (1, 0, [])), envio


def test_cr3_el_ciclo_completo_sin_monedas(integ, monkeypatch) -> None:
    """CR3 (C4): gemela no vista -> fallo -> otra forma -> acierto -> repaso a 7 días -> superado."""
    ay.fijar_ahora(monkeypatch)
    cat.cargar(integ, cat.mapa_v1())
    c = gr.colegio(integ, n=2)
    s1 = c.estudiantes[0]
    otro_grupo = integ.crear_grupo(c.tenant, "OTRO")
    integ._insertar(TeacherGroup(tenant_id=c.tenant, teacher_id=c.profe, group_id=otro_grupo))
    _r, q = ay.sembrar_reto(integ, c.profe, "banco", [
        ay.forma([UNO], "it-1", "F", "original"), ay.forma([UNO], "it-2", "F", "gemela"),
        ay.forma([UNO], "it-3", "F", "repaso"), ay.forma([UNO], "it-9")], grupo=c.grupo)
    _r2, ajena = ay.sembrar_reto(integ, c.profe, "de otro grupo",
                                 [ay.forma([UNO], "it-0", "F", "gemela")], grupo=otro_grupo)
    apagado, inactiva = ay.sembrar_reto(integ, c.profe, "inactivo",
                                        [ay.forma([UNO], "it-00", "F", "gemela")], grupo=c.grupo)
    sembrar(integ, "update challenges set status = 'inactive' where id = :c", c=UUID(apagado))
    _fallar_en_examen(integ, c, 1, "it-1", [UNO])  # el examen usó el ORIGINAL de la familia
    e = ay.entrada_de(integ, s1, UNO)
    nombre = {v: k for k, v in {**q, **ajena, **inactiva}.items()}

    def servida() -> Any:
        estado, (lista, repasar, espera, superados) = ay.leer(integ, s1)
        return ([(etapa, nombre.get(pregunta, "?")) for etapa, _nodo, pregunta in lista],
                repasar, espera, superados)

    antes = ay.dinero(integ, c.tenant, s1)
    primera = servida()
    claves = sorted(ay.pendientes(integ, s1)[0]["pregunta"])
    pasos: dict[str, Any] = {
        "primera": primera,
        "la_pregunta_sale_sin_clave_ni_nodos": claves == sorted(ChallengeQuestionOut.model_fields),
        "responder_el_item_del_examen": ay.responder(integ, s1, e, q["it-1"]),
        "falla_la_gemela": ay.responder(integ, s1, e, q["it-2"], "B"),
        "repite_con_otra_respuesta": ay.responder(integ, s1, e, q["it-2"], "A"),
        "segunda": servida(),
        "acierta": ay.responder(integ, s1, e, q["it-3"], "A"),
        "despues_de_acertar": servida(),
        "antes_de_tiempo": ay.responder(integ, s1, e, q["it-9"], "A"),
    }
    ay.fijar_ahora(monkeypatch, T0 + timedelta(days=6, hours=23))
    pasos["a_los_6_dias_y_23_horas"] = servida()
    ay.fijar_ahora(monkeypatch, T0 + timedelta(days=7))
    pasos["a_los_7_dias"] = servida()
    pasos["acierta_el_repaso"] = ay.responder(integ, s1, e, q["it-9"], "A")
    pasos["al_final"] = servida()
    pasos["dinero_identico"] = ay.dinero(integ, c.tenant, s1) == antes
    pasos["dinero"] = ay.dinero(integ, c.tenant, s1)
    assert pasos == {
        "primera": ([("refuerzo", "it-2")], 0, 0, 0),
        "la_pregunta_sale_sin_clave_ni_nodos": True,
        "responder_el_item_del_examen": (409, "forma_no_vigente"),
        "falla_la_gemela": (200, (False, "A", "en_refuerzo", None, False, 0)),
        "repite_con_otra_respuesta": (200, (False, "A", "en_refuerzo", None, True, 0)),
        "segunda": ([("refuerzo", "it-3")], 0, 0, 0),
        "acierta": (200, (True, "A", "por_repasar", "2026-10-13T15:00:00Z", False, 0)),
        "despues_de_acertar": ([], 1, 0, 0),
        "antes_de_tiempo": (409, "no_toca_todavia"),
        "a_los_6_dias_y_23_horas": ([], 1, 0, 0),
        "a_los_7_dias": ([("repaso", "it-9")], 0, 0, 0),
        "acierta_el_repaso": (200, (True, "A", "superado", None, False, 0)),
        "al_final": ([], 0, 0, 1),
        "dinero_identico": True, "dinero": (0, 1000, None),
    }, f"CR3: {pasos}"


def test_cr4_sin_forma_no_vista_queda_en_espera(integ, monkeypatch) -> None:
    """CR4 (C5): no se repite una vista para rellenar; el profe lo ve como hueco."""
    ay.fijar_ahora(monkeypatch)
    cat.cargar(integ, cat.mapa_v1())
    c = gr.colegio(integ, n=2)
    s1 = c.estudiantes[0]
    visto, q = ay.sembrar_reto(integ, c.profe, "ya lo abrió", [ay.forma([DOS], "d-1")],
                               grupo=c.grupo)
    _abierta, _qo = ay.sembrar_reto(integ, c.profe, "abierta",
                                    [ay.forma([DOS], "d-open", tipo="open")], grupo=c.grupo)
    integ.crear_intento(c.tenant, UUID(visto), s1, status="in_progress")  # la abrió, sin enviar
    _fallar_en_examen(integ, c, 1, "d-9", [DOS])
    sin_formas = ay.leer(integ, s1)
    panel_sin = ay.panel_corto(integ, c.profe, c.grupo)
    _nuevo, q2 = ay.sembrar_reto(integ, c.profe, "contenido nuevo", [ay.forma([DOS], "d-2")],
                                 grupo=c.grupo)
    con_forma = ay.leer(integ, s1)
    observado = {
        "sin_formas": sin_formas, "panel_sin": panel_sin,
        "con_forma_nueva": (con_forma[0], [(e, n, p == q2["d-2"]) for e, n, p in con_forma[1][0]],
                            con_forma[1][2]),
        "panel_con": ay.panel_corto(integ, c.profe, c.grupo),
        "la_vista_nunca_se_sirve": q["d-1"] not in str(sin_formas) + str(con_forma),
    }
    assert observado == {
        "sin_formas": (200, ([], 0, 1, 0)),
        "panel_sin": ({str(s1): [(DOS, "en_espera_de_contenido")]}, [(DOS, 0, 0, 0, 1)],
                      [(DOS, 1)]),
        "con_forma_nueva": (200, [("refuerzo", DOS, True)], 0),
        "panel_con": ({str(s1): [(DOS, "en_refuerzo")]}, [(DOS, 1, 0, 0, 0)], []),
        "la_vista_nunca_se_sirve": True,
    }, f"CR4: {observado}"


def _responder_la_vigente(integ: Any, estudiante: UUID, respuesta: str) -> Any:
    """Responde la primera forma que el servidor le sirve: (estado, próxima fecha)."""
    servidas = ay.pendientes(integ, estudiante)
    if not servidas:
        return ("nada_que_responder", None)
    p = servidas[0]
    r = ay.responder(integ, estudiante, p["entrada_id"], p["pregunta"]["id"], respuesta)
    return (r[1][2], r[1][3]) if r[0] == 200 else r


def test_cr5_retrocesos_y_configuracion(integ, monkeypatch) -> None:
    """CR5 (C6): fallar el repaso devuelve a refuerzo; un superado se reabre; la regla es config."""
    ay.fijar_ahora(monkeypatch)
    cat.cargar(integ, cat.mapa_v1())
    c = gr.colegio(integ, n=2)
    s1, s2 = c.estudiantes
    ay.sembrar_reto(integ, c.profe, "banco",
                    [ay.forma([UNO], f"u-{i}") for i in range(1, 10)], grupo=c.grupo)
    reto, q = ay.sembrar_reto(integ, c.profe, "reto", [ay.forma([UNO], "r-1")], grupo=c.grupo)
    _fallar_en_examen(integ, c, 1, "x-1", [UNO])
    pasos: dict[str, Any] = {"acierta": _responder_la_vigente(integ, s1, "A")}
    ay.fijar_ahora(monkeypatch, T0 + timedelta(days=7))
    pasos["falla_el_repaso"] = _responder_la_vigente(integ, s1, "B")
    pasos["acierta_otra_vez"] = _responder_la_vigente(integ, s1, "A")
    ay.fijar_ahora(monkeypatch, T0 + timedelta(days=14))
    pasos["acierta_el_repaso"] = _responder_la_vigente(integ, s1, "A")
    _fallar_en_examen(integ, c, 1, "x-2", [UNO], codigo="E2")
    pasos["superado_que_falla_otro_examen"] = ay.cola(integ, s1)
    pasos["vuelve_a_acertar"] = _responder_la_vigente(integ, s1, "A")
    ay.jugar(integ, s1, reto, {q["r-1"]: "B"})
    pasos["por_repasar_que_falla_un_reto"] = ay.cola(integ, s1)
    # La regla es configuración: 2 aciertos seguidos y el repaso a 3 días.
    monkeypatch.setattr(refuerzo_service.settings, "refuerzo_aciertos_para_repaso", 2)
    monkeypatch.setattr(refuerzo_service.settings, "refuerzo_dias_repaso", 3)
    _fallar_en_examen(integ, c, 2, "x-3", [UNO], codigo="E3")
    pasos["con_dos_el_primero"] = _responder_la_vigente(integ, s2, "A")
    pasos["con_dos_el_segundo"] = _responder_la_vigente(integ, s2, "A")
    assert pasos == {
        "acierta": ("por_repasar", "2026-10-13T15:00:00Z"),
        "falla_el_repaso": ("en_refuerzo", None),
        "acierta_otra_vez": ("por_repasar", "2026-10-20T15:00:00Z"),
        "acierta_el_repaso": ("superado", None),
        "superado_que_falla_otro_examen": {UNO: ("en_refuerzo", 2, "grader", 1)},
        "vuelve_a_acertar": ("por_repasar", "2026-10-27T15:00:00Z"),
        "por_repasar_que_falla_un_reto": {UNO: ("en_refuerzo", 3, "reto", 1)},
        "con_dos_el_primero": ("en_refuerzo", None),
        "con_dos_el_segundo": ("por_repasar", "2026-10-23T15:00:00Z"),
    }, f"CR5: {pasos}"


def test_cr6_el_panel_es_del_profe_y_la_cola_de_cada_uno(integ, monkeypatch) -> None:
    """CR6 (C7): por estudiante y por nodo, sin caché; nadie lee ni responde la cola de otro."""
    ay.fijar_ahora(monkeypatch)
    cat.cargar(integ, cat.mapa_v1())
    esc = armar(integ)
    companero = integ.crear_perfil(esc.tenant_a, group_code=esc.codigo_a)
    de_otra_institucion = integ.crear_perfil(esc.tenant_b, group_code=esc.codigo_b)
    reto, q = ay.sembrar_reto(integ, esc.d, "reto", [
        ay.forma([UNO], "a"), ay.forma([DOS], "b")], grupo=esc.grupo_a)
    _banco, b = ay.sembrar_reto(integ, esc.d, "banco", [
        ay.forma([UNO], "a-2"), ay.forma([DOS], "b-2")], grupo=esc.grupo_a)
    ay.jugar(integ, esc.e, reto, {q["a"]: "B", q["b"]: "A"})       # E: UNO
    ay.jugar(integ, companero, reto, {q["a"]: "A", q["b"]: "B"})   # su compañero: DOS
    entrada_de_e = ay.entrada_de(integ, esc.e, UNO)
    del_profe = ay.panel(integ, esc.d, esc.grupo_a)
    nombres = {x["profile_id"]: x["full_name"] for x in del_profe.json()["estudiantes"]}
    observado = {
        "panel": ay.panel_corto(integ, esc.d, esc.grupo_a),
        "sin_cache": del_profe.headers.get("cache-control"),
        "nombre_de_la_membresia": nombres.get(str(esc.e)) == integ.valor(
            "select full_name from memberships where profile_id = :p", p=esc.e),
        "prohibidos": {actor: ay.client.get(f"/teachers/groups/{esc.grupo_a}/refuerzo",
                                            headers=h).status_code
                       for actor, h, _ in prohibidos_t(esc, integ)},
        "el_admin_sin_el_grupo": ay.panel(integ, esc.aa, esc.grupo_a).status_code,
        "el_companero_ve_solo_lo_suyo": [n for _e, n, _p in ay.leer(integ, companero)[1][0]],
        "el_companero_responde_la_de_e": ay.responder(integ, companero, entrada_de_e,
                                                      b["a-2"])[0],
        "otra_institucion_responde_la_de_e": ay.responder(integ, de_otra_institucion,
                                                          entrada_de_e, b["a-2"])[0],
        "una_entrada_que_no_existe": ay.responder(integ, esc.e, 999999, b["a-2"])[0],
        "la_de_e_sigue_intacta": ay.cola(integ, esc.e),
        "e_si_puede": ay.responder(integ, esc.e, entrada_de_e, b["a-2"])[0],
    }
    assert observado == {
        "panel": ({str(esc.e): [(UNO, "en_refuerzo")], str(companero): [(DOS, "en_refuerzo")]},
                  [(DOS, 1, 0, 0, 0), (UNO, 1, 0, 0, 0)], []),
        "sin_cache": "no-store", "nombre_de_la_membresia": True,
        "prohibidos": {"E": 403, "DO": 404, "DT": 404, "DM": 404, "AB": 404},
        "el_admin_sin_el_grupo": 404, "el_companero_ve_solo_lo_suyo": [DOS],
        "el_companero_responde_la_de_e": 404, "otra_institucion_responde_la_de_e": 404,
        "una_entrada_que_no_existe": 404,
        "la_de_e_sigue_intacta": {UNO: ("en_refuerzo", 1, "reto", 0)}, "e_si_puede": 200,
    }, f"CR6: {observado}"
