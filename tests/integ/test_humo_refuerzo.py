"""HR1 (humo) y RR1 (réplica) de la cola de refuerzo — `docs/ESPEC_refuerzo.md` §3.

HR1, de punta a punta, el ciclo que pidió Christiam: EXAMEN -> RESULTADOS ->
REFUERZO. 10 estudiantes; un banco sintético de 4 nodos x 2 familias x 3 formas
sembrado en retos; un examen de 8 ítems (los originales) calificado con fallos
al azar (`random.Random(41)`); cada estudiante responde su refuerzo, el reloj
avanza 7 días y responde el repaso. Escribe `tests/_salida/humo_refuerzo.json`
(en `.gitignore`) ANTES de afirmar.

RR1 solo corre con `ENGRAMA_REPLICA_REFUERZO=1`, con entradas que no se usaron
al desarrollar: un estudiante en dos instituciones con el mismo nodo en las dos
colas; un ítem con 3 nodos; preguntas sin `item_ref`; un nodo cuya única forma
es `open`; y 6 entradas con el tope de 5 por vez.
"""
from __future__ import annotations

import json
import os
import random
from collections import Counter
from datetime import timedelta
from typing import Any

import pytest

from src.shared.models import Membership
from tests.curriculo import _ayuda as cat
from tests.grader import _ayuda as gr
from tests.integ_db import RAIZ_BACKEND
from tests.refuerzo import _ayuda as ay

pytestmark = pytest.mark.integ

RUTA_HUMO_REFUERZO = RAIZ_BACKEND / "tests" / "_salida" / "humo_refuerzo.json"
SEMILLA = 41
REPLICA = os.environ.get("ENGRAMA_REPLICA_REFUERZO") == "1"
NODOS = (ay.UNO, ay.DOS, ay.TRES, ay.CUATRO)

# Contenido exacto (ESPEC §3). Los cuatro ceros son CRITERIO; los demás números
# salieron de la primera medición con el código bueno y no se mueven.
HUMO_ESPERADO: dict[str, Any] = {
    "alembic_version": "041_refuerzo", "semilla": 41, "hojas": 10, "entradas": 22,
    "servidas_ya_vistas": 0, "tras_el_refuerzo": {"en_refuerzo": 6, "por_repasar": 16},
    "tras_el_repaso": {"en_refuerzo": 8, "por_repasar": 3, "superado": 11},
    "en_espera_de_contenido": 0, "huecos": 0,
    "filas_en_el_libro": 0, "saldo_movido": 0, "nivel_escrito": 0,
}


def _estados(integ: Any) -> dict[str, int]:
    from sqlalchemy import text

    async def _q() -> dict[str, int]:
        async with integ.Session() as db:
            filas = (await db.execute(text("select status, count(*) from reinforcement_queue "
                                           "group by status order by status"))).all()
            return {f[0]: int(f[1]) for f in filas}

    return integ.run(_q())


def _ronda(integ: Any, rng: random.Random, estudiantes: list[Any], vistos: dict[Any, set[str]],
           item_de: dict[str, str]) -> int:
    """Cada estudiante responde TODO lo que le sirven una vez. Devuelve las ya vistas (0)."""
    ya_vistas = 0
    for estudiante in estudiantes:
        for p in ay.pendientes(integ, estudiante):
            item = item_de[p["pregunta"]["id"]]
            ya_vistas += int(item in vistos[estudiante])
            vistos[estudiante].add(item)
            ay.responder(integ, estudiante, p["entrada_id"], p["pregunta"]["id"],
                         "A" if rng.random() < 0.7 else "B")
    return ya_vistas


def test_hr1_humo_examen_resultados_refuerzo(integ, monkeypatch) -> None:
    rng = random.Random(SEMILLA)
    ay.fijar_ahora(monkeypatch)
    cat.cargar(integ, cat.mapa_v1())
    c = gr.colegio(integ, "9A", n=10)
    banco = [ay.forma([nodo], f"n{n}-f{f}-{k}", f"n{n}-f{f}", rol)
             for n, nodo in enumerate(NODOS) for f in (1, 2)
             for k, rol in enumerate(("original", "gemela", "repaso"), start=1)]
    _reto, q = ay.sembrar_reto(integ, c.profe, "banco", banco, grupo=c.grupo)
    item_de = {pregunta: item for item, pregunta in q.items()}
    originales = [(f["item_ref"], f["nodos"]) for f in banco if f["rol"] == "original"]
    ids = [i for i, _ in originales]
    lista = gr.lista(integ, c.profe, c.codigo_grupo)[1]
    assert ay.examen_con(integ, c, originales) == 201
    hojas = [ay.hoja_con(numero, ids, malas=tuple(i for i in ids if rng.random() < 0.4))
             for numero, _ in lista]
    antes = ay.dinero(integ, c.tenant, c.estudiantes[0])
    envio = gr.enviar(integ, c.profe, c.codigo_grupo, hojas)
    vistos: dict[Any, set[str]] = {e: set(ids) for e in c.estudiantes}  # el examen ya los mostró
    entradas = int(integ.valor("select count(*) from reinforcement_queue"))
    ya_vistas = _ronda(integ, rng, c.estudiantes, vistos, item_de)
    tras_el_refuerzo = _estados(integ)
    ay.fijar_ahora(monkeypatch, ay.T0 + timedelta(days=7))
    ya_vistas += _ronda(integ, rng, c.estudiantes, vistos, item_de)
    panel = ay.panel(integ, c.profe, c.grupo).json()
    espera = Counter(n["estado"] for e in panel["estudiantes"] for n in e["nodos"])
    despues = ay.dinero(integ, c.tenant, c.estudiantes[0])
    datos = {
        "alembic_version": integ.valor("select version_num from alembic_version"),
        "semilla": SEMILLA, "hojas": envio[1][0] if envio[0] == 200 else envio,
        "entradas": entradas, "servidas_ya_vistas": ya_vistas,
        "tras_el_refuerzo": tras_el_refuerzo, "tras_el_repaso": _estados(integ),
        "en_espera_de_contenido": espera.get("en_espera_de_contenido", 0),
        "huecos": len(panel["huecos"]),
        "filas_en_el_libro": despues[0], "saldo_movido": (antes[1] or 0) - (despues[1] or 0),
        "nivel_escrito": int(integ.valor("select count(*) from confirmed_levels")),
    }
    RUTA_HUMO_REFUERZO.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO_REFUERZO.write_text(
        json.dumps(datos, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    assert datos == HUMO_ESPERADO, f"HR1: {datos}"


@pytest.mark.skipif(not REPLICA, reason="réplica del refuerzo: ENGRAMA_REPLICA_REFUERZO=1")
def test_rr1_replica_dos_instituciones_tres_nodos_y_el_tope(integ, monkeypatch) -> None:
    """RR1: la cola es por institución; un ítem mete sus 3 nodos; el tope de 5; `open` espera."""
    ay.fijar_ahora(monkeypatch)
    seis = [f"gr.b2.tema-{i}" for i in range(6)]
    cat.cargar(integ, cat.mapa("replica", list(cat.VIGENTES_V1) + seis))
    a, b = gr.colegio(integ, "A", n=1), gr.colegio(integ, "B", n=1)
    doble = a.estudiantes[0]
    integ._insertar(Membership(tenant_id=b.tenant, profile_id=doble, role="student",
                               group_code="B", is_active=True, full_name="Persona doble"))
    for c, formas in ((a, [ay.forma([n]) for n in seis] + [ay.forma([ay.UNO], tipo="open")]),
                      (b, [ay.forma([seis[0]])])):
        ay.sembrar_reto(integ, c.profe, "banco sin item_ref", formas, grupo=c.grupo)
    gr.lista(integ, a.profe, "A")
    assert ay.examen_con(integ, a, [("x-1", seis[:3]), ("x-2", seis[3:]), ("x-3", [ay.UNO])]) == 201
    envio = gr.enviar(integ, a.profe, "A", [ay.hoja_con(1, ["x-1", "x-2", "x-3"],
                                                        malas=("x-1", "x-2", "x-3"))])
    en_a = ay.leer(integ, doble)
    observado = {
        "envio": envio, "nodos_en_la_cola": len(ay.cola(integ, doble)),
        "servidas_con_el_tope": len(en_a[1][0]), "en_espera_por_open": en_a[1][2],
        "preguntas_distintas": len({p for _e, _n, p in en_a[1][0]}),
        "en_la_otra_institucion": ay.client.get(
            "/challenges/refuerzo",
            headers={**integ.headers(doble), "X-Tenant-ID": str(b.tenant)}).json()["pendientes"],
    }
    assert observado == {
        "envio": (200, (1, 0, [])), "nodos_en_la_cola": 7, "servidas_con_el_tope": 5,
        "en_espera_por_open": 1, "preguntas_distintas": 5, "en_la_otra_institucion": [],
    }, f"RR1: {observado}"
