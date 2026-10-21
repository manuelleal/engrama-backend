"""Las reglas de plata de la subasta — ESPEC_ola1_economia §A.5-§A.6 (modo rápido).

El tiempo se simula moviendo `auctions.ends_at` en la base (`ay.vencer_subasta`).
"""
from __future__ import annotations

import pytest

from tests.economia_ola1 import _ayuda as ay

pytestmark = pytest.mark.integ


def _retenido(integ, subasta: str) -> int:  # type: ignore[no-untyped-def]
    from uuid import UUID
    v = integ.valor("select balance from coin_wallets where owner_type = 'auction' "
                    "and owner_id = :i", i=UUID(subasta))
    return 0 if v is None else int(v)


def test_sb1_retencion_y_devolucion_al_superado(integ) -> None:
    e = ay.escuela(integ, n=2, saldo=100)
    total = ay.total(integ, e.tenant)
    s = ay.crear_subasta(integ, e.p1, e.g1, minima=10).json()["id"]
    pasos = []
    for alumno, monto in ((e.a1[0], 10), (e.a1[1], 15), (e.a1[1], 25)):
        r = ay.pujar(integ, alumno, s, monto)
        pasos.append((r.status_code, ay.saldo(integ, e.a1[0]), ay.saldo(integ, e.a1[1]),
                      _retenido(integ, s)))
    observado = {"pasos": pasos, "conservacion": ay.total(integ, e.tenant) == total,
                 "lider": ay.leer(integ, e.a1[0], f"/subastas/activa?grupo={e.g1}")
                 .json()["lider_id"] == str(e.a1[1])}
    assert observado == {
        "pasos": [(200, 90, 100, 10),   # A retiene 10
                  (200, 100, 85, 15),   # B supera: a A se le devuelve todo al instante
                  (200, 100, 75, 25)],  # B sube su propia puja: solo la diferencia
        "conservacion": True, "lider": True}, f"SB1: {observado}"


def test_sb2_minima_incrementos_y_saldo(integ) -> None:
    e = ay.escuela(integ, n=2)
    ay.sembrar(integ, e.tenant, e.a1[0], 100)
    ay.sembrar(integ, e.tenant, e.a1[1], 12)
    s = ay.crear_subasta(integ, e.p1, e.g1, minima=10).json()["id"]
    observado = {
        "bajo_la_minima": ay.pujar(integ, e.a1[0], s, 5).status_code,
        "primera": ay.pujar(integ, e.a1[1], s, 10).status_code,
        "sube_2": ay.pujar(integ, e.a1[0], s, 12).status_code,
        "sube_5": ay.pujar(integ, e.a1[0], s, 15).status_code,
        "sin_saldo": ay.pujar(integ, e.a1[1], s, 20).status_code,
        "saldos": [ay.saldo(integ, e.a1[0]), ay.saldo(integ, e.a1[1])],
        "segunda_activa": ay.crear_subasta(integ, e.p1, e.g1).status_code,
    }
    assert observado == {"bajo_la_minima": 409, "primera": 200, "sube_2": 409, "sube_5": 200,
                         "sin_saldo": 402, "saldos": [85, 12],
                         "segunda_activa": 409}, f"SB2: {observado}"


def test_sb3_extension_de_10_s_maximo_3(integ) -> None:
    e = ay.escuela(integ, n=2, saldo=200)
    s = ay.crear_subasta(integ, e.p1, e.g1, minima=10).json()["id"]
    ay.pujar(integ, e.a1[0], s, 10)  # con 90 s por delante: no extiende
    vistos = []
    monto = 10
    for i in range(4):
        ay.vencer_subasta(integ, s, en_segundos=5)
        monto += 5
        r = ay.pujar(integ, e.a1[(i + 1) % 2], s, monto)
        vistos.append((r.status_code, r.json()["extensiones"], r.json()["segundos_restantes"]))
    observado = {"vistos": [(c, x, q > 10) for c, x, q in vistos]}
    assert observado == {"vistos": [(200, 1, True), (200, 2, True), (200, 3, True),
                                    (200, 3, False)]}, f"SB3: {observado} {vistos}"


def test_sb4_cierre_a_la_bolsa_y_a_la_mochila(integ) -> None:
    e = ay.escuela(integ, n=2, saldo=100)
    total = ay.total(integ, e.tenant)
    s = ay.crear_subasta(integ, e.p1, e.g1, titulo="Ser capitán de la clase").json()["id"]
    ay.pujar(integ, e.a1[0], s, 10)
    ay.pujar(integ, e.a1[1], s, 20)
    bolsa_antes = ay.bolsa(integ, e.tenant)
    ay.vencer_subasta(integ, s)
    cerrada = ay.leer(integ, e.a1[0], f"/subastas/activa?grupo={e.g1}").json()
    mochila = ay.leer(integ, e.a1[1], "/economia/mochila").json()
    # Sin pujas: un objeto de la tienda reservado vuelve a la tienda y nada se mueve.
    objeto = ay.crear_objeto(integ, e.p2, existencias=3).json()["id"]
    s2 = ay.crear_subasta(integ, e.p2, e.g2, objeto=objeto).json()["id"]
    reservado = ay.stock(integ, objeto)
    sin_pujas = ay.client.post(f"/subastas/{s2}/cerrar", headers=integ.headers(e.p2)).json()
    observado = {
        "estado": cerrada["estado"], "ganador": cerrada["ganador_id"] == str(e.a1[1]),
        "bolsa_sube": ay.bolsa(integ, e.tenant) - bolsa_antes, "retenido": _retenido(integ, s),
        "saldos": [ay.saldo(integ, e.a1[0]), ay.saldo(integ, e.a1[1])],
        "mochila": [(i["nombre"], i["origen"], i["precio_pagado"], i["estado"]) for i in mochila],
        "conservacion": ay.total(integ, e.tenant) == total,
        "sin_pujas": (sin_pujas["estado"], sin_pujas["ganador_id"], reservado,
                      ay.stock(integ, objeto)),
        "pujar_cerrada": ay.pujar(integ, e.a1[0], s, 25).status_code,
    }
    assert observado == {
        "estado": "cerrada", "ganador": True, "bolsa_sube": 20, "retenido": 0,
        "saldos": [100, 80],
        "mochila": [("Ser capitán de la clase", "subasta", 20, "por_entregar")],
        "conservacion": True, "sin_pujas": ("cerrada", None, 2, 3), "pujar_cerrada": 409,
    }, f"SB4: {observado}"


def test_sb5_aislamiento_de_la_subasta(integ) -> None:
    e = ay.escuela(integ, n=1, saldo=100)
    otra = ay.escuela(integ, n=1, saldo=100)
    s = ay.crear_subasta(integ, e.p1, e.g1).json()["id"]
    observado = {
        "otro_grupo_puja": ay.pujar(integ, e.a2[0], s, 10).status_code,
        "otro_grupo_mira": ay.leer(integ, e.a2[0], f"/subastas/activa?grupo={e.g1}").status_code,
        "otra_institucion_puja": ay.pujar(integ, otra.a1[0], s, 10).status_code,
        "profe_ajeno_crea": ay.crear_subasta(integ, e.p2, e.g1).status_code,
        "profe_ajeno_cierra": ay.client.post(f"/subastas/{s}/cerrar",
                                             headers=integ.headers(e.p2)).status_code,
        "saldos": [ay.saldo(integ, e.a2[0]), ay.saldo(integ, otra.a1[0])],
    }
    assert observado == {"otro_grupo_puja": 404, "otro_grupo_mira": 404,
                         "otra_institucion_puja": 404, "profe_ajeno_crea": 404,
                         "profe_ajeno_cierra": 404, "saldos": [100, 100]}, f"SB5: {observado}"
