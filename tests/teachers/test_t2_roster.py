"""F2 y las celdas de T2 — ESPEC §2, §2.2, §3: `GET /teachers/groups/{gid}/students`.

F2 también es el test real de X9 ("T2 incluye balance", §3): el roster nunca
trae `balance` ni `pin_hash` ni `documento_id`, sin importar qué calcule el
service por dentro (`_forzar_balance_en_respuesta` reemplaza la ruta en sitio
para probarlo incluso si alguien reintrodujera el campo pasando por encima
del `response_model`, ver `tests/tramposos/test_tramposos_grupos.py`).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.teachers._actores import armar

pytestmark = pytest.mark.integ
client = TestClient(app)


def test_f2_roster_sin_balance(integ) -> None:
    """F2: D ve a E en el roster, con constancia y sin saldo/documento/pin."""
    esc = armar(integ)
    r = client.get(f"/teachers/groups/{esc.grupo_a}/students", headers=esc.h(integ, esc.d))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == [
        {
            "profile_id": str(esc.e),
            # BUG-11: el nombre que ve el colegio A sale de SU membresía.
            "full_name": integ.fila("select full_name from memberships "
                                    "where tenant_id = :t and profile_id = :p",
                                    t=esc.tenant_a, p=esc.e)["full_name"],
            "consistency": {"label": "constancia", "current_streak": 0},
            "last_attendance_date": None,
        }
    ]
    for prohibido in ("balance", "documento_id", "pin_hash", "saldo"):
        assert prohibido not in r.text, f"{prohibido} sale en el roster"


def test_t2_e_403(integ) -> None:
    esc = armar(integ)
    r = client.get(f"/teachers/groups/{esc.grupo_a}/students", headers=esc.h(integ, esc.e))
    assert r.status_code == 403, r.text


def test_t2_do_404(integ) -> None:
    esc = armar(integ)
    r = client.get(f"/teachers/groups/{esc.grupo_a}/students", headers=esc.h(integ, esc.do))
    assert r.status_code == 404, r.text


def test_t2_dt_404(integ) -> None:
    esc = armar(integ)
    r = client.get(f"/teachers/groups/{esc.grupo_a}/students", headers=esc.h(integ, esc.dt))
    assert r.status_code == 404, r.text


def test_t2_dm_404(integ) -> None:
    esc = armar(integ)
    r = client.get(f"/teachers/groups/{esc.grupo_a}/students",
                   headers=esc.h(integ, esc.dm, tenant=esc.tenant_b))
    assert r.status_code == 404, r.text


def test_t2_ab_404(integ) -> None:
    esc = armar(integ)
    r = client.get(f"/teachers/groups/{esc.grupo_a}/students", headers=esc.h(integ, esc.ab))
    assert r.status_code == 404, r.text


def test_t2_control_aa(integ) -> None:
    """Control: AA (admin del mismo colegio) también ve el roster — §3."""
    esc = armar(integ)
    r = client.get(f"/teachers/groups/{esc.grupo_a}/students", headers=esc.h(integ, esc.aa))
    assert r.status_code == 200, r.text
    assert [s["profile_id"] for s in r.json()] == [str(esc.e)]
