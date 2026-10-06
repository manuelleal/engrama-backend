"""F9 y las celdas de M3 — ESPEC §2, §3: `POST /admin/groups/{gid}/students`."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.teachers._actores import armar

pytestmark = pytest.mark.integ
client = TestClient(app)


def test_f9_aa_matricula_idempotente_y_detecta_conflictos(integ) -> None:
    """F9: AA matricula (201); repetir da 200 sin pisar el nombre; conflictos -> 409."""
    esc = armar(integ)
    r = client.post(f"/admin/groups/{esc.grupo_a}/students", headers=esc.h(integ, esc.aa),
                     json={"documento_id": "doc-nuevo-1", "nombre_completo": "Ana Nueva"})
    assert r.status_code == 201, r.text
    pid = r.json()["profile_id"]
    assert r.json()["resultado"] == "inscrito"

    otra_vez = client.post(f"/admin/groups/{esc.grupo_a}/students", headers=esc.h(integ, esc.aa),
                            json={"documento_id": "doc-nuevo-1", "nombre_completo": "OTRO NOMBRE"})
    assert otra_vez.status_code == 200, otra_vez.text
    assert otra_vez.json() == {"profile_id": pid, "documento_id": "doc-nuevo-1",
                                "resultado": "ya_estaba"}
    # BUG-11: el nombre vive en la membresía (A, P), no en `profiles`; y el
    # segundo POST ("OTRO NOMBRE") no lo pisa.
    assert integ.valor("select full_name from profiles where id = :p", p=pid) == ""
    assert integ.valor(
        "select full_name from memberships where tenant_id = :t and profile_id = :p",
        t=esc.tenant_a, p=pid,
    ) == "Ana Nueva"
    assert integ.valor(
        "select count(*) from memberships where tenant_id = :t and profile_id = :p",
        t=esc.tenant_a, p=pid,
    ) == 1

    # Conflicto: E ya está matriculado en GA; a un grupo distinto -> 409.
    grupo_c = integ.crear_grupo(esc.tenant_a, "GC")
    doc_e = integ.fila("select documento_id from profiles where id = :p", p=esc.e)["documento_id"]
    choque = client.post(f"/admin/groups/{grupo_c}/students", headers=esc.h(integ, esc.aa),
                          json={"documento_id": doc_e, "nombre_completo": "x"})
    assert choque.status_code == 409, choque.text

    # Conflicto: DO tiene membresía 'teacher', no 'student' -> 409.
    doc_do = integ.fila("select documento_id from profiles where id = :p",
                        p=esc.do)["documento_id"]
    rol_ajeno = client.post(f"/admin/groups/{esc.grupo_a}/students", headers=esc.h(integ, esc.aa),
                            json={"documento_id": doc_do, "nombre_completo": "x"})
    assert rol_ajeno.status_code == 409, rol_ajeno.text


def test_m3_e_403(integ) -> None:
    esc = armar(integ)
    r = client.post(f"/admin/groups/{esc.grupo_a}/students", headers=esc.h(integ, esc.e),
                     json={"documento_id": "x", "nombre_completo": "x"})
    assert r.status_code == 403, r.text


def test_m3_d_403(integ) -> None:
    esc = armar(integ)
    r = client.post(f"/admin/groups/{esc.grupo_a}/students", headers=esc.h(integ, esc.d),
                     json={"documento_id": "x", "nombre_completo": "x"})
    assert r.status_code == 403, r.text


def test_m3_ab_404(integ) -> None:
    esc = armar(integ)
    r = client.post(f"/admin/groups/{esc.grupo_a}/students", headers=esc.h(integ, esc.ab),
                     json={"documento_id": "SINT-AB-404", "nombre_completo": "x"})
    assert r.status_code == 404, r.text
