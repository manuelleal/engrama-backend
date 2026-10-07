"""FG3 y FG5: el feed priorizado del estudiante y el logro del grupo por nodo.

`docs/ESPEC_foco_grupo.md` §2.

  FG3  C4  el feed pone primero los retos del foco, sin perder ni ganar ninguno.
  FG5  C6  el logro por nodo: primer intento, ventana, mínimo de evidencia y cortes.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from src.shared.models import TeacherGroup
from tests.curriculo import _ayuda as cat
from tests.foco import _ayuda as ay
from tests.grader._ayuda import colegio
from tests.teachers._actores import armar

pytestmark = pytest.mark.integ

UNO, DOS, TRES, CUATRO = "gr.a1.uno", "gr.a1.dos", "fn.a2.tres", "lx.b1.cuatro"


def _feed_el(integ: Any, mp: pytest.MonkeyPatch, estudiante: UUID, dia: str) -> list[str]:
    ay.fijar_hoy(mp, dia)
    return ay.feed(integ, estudiante)


def test_fg3_el_feed_prioriza_el_foco(integ, monkeypatch) -> None:
    """FG3 (C4): primero lo del foco vigente del grupo del estudiante; lo demás, igual."""
    cat.cargar(integ, cat.mapa_v1())
    esc = armar(integ)
    ay.fijar_hoy(monkeypatch)
    otro_grupo = integ.crear_grupo(esc.tenant_a, "GA2")
    de_otro_grupo = integ.crear_perfil(esc.tenant_a, group_code="GA2")
    integ._insertar(TeacherGroup(tenant_id=esc.tenant_a, teacher_id=esc.d, group_id=otro_grupo))
    r = {
        "a": ay.crear_reto(integ, esc.d, "a", [[UNO]], grupo=esc.grupo_a, minuto=1)[1],
        "b": ay.crear_reto(integ, esc.d, "b", [[], [DOS]], grupo=esc.grupo_a, minuto=2)[1],
        "c": ay.crear_reto(integ, esc.d, "c", [[TRES]], grupo=esc.grupo_a, minuto=3)[1],
        "d": ay.crear_reto(integ, esc.d, "d", [[DOS]], minuto=4)[1],  # global
        "e": ay.crear_reto(integ, esc.d, "e", [[UNO]], grupo=otro_grupo, minuto=5)[1],
    }
    letra = {v: k for k, v in r.items()}

    def letras(ids: list[str]) -> str:
        return "".join(letra.get(i, "?") for i in ids)

    sin_foco = ay.feed(integ, esc.e)
    sin_foco_api = ay.foco_del_estudiante(integ, esc.e)
    foco_ajeno = ay.fijar_foco(integ, esc.d, otro_grupo, "2026-10-05", [TRES, UNO])[0]
    con_foco_de_otro_grupo = ay.feed(integ, esc.e)
    propio = ay.fijar_foco(integ, esc.d, esc.grupo_a, "2026-10-05", [DOS, UNO])[0]
    con_foco = ay.feed(integ, esc.e)
    api = ay.foco_del_estudiante(integ, esc.e)
    observado = {
        "sin_foco": letras(sin_foco), "sin_foco_api": sin_foco_api,
        "focos_fijados": (foco_ajeno, propio),
        "con_el_foco_de_otro_grupo": letras(con_foco_de_otro_grupo),
        "con_foco": letras(con_foco), "mismos_retos": sorted(con_foco) == sorted(sin_foco),
        "api": (api[0], api[1][0], api[1][1], letras(api[1][2])),
        "el_dia_antes": letras(_feed_el(integ, monkeypatch, esc.e, "2026-10-04")),
        "el_ultimo_dia": letras(_feed_el(integ, monkeypatch, esc.e, "2026-10-11")),
        "vencido": letras(_feed_el(integ, monkeypatch, esc.e, "2026-10-12")),
        "vencido_api": ay.foco_del_estudiante(integ, esc.e),
        "el_del_otro_grupo": letras(_feed_el(integ, monkeypatch, de_otro_grupo, "2026-10-06")),
    }
    assert observado == {
        "sin_foco": "dcba", "sin_foco_api": (200, (None, [], [])), "focos_fijados": (200, 200),
        "con_el_foco_de_otro_grupo": "dcba", "con_foco": "dbac", "mismos_retos": True,
        "api": (200, "2026-10-05", [DOS, UNO], "dba"),
        "el_dia_antes": "dcba", "el_ultimo_dia": "dbac", "vencido": "dcba",
        "vencido_api": (200, (None, [], [])), "el_del_otro_grupo": "ed",
    }, f"FG3: {observado}"


def _intento(integ: Any, c: Any, reto: str, estudiante: UUID, marcas: dict[str, bool], *,
             hace: timedelta = timedelta(hours=2)) -> None:
    integ.crear_intento(c.tenant, UUID(reto), estudiante, answers=ay.respuestas(marcas),
                        completed_at=datetime.now(UTC) - hace)


def test_fg5_logro_del_grupo_por_nodo(integ, monkeypatch) -> None:
    """FG5 (C6): conteos exactos por nodo; solo el primer intento, en la ventana y del grupo."""
    cat.cargar(integ, cat.mapa_v1())
    c = colegio(integ, "11A", n=7)
    s = c.estudiantes
    hoy = datetime.now(UTC).date()
    foco = ay.fijar_foco(integ, c.profe, c.grupo, str(hoy - timedelta(days=1)),
                         [UNO, DOS, TRES, CUATRO])[0]
    _, ra, (a1, a2) = ay.crear_reto(integ, c.profe, "RA", [[UNO], [UNO, DOS]], grupo=c.grupo)
    _, rb, (b1, b2) = ay.crear_reto(integ, c.profe, "RB", [[UNO], [DOS]], grupo=c.grupo)
    _, rc, (c1, c2) = ay.crear_reto(integ, c.profe, "RC", [[TRES], []], grupo=c.grupo)
    _, rg, (g1,) = ay.crear_reto(integ, c.profe, "RG", [[UNO]])  # global: no cuenta
    for i, estudiante in enumerate(s[:5]):
        _intento(integ, c, ra, estudiante, {a1: True, a2: i < 3})
        _intento(integ, c, rb, estudiante, {b1: True, b2: i == 0})
    for estudiante in s[:4]:
        _intento(integ, c, rc, estudiante, {c1: True, c2: False})
    # Lo que NO cuenta: un segundo intento, uno de hace 29 días y un reto global.
    _intento(integ, c, ra, s[0], {a1: False, a2: False}, hace=timedelta(hours=1))
    _intento(integ, c, ra, s[5], {a1: True, a2: True}, hace=timedelta(days=29))
    _intento(integ, c, rg, s[1], {g1: False})
    estado, cuerpo = ay.logro(integ, c.profe, c.grupo)
    nodos = {n["nodo"]["id"]: (n["students"], n["items"], n["correct"], n["challenges"],
                               n["status"], n["label"]) for n in cuerpo["nodos"]}
    observado = {
        "foco": foco, "estado": estado, "group_students": cuerpo["group_students"],
        "orden": [n["nodo"]["id"] for n in cuerpo["nodos"]], "nodos": nodos,
        "minimos": (cuerpo["method"]["min_students"], cuerpo["method"]["min_items"]),
        "sin_nombres": "full_name" not in str(cuerpo) and "profile_id" not in str(cuerpo),
    }
    assert observado == {
        "foco": 200, "estado": 200, "group_students": 7, "orden": [UNO, DOS, TRES, CUATRO],
        "nodos": {UNO: (5, 15, 13, 2, "logrado", "logrado"),
                  DOS: (5, 10, 4, 2, "a_reforzar", "a reforzar"),
                  TRES: (4, 4, 4, 1, "datos_insuficientes", "datos insuficientes"),
                  CUATRO: (0, 0, 0, 0, "datos_insuficientes", "datos insuficientes")},
        "minimos": (5, 8), "sin_nombres": True,
    }, f"FG5: {observado}"
