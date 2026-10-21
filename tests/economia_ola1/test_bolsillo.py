"""Las reglas de plata del bolsillo (Dar, Corregir, presupuesto) — ESPEC_ola1_economia §A.6.

Modo rápido (decisión 017): una prueba por regla de plata, cada una con un
`observado` que nombra lo medido para que su tramposo
(`tests/tramposos/test_tramposos_ola1_economia.py`) la ponga roja con un mensaje
reconocible.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from src.bolsillo import consultas
from tests.economia_ola1 import _ayuda as ay

pytestmark = pytest.mark.integ


def test_oe1_tope_por_entrega(integ) -> None:
    e = ay.escuela(integ, n=1)
    ay.recargar(integ, e.admin, e.p1, 100)
    r21 = ay.dar(integ, e.p1, e.a1[0], 21)
    saldo_tras_21 = ay.saldo(integ, e.a1[0])
    r20 = ay.dar(integ, e.p1, e.a1[0], 20)
    observado = {"21": r21.status_code, "saldo_tras_21": saldo_tras_21, "20": r20.status_code,
                 "saldo": ay.saldo(integ, e.a1[0]), "mensaje_21": "1 a 20" in ay.detalle(r21)}
    assert observado == {"21": 422, "saldo_tras_21": 0, "20": 201, "saldo": 20,
                         "mensaje_21": True}, f"OE1: {observado}"


def test_oe2_tope_semanal_entre_dos_profes(integ) -> None:
    """P1 y el admin (que ve todos los grupos) dan 20 cada uno; 1 más ya no entra."""
    e = ay.escuela(integ, n=1)
    ay.recargar(integ, e.admin, e.p1, 100)
    ay.recargar(integ, e.admin, e.admin, 100)
    pasada = ay.dar(integ, e.p1, e.a1[0], 20).json()["entrega_id"]
    # Al domingo anterior (un minuto antes del lunes local): no cuenta en esta semana.
    ay.mover_entrega_a(integ, pasada, consultas.lunes_actual() - timedelta(minutes=1))
    estados = [ay.dar(integ, e.p1, e.a1[0], 20).status_code,
               ay.dar(integ, e.admin, e.a1[0], 20).status_code]
    tercero = ay.dar(integ, e.p1, e.a1[0], 1)
    observado = {"estados": estados, "tercero": tercero.status_code,
                 "saldo": ay.saldo(integ, e.a1[0])}
    assert observado == {"estados": [201, 201], "tercero": 409, "saldo": 60}, f"OE2: {observado}"


def test_oe3_presupuesto_insuficiente(integ) -> None:
    e = ay.escuela(integ, n=1)
    ay.recargar(integ, e.admin, e.p1, 15)
    r16 = ay.dar(integ, e.p1, e.a1[0], 16)
    observado = {"16": r16.status_code, "bolsillo": ay.bolsillo(integ, e.tenant, e.p1),
                 "saldo": ay.saldo(integ, e.a1[0]),
                 "15": ay.dar(integ, e.p1, e.a1[0], 15).status_code,
                 "bolsillo_final": ay.bolsillo(integ, e.tenant, e.p1)}
    assert observado == {"16": 402, "bolsillo": 15, "saldo": 0, "15": 201,
                         "bolsillo_final": 0}, f"OE3: {observado}"


def test_oe4_profe_sin_el_grupo_del_estudiante(integ) -> None:
    """P2 no tiene el 10A: no le da a un estudiante de P1 (404, no delata)."""
    e = ay.escuela(integ, n=1)
    ay.recargar(integ, e.admin, e.p2, 100)
    r = ay.dar(integ, e.p2, e.a1[0], 5)
    estudiante = ay.dar(integ, e.a1[0], e.a1[0], 5)
    observado = {"p2_al_10A": r.status_code, "estudiante_da": estudiante.status_code,
                 "saldo": ay.saldo(integ, e.a1[0])}
    assert observado == {"p2_al_10A": 404, "estudiante_da": 403, "saldo": 0}, f"OE4: {observado}"


def test_oe5_corregir_lo_ya_gastado_no_deja_negativo(integ) -> None:
    e = ay.escuela(integ, n=1)
    ay.recargar(integ, e.admin, e.p1, 100)
    entrega = ay.dar(integ, e.p1, e.a1[0], 20).json()["entrega_id"]
    ay.sembrar(integ, e.tenant, e.a1[0], 20)  # 40 en total
    objeto = ay.crear_objeto(integ, e.p1, precio=40).json()["id"]
    compra = ay.comprar(integ, e.a1[0], objeto).status_code  # queda en 0
    r = ay.corregir(integ, e.p1, entrega, 20)
    observado = {"compra": compra, "corregir": r.status_code,
                 "saldo": ay.saldo(integ, e.a1[0]),
                 "dice_que_gasto": "ya gastó" in ay.detalle(r)}
    assert observado == {"compra": 201, "corregir": 409, "saldo": 0,
                         "dice_que_gasto": True}, f"OE5: {observado}"


def test_oe6_corregir_solo_14_dias(integ) -> None:
    e = ay.escuela(integ, n=1)
    ay.recargar(integ, e.admin, e.p1, 100)
    vieja = ay.dar(integ, e.p1, e.a1[0], 10).json()["entrega_id"]
    nueva = ay.dar(integ, e.p1, e.a1[0], 10).json()["entrega_id"]
    ay.envejecer_entrega(integ, vieja, 15)
    ay.envejecer_entrega(integ, nueva, 13)
    observado = {"15_dias": ay.corregir(integ, e.p1, vieja).status_code,
                 "13_dias": ay.corregir(integ, e.p1, nueva).status_code,
                 "saldo": ay.saldo(integ, e.a1[0]),
                 "bolsillo": ay.bolsillo(integ, e.tenant, e.p1)}
    assert observado == {"15_dias": 409, "13_dias": 201, "saldo": 10,
                         "bolsillo": 90}, f"OE6: {observado}"


def test_oe7_corregir_hasta_el_original_y_solo_lo_propio(integ) -> None:
    e = ay.escuela(integ, n=1)
    ay.recargar(integ, e.admin, e.p1, 100)
    entrega = ay.dar(integ, e.p1, e.a1[0], 15).json()["entrega_id"]
    observado = {"admin_corrige_ajena": ay.corregir(integ, e.admin, entrega, 5).status_code,
                 "10": ay.corregir(integ, e.p1, entrega, 10).status_code,
                 "6": ay.corregir(integ, e.p1, entrega, 6).status_code,
                 "5": ay.corregir(integ, e.p1, entrega, 5).status_code,
                 "1": ay.corregir(integ, e.p1, entrega, 1).status_code,
                 "saldo": ay.saldo(integ, e.a1[0])}
    assert observado == {"admin_corrige_ajena": 404, "10": 201, "6": 409, "5": 201, "1": 409,
                         "saldo": 0}, f"OE7: {observado}"


def test_oe9_misma_llave_paga_una_vez(integ) -> None:
    e = ay.escuela(integ, n=1)
    ay.recargar(integ, e.admin, e.p1, 100)
    r1 = ay.dar(integ, e.p1, e.a1[0], 10, llave="toque-0001")
    r2 = ay.dar(integ, e.p1, e.a1[0], 10, llave="toque-0001")
    otro = ay.dar(integ, e.p1, e.a1[0], 12, llave="toque-0001")
    observado = {"estados": [r1.status_code, r2.status_code, otro.status_code],
                 "mismo_id": r1.json()["entrega_id"] == r2.json()["entrega_id"],
                 "filas": ay.filas(integ, "teacher_award", e.tenant),
                 "saldo": ay.saldo(integ, e.a1[0])}
    assert observado == {"estados": [201, 200, 409], "mismo_id": True, "filas": 1,
                         "saldo": 10}, f"OE9: {observado}"


def test_oe10_recarga_semanal_con_tope(integ) -> None:
    e = ay.escuela(integ, pool=150, n=1)
    observado = {
        "100": ay.recargar(integ, e.admin, e.p1, 100).status_code,
        "1_mas": ay.recargar(integ, e.admin, e.p1, 1).status_code,
        "profe_recarga": ay.recargar(integ, e.p1, e.p2, 10).status_code,
        "bolsa_no_alcanza": ay.recargar(integ, e.admin, e.p2, 60).status_code,
        "devolver_de_mas": ay.recargar(integ, e.admin, e.p1, 101, devolver=True).status_code,
        "bolsa": ay.bolsa(integ, e.tenant), "bolsillo": ay.bolsillo(integ, e.tenant, e.p1),
    }
    assert observado == {"100": 201, "1_mas": 409, "profe_recarga": 403,
                         "bolsa_no_alcanza": 402, "devolver_de_mas": 409, "bolsa": 50,
                         "bolsillo": 100}, f"OE10: {observado}"


def test_oe15a_aislamiento_del_bolsillo(integ) -> None:
    """El admin y el profe de T2 no tocan nada de T1: todo 404 o vacío."""
    t1 = ay.escuela(integ, n=1)
    t2 = ay.escuela(integ, n=1)
    ay.recargar(integ, t1.admin, t1.p1, 100)
    entrega = ay.dar(integ, t1.p1, t1.a1[0], 10).json()["entrega_id"]
    ay.recargar(integ, t2.admin, t2.p1, 100)
    panel = ay.leer(integ, t2.admin, "/admin/presupuestos").json()
    observado = {
        "recarga_ajena": ay.recargar(integ, t2.admin, t1.p1, 10).status_code,
        "dar_ajeno": ay.dar(integ, t2.p1, t1.a1[0], 5).status_code,
        "corregir_ajeno": ay.corregir(integ, t2.p1, entrega).status_code,
        "saldos_grupo_ajeno": ay.leer(integ, t2.p1,
                                      f"/economia/grupo/{t1.g1}/saldos").status_code,
        "panel_solo_t2": sorted(p["teacher_id"] for p in panel["profes"]) == sorted(
            str(x) for x in (t2.admin, t2.p1, t2.p2)),
        "t1_intacto": (ay.saldo(integ, t1.a1[0]), ay.bolsillo(integ, t1.tenant, t1.p1)),
    }
    assert observado == {"recarga_ajena": 404, "dar_ajeno": 404, "corregir_ajeno": 404,
                         "saldos_grupo_ajeno": 404, "panel_solo_t2": True,
                         "t1_intacto": (10, 90)}, f"OE15a: {observado}"
