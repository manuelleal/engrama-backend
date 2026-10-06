"""GR1, GR2, GR3 y GR10: el contrato de `/auth/me`, la lista y el examen.

`docs/ESPEC_grader_anillo.md` §2 y §9.5.

  GR1 (no-integ)  C1   los 7 campos de `/auth/me` que lee el Grader.
  GR2             C2   la lista numerada: estable, y el número no se reutiliza.
  GR3             C3   el examen: 201, 200 igual, 409 con otra huella, 422.
  GR10            C11  los nodos de cada ítem, resueltos por el catálogo y reapuntados.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from src.auth.schemas import MembershipOut, ProfileOut
from tests.curriculo import _ayuda as cat
from tests.grader import _ayuda as ay
from tests.seguridad.veredictos import sembrar


def _campos(modelo: Any, nombres: tuple[str, ...]) -> dict[str, Any]:
    return {n: (modelo.model_fields[n].annotation if n in modelo.model_fields else "FALTA")
            for n in nombres}


def test_gr1_contrato_de_auth_me() -> None:
    """GR1 (C1): los 7 campos que lee el Grader existen con ese nombre y ese tipo."""
    observado = {
        "perfil": _campos(ProfileOut, ("id", "full_name", "active_tenant_id",
                                       "must_change_password", "memberships")),
        "membresia": _campos(MembershipOut, ("tenant_id", "role", "is_active")),
    }
    assert observado == {
        "perfil": {"id": UUID, "full_name": str, "active_tenant_id": UUID,
                   "must_change_password": bool, "memberships": list[MembershipOut]},
        "membresia": {"tenant_id": UUID, "role": str, "is_active": bool},
    }, f"GR1: {observado}"


def _numeros(respuesta: tuple[int, list[tuple[int, str]]]) -> list[int]:
    return [numero for numero, _ in respuesta[1]]


@pytest.mark.integ
def test_gr2_la_lista_numerada_es_estable_y_no_reutiliza(integ) -> None:
    """GR2 (C2): 1, 2, 3 por orden de matrícula; el de quien sale no vuelve."""
    c = ay.colegio(integ, n=3)
    primera = ay.lista(integ, c.profe, c.codigo_grupo)
    otra_vez = ay.lista(integ, c.profe, c.codigo_grupo)
    cuarto = ay.matricular(integ, c.tenant, c.codigo_grupo, hace_dias=5)
    con_el_cuarto = ay.lista(integ, c.profe, c.codigo_grupo)
    sembrar(integ, "update memberships set is_active = false where profile_id = :p",
            p=c.estudiantes[1])  # sale el número 2
    sin_el_dos = ay.lista(integ, c.profe, c.codigo_grupo)
    quinto = ay.matricular(integ, c.tenant, c.codigo_grupo, hace_dias=1)
    con_el_quinto = ay.lista(integ, c.profe, c.codigo_grupo)
    por_perfil = {perfil: numero for numero, perfil in con_el_quinto[1]}
    observado = {
        "primera": (primera[0], primera[1] == [(i + 1, str(e))
                                               for i, e in enumerate(c.estudiantes)]),
        "otra_vez_igual": otra_vez == primera,
        "el_cuarto": dict((p, n) for n, p in con_el_cuarto[1]).get(str(cuarto)),
        "sin_el_dos": _numeros(sin_el_dos),
        "el_quinto": por_perfil.get(str(quinto)),
        "al_final": _numeros(con_el_quinto),
        "filas": ay.cuenta(integ, "grader_list_numbers"),
        "grupo_que_no_existe": ay.lista(integ, c.profe, "no-existe")[0],
    }
    assert observado == {
        "primera": (200, True), "otra_vez_igual": True, "el_cuarto": 4,
        "sin_el_dos": [1, 3, 4], "el_quinto": 5, "al_final": [1, 3, 4, 5], "filas": 5,
        "grupo_que_no_existe": 404,
    }, f"GR2: {observado}"


@pytest.mark.integ
def test_gr3_el_examen_se_registra_una_vez(integ) -> None:
    """GR3 (C3): 201; igual, 200 sin cambios; otra huella, 409; lo que no cumple, 422."""
    c = ay.colegio(integ)
    bueno = ay.examen(c.codigo_grupo)
    primera = ay.registrar(integ, c.profe, bueno)
    filas_1 = ay.filas(integ)
    otra_vez = ay.registrar(integ, c.profe, bueno)
    otra_huella = ay.registrar(integ, c.profe, ay.examen(c.codigo_grupo, huella=ay.OTRA_HUELLA,
                                                         titulo="otro"))
    repetido = ay.examen(c.codigo_grupo, codigo="X2")
    repetido["items"][1]["item_id"] = repetido["items"][0]["item_id"]
    observado = {
        "primera": primera, "otra_vez": otra_vez, "otra_huella": otra_huella,
        "filas": filas_1, "nada_cambio": ay.filas(integ) == filas_1,
        "titulo_guardado": integ.valor("select titulo from grader_exams"),
        "n_items_no_coincide": ay.registrar(
            integ, c.profe, ay.examen(c.codigo_grupo, codigo="X1", n_items=14))[0],
        "item_id_repetido": ay.registrar(integ, c.profe, repetido)[0],
        "codigo_de_la_ruta_distinto": ay.registrar(
            integ, c.profe, ay.examen(c.codigo_grupo, codigo="X3"), en_la_ruta="X4"),
        "huella_en_mayuscula": ay.registrar(
            integ, c.profe, ay.examen(c.codigo_grupo, codigo="X5", huella="A" * 64))[0],
        "grupo_que_no_existe": ay.registrar(
            integ, c.profe, ay.examen("no-existe", codigo="X6"))[0],
        "filas_al_final": ay.filas(integ),
    }
    assert observado == {
        "primera": (201, True), "otra_vez": (200, False),
        "otra_huella": (409, "examen_con_otra_huella"),
        "filas": (1, 15, 0, 0), "nada_cambio": True, "titulo_guardado": "Examen sintético",
        "n_items_no_coincide": 422, "item_id_repetido": 422,
        "codigo_de_la_ruta_distinto": (422, "codigo_no_coincide"),
        "huella_en_mayuscula": 422, "grupo_que_no_existe": 404,
        "filas_al_final": (1, 15, 0, 0),
    }, f"GR3: {observado}"


def _nodos_guardados(integ: Any, codigo: str) -> dict[str, list[str]]:
    from sqlalchemy import text

    async def _q() -> dict[str, list[str]]:
        async with integ.Session() as db:
            filas = (await db.execute(text(
                "select i.item_id, i.nodos from grader_exam_items i "
                "join grader_exams e on e.id = i.exam_id where e.codigo = :c "
                "order by i.posicion"), {"c": codigo})).all()
            return {f[0]: list(f[1]) for f in filas}

    return integ.run(_q())


@pytest.mark.integ
def test_gr10_cada_item_lleva_sus_nodos(integ) -> None:
    """GR10 (C11): se guardan los vigentes; un desconocido no entra; una fusión reapunta."""
    c = ay.colegio(integ)
    con_el_catalogo_vacio = ay.registrar(integ, c.profe, ay.examen(
        c.codigo_grupo, 1, codigo="V1", items=[ay.item("i1", nodos=["gr.a1.dos"])]))
    cat.cargar(integ, cat.mapa_v1())
    ids = ay.ids_de_items(4)
    items = [ay.item(ids[0], nodos=["gr.a1.dos"]),
             ay.item(ids[1], nodos=["gr.a1.viejo", "gr.a1.uno", "lx.b1.cuatro"]),
             ay.item(ids[2], nodos=[]), ay.item(ids[3])]
    registro = ay.registrar(integ, c.profe, ay.examen(c.codigo_grupo, 4, items=items))
    guardados = _nodos_guardados(integ, ay.CODIGO)
    desconocido = ay.registrar(integ, c.profe, ay.examen(
        c.codigo_grupo, 2, codigo="D1",
        items=[ay.item("i1", nodos=["gr.a1.uno"]), ay.item("i2", nodos=["no.existe"])]))
    nueve = ay.registrar(integ, c.profe, ay.examen(
        c.codigo_grupo, 1, codigo="N9",
        items=[ay.item("i1", nodos=[f"gr.a1.n{i}" for i in range(9)])]))[0]
    fusion = cat.cargar(integ, cat.mapa(
        "v2", [i for i in cat.VIGENTES_V1 if i != "gr.a1.dos"],
        {**cat.REEMPLAZOS_V1, "gr.a1.dos": "fn.a2.tres"}))
    observado = {
        "con_el_catalogo_vacio": con_el_catalogo_vacio, "registro": registro,
        "guardados": guardados, "desconocido": desconocido, "nueve_nodos": nueve,
        "examenes": sorted(str(x) for x in [integ.valor("select count(*) from grader_exams")]),
        "reapuntadas": fusion["reapuntadas"].get("grader_exam_items")
        if isinstance(fusion, dict) else fusion,
        "tras_la_fusion": _nodos_guardados(integ, ay.CODIGO).get(ids[0]),
    }
    assert observado == {
        "con_el_catalogo_vacio": (422, {"code": "nodo_desconocido", "nodos": ["gr.a1.dos"]}),
        "registro": (201, True),
        "guardados": {ids[0]: ["gr.a1.dos"], ids[1]: ["gr.a1.uno", "lx.b1.cuatro"],
                      ids[2]: [], ids[3]: []},
        "desconocido": (422, {"code": "nodo_desconocido", "nodos": ["no.existe"]}),
        "nueve_nodos": 422, "examenes": ["1"], "reapuntadas": 1,
        "tras_la_fusion": ["fn.a2.tres"],
    }, f"GR10: {observado}"
