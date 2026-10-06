"""GR4-GR9: las hojas calificadas — `docs/ESPEC_grader_anillo.md` §2 y §9.5.

  GR4  C4  punta a punta: 15 ítems, una hoja con 11 aciertos.
  GR5  C5  reenviar REEMPLAZA: una fila por (examen, número).
  GR6  C6  aislamiento entre 3 instituciones, y dentro de una.
  GR7  C7  no se confía en el cliente: cada motivo de rechazo, y el lote sigue.
  GR8  C8  sin imágenes: un campo de más es 422 y 0 filas.
  GR9  C9  recibir resultados no mueve el nivel confirmado ni las monedas.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.grader import _ayuda as ay
from tests.seguridad.veredictos import sembrar

pytestmark = pytest.mark.integ
client = TestClient(app, raise_server_exceptions=False)


def _listo(integ: Any, c: ay.Colegio, n: int = 15, **examen: Any) -> None:
    """La lista pedida (los números existen) y el examen registrado."""
    assert ay.lista(integ, c.profe, c.codigo_grupo)[0] == 200
    assert ay.registrar(integ, c.profe, ay.examen(c.codigo_grupo, n, **examen))[0] == 201


def test_gr4_punta_a_punta(integ) -> None:
    """GR4 (C4): una hoja con 11 de 15 entra; quedan 15 ítems y la hoja dice 11 de 15."""
    c = ay.colegio(integ)
    _listo(integ, c)
    respuesta = ay.enviar(integ, c.profe, c.codigo_grupo,
                          [ay.hoja(2, malas=(0, 5), vacias=(7,), dobles=(9,), forma="B")])
    fila = integ.fila("select profile_id, enviada_por, forma, numero from grader_sheets")
    observado = {
        "respuesta": respuesta, "filas": ay.filas(integ), "hoja": ay.hoja_guardada(integ, 2),
        "es_del_estudiante_2": fila is not None and fila["profile_id"] == c.estudiantes[1],
        "la_envio_el_profe": fila is not None and fila["enviada_por"] == c.profe,
        "forma": fila["forma"] if fila else None,
        "estados": integ.fila(
            "select count(*) filter (where estado = 'marcada') as m, "
            "count(*) filter (where estado = 'vacia') as v, "
            "count(*) filter (where estado = 'doble') as d from grader_sheet_items"),
    }
    assert observado == {
        "respuesta": (200, (1, 0, [])), "filas": (1, 15, 1, 15), "hoja": (11, 15, 11),
        "es_del_estudiante_2": True, "la_envio_el_profe": True, "forma": "B",
        "estados": {"m": 13, "v": 1, "d": 1},
    }, f"GR4: {observado}"


def test_gr5_reenviar_reemplaza(integ) -> None:
    """GR5 (C5): la misma hoja dos veces es UNA fila; corregida, la fila lo refleja."""
    c = ay.colegio(integ)
    _listo(integ, c)
    original = ay.hoja(1, malas=(0, 1, 2, 3))
    primera = ay.enviar(integ, c.profe, c.codigo_grupo, [original])
    otra_vez = ay.enviar(integ, c.profe, c.codigo_grupo, [original])
    tras_repetir = (ay.filas(integ), ay.hoja_guardada(integ, 1))
    corregida = ay.enviar(integ, c.profe, c.codigo_grupo, [ay.hoja(1, malas=(0, 1, 2))])
    tras_corregir = (ay.filas(integ), ay.hoja_guardada(integ, 1))
    dos_en_un_lote = ay.enviar(integ, c.profe, c.codigo_grupo,
                               [ay.hoja(3, malas=(0,)), ay.hoja(3, malas=())])
    observado = {
        "primera": primera, "otra_vez": otra_vez, "tras_repetir": tras_repetir,
        "corregida": corregida, "tras_corregir": tras_corregir,
        "dos_en_un_lote": dos_en_un_lote, "la_segunda_gana": ay.hoja_guardada(integ, 3),
        "filas_al_final": ay.filas(integ),
    }
    assert observado == {
        "primera": (200, (1, 0, [])), "otra_vez": (200, (1, 1, [])),
        "tras_repetir": ((1, 15, 1, 15), (11, 15, 11)),
        "corregida": (200, (1, 1, [])), "tras_corregir": ((1, 15, 1, 15), (12, 15, 12)),
        "dos_en_un_lote": (200, (2, 1, [])), "la_segunda_gana": (15, 15, 15),
        "filas_al_final": (1, 15, 2, 30),
    }, f"GR5: {observado}"


def _tres_llamadas(integ: Any, quien: Any, codigo_grupo: str, codigo: str) -> tuple[int, ...]:
    """(lista, examen, resultados) de `quien` contra ese grupo y ese código."""
    return (ay.lista(integ, quien, codigo_grupo)[0],
            ay.registrar(integ, quien, ay.examen(codigo_grupo, codigo=codigo))[0],
            ay.enviar(integ, quien, codigo_grupo, [ay.hoja(1, codigo=codigo)],
                      codigo=codigo)[0])


def test_gr6_aislamiento_entre_instituciones_y_grupos(integ) -> None:
    """GR6 (C6): nadie lee ni escribe en un grupo o un examen que no es suyo."""
    x, y, z = ay.colegio(integ, "11A"), ay.colegio(integ, "11B"), ay.colegio(integ, "11C")
    for c in (x, y, z):
        assert ay.lista(integ, c.profe, c.codigo_grupo)[0] == 200
    assert ay.registrar(integ, x.profe, ay.examen("11A"))[0] == 201
    assert ay.registrar(integ, z.profe, ay.examen("11C", codigo="DE-Z"))[0] == 201
    sin_grupo = integ.crear_perfil(x.tenant, rol="teacher")  # docente de X sin el 11A
    admin_x = integ.crear_perfil(x.tenant, rol="admin")
    antes = ay.filas(integ)
    observado = {
        "x_en_el_grupo_de_y": _tres_llamadas(integ, x.profe, "11B", "NUEVO-1"),
        "x_en_el_examen_de_z": ay.enviar(integ, x.profe, "11A", [ay.hoja(1, codigo="DE-Z")],
                                         codigo="DE-Z")[0],
        "y_en_el_examen_de_x": ay.enviar(integ, y.profe, "11B", [ay.hoja(1)])[0],
        "docente_sin_el_grupo": _tres_llamadas(integ, sin_grupo, "11A", "NUEVO-2"),
        "docente_sin_el_grupo_en_el_examen": ay.enviar(integ, sin_grupo, "11A", [ay.hoja(1)])[0],
        "estudiante": _tres_llamadas(integ, x.estudiantes[0], "11A", "NUEVO-3"),
        "nada_escrito": ay.filas(integ) == antes,
        # El mismo código en otra institución NO choca con el de X ni lo deja ver.
        "y_registra_el_mismo_codigo": ay.registrar(
            integ, y.profe, ay.examen("11B", huella=ay.OTRA_HUELLA)),
        "y_envia_a_su_examen": ay.enviar(integ, y.profe, "11B", [ay.hoja(1)],
                                         huella=ay.OTRA_HUELLA),
        "hojas_en_el_examen_de_x": int(integ.valor(
            "select count(*) from grader_sheets s join grader_exams e on e.id = s.exam_id "
            "where e.tenant_id = :t", t=x.tenant)),
        "el_admin_de_x_ve_la_lista": ay.lista(integ, admin_x, "11A")[0],
        "examenes": ay.cuenta(integ, "grader_exams"),
    }
    assert observado == {
        "x_en_el_grupo_de_y": (404, 404, 404), "x_en_el_examen_de_z": 404,
        "y_en_el_examen_de_x": 404,
        "docente_sin_el_grupo": (404, 404, 404), "docente_sin_el_grupo_en_el_examen": 404,
        "estudiante": (403, 403, 403), "nada_escrito": True,
        "y_registra_el_mismo_codigo": (201, True), "y_envia_a_su_examen": (200, (1, 0, [])),
        "hojas_en_el_examen_de_x": 0, "el_admin_de_x_ve_la_lista": 200, "examenes": 3,
    }, f"GR6: {observado}"


def test_gr7_no_se_confia_en_el_cliente(integ) -> None:
    """GR7 (C7): cada hoja mala se rechaza con su motivo, y las buenas del lote entran."""
    c = ay.colegio(integ, n=9)
    _listo(integ, c)
    sin_un_item = ay.hoja(6)
    sin_un_item["items"] = sin_un_item["items"][:-1]
    de_otro = ay.hoja(8)
    de_otro["items"][0]["resuelta_por"] = str(uuid4())
    doble_marcado_correcto = ay.hoja(9, dobles=(0,))
    doble_marcado_correcto["items"][0]["correcta"] = True  # dice que acertó; no cuenta
    # Coherente en todo lo demás (el ítem no dice ser correcto y `aciertos`
    # cuadra): lo ÚNICO que la rechaza es el estado.
    dudosa = ay.hoja(3, malas=(4,))
    dudosa["items"][4]["estado"] = "dudosa"
    lote = [
        ay.hoja(1, malas=(0,)),
        ay.hoja(2, malas=(0, 1, 2), aciertos=15),
        dudosa,
        ay.hoja(41),
        ay.hoja(5, event_id="grd:OTRO:5"),
        sin_un_item,
        ay.hoja(7, total=14),
        de_otro,
        doble_marcado_correcto,
    ]
    respuesta = ay.enviar(integ, c.profe, c.codigo_grupo, lote)
    observado = {
        "respuesta": respuesta, "filas": ay.filas(integ),
        "la_buena": ay.hoja_guardada(integ, 1),
        "el_doble_no_sumo": ay.hoja_guardada(integ, 9),
        "la_de_aciertos_falsos": ay.hoja_guardada(integ, 2),
    }
    assert observado == {
        "respuesta": (200, (2, 0, [
            (2, "aciertos_no_coinciden"), (3, "estado_invalido"),
            (41, "numero_sin_estudiante"), (5, "event_id_invalido"),
            (6, "items_no_coinciden"), (7, "total_no_coincide"),
            (8, "resuelta_por_invalido")])),
        "filas": (1, 15, 2, 30), "la_buena": (14, 15, 14), "el_doble_no_sumo": (14, 15, 14),
        "la_de_aciertos_falsos": None,
    }, f"GR7: {observado}"


def test_gr8_sin_imagenes(integ) -> None:
    """GR8 (C8): un campo de más en la raíz, la hoja o el ítem es 422, y no se guarda nada."""
    c = ay.colegio(integ)
    _listo(integ, c)
    imagen = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    en_el_item = ay.hoja(1)
    en_el_item["items"][0]["recorte"] = imagen
    con_imagen = ay.examen(c.codigo_grupo, codigo="IMG")
    con_imagen["items"][0]["imagen"] = imagen
    observado = {
        "en_la_raiz": ay.enviar(integ, c.profe, c.codigo_grupo, [ay.hoja(1)], foto=imagen)[0],
        "en_la_hoja": ay.enviar(integ, c.profe, c.codigo_grupo, [ay.hoja(1, imagen=imagen)])[0],
        "en_el_item": ay.enviar(integ, c.profe, c.codigo_grupo, [en_el_item])[0],
        "en_el_examen": ay.registrar(integ, c.profe, con_imagen)[0],
        "filas": ay.filas(integ),
        "control_sin_el_campo": ay.enviar(integ, c.profe, c.codigo_grupo, [ay.hoja(1)]),
    }
    assert observado == {
        "en_la_raiz": 422, "en_la_hoja": 422, "en_el_item": 422, "en_el_examen": 422,
        "filas": (1, 15, 0, 0), "control_sin_el_campo": (200, (1, 0, [])),
    }, f"GR8: {observado}"


def _nivel(integ: Any, quien: Any) -> Any:
    r = client.get("/auth/me", headers=integ.headers(quien))
    return r.json().get("confirmed_level") if r.status_code == 200 else r.status_code


def test_gr9_el_nivel_y_las_monedas_no_se_mueven(integ) -> None:
    """GR9 (C9): `confirmed_level` idéntico antes y después, con y sin nivel previo."""
    c = ay.colegio(integ)
    _listo(integ, c)
    con_nivel, sin_nivel = c.estudiantes[0], c.estudiantes[1]
    sembrar(integ,
            "insert into confirmed_levels (tenant_id, profile_id, cefr, source, provisional, "
            "assessed_at) values (:t, :p, 'A2', 'set', false, '2026-09-01T10:00:00Z')",
            t=c.tenant, p=con_nivel)
    antes = (_nivel(integ, con_nivel), _nivel(integ, sin_nivel))
    respuesta = ay.enviar(integ, c.profe, c.codigo_grupo, [ay.hoja(1), ay.hoja(2)])
    despues = (_nivel(integ, con_nivel), _nivel(integ, sin_nivel))
    observado = {
        "respuesta": respuesta, "nivel_identico": antes == despues,
        "tenia": antes[0]["cefr"] if isinstance(antes[0], dict) else antes[0],
        "el_que_no_tenia": despues[1],
        "niveles_guardados": int(integ.valor("select count(*) from confirmed_levels")),
        "filas_en_el_libro": int(integ.valor("select count(*) from coin_ledger")),
        "bolsa": integ.saldo("tenant", c.tenant),
    }
    assert observado == {
        "respuesta": (200, (2, 0, [])), "nivel_identico": True, "tenia": "A2",
        "el_que_no_tenia": None, "niveles_guardados": 1, "filas_en_el_libro": 0, "bolsa": 1000,
    }, f"GR9: {observado}"
