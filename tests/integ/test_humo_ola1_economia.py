"""HE1: el humo de la economía de la ola 1 — `docs/ESPEC_ola1_economia.md` §4 y §A.6.

Escenario fijo, sin azar (los números esperados se calcularon en la espec ANTES
del código; la subasta del paso 8 se agregó con la ADENDA 1, también antes de
correr): una institución con bolsa 10.000, un admin, P1 con el 10A y P2 con el
10B, 5 estudiantes por grupo con 50 monedas sembradas por `award_coins`.

Escribe `tests/_salida/humo_ola1_economia.json` (en `.gitignore`) ANTES de afirmar.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from tests.economia_ola1 import _ayuda as ay
from tests.integ_db import RAIZ_BACKEND

pytestmark = pytest.mark.integ

RUTA_HUMO = RAIZ_BACKEND / "tests" / "_salida" / "humo_ola1_economia.json"

HUMO_ESPERADO: dict[str, Any] = {
    "alembic_version": "047_economia_ola1",
    "recargas": 200, "entregas": [8, 130], "correcciones": [1, 5],
    "compras_201": 7, "agotado_409": 1, "sin_saldo_402": 1,
    "entregadas": 5, "devueltas": 2, "pendientes_de_tienda": 0,
    # 10000 − 500 − 200 + 7·40 − 2·40 = 9500, y la subasta del paso 8 suma 15.
    "bolsa": 9515, "bolsillos": [5, 70],
    "saldos_p1": [25, 30, 30, 70, 55], "saldos_p2": [20, 20, 60, 50, 50],
    "conservacion": True, "stock": [7, 0, 1], "saldo_negativo": 0,
    "subasta": {"estado": "cerrada", "ganador_es_el_quinto": True, "puja": 15,
                "mochila_del_ganador": ["devuelto", "por_entregar"]},
}


def _escenario(integ: Any) -> dict[str, Any]:
    e = ay.escuela(integ, n=5, saldo=50)
    total = ay.total(integ, e.tenant)
    recargas = [ay.recargar(integ, e.admin, p, 100).status_code for p in (e.p1, e.p2)]
    entregas = [ay.dar(integ, e.p1, a, 20).json() for a in e.a1]
    entregas += [ay.dar(integ, e.p2, a, 10, motivo="tarea").json() for a in e.a2[:3]]
    ay.corregir(integ, e.p1, entregas[0]["entrega_id"], 5)
    cancion = ay.crear_objeto(integ, e.admin, existencias=10).json()["id"]
    pausa = ay.crear_objeto(integ, e.p1, "Cinco minutos de pausa", existencias=2).json()["id"]
    libreta = ay.crear_objeto(integ, e.p2, "Libreta", precio=120, tipo="fisico",
                              existencias=1).json()["id"]
    compras = [ay.comprar(integ, a, cancion) for a in e.a1]
    compras += [ay.comprar(integ, a, pausa) for a in e.a2[:2]]
    agotado = ay.comprar(integ, e.a2[2], pausa).status_code
    sin_saldo = ay.comprar(integ, e.a2[2], libreta).status_code
    entregadas = [ay.entregar(integ, e.p1, c.json()["id"]).status_code
                  for c in compras[:3] + compras[5:]]
    for c in compras[3:5]:
        ay.envejecer_compra(integ, c.json()["id"], 15)
    pendientes = ay.leer(integ, e.p1, f"/economia/grupo/{e.g1}/mochila").json()
    s = ay.crear_subasta(integ, e.p1, e.g1, titulo="Ser capitán de la clase").json()["id"]
    ay.pujar(integ, e.a1[3], s, 10)
    ay.pujar(integ, e.a1[4], s, 15)
    cerrada = ay.client.post(f"/subastas/{s}/cerrar", headers=integ.headers(e.p1)).json()
    mochila = ay.leer(integ, e.a1[4], "/economia/mochila").json()
    return {"e": e, "total": total, "recargas": recargas, "entregas": entregas,
            "compras": compras, "agotado": agotado, "sin_saldo": sin_saldo,
            "entregadas": entregadas, "pendientes": pendientes, "cerrada": cerrada,
            "mochila": mochila, "objetos": (cancion, pausa, libreta)}


def test_he1_humo_ola1_economia(integ) -> None:
    v = _escenario(integ)
    e = v["e"]
    datos = {
        "alembic_version": integ.valor("select version_num from alembic_version"),
        "recargas": 100 * sum(1 for c in v["recargas"] if c == 201),
        "entregas": [len(v["entregas"]), sum(x["monto"] for x in v["entregas"])],
        "correcciones": [ay.filas(integ, "teacher_reversal", e.tenant),
                         int(integ.valor("select coalesce(sum(amount), 0) from coin_ledger "
                                         "where action = 'teacher_reversal'"))],
        "compras_201": sum(1 for c in v["compras"] if c.status_code == 201),
        "agotado_409": int(v["agotado"] == 409), "sin_saldo_402": int(v["sin_saldo"] == 402),
        "entregadas": sum(1 for c in v["entregadas"] if c == 200),
        "devueltas": ay.filas(integ, "shop_refund", e.tenant),
        "pendientes_de_tienda": sum(1 for i in v["pendientes"]
                                    if i["estado"] == "por_entregar" and i["origen"] == "tienda"),
        "bolsa": ay.bolsa(integ, e.tenant),
        "bolsillos": [ay.bolsillo(integ, e.tenant, p) for p in (e.p1, e.p2)],
        "saldos_p1": [ay.saldo(integ, a) for a in e.a1],
        "saldos_p2": [ay.saldo(integ, a) for a in e.a2],
        "conservacion": ay.total(integ, e.tenant) == v["total"],
        "stock": [ay.stock(integ, o) for o in v["objetos"]],
        "saldo_negativo": int(integ.valor("select count(*) from coin_wallets where balance < 0")),
        "subasta": {"estado": v["cerrada"]["estado"],
                    "ganador_es_el_quinto": v["cerrada"]["ganador_id"] == str(e.a1[4]),
                    "puja": v["cerrada"]["puja_actual"],
                    "mochila_del_ganador": sorted(i["estado"] for i in v["mochila"])},
    }
    RUTA_HUMO.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO.write_text(json.dumps(datos, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    assert datos == HUMO_ESPERADO, f"HE1: {datos}"
