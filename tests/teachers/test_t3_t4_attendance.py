"""F3, F4 y las celdas de T3/T4 — ESPEC §2, §3.

F4 es también el test real de X5 ("close no cambia el status", §3): cierra la
sesión y exige que el check-in posterior dé 410 — si `close_session` no
cambia `status`, el check-in seguiría dando 200.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.teachers._actores import armar

pytestmark = pytest.mark.integ
client = TestClient(app)


# =============================================================================
# T3 — POST /teachers/groups/{gid}/attendance-sessions
# =============================================================================
def test_f3_docente_abre_sesion(integ) -> None:
    esc = armar(integ)
    r = client.post(f"/teachers/groups/{esc.grupo_a}/attendance-sessions",
                     headers=esc.h(integ, esc.d), json={"duration_minutes": 20})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "active"
    assert len(body["session_code"]) == 6
    fila = integ.fila("select group_id, created_by from attendance_sessions where id = :i",
                      i=body["id"])
    assert fila == {"group_id": esc.grupo_a, "created_by": esc.d}


def test_t3_e_403(integ) -> None:
    esc = armar(integ)
    r = client.post(f"/teachers/groups/{esc.grupo_a}/attendance-sessions",
                     headers=esc.h(integ, esc.e), json={})
    assert r.status_code == 403, r.text


def test_t3_do_404(integ) -> None:
    esc = armar(integ)
    r = client.post(f"/teachers/groups/{esc.grupo_a}/attendance-sessions",
                     headers=esc.h(integ, esc.do), json={})
    assert r.status_code == 404, r.text


def test_t3_dt_404(integ) -> None:
    esc = armar(integ)
    r = client.post(f"/teachers/groups/{esc.grupo_a}/attendance-sessions",
                     headers=esc.h(integ, esc.dt), json={})
    assert r.status_code == 404, r.text


def test_t3_dm_404(integ) -> None:
    esc = armar(integ)
    r = client.post(f"/teachers/groups/{esc.grupo_a}/attendance-sessions",
                     headers=esc.h(integ, esc.dm, tenant=esc.tenant_b), json={})
    assert r.status_code == 404, r.text


def test_t3_ab_404(integ) -> None:
    esc = armar(integ)
    r = client.post(f"/teachers/groups/{esc.grupo_a}/attendance-sessions",
                     headers=esc.h(integ, esc.ab), json={})
    assert r.status_code == 404, r.text


# =============================================================================
# T4 — POST /teachers/attendance-sessions/{sid}/close
# =============================================================================
def _sembrar_sesion(integ, esc) -> str:
    """Sesión activa para GA, creada por D. Devuelve su `id` (UUID en texto)."""
    codigo = integ.crear_sesion_asistencia(esc.tenant_a, esc.grupo_a, esc.d)
    return str(integ.valor(
        "select id from attendance_sessions where session_code = :c", c=codigo
    ))


def test_f4_cerrar_expira_y_bloquea_checkin(integ) -> None:
    """F4/X5: D cierra su sesión; el check-in posterior da 410, no 200."""
    esc = armar(integ)
    codigo = integ.crear_sesion_asistencia(esc.tenant_a, esc.grupo_a, esc.d)
    sid = integ.valor("select id from attendance_sessions where session_code = :c", c=codigo)

    r = client.post(f"/teachers/attendance-sessions/{sid}/close", headers=esc.h(integ, esc.d))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "expired"
    assert integ.valor("select status from attendance_sessions where id = :i", i=sid) == "expired"

    checkin = client.post("/core/attendance/check-in", headers=esc.h(integ, esc.e),
                          json={"session_code": codigo})
    assert checkin.status_code == 410, checkin.text


def test_t4_e_403(integ) -> None:
    esc = armar(integ)
    sid = _sembrar_sesion(integ, esc)
    r = client.post(f"/teachers/attendance-sessions/{sid}/close", headers=esc.h(integ, esc.e))
    assert r.status_code == 403, r.text


def test_t4_do_404(integ) -> None:
    esc = armar(integ)
    sid = _sembrar_sesion(integ, esc)
    r = client.post(f"/teachers/attendance-sessions/{sid}/close", headers=esc.h(integ, esc.do))
    assert r.status_code == 404, r.text


def test_t4_dt_404(integ) -> None:
    esc = armar(integ)
    sid = _sembrar_sesion(integ, esc)
    r = client.post(f"/teachers/attendance-sessions/{sid}/close", headers=esc.h(integ, esc.dt))
    assert r.status_code == 404, r.text


def test_t4_dm_404(integ) -> None:
    esc = armar(integ)
    sid = _sembrar_sesion(integ, esc)
    r = client.post(f"/teachers/attendance-sessions/{sid}/close",
                     headers=esc.h(integ, esc.dm, tenant=esc.tenant_b))
    assert r.status_code == 404, r.text


def test_t4_ab_404(integ) -> None:
    esc = armar(integ)
    sid = _sembrar_sesion(integ, esc)
    r = client.post(f"/teachers/attendance-sessions/{sid}/close", headers=esc.h(integ, esc.ab))
    assert r.status_code == 404, r.text
