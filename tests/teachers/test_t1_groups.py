"""F1 y las celdas de T1 — ESPEC §3, §4: `GET /teachers/groups`.

F1: funcional (D ve GA con su conteo de estudiantes). Celdas: "E 403 · DO, DT,
DM, AB: 200 sin GA | D" — a diferencia de T2-T7, los no asignados NO reciben
404: T1 es un LISTADO, así que "prohibido" es "200 pero sin GA adentro".
Cada función es una sola celda, sin parametrize: los tramposos (X1, X2) las
llaman directo, como en `tests/tramposos/test_tramposos_seguridad.py`.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.teachers._actores import armar

pytestmark = pytest.mark.integ
client = TestClient(app)


def test_f1_docente_ve_su_grupo_con_conteo(integ) -> None:
    """F1: D ve exactamente GA, con 1 estudiante (E, ya matriculado)."""
    esc = armar(integ)
    r = client.get("/teachers/groups", headers=esc.h(integ, esc.d))
    assert r.status_code == 200, r.text
    assert r.json() == [
        {"id": str(esc.grupo_a), "group_code": esc.codigo_a, "student_count": 1}
    ]


def test_t1_e_403(integ) -> None:
    esc = armar(integ)
    r = client.get("/teachers/groups", headers=esc.h(integ, esc.e))
    assert r.status_code == 403, r.text


def test_t1_do_200_sin_ga(integ) -> None:
    esc = armar(integ)
    r = client.get("/teachers/groups", headers=esc.h(integ, esc.do))
    assert r.status_code == 200, r.text
    assert str(esc.grupo_a) not in {g["id"] for g in r.json()}


def test_t1_dt_200_sin_ga(integ) -> None:
    esc = armar(integ)
    r = client.get("/teachers/groups", headers=esc.h(integ, esc.dt))
    assert r.status_code == 200, r.text
    assert str(esc.grupo_a) not in {g["id"] for g in r.json()}


def test_t1_dm_200_sin_ga(integ) -> None:
    esc = armar(integ)
    r = client.get("/teachers/groups", headers=esc.h(integ, esc.dm, tenant=esc.tenant_b))
    assert r.status_code == 200, r.text
    assert str(esc.grupo_a) not in {g["id"] for g in r.json()}


def test_t1_ab_200_sin_ga(integ) -> None:
    esc = armar(integ)
    r = client.get("/teachers/groups", headers=esc.h(integ, esc.ab))
    assert r.status_code == 200, r.text
    ids = {g["id"] for g in r.json()}
    assert str(esc.grupo_a) not in ids
    assert str(esc.grupo_b) in ids  # control: AB sí ve el suyo
