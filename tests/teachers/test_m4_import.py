"""F10, F11 y las celdas de M4 — ESPEC §2, §3: `POST /admin/groups/{gid}/students/import`.

F11 es también el test real de X8 ("CSV escribe antes de fallar", §3): una
fila válida seguida de una inválida no debe dejar NINGÚN perfil nuevo, ni
siquiera el de la fila válida.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.teachers._actores import armar

pytestmark = pytest.mark.integ
client = TestClient(app)


def test_f10_import_valido_es_idempotente(integ) -> None:
    """F10: 3 filas nuevas -> creados=3; reimportar el MISMO archivo -> creados=0."""
    esc = armar(integ)
    csv_texto = "documento_id,nombre_completo\ndoc-a,Ana\ndoc-b,Beto\ndoc-c,Caro\n"
    r = client.post(f"/admin/groups/{esc.grupo_a}/students/import",
                     headers={**esc.h(integ, esc.aa), "Content-Type": "text/csv"},
                     content=csv_texto.encode("utf-8"))
    assert r.status_code == 201, r.text
    assert r.json() == {"creados": 3, "ya_estaban": 0, "total": 3}
    assert integ.valor(
        "select count(*) from memberships where tenant_id = :t and group_code = :g",
        t=esc.tenant_a, g=esc.codigo_a,
    ) == 4  # 3 nuevos + E, ya matriculado por `armar`

    otra_vez = client.post(f"/admin/groups/{esc.grupo_a}/students/import",
                            headers={**esc.h(integ, esc.aa), "Content-Type": "text/csv"},
                            content=csv_texto.encode("utf-8"))
    assert otra_vez.status_code == 201, otra_vez.text
    assert otra_vez.json() == {"creados": 0, "ya_estaban": 3, "total": 3}


def test_f11_import_invalido_no_escribe_nada(integ) -> None:
    """F11/X8: fila 1 válida + fila 2 inválida -> 422, y la fila 1 NO se creó."""
    esc = armar(integ)
    csv_texto = "documento_id,nombre_completo\ndoc-valida,Ana\nmal!,\n"
    r = client.post(f"/admin/groups/{esc.grupo_a}/students/import",
                     headers={**esc.h(integ, esc.aa), "Content-Type": "text/csv"},
                     content=csv_texto.encode("utf-8"))
    assert r.status_code == 422, r.text
    assert r.json() == [
        {"fila": 2, "motivo": "documento_id inválido: 'mal!'"},
    ]
    assert integ.valor(
        "select count(*) from profiles where documento_id = 'doc-valida'"
    ) == 0, "la fila válida se escribió aunque otra fila del archivo falló"


def test_m4_e_403(integ) -> None:
    esc = armar(integ)
    r = client.post(f"/admin/groups/{esc.grupo_a}/students/import",
                     headers={**esc.h(integ, esc.e), "Content-Type": "text/csv"},
                     content=b"documento_id,nombre_completo\n")
    assert r.status_code == 403, r.text


def test_m4_d_403(integ) -> None:
    esc = armar(integ)
    r = client.post(f"/admin/groups/{esc.grupo_a}/students/import",
                     headers={**esc.h(integ, esc.d), "Content-Type": "text/csv"},
                     content=b"documento_id,nombre_completo\n")
    assert r.status_code == 403, r.text


def test_m4_ab_404(integ) -> None:
    esc = armar(integ)
    r = client.post(f"/admin/groups/{esc.grupo_a}/students/import",
                     headers={**esc.h(integ, esc.ab), "Content-Type": "text/csv"},
                     content=b"documento_id,nombre_completo\n")
    assert r.status_code == 404, r.text
