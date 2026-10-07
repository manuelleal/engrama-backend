"""Ayudas de los tests de la cola de refuerzo (no empieza por `test_`: no se recolecta).

Un banco sintético sembrado por `POST /challenges/` (el contrato del guion de
sembrado, con `item_ref`, `familia` y `rol`), el Grader simulado de
`tests/grader/_ayuda.py`, y el reloj del refuerzo fijado a mano.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.refuerzo import service as refuerzo_service
from tests.grader import _ayuda as gr

client = TestClient(app, raise_server_exceptions=False)

UNO, DOS, TRES, CUATRO = "gr.a1.uno", "gr.a1.dos", "fn.a2.tres", "lx.b1.cuatro"
T0 = datetime(2026, 10, 6, 15, 0, tzinfo=UTC)


def fijar_ahora(mp: pytest.MonkeyPatch, instante: datetime = T0) -> None:
    mp.setattr(refuerzo_service, "_ahora", lambda: instante)


def _json(r: Any) -> Any:
    try:
        return r.json()
    except ValueError:
        return None


def _detalle(r: Any) -> Any:
    cuerpo = _json(r)
    return cuerpo.get("detail") if isinstance(cuerpo, dict) else None


def forma(nodos: list[str], item_ref: str | None = None, familia: str | None = None,
          rol: str | None = None, tipo: str = "multiple_choice") -> dict[str, Any]:
    """Una pregunta del banco sintético. La correcta es siempre "A"."""
    q: dict[str, Any] = {"question_type": tipo, "question_text": f"Pregunta {item_ref or '?'}",
                         "correct_answer": "A", "nodos": nodos,
                         "options_json": [{"label": "A", "value": "uno"},
                                          {"label": "B", "value": "dos"}]}
    for clave, valor in (("item_ref", item_ref), ("familia", familia), ("rol", rol)):
        if valor is not None:
            q[clave] = valor
    return q


def sembrar_reto(integ: Any, quien: UUID, titulo: str, formas: list[dict[str, Any]], *,
                 grupo: UUID | None = None) -> tuple[str, dict[str, str]]:
    """`POST /challenges/`: (id del reto, `{item_ref o posición: id de la pregunta}`)."""
    cuerpo = {"title": titulo, "description": "sintético", "skill": "grammar",
              "group_id": str(grupo) if grupo else None, "max_attempts": 5, "max_winners": 100,
              "questions": [{**f, "order_index": i} for i, f in enumerate(formas, start=1)]}
    r = client.post("/challenges/", headers=integ.headers(quien), json=cuerpo)
    assert r.status_code == 201, r.text
    datos = r.json()
    ids = [q["id"] for q in sorted(datos["questions"], key=lambda q: q["order_index"])]
    return datos["id"], {f.get("item_ref") or str(i): q
                         for i, (f, q) in enumerate(zip(formas, ids, strict=True), start=1)}


def examen_con(integ: Any, c: gr.Colegio, items: list[tuple[str, list[str]]], *,
               codigo: str = gr.CODIGO) -> int:
    """Registra un examen cuyos ítems son `(item_id, nodos)`. Devuelve el estado."""
    cuerpo = gr.examen(c.codigo_grupo, len(items), codigo=codigo,
                       items=[gr.item(i, nodos=n) for i, n in items])
    return gr.registrar(integ, c.profe, cuerpo)[0]


def hoja_con(numero: int, items: list[str], malas: tuple[str, ...] = (), *,
             vacias: tuple[str, ...] = (), dobles: tuple[str, ...] = (),
             codigo: str = gr.CODIGO) -> dict[str, Any]:
    """Una hoja honesta sobre ESOS ítems; `malas`, `vacias` y `dobles` son `item_id`."""
    filas = []
    for item_id in items:
        if item_id in vacias:
            filas.append(gr.item_de_hoja(item_id, estado="vacia", correcta=False,
                                         elegida_texto=None))
        elif item_id in dobles:
            filas.append(gr.item_de_hoja(item_id, estado="doble", correcta=False,
                                         elegida_texto=None))
        else:
            filas.append(gr.item_de_hoja(item_id, correcta=item_id not in malas))
    aciertos = sum(1 for f in filas if f["estado"] == "marcada" and f["correcta"])
    return {"event_id": f"grd:{codigo}:{numero}", "numero": numero, "forma": "A",
            "calificado_en": gr.CALIFICADO, "items": filas, "aciertos": aciertos,
            "total": len(items)}


def cola(integ: Any, estudiante: UUID) -> dict[str, tuple[Any, ...]]:
    """`{nodo: (estado, fallos, origen, reaperturas)}` de la cola de ese estudiante."""
    from sqlalchemy import text

    async def _q() -> dict[str, tuple[Any, ...]]:
        async with integ.Session() as db:
            filas = (await db.execute(text(
                "select node_id, status, failures, origin, reopened from reinforcement_queue "
                "where profile_id = :p order by node_id"), {"p": estudiante})).all()
            return {f[0]: (f[1], f[2], f[3], f[4]) for f in filas}

    return integ.run(_q())


def leer(integ: Any, estudiante: UUID) -> tuple[int, Any]:
    """`GET /challenges/refuerzo`: (estado, ([(etapa, nodo, pregunta)], repasar, espera, superados))."""
    r = client.get("/challenges/refuerzo", headers=integ.headers(estudiante))
    if r.status_code != 200:
        return r.status_code, _detalle(r)
    c = r.json()
    return 200, ([(p["etapa"], p["nodo"]["id"], p["pregunta"]["id"]) for p in c["pendientes"]],
                 c["por_repasar"], c["en_espera_de_contenido"], c["superados"])


def pendientes(integ: Any, estudiante: UUID) -> list[dict[str, Any]]:
    """Los `pendientes` crudos (con `entrada_id` y la pregunta completa)."""
    r = client.get("/challenges/refuerzo", headers=integ.headers(estudiante))
    assert r.status_code == 200, r.text
    return list(r.json()["pendientes"])


def entrada_de(integ: Any, estudiante: UUID, nodo: str) -> int:
    return int(integ.valor("select id from reinforcement_queue where profile_id = :p "
                           "and node_id = :n", p=estudiante, n=nodo))


def responder(integ: Any, estudiante: UUID, entrada: int, pregunta: str,
              respuesta: str = "A") -> tuple[int, Any]:
    """`POST .../respuestas`: (estado, (acertó, correcta, estado, próxima, repetida, monedas))."""
    r = client.post(f"/challenges/refuerzo/{entrada}/respuestas",
                    headers=integ.headers(estudiante),
                    json={"question_id": pregunta, "answer": respuesta})
    if r.status_code != 200:
        return r.status_code, _detalle(r)
    c = r.json()
    return 200, (c["is_correct"], c["correct_answer"], c["estado"], c["proxima_fecha"],
                 c["repetida"], c["coins_earned"])


def panel(integ: Any, quien: UUID, grupo: UUID, **headers: str) -> Any:
    return client.get(f"/teachers/groups/{grupo}/refuerzo",
                      headers={**integ.headers(quien), **headers})


def panel_corto(integ: Any, quien: UUID, grupo: UUID) -> Any:
    """({estudiante: [(nodo, estado)]}, [(nodo, refuerzo, repasar, superado, espera)], huecos)."""
    r = panel(integ, quien, grupo)
    if r.status_code != 200:
        return r.status_code
    c = r.json()
    return ({e["profile_id"]: [(n["nodo"]["id"], n["estado"]) for n in e["nodos"]]
             for e in c["estudiantes"] if e["nodos"]},
            [(n["nodo"]["id"], n["en_refuerzo"], n["por_repasar"], n["superado"],
              n["en_espera_de_contenido"]) for n in c["por_nodo"]],
            [(h["nodo"]["id"], h["estudiantes_en_espera"]) for h in c["huecos"]])


def dinero(integ: Any, tenant: UUID, estudiante: UUID) -> tuple[int, Any, Any]:
    """(filas en el libro, saldo de la bolsa, saldo del estudiante)."""
    return (int(integ.valor("select count(*) from coin_ledger")),
            integ.saldo("tenant", tenant), integ.saldo("profile", estudiante))


def jugar(integ: Any, estudiante: UUID, reto: str, respuestas: dict[str, str]) -> tuple[int, Any]:
    """Abre un intento y lo envía: (estado, (¿ganó?, monedas)). `respuestas` = `{pregunta: label}`."""
    h = integ.headers(estudiante)
    inicio = client.post(f"/challenges/{reto}/attempt", headers=h)
    assert inicio.status_code == 201, inicio.text
    r = client.post(f"/challenges/attempts/{inicio.json()['attempt_id']}/submit", headers=h,
                    json={"answers": [{"question_id": q, "answer": a}
                                      for q, a in respuestas.items()]})
    if r.status_code != 200:
        return r.status_code, _detalle(r)
    return 200, (r.json()["is_correct"], r.json()["coins_earned"])
