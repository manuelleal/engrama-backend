"""La asistencia paga 5 + 5 por puntualidad — `docs/ESPEC_economia_oleada0.md` §1.1.

  EA1  C2  check-in puntual: 200, 10 monedas; el asiento lleva base, puntualidad y puntual
  EA2  C3  a los 5:00 paga 10; a los 5:01 paga 5 (`puntualidad: 0`)
  EA3  C4  los números son configuración: con 4 + 3 y 10 minutos paga 7 y 4

El reloj se fija con la costura `attendance._ahora`; la sesión se abre con
`crear_sesion_asistencia(inicio=...)`. Los tramposos ZT1-ZT3:
`tests/tramposos/test_tramposos_economia.py`. Los siguientes commits de la
oleada agregan aquí la racha (ER*) y el pago único por día (ED*).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.engrama_core.service import attendance as attendance_mod
from src.main import app
from src.shared.config import settings

pytestmark = pytest.mark.integ
client = TestClient(app)

POOL = 1000
INICIO = datetime(2026, 10, 6, 23, 0, tzinfo=UTC)  # las 18:00 de Bogotá


def fijar_ahora(mp: pytest.MonkeyPatch, instante: datetime) -> None:
    """El reloj de la asistencia (`attendance._ahora`) marca `instante`."""
    mp.setattr(attendance_mod, "_ahora", lambda: instante)


def escena(integ: Any, *, estudiantes: int = 1, inicio: datetime = INICIO,
           expira_en: timedelta = timedelta(minutes=15)) -> tuple[UUID, str, list[UUID]]:
    """Colegio (pool 1000), grupo G1 y una sesión abierta en `inicio`.

    Devuelve (colegio, código de la sesión, estudiantes de G1).
    """
    tenant = integ.crear_tenant(pool=POOL)
    grupo = integ.crear_grupo(tenant, "G1")
    docente = integ.crear_perfil(tenant, rol="teacher", group_code="G1")
    alumnos = [integ.crear_perfil(tenant, group_code="G1") for _ in range(estudiantes)]
    codigo = integ.crear_sesion_asistencia(tenant, grupo, docente, inicio=inicio,
                                           expira_en=expira_en)
    return tenant, codigo, alumnos


def marcar(integ: Any, alumno: UUID, codigo: str) -> Any:
    return client.post("/core/attendance/check-in", json={"session_code": codigo},
                       headers=integ.headers(alumno))


def asientos(integ: Any, alumno: UUID) -> list[dict[str, Any]]:
    """Los asientos 'attendance' del libro cuyo destino es la billetera del estudiante."""
    async def _q() -> list[dict[str, Any]]:
        from sqlalchemy import text
        async with integ.Session() as db:
            filas = (await db.execute(text(
                "select l.amount, l.metadata, l.from_wallet_id, l.idempotency_key "
                "from coin_ledger l join coin_wallets w on w.id = l.to_wallet_id "
                "where l.action = 'attendance' and w.owner_id = :p order by l.created_at"),
                {"p": alumno})).mappings().all()
            return [dict(f) for f in filas]
    return integ.run(_q())  # type: ignore[no-any-return]


# =============================================================================
# EA1 — C2: check-in puntual
# =============================================================================
def test_ea1_checkin_puntual_paga_10(integ, monkeypatch) -> None:
    tenant, codigo, (alumno,) = escena(integ)
    fijar_ahora(monkeypatch, INICIO + timedelta(minutes=2))

    r = marcar(integ, alumno, codigo)
    assert r.status_code == 200, f"EA1: {r.status_code} {r.text}"
    body = r.json()
    assert body["coins_awarded"] == 10, f"EA1: la respuesta dice {body['coins_awarded']}, no 10"
    assert body["message"] == "Check-in exitoso! +10 coins", f"EA1: {body['message']!r}"

    filas = asientos(integ, alumno)
    assert len(filas) == 1, f"EA1: {len(filas)} asientos de asistencia"
    asiento = filas[0]
    assert asiento["amount"] == 10, f"EA1: el asiento es de {asiento['amount']}, no 10"
    meta = asiento["metadata"]
    assert (meta["base"], meta["puntualidad"], meta["puntual"]) == (5, 5, True), f"EA1: {meta}"
    assert "multiplier" not in meta, f"EA1: el asiento aún lleva el multiplicador: {meta}"
    assert integ.saldo("profile", alumno) == 10, "EA1: el saldo del estudiante no es 10"
    assert integ.saldo("tenant", tenant) == POOL - 10, "EA1: la bolsa no bajó 10"


# =============================================================================
# EA2 — C3: el límite es inclusivo
# =============================================================================
def test_ea2_el_limite_de_cinco_minutos_es_inclusivo(integ, monkeypatch) -> None:
    _, codigo, (en_el_limite, pasado) = escena(integ, estudiantes=2)

    fijar_ahora(monkeypatch, INICIO + timedelta(minutes=5))
    a = marcar(integ, en_el_limite, codigo)
    fijar_ahora(monkeypatch, INICIO + timedelta(minutes=5, seconds=1))
    b = marcar(integ, pasado, codigo)

    assert (a.status_code, b.status_code) == (200, 200), f"EA2: {a.text} | {b.text}"
    assert a.json()["coins_awarded"] == 10, f"EA2: a los 5:00 pagó {a.json()['coins_awarded']}"
    assert b.json()["coins_awarded"] == 5, f"EA2: a los 5:01 pagó {b.json()['coins_awarded']}"
    meta = asientos(integ, pasado)[0]["metadata"]
    assert (meta["base"], meta["puntualidad"], meta["puntual"]) == (5, 0, False), f"EA2: {meta}"


# =============================================================================
# EA3 — C4: son configuración, sin tocar código
# =============================================================================
def test_ea3_los_numeros_son_configuracion(integ, monkeypatch) -> None:
    monkeypatch.setattr(settings, "asistencia_monedas_base", 4)
    monkeypatch.setattr(settings, "asistencia_monedas_puntualidad", 3)
    monkeypatch.setattr(settings, "asistencia_minutos_puntualidad", 10)
    _, codigo, (a, b) = escena(integ, estudiantes=2)

    fijar_ahora(monkeypatch, INICIO + timedelta(minutes=8))
    en_8 = marcar(integ, a, codigo)
    fijar_ahora(monkeypatch, INICIO + timedelta(minutes=11))
    en_11 = marcar(integ, b, codigo)

    assert (en_8.status_code, en_11.status_code) == (200, 200), f"EA3: {en_8.text} | {en_11.text}"
    pagos = (en_8.json()["coins_awarded"], en_11.json()["coins_awarded"])
    assert pagos == (7, 4), f"EA3: pagó {pagos}, esperado (7, 4)"
    assert integ.saldo("profile", a) == 7 and integ.saldo("profile", b) == 4, "EA3: saldos"
