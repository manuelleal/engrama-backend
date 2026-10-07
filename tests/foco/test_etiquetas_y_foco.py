"""FG1, FG2 y FG4: las etiquetas de nodo, el foco y su aislamiento.

`docs/ESPEC_foco_grupo.md` §2.

  FG1  C2  las preguntas de los retos llevan nodos; reetiquetar; quién puede.
  FG2  C3  el foco: crear, reemplazar, no solapar, vigencia y borrar.
  FG4  C5  nadie fija ni lee el foco de un grupo que no es suyo.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.challenge_engine.schemas import ChallengeOut, ChallengeQuestionOut
from src.main import app
from tests.curriculo import _ayuda as cat
from tests.foco import _ayuda as ay
from tests.teachers._actores import armar, prohibidos_t

pytestmark = pytest.mark.integ
client = TestClient(app, raise_server_exceptions=False)


def _fusionar_dos_en_tres(integ: Any) -> Any:
    """Una carga del mapa que fusiona `gr.a1.dos` en `fn.a2.tres`."""
    return cat.cargar(integ, cat.mapa(
        "v2", [i for i in cat.VIGENTES_V1 if i != "gr.a1.dos"],
        {**cat.REEMPLAZOS_V1, "gr.a1.dos": "fn.a2.tres"}))


def _reapuntadas(resumen: Any, tabla: str) -> Any:
    return resumen["reapuntadas"].get(tabla) if isinstance(resumen, dict) else resumen


def test_fg1_las_preguntas_llevan_nodos(integ) -> None:
    """FG1 (C2): se guardan los vigentes, se reetiqueta todo o nada, y solo quien puede."""
    cat.cargar(integ, cat.mapa_v1())
    esc = armar(integ)
    creado = ay.crear_reto(integ, esc.d, "con nodos", [["gr.a1.dos"],
                                                      ["gr.a1.viejo", "gr.a1.uno"], None],
                           grupo=esc.grupo_a)
    reto, (q1, q2, q3) = creado[1], creado[2]
    otro = ay.crear_reto(integ, esc.d, "otro", [[]], grupo=esc.grupo_a, minuto=1)
    del_global = ay.crear_reto(integ, esc.d, "global", [["gr.a1.uno"]], minuto=2)
    antes = int(integ.valor("select count(*) from challenges"))
    desconocido = ay.crear_reto(integ, esc.d, "malo", [["gr.a1.uno"], ["no.existe"]],
                                grupo=esc.grupo_a)
    visto = client.get(f"/challenges/{reto}", headers=integ.headers(esc.e)).json()
    observado = {
        "creado": creado[0], "guardados": ay.etiquetas(integ, esc.d, reto),
        "desconocido": desconocido[:2],
        "retos_tras_el_desconocido": int(integ.valor("select count(*) from challenges")) - antes,
        "claves_del_reto": sorted(visto) == sorted(ChallengeOut.model_fields),
        "claves_de_la_pregunta": sorted(visto["questions"][0]) == sorted(
            ChallengeQuestionOut.model_fields),
        "reetiquetar_una": ay.reetiquetar(integ, esc.d, reto, {q3: ["fn.a2.tres"]}),
        "con_una_pregunta_ajena": ay.reetiquetar(
            integ, esc.d, reto, {q1: ["lx.b1.cuatro"], otro[2][0]: ["lx.b1.cuatro"]}),
        "con_un_nodo_desconocido": ay.reetiquetar(
            integ, esc.d, reto, {q1: ["lx.b1.cuatro"], q2: ["no.existe"]}),
        "nada_cambio": (ay.etiquetas(integ, esc.d, reto)[1],
                        ay.nodos_de_pregunta(integ, otro[2][0])),
        "quien_no_puede": {actor: _dos(integ, h, reto, q1)
                           for actor, h, _ in prohibidos_t(esc, integ)},
        "el_admin": ay.etiquetas(integ, esc.aa, reto)[0],
        "reto_global": (ay.etiquetas(integ, esc.d, del_global[1])[0],
                        ay.etiquetas(integ, esc.aa, del_global[1])[0]),
        "reapuntadas": _reapuntadas(_fusionar_dos_en_tres(integ), "challenge_questions"),
        "tras_la_fusion": ay.nodos_de_pregunta(integ, q1),
    }
    assert observado == {
        "creado": 201, "guardados": (200, [["gr.a1.dos"], ["gr.a1.uno"], []]),
        "desconocido": (422, {"code": "nodo_desconocido", "nodos": ["no.existe"]}),
        "retos_tras_el_desconocido": 0, "claves_del_reto": True, "claves_de_la_pregunta": True,
        "reetiquetar_una": (200, [["gr.a1.dos"], ["gr.a1.uno"], ["fn.a2.tres"]]),
        "con_una_pregunta_ajena": (422, "pregunta_ajena"),
        "con_un_nodo_desconocido": (422, {"code": "nodo_desconocido", "nodos": ["no.existe"]}),
        "nada_cambio": ([["gr.a1.dos"], ["gr.a1.uno"], ["fn.a2.tres"]], []),
        "quien_no_puede": {"E": (403, 403), "DO": (404, 404), "DT": (404, 404),
                           "DM": (404, 404), "AB": (404, 404)},
        "el_admin": 200, "reto_global": (404, 200),
        "reapuntadas": 1, "tras_la_fusion": ["fn.a2.tres"],
    }, f"FG1: {observado}"


def _dos(integ: Any, headers: dict[str, str], reto: str, pregunta: str) -> tuple[int, int]:
    """(GET, PUT) de las etiquetas con ESOS headers (los de un actor que no puede)."""
    leer = client.get(f"/teachers/challenges/{reto}/nodos", headers=headers).status_code
    escribir = client.put(f"/teachers/challenges/{reto}/nodos", headers=headers, json={
        "preguntas": [{"question_id": pregunta, "nodos": ["lx.b1.cuatro"]}]}).status_code
    return leer, escribir


def _vigente_el(integ: Any, mp: pytest.MonkeyPatch, esc: Any, dia: str) -> Any:
    ay.fijar_hoy(mp, dia)
    return ay.leer_foco(integ, esc.d, esc.grupo_a)[1][1]


def test_fg2_el_foco_del_grupo(integ, monkeypatch) -> None:
    """FG2 (C3): un periodo por `desde`, sin solapes, y `vigente` según "hoy"."""
    cat.cargar(integ, cat.mapa_v1())
    esc = armar(integ)
    ay.fijar_hoy(monkeypatch)
    g, d = esc.grupo_a, esc.d
    primero = ay.fijar_foco(integ, d, g, "2026-10-05", ["gr.a1.dos", "gr.a1.viejo", "gr.a1.uno"],
                            "2026-10-11")
    por_defecto = ay.fijar_foco(integ, d, g, "2026-10-12", ["fn.a2.tres"])
    reemplazo = ay.fijar_foco(integ, d, g, "2026-10-05", ["gr.a1.dos", "fn.a2.tres"],
                              "2026-10-09")
    solapado = ay.fijar_foco(integ, d, g, "2026-10-08", ["gr.a1.uno"], "2026-10-13")
    tras_solapado = ay.nodos_del_foco(integ, g)
    pegado = ay.fijar_foco(integ, d, g, "2026-10-10", ["gr.a1.uno"], "2026-10-11")
    trece = [f"gr.a1.n{i}" for i in range(13)]
    observado = {
        "primero": primero, "por_defecto": por_defecto, "reemplazo": reemplazo,
        "solapado": solapado, "tras_solapado": tras_solapado, "pegado": pegado,
        "no_valen": {
            "hasta_antes_de_desde": ay.fijar_foco(integ, d, g, "2026-11-10", ["gr.a1.uno"],
                                                  "2026-11-09")[0],
            "63_dias": ay.fijar_foco(integ, d, g, "2027-01-01", ["gr.a1.uno"], "2027-03-05")[0],
            "sin_nodos": ay.fijar_foco(integ, d, g, "2026-11-10", [])[0],
            "13_nodos": ay.fijar_foco(integ, d, g, "2026-11-10", trece)[0],
            "nodo_desconocido": ay.fijar_foco(integ, d, g, "2026-11-10", ["no.existe"]),
            "fecha_que_no_es": ay.fijar_foco(integ, d, g, "mañana", ["gr.a1.uno"])[0],
        },
        "leer": ay.leer_foco(integ, d, g),
        "vigente_por_dia": {dia: _vigente_el(integ, monkeypatch, esc, dia) for dia in (
            "2026-10-04", "2026-10-05", "2026-10-09", "2026-10-10", "2026-10-18",
            "2026-10-19")},
        "borrar": (ay.borrar_foco(integ, d, g, "2026-10-12"),
                   ay.borrar_foco(integ, d, g, "2026-10-12")),
        "reapuntadas": _reapuntadas(_fusionar_dos_en_tres(integ), "group_focus"),
        "tras_la_fusion": ay.nodos_del_foco(integ, g),
    }
    assert observado == {
        "primero": (200, ("2026-10-05", "2026-10-11", True, ["gr.a1.dos", "gr.a1.uno"])),
        "por_defecto": (200, ("2026-10-12", "2026-10-18", False, ["fn.a2.tres"])),
        "reemplazo": (200, ("2026-10-05", "2026-10-09", True, ["gr.a1.dos", "fn.a2.tres"])),
        "solapado": (409, "foco_solapado"),
        "tras_solapado": [["gr.a1.dos", "fn.a2.tres"], ["fn.a2.tres"]],
        "pegado": (200, ("2026-10-10", "2026-10-11", False, ["gr.a1.uno"])),
        "no_valen": {"hasta_antes_de_desde": 422, "63_dias": 422, "sin_nodos": 422,
                     "13_nodos": 422,
                     "nodo_desconocido": (422, {"code": "nodo_desconocido",
                                                "nodos": ["no.existe"]}),
                     "fecha_que_no_es": 422},
        "leer": (200, ("2026-10-06", "2026-10-05", ["2026-10-12", "2026-10-10", "2026-10-05"])),
        "vigente_por_dia": {"2026-10-04": None, "2026-10-05": "2026-10-05",
                            "2026-10-09": "2026-10-05", "2026-10-10": "2026-10-10",
                            "2026-10-18": "2026-10-12", "2026-10-19": None},
        "borrar": (204, 404), "reapuntadas": 1,
        "tras_la_fusion": [["fn.a2.tres"], ["gr.a1.uno"]],
    }, f"FG2: {observado}"


def _cuatro(integ: Any, headers: dict[str, str], grupo: UUID) -> tuple[int, int, int, int]:
    """(PUT, GET, DELETE, logro) del foco de ese grupo con ESOS headers."""
    base = f"/teachers/groups/{grupo}/foco"
    cuerpo = {"desde": "2026-10-05", "nodos": ["gr.a1.uno"]}
    return (client.put(base, headers=headers, json=cuerpo).status_code,
            client.get(base, headers=headers).status_code,
            client.delete(f"{base}/2026-10-05", headers=headers).status_code,
            client.get(f"{base}/logro", headers=headers).status_code)


def test_fg4_aislamiento_del_foco(integ, monkeypatch) -> None:
    """FG4 (C5): E 403; DO, DT, DM y AB 404; el admin fija y lee, pero no ve el logro."""
    cat.cargar(integ, cat.mapa_v1())
    esc = armar(integ)
    ay.fijar_hoy(monkeypatch)
    observado = {
        "prohibidos": {actor: _cuatro(integ, h, esc.grupo_a)
                       for actor, h, _ in prohibidos_t(esc, integ)},
        "filas_de_los_prohibidos": int(integ.valor("select count(*) from group_focus")),
        "el_admin": _cuatro(integ, integ.headers(esc.aa), esc.grupo_a),
        "el_dueno": _cuatro(integ, integ.headers(esc.d), esc.grupo_a),
    }
    assert observado == {
        "prohibidos": {"E": (403, 403, 403, 403), "DO": (404, 404, 404, 404),
                       "DT": (404, 404, 404, 404), "DM": (404, 404, 404, 404),
                       "AB": (404, 404, 404, 404)},
        "filas_de_los_prohibidos": 0,
        "el_admin": (200, 200, 204, 404), "el_dueno": (200, 200, 204, 200),
    }, f"FG4: {observado}"
