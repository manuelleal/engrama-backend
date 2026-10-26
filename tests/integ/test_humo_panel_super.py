"""Humo del panel del super admin — docs/ESPEC_panel_super_admin.md §3.

Siembra A y B (semilla fija de `tests/panel/_siembra.py`), llama las tres rutas
y escribe `tests/_salida/humo_panel_super.json` (en `.gitignore`): SOLO códigos
neutros y cifras, nunca el nombre de un tenant. Afirma que el archivo existe y
dice exactamente lo esperado.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.integ_db import RAIZ_BACKEND
from tests.panel import _siembra as sb

pytestmark = pytest.mark.integ
client = TestClient(app)

RUTA = RAIZ_BACKEND / "tests" / "_salida" / "humo_panel_super.json"


def test_humo_panel_super_escribe_su_archivo(integ, monkeypatch) -> None:
    s, a, _b = sb.sembrar(integ, monkeypatch)
    sup = integ.headers(sb.super_admin(s))
    lista = client.get("/super/clientes", headers=sup)
    detalle = client.get(f"/super/clientes/{a.id}", headers=sup)
    admin = client.get("/admin/metricas", headers=integ.headers(a.personas["admin"]))
    salida: dict[str, Any] = {
        "estados": [lista.status_code, detalle.status_code, admin.status_code],
        "clientes": {c["codigo"]: c["metricas"] for c in lista.json()["clientes"]},
        "totales": lista.json()["totales"],
        "detalle_dias": len(detalle.json()["registros_por_dia"]),
        "detalle_semanas": len(detalle.json()["monedas_por_semana"]),
        "admin": admin.json()["metricas"],
    }
    RUTA.parent.mkdir(parents=True, exist_ok=True)
    RUTA.write_text(json.dumps(salida, ensure_ascii=False, indent=1, sort_keys=True),
                    encoding="utf-8")
    leido = json.loads(RUTA.read_text(encoding="utf-8"))
    assert leido["estados"] == [200, 200, 200], leido["estados"]
    assert leido["clientes"] == {"Cliente 01": sb.ESPERADO_A, "Cliente 02": sb.ESPERADO_B}
    assert leido["admin"] == sb.ESPERADO_A
    assert (leido["detalle_dias"], leido["detalle_semanas"]) == (30, 8)
    texto = RUTA.read_text(encoding="utf-8")
    assert sb.NOMBRE_A not in texto and sb.NOMBRE_B not in texto
