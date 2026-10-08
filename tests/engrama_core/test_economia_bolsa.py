"""La alerta de bolsa baja — `docs/ESPEC_economia_oleada0.md` §1.7.

  UE5  C19  (no-integ) el umbral es el 10 % de lo emitido con el redondeo único; en
            alerta solo POR DEBAJO; el cruce se detecta una vez; con lo emitido en 0
            o el porcentaje en 0 no hay alerta
  EB1  C20  emitido 1.000, saldo 105: una paga de 10 (queda 95) escribe UNA línea
            `bolsa_baja`; la siguiente paga no escribe otra; la paga ocurre igual
            (200, no 402)
  EB2  C21  `bolsa --slug`: salida 0 y `en_alerta: false` por encima; salida 3 y
            `en_alerta: true` por debajo; tras una recarga que supera el umbral,
            vuelve a 0

Los tramposos ZE5, ZT18 y ZT19 están en `tests/tramposos/test_tramposos_economia*.py`;
cada regla se llama por el módulo (`economia.f`) para que se pueda reemplazar.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import pytest

from src.engrama_core.service import economia
from src.onboarding import recarga as recarga_mod
from src.shared.config import Settings
from tests.engrama_core import test_economia_asistencia as ea
from tests.onboarding import test_recarga as rec
from tests.onboarding._ayuda import sembrar_institucion
from tests.seguridad.veredictos import sembrar

LOGGER = "engrama.economia"


# =============================================================================
# UE5 — C19: las tres reglas puras
# =============================================================================
def test_ue5_el_umbral_y_el_cruce_de_la_alerta() -> None:
    umbral = economia.umbral_de_alerta
    umbrales = {"10% de 1000": umbral(1000, 10), "10% de 200000": umbral(200_000, 10),
                "10% de 1005": umbral(1005, 10),  # 100,5 -> 101 (la mitad hacia arriba)
                "10% de 1004": umbral(1004, 10),  # 100,4 -> 100
                "25% de 3000": umbral(3000, 25),
                "emitido 0": umbral(0, 10), "porcentaje 0": umbral(1000, 0)}
    assert umbrales == {"10% de 1000": 100, "10% de 200000": 20_000, "10% de 1005": 101,
                        "10% de 1004": 100, "25% de 3000": 750, "emitido 0": 0,
                        "porcentaje 0": 0}, f"UE5: los umbrales {umbrales}"

    alerta = economia.en_alerta
    tabla = {"99 de 100": alerta(99, 100), "100 de 100": alerta(100, 100),
             "101 de 100": alerta(101, 100),
             # sin umbral (emitido 0 o porcentaje 0) ni una bolsa vacía está en alerta
             "0 sin umbral": alerta(0, 0)}
    assert tabla == {"99 de 100": True, "100 de 100": False, "101 de 100": False,
                     "0 sin umbral": False}, f"UE5: en alerta {tabla}"

    cruza = economia.cruza_el_umbral
    cruces = {"105 -> 95": cruza(105, 95, 100),    # cruza: avisa
              "95 -> 85": cruza(95, 85, 100),      # ya estaba baja: no avisa otra vez
              "100 -> 99": cruza(100, 99, 100),    # justo en el umbral todavía estaba bien
              "120 -> 100": cruza(120, 100, 100),  # llegar al umbral no es cruzarlo
              "5 -> 0 sin umbral": cruza(5, 0, 0)}
    assert cruces == {"105 -> 95": True, "95 -> 85": False, "100 -> 99": True,
                      "120 -> 100": False, "5 -> 0 sin umbral": False}, f"UE5: cruces {cruces}"

    # La CLI no carga `Settings`: su defecto y su rango deben ser los mismos de la clase.
    campo = Settings.model_fields["bolsa_umbral_alerta_pct"]
    rango = tuple(m.ge if hasattr(m, "ge") else m.le for m in campo.metadata)
    de_la_cli = (recarga_mod.UMBRAL_PCT_POR_DEFECTO, recarga_mod.UMBRAL_PCT_RANGO)
    assert de_la_cli == (campo.default, rango) == (10, (0, 100)), \
        f"UE5: la CLI usa {de_la_cli} y Settings {(campo.default, rango)}"


# =============================================================================
# EB1 — C20: el aviso al cruzar el umbral (una línea por cruce; la paga ocurre)
# =============================================================================
def _lineas_bolsa_baja(caplog: Any) -> list[tuple[str, str]]:
    return [(r.levelname, r.getMessage()) for r in caplog.records
            if r.name == LOGGER and r.getMessage().startswith("bolsa_baja")]


@pytest.mark.integ
def test_eb1_cruzar_el_umbral_avisa_una_vez_y_no_bloquea(integ, monkeypatch, caplog) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER)
    esc = ea.armar(integ, estudiantes=3)  # emitido (coin_pool) = 1000 -> umbral 100
    sembrar(integ, "update coin_wallets set balance = 105 where owner_type = 'tenant' "
                   "and owner_id = :t", t=esc.tenant)
    codigo = ea.abrir(integ, esc)
    ea.fijar_ahora(monkeypatch, ea.INICIO + timedelta(minutes=1))  # puntual: paga 10
    cruza, ya_baja, otra = esc.alumnos

    r1 = ea.marcar(integ, cruza, codigo)  # 105 -> 95: cruza el umbral
    assert r1.status_code == 200, \
        f"EB1: la paga que cruza el umbral respondió {r1.status_code} ({r1.text})"
    assert r1.json()["coins_awarded"] == 10, f"EB1: la paga fue de {r1.json()['coins_awarded']}"
    lineas = _lineas_bolsa_baja(caplog)
    assert len(lineas) == 1, f"EB1: {len(lineas)} líneas bolsa_baja al cruzar, esperada 1"
    assert lineas == [("WARNING", f"bolsa_baja institucion={esc.tenant} saldo=95 umbral=100 "
                                  "emitido=1000")], f"EB1: la línea es {lineas}"

    r2 = ea.marcar(integ, ya_baja, codigo)  # 95 -> 85: ya estaba baja
    r3 = ea.marcar(integ, otra, codigo)     # 85 -> 75
    pagas = [(r.status_code, r.json().get("coins_awarded")) for r in (r2, r3)]
    assert pagas == [(200, 10), (200, 10)], \
        f"EB1: con la bolsa en alerta las pagas respondieron {pagas} (la alerta no bloquea)"
    despues = len(_lineas_bolsa_baja(caplog))
    assert despues == 1, f"EB1: {despues} líneas bolsa_baja tras tres pagas (una por cruce)"
    assert integ.saldo("tenant", esc.tenant) == 75, "EB1: la bolsa no quedó en 75"


# =============================================================================
# EB2 — C21: la orden `bolsa`
# =============================================================================
def _poner_saldo(integ: Any, slug: str, saldo: int) -> None:
    sembrar(integ, "update coin_wallets set balance = :s where owner_type = 'tenant' and "
                   "owner_id = (select id from tenants where slug = :g)", s=saldo, g=slug)


@pytest.mark.integ
def test_eb2_la_orden_bolsa_dice_si_esta_en_alerta(integ, capsys, monkeypatch) -> None:
    monkeypatch.delenv("BOLSA_UMBRAL_ALERTA_PCT", raising=False)
    sembrar_institucion(integ, "inst-a", pool=1000)

    def bolsa(slug: str = "inst-a") -> tuple[int, dict[str, Any]]:
        return rec.cli(capsys, integ, ["bolsa", "--slug", slug])

    def estado(saldo: int, emitido: int, umbral: int, alerta: bool) -> dict[str, Any]:
        return {"institucion": "inst-a", "saldo": saldo, "emitido": emitido, "umbral": umbral,
                "porcentaje": 10, "en_alerta": alerta}

    llena = bolsa()
    _poner_saldo(integ, "inst-a", 100)
    en_el_umbral = bolsa()
    _poner_saldo(integ, "inst-a", 99)
    baja = bolsa()
    assert (llena, en_el_umbral, baja) == (
        (0, estado(1000, 1000, 100, False)), (0, estado(100, 1000, 100, False)),
        (3, estado(99, 1000, 100, True))), f"EB2: llena, en el umbral y baja: " \
                                           f"{(llena, en_el_umbral, baja)}"

    # Una recarga que supera el umbral (que también sube: es el 10 % de lo emitido).
    recarga = rec.cli(capsys, integ, rec.orden(monedas=500, referencia="REC-EB2"))
    assert recarga[0] == 0, f"EB2: la recarga salió con {recarga}"
    recargada = bolsa()
    assert recargada == (0, estado(599, 1500, 150, False)), \
        f"EB2: tras recargar 500 la orden bolsa dice {recargada}"

    # El porcentaje es configuración (0 = alerta apagada), y una institución que no existe es 1.
    _poner_saldo(integ, "inst-a", 0)
    vacia = bolsa()[0]
    monkeypatch.setenv("BOLSA_UMBRAL_ALERTA_PCT", "0")
    apagada = bolsa()
    no_existe = bolsa("inst-fantasma")[0]
    assert (vacia, apagada[0], apagada[1]["umbral"], apagada[1]["en_alerta"], no_existe) == (
        3, 0, 0, False, 1), f"EB2: vacía {vacia}, apagada {apagada}, no existe {no_existe}"
