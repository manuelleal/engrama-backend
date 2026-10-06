"""UM1 y MN1-MN3: el catálogo de nodos — `docs/ESPEC_catalogo_nodos.md` §2.

  UM1 (no-integ)  C1  la lectura pura del archivo y cada motivo de rechazo.
  MN1             C2  la carga, su repetición y el `GET` del profe.
  MN2             C3  un nodo no se borra; la carga rechazada no deja nada.
  MN3             C4  `canonicos`: vigente, reemplazado, repetidos y desconocidos.

Cada test arma UN `observado` y lo compara entero: así el tramposo cae con el
mensaje del mecanismo que rompió.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.curriculo.mapa import MapaInvalido, leer_mapa
from tests.curriculo import _ayuda as ay

N = ay.nodo


def _leer(datos: Any) -> Any:
    try:
        m = leer_mapa(datos)
    except MapaInvalido as exc:
        return (exc.motivo, exc.ids)
    return {"version": m.version, "nodos": [n.id for n in m.nodos], "reemplazos": m.reemplazos}


def _con(**cambios: Any) -> dict[str, Any]:
    return {**ay.mapa("v1", ["gr.a1.uno", "gr.a1.dos"]), **cambios}


def test_um1_lectura_pura_del_mapa() -> None:
    """UM1 (C1): un mapa válido se lee, y cada archivo roto da su motivo."""
    r = [{"id": "gr.a1.viejo", "reemplazado_por": "gr.a1.uno"}]
    observado = {
        "valido": _leer(ay.mapa_v1()),
        "sin_version": _leer(_con(version="")),
        "sin_nodos": _leer(_con(nodos=[])),
        "no_es_un_objeto": _leer([1, 2]),
        "id_con_espacio": _leer(_con(nodos=[N("gr.a1.uno"), {**N("gr.a1.dos"), "id": "gr a1"}])),
        "id_de_129": _leer(_con(nodos=[{**N("gr.a1.uno"), "id": "g" * 129}])),
        "id_de_128": _leer(_con(nodos=[{**N("gr.a1.uno"), "id": "g" * 128}]))["nodos"] == ["g" * 128],
        "id_repetido": _leer(_con(nodos=[N("gr.a1.uno"), N("gr.a1.dos"), N("gr.a1.uno")])),
        "campo_faltante": _leer(_con(nodos=[{"id": "gr.a1.uno", "tipo": "gramatica",
                                             "nivel": "A1"}])),
        "reemplazo_a_uno_que_no_existe": _leer(_con(
            reemplazos=[{"id": "gr.a1.viejo", "reemplazado_por": "gr.a1.fantasma"}])),
        "reemplazo_en_ciclo": _leer(_con(reemplazos=[
            {"id": "gr.a1.a", "reemplazado_por": "gr.a1.b"},
            {"id": "gr.a1.b", "reemplazado_por": "gr.a1.a"}])),
        "vigente_y_reemplazado_a_la_vez": _leer(_con(
            reemplazos=[{"id": "gr.a1.dos", "reemplazado_por": "gr.a1.uno"}])),
        "sin_reemplazos": _leer({"version": "v1", "nodos": [N("gr.a1.uno")]})["reemplazos"],
        "uno_solo": _leer(_con(reemplazos=r))["reemplazos"],
    }
    assert observado == {
        "valido": {"version": "v1", "nodos": list(ay.VIGENTES_V1),
                   "reemplazos": {"gr.a1.viejo": "gr.a1.uno", "gr.a1.mas-viejo": "gr.a1.uno"}},
        "sin_version": ("sin_version", []), "sin_nodos": ("sin_nodos", []),
        "no_es_un_objeto": ("sin_nodos", []),
        "id_con_espacio": ("id_invalido", ["gr a1"]),
        "id_de_129": ("id_invalido", ["g" * 129]), "id_de_128": True,
        "id_repetido": ("id_repetido", ["gr.a1.uno"]),
        "campo_faltante": ("campo_faltante", ["gr.a1.uno"]),
        "reemplazo_a_uno_que_no_existe": ("reemplazo_invalido", ["gr.a1.viejo"]),
        "reemplazo_en_ciclo": ("reemplazo_invalido", ["gr.a1.a"]),
        "vigente_y_reemplazado_a_la_vez": ("reemplazo_invalido", ["gr.a1.dos"]),
        "sin_reemplazos": {}, "uno_solo": {"gr.a1.viejo": "gr.a1.uno"},
    }, f"UM1: {observado}"


@pytest.mark.integ
def test_mn1_la_carga_su_repeticion_y_el_get(integ) -> None:
    """MN1 (C2): 6 vigentes y 2 reemplazados entran; repetir no cambia nada; el GET los trae."""
    colegio = integ.crear_tenant()
    profe = integ.crear_perfil(colegio, rol="teacher")
    estudiante = integ.crear_perfil(colegio)
    vacio = ay.leer(integ, profe)
    primera = ay.cargar(integ, ay.mapa_v1())
    filas = ay.tabla(integ)
    segunda = ay.cargar(integ, ay.mapa_v1())
    observado = {
        "catalogo_vacio": vacio, "primera": primera, "segunda": segunda,
        "filas": len(filas), "repetir_no_cambia_filas": ay.tabla(integ) == filas,
        "profe": ay.leer(integ, profe), "estudiante": ay.leer(integ, estudiante)[0],
    }
    resumen = {"version": "v1", "vigentes": 6, "reemplazados": 2, "cambiados": 0,
               "reapuntadas": dict.fromkeys(primera["reapuntadas"], 0)}
    assert observado == {
        "catalogo_vacio": (200, None, []),
        "primera": {**resumen, "nuevos": 8}, "segunda": {**resumen, "nuevos": 0},
        "filas": 8, "repetir_no_cambia_filas": True,
        "profe": (200, "v1", list(ay.VIGENTES_V1)), "estudiante": 403,
    }, f"MN1: {observado}"


@pytest.mark.integ
def test_mn2_un_nodo_no_se_borra(integ) -> None:
    """MN2 (C3): el archivo que pierde un id se rechaza ENTERO; declarado como reemplazo, entra."""
    ay.cargar(integ, ay.mapa_v1())
    antes = ay.tabla(integ)
    sin_seis = [i for i in ay.VIGENTES_V1 if i != "pr.c1.seis"] + ["gr.b1.nuevo-a",
                                                                   "gr.b1.nuevo-b"]
    rechazada = ay.cargar(integ, ay.mapa("v2", sin_seis, ay.REEMPLAZOS_V1))
    tras_rechazo = ay.tabla(integ)
    declarada = ay.cargar(integ, ay.mapa("v2", sin_seis, {**ay.REEMPLAZOS_V1,
                                                         "pr.c1.seis": "gr.b1.nuevo-a"}))
    despues = ay.tabla(integ)
    observado = {
        "rechazada": rechazada, "la_tabla_quedo_identica": tras_rechazo == antes,
        "nuevos_que_se_colaron": sorted(set(tras_rechazo) - set(antes)),
        "declarada": {k: declarada[k] for k in ("vigentes", "reemplazados", "nuevos",
                                                "cambiados")},
        "seis_apunta_a": despues.get("pr.c1.seis"), "filas": len(despues),
    }
    assert observado == {
        "rechazada": ("rechazada", "nodo_desaparecido", ["pr.c1.seis"]),
        "la_tabla_quedo_identica": True, "nuevos_que_se_colaron": [],
        "declarada": {"vigentes": 7, "reemplazados": 3, "nuevos": 2, "cambiados": 1},
        "seis_apunta_a": "gr.b1.nuevo-a", "filas": 10,
    }, f"MN2: {observado}"


@pytest.mark.integ
def test_mn3_canonicos_resuelve_y_rechaza(integ) -> None:
    """MN3 (C4): vigente, reemplazado (con cadena), repetidos y desconocidos."""
    con_el_catalogo_vacio = ay.resolver(integ, ["gr.a1.dos"])
    ay.cargar(integ, ay.mapa_v1())
    observado = {
        "con_el_catalogo_vacio": con_el_catalogo_vacio,
        "vigente": ay.resolver(integ, ["gr.a1.dos"]),
        "reemplazado": ay.resolver(integ, ["gr.a1.viejo"]),
        "cadena_repetidos_y_orden": ay.resolver(
            integ, ["gr.a1.mas-viejo", "gr.a1.uno", "gr.a1.dos", "gr.a1.dos"]),
        "con_desconocidos": ay.resolver(
            integ, ["gr.a1.dos", "no.existe", "gr.a1.viejo", "tampoco"]),
        "ninguno": ay.resolver(integ, []),
    }
    assert observado == {
        "con_el_catalogo_vacio": (422, {"code": "nodo_desconocido", "nodos": ["gr.a1.dos"]}),
        "vigente": ["gr.a1.dos"], "reemplazado": ["gr.a1.uno"],
        "cadena_repetidos_y_orden": ["gr.a1.uno", "gr.a1.dos"],
        "con_desconocidos": (422, {"code": "nodo_desconocido",
                                   "nodos": ["no.existe", "tampoco"]}),
        "ninguno": [],
    }, f"MN3: {observado}"
