"""Ayudas de los tests de la respuesta por pregunta, L1 (no se recolecta).

Los retos se siembran por `POST /challenges/`, con `explanation` en la forma
del banco. Todo se responde por HTTP.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app, raise_server_exceptions=False)

OPCIONES = {"A": "goes", "B": "go", "C": "going"}
EXPLICACION = {"regla": "Con he, she, it el verbo lleva -s.",
               "por_opcion": {"B": "Go es para I, you, we, they.", "C": "Going necesita is."},
               "ejemplo": "He plays football."}


def _json(r: Any) -> Any:
    try:
        return r.json()
    except ValueError:
        return None


def _detalle(r: Any) -> Any:
    cuerpo = _json(r)
    return cuerpo.get("detail") if isinstance(cuerpo, dict) else None


def pregunta(texto: str = "She ___ to school every day.", clave: str = "A", *,
             opciones: dict[str, str] | None = None, tipo: str = "multiple_choice",
             **campos: Any) -> dict[str, Any]:
    """Una pregunta para sembrar. `campos`: explanation, item_ref, familia, rol, nodos..."""
    q: dict[str, Any] = {"question_type": tipo, "question_text": texto, "correct_answer": clave,
                         **campos}
    if tipo == "multiple_choice":
        q["options_json"] = [{"label": k, "value": v}
                             for k, v in (opciones or OPCIONES).items()]
    return q


def reto(integ: Any, profe: UUID, titulo: str, preguntas: list[dict[str, Any]], *,
         grupo: UUID | None, nivel: str | None = "A2", **campos: Any) -> tuple[str, list[str]]:
    """`POST /challenges/`: (id del reto, [ids de las preguntas, en orden])."""
    tipos = {q["question_type"] for q in preguntas}
    cuerpo = {"title": titulo, "description": "sintético", "skill": "grammar",
              "challenge_type": "multiple_choice" if tipos == {"multiple_choice"} else "fill_blank",
              "group_id": str(grupo) if grupo else None, "max_attempts": 50,
              "max_winners": 100, "cefr_level": nivel, **campos,
              "questions": [{**q, "order_index": i} for i, q in enumerate(preguntas, start=1)]}
    r = client.post("/challenges/", headers=integ.headers(profe), json=cuerpo)
    assert r.status_code == 201, r.text
    ordenadas = sorted(r.json()["questions"], key=lambda q: q["order_index"])
    return r.json()["id"], [q["id"] for q in ordenadas]


def abrir(integ: Any, quien: UUID, reto_id: str, **headers: str) -> Any:
    """`POST /challenges/{id}/attempt`: el cuerpo, o `(estado, detalle)`."""
    r = client.post(f"/challenges/{reto_id}/attempt", headers={**integ.headers(quien), **headers})
    return r.json() if r.status_code == 201 else (r.status_code, _detalle(r))


def intento(integ: Any, quien: UUID, reto_id: str) -> tuple[str, list[str]]:
    """Abre (o retoma) un intento: (id del intento, [ids de SUS preguntas, en orden])."""
    cuerpo = abrir(integ, quien, reto_id)
    assert isinstance(cuerpo, dict), f"no se pudo abrir el intento: {cuerpo}"
    ordenadas = sorted(cuerpo["challenge"]["questions"], key=lambda q: q["order_index"])
    return cuerpo["attempt_id"], [q["id"] for q in ordenadas]


def responder_crudo(integ: Any, quien: UUID, intento_id: str, pregunta_id: str,
                    respuesta: str, cliente: TestClient | None = None, **headers: str) -> Any:
    return (cliente or client).post(
        f"/challenges/attempts/{intento_id}/answers",
        headers={**integ.headers(quien), **headers},
        json={"question_id": pregunta_id, "answer": respuesta})


def responder(integ: Any, quien: UUID, intento_id: str, pregunta_id: str, respuesta: str,
              **headers: str) -> Any:
    """`(estado, (¿acertó?, guardada, correcta, oración, explicación, ¿repetida?, n, total))`."""
    r = responder_crudo(integ, quien, intento_id, pregunta_id, respuesta, **headers)
    if r.status_code != 200:
        return r.status_code, _detalle(r)
    c = r.json()
    return 200, (c["is_correct"], c["answer"], c["correct_answer"], c["oracion_correcta"],
                 c["explanation"], c["repetida"], c["respondidas"], c["total"])


def corta(respuesta: Any) -> Any:
    """De `responder`: (estado, ¿acertó?, guardada, ¿repetida?) o (estado, detalle)."""
    estado, cuerpo = respuesta
    if estado != 200:
        return estado, cuerpo
    return estado, cuerpo[0], cuerpo[1], cuerpo[5]


def retomar(integ: Any, quien: UUID, intento_id: str) -> Any:
    r = client.get(f"/challenges/attempts/{intento_id}/answers", headers=integ.headers(quien))
    return r.json() if r.status_code == 200 else (r.status_code, _detalle(r))


def terminar_crudo(integ: Any, quien: UUID, intento_id: str) -> Any:
    return client.post(f"/challenges/attempts/{intento_id}/finish", headers=integ.headers(quien))


def terminar(integ: Any, quien: UUID, intento_id: str) -> tuple[int, Any]:
    """`POST …/finish`: (estado, (¿ganó?, monedas)) o (estado, detalle)."""
    r = terminar_crudo(integ, quien, intento_id)
    if r.status_code != 200:
        return r.status_code, _detalle(r)
    return 200, (r.json()["is_correct"], r.json()["coins_earned"])


def enviar(integ: Any, quien: UUID, intento_id: str, respuestas: dict[str, str]) -> tuple[int, Any]:
    """`POST …/submit` (la ruta de siempre): (estado, (¿ganó?, monedas)) o (estado, detalle)."""
    r = client.post(f"/challenges/attempts/{intento_id}/submit", headers=integ.headers(quien),
                    json={"answers": [{"question_id": q, "answer": a}
                                      for q, a in respuestas.items()]})
    if r.status_code != 200:
        return r.status_code, _detalle(r)
    return 200, (r.json()["is_correct"], r.json()["coins_earned"])


def jugar(integ: Any, quien: UUID, reto_id: str, letras: str) -> tuple[int, Any]:
    """Un intento entero pregunta por pregunta: abre, responde cada una y termina.

    `letras`: una por pregunta del intento, en orden; "-" = no la responde.
    """
    intento_id, preguntas = intento(integ, quien, reto_id)
    for pregunta_id, letra in zip(preguntas, letras, strict=True):
        if letra != "-":
            assert responder(integ, quien, intento_id, pregunta_id, letra)[0] == 200
    return terminar(integ, quien, intento_id)


def a_la_vez(*llamadas: Callable[[TestClient], Any]) -> list[Any]:
    """Corre las llamadas AL MISMO TIEMPO (un hilo y un cliente por llamada)."""
    barrera = threading.Barrier(len(llamadas))
    resultados: list[Any] = [None] * len(llamadas)

    def _correr(i: int, llamada: Callable[[TestClient], Any]) -> None:
        cliente = TestClient(app, raise_server_exceptions=False)
        barrera.wait(timeout=30)
        resultados[i] = llamada(cliente)

    hilos = [threading.Thread(target=_correr, args=(i, f)) for i, f in enumerate(llamadas)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=120)
    return resultados


def pagas(integ: Any, reto_id: str) -> list[int]:
    """Los montos pagados por ese reto, de menor a mayor (el id del libro no da el orden)."""
    from sqlalchemy import text

    async def _q() -> list[int]:
        async with integ.Session() as db:
            filas = (await db.execute(text(
                "select amount from coin_ledger where action = 'challenge' and amount > 0 "
                "and metadata->>'challenge_id' = :r order by amount"), {"r": reto_id})).scalars()
            return [int(m) for m in filas]

    return list(integ.run(_q()))


def filas(integ: Any, sql: str, **params: Any) -> list[tuple[Any, ...]]:
    from sqlalchemy import text

    async def _q() -> list[tuple[Any, ...]]:
        async with integ.Session() as db:
            return [tuple(f) for f in (await db.execute(text(sql), params)).all()]

    return list(integ.run(_q()))
