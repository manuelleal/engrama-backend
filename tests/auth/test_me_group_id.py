"""`/auth/me` trae el `group_id` de cada membresía (sprint de la economía, decisión 017).

El estudiante solo conoce su `group_code`; con el `group_id` en su propia membresía puede
pedir lo que pide un UUID. Se resuelve DENTRO del tenant de cada membresía: dos instituciones
con un grupo "10A" no se mezclan. Quien no tiene grupo (profe, admin) recibe None.
"""
from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.economia_ola1 import _ayuda as ay

pytestmark = pytest.mark.integ
client = TestClient(app, raise_server_exceptions=False)


def _membresias(integ, quien: UUID) -> list[dict]:  # type: ignore[no-untyped-def]
    r = client.get("/auth/me", headers=integ.headers(quien))
    assert r.status_code == 200, r.text
    return r.json()["memberships"]


def test_me1_group_id_en_la_membresia(integ) -> None:
    e = ay.escuela(integ, n=1)
    otra = ay.escuela(integ, n=1)  # su "10A" es OTRO grupo
    observado = {
        "estudiante": [(m["group_code"], m["group_id"]) for m in _membresias(integ, e.a1[0])],
        "estudiante_b": [(m["group_code"], m["group_id"]) for m in _membresias(integ, e.a2[0])],
        "otra_institucion": [m["group_id"] for m in _membresias(integ, otra.a1[0])],
        "profe": [m["group_id"] for m in _membresias(integ, e.p1)],
        "admin": [m["group_id"] for m in _membresias(integ, e.admin)],
    }
    assert observado == {
        "estudiante": [("10A", str(e.g1))], "estudiante_b": [("10B", str(e.g2))],
        "otra_institucion": [str(otra.g1)], "profe": [None], "admin": [None],
    }, f"ME1: {observado}"
