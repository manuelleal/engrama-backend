"""El check-in dice el desglose — `docs/ESPEC_economia_oleada0.md` §13.

  CK1  C32  puntual: 200, base 5, puntualidad 5, puntual, no ya cobrada; la suma cuadra
  CK2  C33  a los 5:01 puntualidad 0 y no puntual; a los 5:00 exactos sí es puntual
  CK3  C34  la segunda sesión del día: ya_cobrada_hoy verdadero y todo en 0
  CK4  C35  con la configuración en 0 NO es "ya cobrada"

Reusa el montaje de `test_economia_asistencia.py` (reloj fijo, colegio, grupo y
sesiones). Los tramposos: `tests/tramposos/test_tramposos_economia.py` (ZK4-ZK6).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.shared.config import settings
from tests.engrama_core.test_economia_asistencia import (
    INICIO,
    POOL,
    abrir,
    armar,
    asientos,
    fijar_ahora,
    marcar,
)

pytestmark = pytest.mark.integ

CAMPOS = ("coins_awarded", "base", "puntualidad", "puntual", "ya_cobrada_hoy")


def _desglose(cuerpo: dict[str, Any]) -> dict[str, Any]:
    """Los cinco campos del desglose, con `.get` (una clave que falta se ve, no revienta)."""
    return {campo: cuerpo.get(campo) for campo in CAMPOS}


def _suma_cuadra(cuerpo: dict[str, Any]) -> bool:
    return bool(cuerpo.get("base", -1) + cuerpo.get("puntualidad", -1)
                == cuerpo.get("coins_awarded"))


def test_ck1_el_checkin_puntual_dice_el_desglose(integ, monkeypatch) -> None:
    esc = armar(integ)
    (alumno,), codigo = esc.alumnos, abrir(integ, esc)
    fijar_ahora(monkeypatch, INICIO + timedelta(minutes=2))

    r = marcar(integ, alumno, codigo)
    assert r.status_code == 200, f"CK1: {r.status_code} {r.text}"
    cuerpo = r.json()
    assert _desglose(cuerpo) == {"coins_awarded": 10, "base": 5, "puntualidad": 5,
                                 "puntual": True, "ya_cobrada_hoy": False}, \
        f"CK1: el desglose es {_desglose(cuerpo)}"
    assert _suma_cuadra(cuerpo), f"CK1: base + puntualidad no suma coins_awarded: {cuerpo}"
    meta = asientos(integ, alumno)[0]["metadata"]
    assert (meta["base"], meta["puntualidad"], meta["puntual"]) == (
        cuerpo.get("base"), cuerpo.get("puntualidad"), cuerpo.get("puntual")), \
        f"CK1: la respuesta ({_desglose(cuerpo)}) no coincide con el asiento ({meta})"


def test_ck2_el_checkin_tarde_no_es_puntual(integ, monkeypatch) -> None:
    esc = armar(integ, estudiantes=2)
    (en_el_limite, pasado), codigo = esc.alumnos, abrir(integ, esc)

    fijar_ahora(monkeypatch, INICIO + timedelta(minutes=5))
    a = marcar(integ, en_el_limite, codigo)
    fijar_ahora(monkeypatch, INICIO + timedelta(minutes=5, seconds=1))
    b = marcar(integ, pasado, codigo)

    assert (a.status_code, b.status_code) == (200, 200), f"CK2: {a.text} | {b.text}"
    assert _desglose(a.json()) == {"coins_awarded": 10, "base": 5, "puntualidad": 5,
                                   "puntual": True, "ya_cobrada_hoy": False}, \
        f"CK2: a los 5:00 el desglose es {_desglose(a.json())}"
    assert _desglose(b.json()) == {"coins_awarded": 5, "base": 5, "puntualidad": 0,
                                   "puntual": False, "ya_cobrada_hoy": False}, \
        f"CK2: a los 5:01 el desglose es {_desglose(b.json())}"
    assert _suma_cuadra(a.json()) and _suma_cuadra(b.json()), f"CK2: no suma: {a.text} | {b.text}"


def test_ck3_la_segunda_sesion_del_dia_dice_que_ya_estaba_cobrada(integ, monkeypatch) -> None:
    """La 1.ª sesión paga 10 (puntual); la 2.ª, también puntual, dice ya_cobrada_hoy y ceros."""
    esc = armar(integ)
    (alumno,) = esc.alumnos
    primera = abrir(integ, esc, datetime(2026, 10, 6, 18, 0, tzinfo=UTC))
    segunda = abrir(integ, esc, datetime(2026, 10, 6, 20, 0, tzinfo=UTC))

    fijar_ahora(monkeypatch, datetime(2026, 10, 6, 18, 1, tzinfo=UTC))
    r1 = marcar(integ, alumno, primera)
    fijar_ahora(monkeypatch, datetime(2026, 10, 6, 20, 1, tzinfo=UTC))  # puntual para la 2.ª
    r2 = marcar(integ, alumno, segunda)

    assert (r1.status_code, r2.status_code) == (200, 200), f"CK3: {r1.text} | {r2.text}"
    assert _desglose(r1.json()) == {"coins_awarded": 10, "base": 5, "puntualidad": 5,
                                    "puntual": True, "ya_cobrada_hoy": False}, \
        f"CK3: la 1.ª dijo {_desglose(r1.json())}"
    assert _desglose(r2.json()) == {"coins_awarded": 0, "base": 0, "puntualidad": 0,
                                    "puntual": False, "ya_cobrada_hoy": True}, \
        f"CK3: la 2.ª dijo {_desglose(r2.json())}"
    # La asistencia se registró (2 filas) y se pagó una sola vez.
    filas = int(integ.valor("select count(*) from attendance where student_id = :p", p=alumno))
    assert (filas, len(asientos(integ, alumno))) == (2, 1), "CK3: filas y asientos"
    assert integ.saldo("tenant", esc.tenant) == POOL - 10, "CK3: la bolsa"


def test_ck4_la_configuracion_en_cero_no_es_ya_cobrada(integ, monkeypatch) -> None:
    """coins_awarded == 0 por configuración: ya_cobrada_hoy FALSO, puntual dice la hora."""
    monkeypatch.setattr(settings, "asistencia_monedas_base", 0)
    monkeypatch.setattr(settings, "asistencia_monedas_puntualidad", 0)
    esc = armar(integ)
    (alumno,), codigo = esc.alumnos, abrir(integ, esc)
    fijar_ahora(monkeypatch, INICIO + timedelta(minutes=1))

    r = marcar(integ, alumno, codigo)
    assert r.status_code == 200, f"CK4: {r.status_code} {r.text}"
    assert _desglose(r.json()) == {"coins_awarded": 0, "base": 0, "puntualidad": 0,
                                   "puntual": True, "ya_cobrada_hoy": False}, \
        f"CK4: con la configuración en 0 el desglose es {_desglose(r.json())}"
    assert len(asientos(integ, alumno)) == 0, "CK4: con 0 monedas no debe haber asiento"
