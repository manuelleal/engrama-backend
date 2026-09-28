"""F7, F8 y las celdas de M1/M2 — ESPEC §2, §3.

M1: `E 403 · D 403 | AA`. M2: `E 403 · D 403 · AB 404 | AA`.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.teachers._actores import armar

pytestmark = pytest.mark.integ
client = TestClient(app)


# =============================================================================
# M1 — POST /admin/groups
# =============================================================================
def test_f7_aa_crea_grupo_idempotente(integ) -> None:
    """F7: AA crea un grupo nuevo (201); repetir el código da 409, sin duplicar."""
    esc = armar(integ)
    r = client.post("/admin/groups", headers=esc.h(integ, esc.aa),
                     json={"group_code": "GX", "max_capacity": 30})
    assert r.status_code == 201, r.text
    assert r.json()["group_code"] == "GX"
    assert r.json()["max_capacity"] == 30

    dup = client.post("/admin/groups", headers=esc.h(integ, esc.aa), json={"group_code": "GX"})
    assert dup.status_code == 409, dup.text
    assert integ.valor("select count(*) from groups where tenant_id = :t and group_code = 'GX'",
                       t=esc.tenant_a) == 1


def test_m1_e_403(integ) -> None:
    esc = armar(integ)
    r = client.post("/admin/groups", headers=esc.h(integ, esc.e), json={"group_code": "GY"})
    assert r.status_code == 403, r.text


def test_m1_d_403(integ) -> None:
    esc = armar(integ)
    r = client.post("/admin/groups", headers=esc.h(integ, esc.d), json={"group_code": "GY"})
    assert r.status_code == 403, r.text


# =============================================================================
# M2 — POST /admin/groups/{gid}/teachers
# =============================================================================
def test_f8_aa_asigna_docente_idempotente(integ) -> None:
    """F8: AA asigna a DO a GA (201); repetir da 200, sin duplicar la fila."""
    esc = armar(integ)
    doc_do = integ.fila("select documento_id from profiles where id = :p", p=esc.do)["documento_id"]

    r = client.post(f"/admin/groups/{esc.grupo_a}/teachers", headers=esc.h(integ, esc.aa),
                     json={"documento_id": doc_do})
    assert r.status_code == 201, r.text
    assert r.json() == {"teacher_id": str(esc.do), "documento_id": doc_do, "resultado": "asignado"}

    otra_vez = client.post(f"/admin/groups/{esc.grupo_a}/teachers", headers=esc.h(integ, esc.aa),
                            json={"documento_id": doc_do})
    assert otra_vez.status_code == 200, otra_vez.text
    assert otra_vez.json()["resultado"] == "ya_estaba"
    assert integ.valor(
        "select count(*) from teacher_groups where teacher_id = :p and group_id = :g",
        p=esc.do, g=esc.grupo_a,
    ) == 1


def test_m2_documento_sin_membresia_docente_404(integ) -> None:
    """Control negativo del contrato: E (estudiante) no es docente -> 404, no 201."""
    esc = armar(integ)
    doc_e = integ.fila("select documento_id from profiles where id = :p", p=esc.e)["documento_id"]
    r = client.post(f"/admin/groups/{esc.grupo_a}/teachers", headers=esc.h(integ, esc.aa),
                     json={"documento_id": doc_e})
    assert r.status_code == 404, r.text


def test_m2_e_403(integ) -> None:
    esc = armar(integ)
    r = client.post(f"/admin/groups/{esc.grupo_a}/teachers", headers=esc.h(integ, esc.e),
                     json={"documento_id": "x"})
    assert r.status_code == 403, r.text


def test_m2_d_403(integ) -> None:
    esc = armar(integ)
    r = client.post(f"/admin/groups/{esc.grupo_a}/teachers", headers=esc.h(integ, esc.d),
                     json={"documento_id": "x"})
    assert r.status_code == 403, r.text


def test_m2_ab_404(integ) -> None:
    esc = armar(integ)
    r = client.post(f"/admin/groups/{esc.grupo_a}/teachers", headers=esc.h(integ, esc.ab),
                     json={"documento_id": "x"})
    assert r.status_code == 404, r.text
