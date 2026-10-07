"""Ayudas de los tests del foco del grupo (no empieza por `test_`: no se recolecta).

Los retos se crean por `POST /challenges/` (el mismo contrato que usa el guion
de sembrado) y su `created_at` se fija a mano: el orden del feed no depende
del reloj del contenedor de pruebas.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.foco import service as foco_service
from src.main import app
from tests.seguridad.veredictos import sembrar

client = TestClient(app, raise_server_exceptions=False)

HOY = "2026-10-06"
BASE = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def fijar_hoy(mp: pytest.MonkeyPatch, dia: str = HOY, hora_utc: int = 15) -> None:
    """"Ahora" para el foco: ese día a esa hora UTC (las 10:00 de Bogotá por defecto)."""
    instante = datetime.fromisoformat(f"{dia}T{hora_utc:02d}:00:00+00:00")
    mp.setattr(foco_service, "_ahora", lambda: instante)


def _json(r: Any) -> Any:
    try:
        return r.json()
    except ValueError:
        return None


def _detalle(r: Any) -> Any:
    cuerpo = _json(r)
    return cuerpo.get("detail") if isinstance(cuerpo, dict) else None


def pregunta(nodos: list[str] | None = None, orden: int = 1) -> dict[str, Any]:
    q: dict[str, Any] = {"question_text": f"Pregunta {orden}", "correct_answer": "A",
                         "order_index": orden,
                         "options_json": [{"label": "A", "value": "uno"},
                                          {"label": "B", "value": "dos"}]}
    if nodos is not None:
        q["nodos"] = nodos
    return q


def crear_reto(integ: Any, quien: UUID, titulo: str, nodos_por_pregunta: list[Any], *,
               grupo: UUID | None = None, minuto: int = 0) -> tuple[int, Any, list[str]]:
    """`POST /challenges/`: (estado, id del reto o detalle, [ids de sus preguntas])."""
    cuerpo = {"title": titulo, "description": "sintético", "skill": "grammar",
              "group_id": str(grupo) if grupo else None, "max_attempts": 3, "max_winners": 100,
              "questions": [pregunta(n, i) for i, n in enumerate(nodos_por_pregunta, start=1)]}
    r = client.post("/challenges/", headers=integ.headers(quien), json=cuerpo)
    if r.status_code != 201:
        return r.status_code, _detalle(r), []
    datos = r.json()
    sembrar(integ, "update challenges set created_at = :f where id = :c",
            f=BASE + timedelta(minutes=minuto), c=UUID(datos["id"]))
    return 201, datos["id"], [q["id"] for q in datos["questions"]]


def etiquetas(integ: Any, quien: UUID, reto: str, **headers: str) -> tuple[int, Any]:
    """`GET /teachers/challenges/{cid}/nodos`: (estado, [nodos de cada pregunta, en orden])."""
    r = client.get(f"/teachers/challenges/{reto}/nodos",
                   headers={**integ.headers(quien), **headers})
    if r.status_code != 200:
        return r.status_code, _detalle(r)
    return 200, [p["nodos"] for p in r.json()["preguntas"]]


def reetiquetar(integ: Any, quien: UUID, reto: str, cambios: dict[str, list[str]],
                **headers: str) -> tuple[int, Any]:
    cuerpo = {"preguntas": [{"question_id": q, "nodos": n} for q, n in cambios.items()]}
    r = client.put(f"/teachers/challenges/{reto}/nodos",
                   headers={**integ.headers(quien), **headers}, json=cuerpo)
    if r.status_code != 200:
        return r.status_code, _detalle(r)
    return 200, [p["nodos"] for p in r.json()["preguntas"]]


def fijar_foco(integ: Any, quien: UUID, grupo: UUID, desde: str, nodos: list[str],
               hasta: str | None = None, **headers: str) -> tuple[int, Any]:
    """`PUT /teachers/groups/{gid}/foco`: (estado, (desde, hasta, vigente, [ids]) o detalle)."""
    cuerpo: dict[str, Any] = {"desde": desde, "nodos": nodos}
    if hasta is not None:
        cuerpo["hasta"] = hasta
    r = client.put(f"/teachers/groups/{grupo}/foco",
                   headers={**integ.headers(quien), **headers}, json=cuerpo)
    if r.status_code != 200:
        return r.status_code, _detalle(r)
    c = r.json()
    return 200, (c["desde"], c["hasta"], c["vigente"], [n["id"] for n in c["nodos"]])


def leer_foco(integ: Any, quien: UUID, grupo: UUID, **headers: str) -> tuple[int, Any]:
    """`GET .../foco`: (estado, (hoy, desde del vigente o None, [desde de cada periodo]))."""
    r = client.get(f"/teachers/groups/{grupo}/foco",
                   headers={**integ.headers(quien), **headers})
    if r.status_code != 200:
        return r.status_code, _detalle(r)
    c = r.json()
    return 200, (c["hoy"], c["vigente"]["desde"] if c["vigente"] else None,
                 [p["desde"] for p in c["periodos"]])


def borrar_foco(integ: Any, quien: UUID, grupo: UUID, desde: str, **headers: str) -> int:
    return client.delete(f"/teachers/groups/{grupo}/foco/{desde}",
                         headers={**integ.headers(quien), **headers}).status_code


def logro(integ: Any, quien: UUID, grupo: UUID, **headers: str) -> tuple[int, Any]:
    r = client.get(f"/teachers/groups/{grupo}/foco/logro",
                   headers={**integ.headers(quien), **headers})
    return r.status_code, _json(r) if r.status_code == 200 else _detalle(r)


def feed(integ: Any, estudiante: UUID) -> list[str]:
    """Los ids de `GET /challenges/`, en el orden en que llegan."""
    r = client.get("/challenges/", headers=integ.headers(estudiante))
    assert r.status_code == 200, r.text
    return [c["id"] for c in r.json()]


def foco_del_estudiante(integ: Any, estudiante: UUID) -> tuple[int, Any]:
    """`GET /challenges/foco`: (estado, (desde o None, [ids de nodos], [retos en foco]))."""
    r = client.get("/challenges/foco", headers=integ.headers(estudiante))
    if r.status_code != 200:
        return r.status_code, _detalle(r)
    c = r.json()
    v = c["vigente"]
    return 200, (v["desde"] if v else None, [n["id"] for n in v["nodos"]] if v else [],
                 c["retos_en_foco"])


def respuestas(marcas: dict[str, bool]) -> list[dict[str, Any]]:
    """El `answers` de un intento, como lo guarda `attempts.py`: `{pregunta: ¿acertó?}`."""
    return [{"question_id": q, "given_answer": "A" if ok else "B", "correct_answer": "A",
             "is_correct": ok} for q, ok in marcas.items()]


def nodos_de_pregunta(integ: Any, question_id: str) -> list[str]:
    from sqlalchemy import text

    async def _q() -> list[str]:
        async with integ.Session() as db:
            fila = (await db.execute(text("select nodes from challenge_questions "
                                          "where id = :q"), {"q": UUID(question_id)})).first()
            return list(fila[0]) if fila else []

    return integ.run(_q())


def nodos_del_foco(integ: Any, grupo: UUID) -> list[list[str]]:
    from sqlalchemy import text

    async def _q() -> list[list[str]]:
        async with integ.Session() as db:
            filas = (await db.execute(text("select nodes from group_focus where group_id = :g "
                                           "order by starts_on"), {"g": grupo})).all()
            return [list(f[0]) for f in filas]

    return integ.run(_q())
