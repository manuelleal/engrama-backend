"""Ayudas de los tests de la racha semanal (no empieza por `test_`: no se recolecta).

El calendario se mueve con la costura `racha.service._ahora` (el reloj de la
asistencia y el del refuerzo siguen en la hora real: no deciden el día de la
racha). Los retos se siembran por `POST /challenges/`, con `item_ref`.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.racha import service as racha_service

client = TestClient(app, raise_server_exceptions=False)

LUNES = date(2026, 10, 12)  # un lunes; las semanas de los tests cuelgan de aquí


def dia(n: int) -> date:
    """El día `n` desde el lunes base (0 = lunes, 7 = el lunes siguiente)."""
    return LUNES + timedelta(days=n)


def fijar_dia(mp: pytest.MonkeyPatch, fecha: date) -> None:
    """Es mediodía de `fecha` en Bogotá (17:00 UTC) para la racha."""
    instante = datetime(fecha.year, fecha.month, fecha.day, 17, 0, tzinfo=UTC)
    mp.setattr(racha_service, "_ahora", lambda: instante)


def _json(r: Any) -> Any:
    try:
        return r.json()
    except ValueError:
        return None


def leer(integ: Any, quien: UUID, **headers: str) -> Any:
    """`GET /core/racha` entero, o `(estado, cuerpo)` si no es 200."""
    r = client.get("/core/racha", headers={**integ.headers(quien), **headers})
    return r.json() if r.status_code == 200 else (r.status_code, _json(r))


def corta(integ: Any, quien: UUID, **headers: str) -> Any:
    """(racha, mejor, total, protectores, días activos de la semana, ¿cumplida?)."""
    c = leer(integ, quien, **headers)
    if not isinstance(c, dict):
        return c
    return (c.get("racha_semanas"), c.get("mejor_racha"), c.get("semanas_cumplidas"),
            c.get("protectores"), c.get("semana", {}).get("dias_activos"),
            c.get("semana", {}).get("cumplida"))


def hoy(integ: Any, quien: UUID) -> Any:
    """(respuestas, correctas, ¿activo?) de hoy."""
    c = leer(integ, quien)
    if not isinstance(c, dict):
        return c
    h = c.get("hoy", {})
    return (h.get("respuestas"), h.get("correctas"), h.get("activo"))


def en_la_base(integ: Any, quien: UUID) -> Any:
    """(racha, mejor, total, protectores) GUARDADOS, o None si no hay fila."""
    f = integ.fila("select racha_semanas, mejor_racha, semanas_cumplidas, protectores "
                   "from streak_state where profile_id = :p", p=quien)
    return None if f is None else tuple(f.values())


def por_origen(integ: Any, quien: UUID, fecha: date) -> Any:
    return integ.valor("select por_origen from activity_days where profile_id = :p "
                       "and local_date = :f", p=quien, f=fecha)


def bonos(integ: Any, quien: UUID) -> list[tuple[str, int]]:
    """Las pagas del bono de ese estudiante: (los 8 últimos de la llave, monto)."""
    from sqlalchemy import text

    async def _q() -> list[tuple[str, int]]:
        async with integ.Session() as db:
            filas = (await db.execute(text(
                "select idempotency_key, amount from coin_ledger where action = 'streak_week' "
                "and idempotency_key like :p order by idempotency_key"),
                {"p": f"%:{quien}:%"})).all()
            return [(str(k)[-8:], int(m)) for k, m in filas]

    return list(integ.run(_q()))


def sembrar(integ: Any, profe: UUID, titulo: str, n: int, *, grupo: UUID | None = None,
            prefijo: str | None = None, nodos: list[str] | None = None,
            nivel: str | None = None, **campos: Any) -> tuple[str, list[str]]:
    """Un reto de `n` preguntas (la correcta es "A"). Devuelve (reto, [preguntas])."""
    pre = prefijo or titulo
    cuerpo = {"title": titulo, "description": "sintético", "skill": "grammar",
              "group_id": str(grupo) if grupo else None, "max_attempts": 50,
              "max_winners": 100, "cefr_level": nivel, **campos,
              "questions": [{"question_type": "multiple_choice", "question_text": f"{pre} {i}",
                             "correct_answer": "A", "order_index": i, "item_ref": f"{pre}-{i}",
                             "nodos": nodos or [],
                             "options_json": [{"label": "A", "value": "uno"},
                                              {"label": "B", "value": "dos"}]}
                            for i in range(1, n + 1)]}
    r = client.post("/challenges/", headers=integ.headers(profe), json=cuerpo)
    assert r.status_code == 201, r.text
    preguntas = sorted(r.json()["questions"], key=lambda q: q["order_index"])
    return r.json()["id"], [q["id"] for q in preguntas]


def jugar(integ: Any, estudiante: UUID, reto: str, preguntas: list[str],
          respuestas: str) -> tuple[int, Any]:
    """Abre y envía. `respuestas` es una letra por pregunta; "-" = en blanco.

    Devuelve (estado, (¿ganó?, monedas)) o (estado, detalle).
    """
    h = integ.headers(estudiante)
    inicio = client.post(f"/challenges/{reto}/attempt", headers=h)
    if inicio.status_code != 201:
        return inicio.status_code, _json(inicio)
    r = client.post(
        f"/challenges/attempts/{inicio.json()['attempt_id']}/submit", headers=h,
        json={"answers": [{"question_id": q, "answer": "" if a == "-" else a}
                          for q, a in zip(preguntas, respuestas, strict=True)]})
    if r.status_code != 200:
        return r.status_code, (_json(r) or {}).get("detail")
    return 200, (r.json()["is_correct"], r.json()["coins_earned"])


def asistir(integ: Any, tenant: UUID, grupo: UUID, profe: UUID, estudiante: UUID) -> Any:
    """Abre una sesión nueva del grupo y marca. Devuelve la respuesta."""
    codigo = integ.crear_sesion_asistencia(tenant, grupo, profe)
    return client.post("/core/attendance/check-in", json={"session_code": codigo},
                       headers=integ.headers(estudiante))
