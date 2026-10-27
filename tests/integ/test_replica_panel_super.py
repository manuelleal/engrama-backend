"""Réplica del panel con entradas nuevas — docs/ESPEC_panel_super_admin.md §3.

Tres clientes con OTRA semilla (20261027) y cifras que no se usaron al desarrollar.
Lo esperado se calcula aquí con un modelo propio y simple (cada persona, cada
flujo de monedas con su efecto), sin llamar al código del panel; después se
compara con lo que dicen las rutas: PS1 (super), AM1 (cada admin) y AM4 (sin nombre).
Escribe `tests/_salida/replica_panel_super.json`.
"""
from __future__ import annotations

import json
import random
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.integ_db import RAIZ_BACKEND
from tests.panel import _siembra as sb

pytestmark = pytest.mark.integ
client = TestClient(app)
RUTA = RAIZ_BACKEND / "tests" / "_salida" / "replica_panel_super.json"
SEMILLA = 20261027

# Flujo de monedas -> (origen, destino, acción, Δ emitidas, Δ gastadas) por cada moneda.
FLUJOS = {
    "reto": ("bolsa", "alumno", "challenge", 1, 0),
    "dar": ("bolsillo", "alumno", "teacher_award", 1, 0),
    "corregir": ("alumno", "bolsillo", "teacher_reversal", -1, 0),
    "comprar": ("alumno", "bolsa", "shop_purchase", 0, 1),
    "devolver": ("bolsa", "alumno", "shop_refund", 0, -1),
    "retener": ("alumno", "puja", "auction_hold", 0, 0),
    "liquidar": ("puja", "bolsa", "auction_settle", 0, 1),
    "reembolsar": ("puja", "alumno", "auction_refund", 0, 0),
    "recargar": (None, "bolsa", "pool_topup", 0, 0),
    "presupuesto": ("bolsa", "bolsillo", "budget_allocation", 0, 0),
}


def _sembrar_uno(s: sb.Sembrador, rnd: random.Random, i: int) -> tuple[Any, dict[str, Any]]:
    ah = s.ahora
    bolsa = rnd.randint(100, 9000)
    c = s.tenant(f"Cliente real numero {i} SA", creado_hace=timedelta(days=200 - i), bolsa=bolsa)
    s.miembro(c, "admin", "admin", creado=sb.en_dia_local(ah, 50))
    profes = rnd.randint(1, 4)
    for k in range(profes):
        s.miembro(c, f"p{k}", "teacher", creado=sb.en_dia_local(ah, 50))
    grupos = rnd.randint(1, 3)
    for k in range(grupos):
        s.grupo(c, f"R{i}-{k}")
    estudiantes = activos = registros = 0
    for k in range(rnd.randint(3, 9)):
        dias, activo = rnd.randint(0, 45), rnd.random() > 0.2
        pid = s.miembro(c, f"e{k}", "student", creado=sb.en_dia_local(ah, dias), activo=activo)
        estudiantes += activo
        registros += dias <= 29
        horas = rnd.choice([1, 30, 100, 160, 170, 400])
        if rnd.random() > 0.3:
            s.intento(c, pid, ah - timedelta(hours=horas))
            activos += activo and horas < 168
    s.billetera(c, "alumno", "profile", c.personas["e0"])
    s.billetera(c, "bolsillo", "membership", c.billeteras["m:p0"])
    s.billetera(c, "puja", "auction", c.id)
    emitidas = gastadas = 0
    for _ in range(rnd.randint(5, 15)):
        nombre = rnd.choice(list(FLUJOS))
        desde, hacia, accion, de, dg = FLUJOS[nombre]
        monto = rnd.randint(1, 50)
        s.asiento(c, desde, hacia, monto, accion, ah - timedelta(days=rnd.randint(0, 80)))
        emitidas, gastadas = emitidas + de * monto, gastadas + dg * monto
    return c, {"profes": profes, "admins": 1, "grupos": grupos, "estudiantes": estudiantes,
               "activos_7d": activos, "registros_30d": registros,
               "monedas": {"bolsa": bolsa, "emitidas": emitidas, "gastadas": gastadas}}


def test_replica_panel_super_con_tres_clientes_nuevos(integ, monkeypatch) -> None:
    s = sb.Sembrador(integ, sb.fijar_reloj(monkeypatch))
    rnd = random.Random(SEMILLA)
    clientes = [_sembrar_uno(s, rnd, i) for i in range(1, 4)]
    lista = client.get("/super/clientes", headers=integ.headers(sb.super_admin(s))).json()
    vistos_super = {c["codigo"]: c["metricas"] for c in lista["clientes"]}
    esperados = {f"Cliente {i:02d}": e for i, (_c, e) in enumerate(clientes, start=1)}
    vistos_admin: dict[str, Any] = {}
    nombres_filtrados: list[str] = []
    for i, (c, _e) in enumerate(clientes, start=1):
        r = client.get("/admin/metricas", headers=integ.headers(c.personas["admin"]))
        vistos_admin[f"Cliente {i:02d}"] = r.json()["metricas"]
        nombres_filtrados += [o.nombre for o, _ in clientes if o.nombre in r.text]
    RUTA.parent.mkdir(parents=True, exist_ok=True)
    RUTA.write_text(json.dumps({"esperados": esperados, "super": vistos_super,
                                "admin": vistos_admin}, indent=1, sort_keys=True),
                    encoding="utf-8")
    assert vistos_super == esperados, f"réplica PS1: {vistos_super} != {esperados}"
    assert vistos_admin == esperados, f"réplica AM1: {vistos_admin}"
    assert nombres_filtrados == [], f"réplica AM4: {nombres_filtrados}"
