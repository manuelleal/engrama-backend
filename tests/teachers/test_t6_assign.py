"""F6 y las celdas de T6 — ESPEC §2, §3: `PUT /teachers/groups/{gid}/challenges/{cid}`.

F6 es también el test real de X7 ("T6 no revisa el grupo actual", §3): un
reto YA asignado a un grupo que D no ve (GC, del mismo colegio) no puede
"robarse" hacia GA — debe dar 404, no 200.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.teachers._actores import armar

pytestmark = pytest.mark.integ
client = TestClient(app)


def test_f6_no_reasigna_reto_de_grupo_no_visible(integ) -> None:
    """F6/X7: reto en GC (invisible para D) -> PUT a GA da 404, group_id intacto."""
    esc = armar(integ)
    grupo_c = integ.crear_grupo(esc.tenant_a, "GC")
    cid, _ = integ.crear_challenge(esc.tenant_a, esc.d, group_id=grupo_c)

    r = client.put(f"/teachers/groups/{esc.grupo_a}/challenges/{cid}",
                    headers=esc.h(integ, esc.d))
    assert r.status_code == 404, r.text
    assert integ.valor("select group_id from challenges where id = :c", c=cid) == grupo_c


def test_t6_control_d_reasigna_reto_sin_grupo(integ) -> None:
    """Control: un reto SIN grupo sí se puede asignar a GA."""
    esc = armar(integ)
    cid, _ = integ.crear_challenge(esc.tenant_a, esc.d, group_id=None)
    r = client.put(f"/teachers/groups/{esc.grupo_a}/challenges/{cid}",
                    headers=esc.h(integ, esc.d))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == str(cid)
    assert integ.valor("select group_id from challenges where id = :c", c=cid) == esc.grupo_a


def test_t6_e_403(integ) -> None:
    esc = armar(integ)
    cid, _ = integ.crear_challenge(esc.tenant_a, esc.d, group_id=None)
    r = client.put(f"/teachers/groups/{esc.grupo_a}/challenges/{cid}",
                    headers=esc.h(integ, esc.e))
    assert r.status_code == 403, r.text


def test_t6_do_404(integ) -> None:
    esc = armar(integ)
    cid, _ = integ.crear_challenge(esc.tenant_a, esc.d, group_id=None)
    r = client.put(f"/teachers/groups/{esc.grupo_a}/challenges/{cid}",
                    headers=esc.h(integ, esc.do))
    assert r.status_code == 404, r.text


def test_t6_dt_404(integ) -> None:
    esc = armar(integ)
    cid, _ = integ.crear_challenge(esc.tenant_a, esc.d, group_id=None)
    r = client.put(f"/teachers/groups/{esc.grupo_a}/challenges/{cid}",
                    headers=esc.h(integ, esc.dt))
    assert r.status_code == 404, r.text


def test_t6_dm_404(integ) -> None:
    esc = armar(integ)
    cid, _ = integ.crear_challenge(esc.tenant_a, esc.d, group_id=None)
    r = client.put(f"/teachers/groups/{esc.grupo_a}/challenges/{cid}",
                    headers=esc.h(integ, esc.dm, tenant=esc.tenant_b))
    assert r.status_code == 404, r.text


def test_t6_ab_404(integ) -> None:
    esc = armar(integ)
    cid, _ = integ.crear_challenge(esc.tenant_a, esc.d, group_id=None)
    r = client.put(f"/teachers/groups/{esc.grupo_a}/challenges/{cid}",
                    headers=esc.h(integ, esc.ab))
    assert r.status_code == 404, r.text
