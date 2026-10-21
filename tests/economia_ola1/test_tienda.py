"""Las reglas de plata de la tienda y la mochila — ESPEC_ola1_economia §A.6 (modo rápido)."""
from __future__ import annotations

import pytest

from tests.economia_ola1 import _ayuda as ay

pytestmark = pytest.mark.integ


def test_oe11_12_sin_saldo_y_sin_existencias(integ) -> None:
    e = ay.escuela(integ, n=2, saldo=40)
    objeto = ay.crear_objeto(integ, e.admin, existencias=1).json()["id"]
    caro = ay.crear_objeto(integ, e.admin, "Libreta", precio=120, tipo="fisico").json()["id"]
    observado = {
        "sin_saldo": ay.comprar(integ, e.a1[0], caro).status_code,
        "primera": ay.comprar(integ, e.a1[0], objeto).status_code,
        "agotado": ay.comprar(integ, e.a1[1], objeto).status_code,
        "stock": ay.stock(integ, objeto), "stock_caro": ay.stock(integ, caro),
        "saldos": [ay.saldo(integ, e.a1[0]), ay.saldo(integ, e.a1[1])],
        "profe_compra": ay.comprar(integ, e.p1, objeto).status_code,
    }
    assert observado == {"sin_saldo": 402, "primera": 201, "agotado": 409, "stock": 0,
                         "stock_caro": 10, "saldos": [0, 40], "profe_compra": 403}, (
        f"OE11-12: {observado}")


def test_oe13_la_compra_vuelve_a_la_bolsa(integ) -> None:
    e = ay.escuela(integ, n=1, saldo=50)
    objeto = ay.crear_objeto(integ, e.p1).json()["id"]
    antes = {"bolsa": ay.bolsa(integ, e.tenant), "total": ay.total(integ, e.tenant)}
    r = ay.comprar(integ, e.a1[0], objeto, llave="compra-0001")
    repetida = ay.comprar(integ, e.a1[0], objeto, llave="compra-0001")
    observado = {
        "estados": [r.status_code, repetida.status_code],
        "bolsa_sube": ay.bolsa(integ, e.tenant) - antes["bolsa"],
        "saldo": ay.saldo(integ, e.a1[0]),
        "conservacion": ay.total(integ, e.tenant) == antes["total"],
        "mochila": [(i["estado"], i["precio_pagado"], i["origen"])
                    for i in ay.leer(integ, e.a1[0], "/economia/mochila").json()],
    }
    assert observado == {"estados": [201, 200], "bolsa_sube": 40, "saldo": 10,
                         "conservacion": True,
                         "mochila": [("por_entregar", 40, "tienda")]}, f"OE13: {observado}"


def test_oe14_devolucion_a_los_14_dias_una_sola_vez(integ) -> None:
    e = ay.escuela(integ, n=2, saldo=40)
    objeto = ay.crear_objeto(integ, e.admin, existencias=5).json()["id"]
    vieja = ay.comprar(integ, e.a1[0], objeto).json()["id"]
    reciente = ay.comprar(integ, e.a1[1], objeto).json()["id"]
    ay.envejecer_compra(integ, vieja, 15)
    ay.envejecer_compra(integ, reciente, 13)
    primera = ay.leer(integ, e.a1[0], "/economia/mochila").json()
    segunda = ay.leer(integ, e.a1[0], "/economia/mochila").json()
    ay.leer(integ, e.p1, f"/economia/grupo/{e.g1}/mochila")
    observado = {
        "vieja": [i["estado"] for i in primera], "otra_vez": [i["estado"] for i in segunda],
        "saldo_devuelto": ay.saldo(integ, e.a1[0]),
        "devoluciones": ay.filas(integ, "shop_refund", e.tenant),
        "reciente_sigue": ay.leer(integ, e.a1[1], "/economia/mochila").json()[0]["estado"],
        "stock": ay.stock(integ, objeto),
        "entregar_vencida": ay.entregar(integ, e.admin, vieja).status_code,
        "entregar_reciente": ay.entregar(integ, e.p1, reciente).status_code,
    }
    assert observado == {"vieja": ["devuelto"], "otra_vez": ["devuelto"], "saldo_devuelto": 40,
                         "devoluciones": 1, "reciente_sigue": "por_entregar", "stock": 4,
                         "entregar_vencida": 409, "entregar_reciente": 200}, f"OE14: {observado}"


def test_oe15b_aislamiento_de_la_tienda(integ) -> None:
    t1 = ay.escuela(integ, n=1, saldo=100)
    t2 = ay.escuela(integ, n=1, saldo=100)
    objeto = ay.crear_objeto(integ, t1.admin).json()["id"]
    compra = ay.comprar(integ, t1.a1[0], objeto).json()["id"]
    observado = {
        "compra_ajena": ay.comprar(integ, t2.a1[0], objeto).status_code,
        "vitrina_t2": ay.leer(integ, t2.a1[0], "/economia/tienda").json(),
        "catalogo_t2": ay.leer(integ, t2.admin, "/economia/tienda").json(),
        "entregar_ajena": ay.entregar(integ, t2.admin, compra).status_code,
        "mochila_grupo_ajeno": ay.leer(integ, t2.p1,
                                       f"/economia/grupo/{t1.g1}/mochila").status_code,
        "saldo_t2": ay.saldo(integ, t2.a1[0]),
    }
    assert observado == {"compra_ajena": 404, "vitrina_t2": [], "catalogo_t2": [],
                         "entregar_ajena": 404, "mochila_grupo_ajeno": 404,
                         "saldo_t2": 100}, f"OE15b: {observado}"


def test_oe16_17_nada_academico_y_solo_escalones(integ) -> None:
    e = ay.escuela(integ, n=1)
    observado = {
        "examen": ay.crear_objeto(integ, e.p1, "+1 punto en el examen").status_code,
        "nota": ay.crear_objeto(integ, e.p1, "Subir la nota").status_code,
        "precio_50": ay.crear_objeto(integ, e.p1, precio=50).status_code,
        "tipo_nota": ay.crear_objeto(integ, e.p1, tipo="nota").status_code,
        "bueno": ay.crear_objeto(integ, e.p1, precio=600).status_code,
        "estudiante_crea": ay.crear_objeto(integ, e.a1[0]).status_code,
    }
    assert observado == {"examen": 422, "nota": 422, "precio_50": 422, "tipo_nota": 422,
                         "bueno": 201, "estudiante_crea": 403}, f"OE16-17: {observado}"
