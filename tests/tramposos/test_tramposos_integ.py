"""Tramposos de la fixture de integración (espec §4).

Cada tramposo es una versión rota a propósito. Se inyecta con monkeypatch en
el módulo donde se USA la función, se corre el cuerpo del test real y se exige
AssertionError. Si el test real pasara con el tramposo puesto, `pytest.raises`
falla y este archivo queda en rojo: el test real no estaría probando nada.

  T1  ledger descuadrado: award_coins acredita al estudiante sin debitar la
      billetera del tenant  -> debe fallar test_award_coins_double_entry.
  T2  racha: streak_multiplier devuelve siempre 1.0
                            -> debe fallar test_checkin_streak_7_awards_75.
  T3  base sin migrar: la preparación de la base sin `upgrade head`
                            -> debe fallar el humo.

Los tests reales se importan como módulo (no por nombre) para que pytest no
los vuelva a recolectar aquí.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

import tests.engrama_core.test_attendance as tests_asistencia
import tests.engrama_core.test_coins as tests_monedas
from src.engrama_core.service import attendance as attendance_mod
from src.engrama_core.service import coins as coins_mod
from src.shared.models import CoinLedger
from tests import integ_db

pytestmark = pytest.mark.integ


# =============================================================================
# T1 — ledger descuadrado
# =============================================================================
async def _award_sin_debito(
    db: Any,
    *,
    student_id: UUID,
    tenant_id: UUID,
    amount: int,
    action: str,
    metadata: dict[str, Any] | None = None,
    created_by_profile_id: UUID | None = None,
) -> CoinLedger:
    """Igual que award_coins, pero NO descuenta la wallet del tenant."""
    from_wallet = await coins_mod.get_wallet(
        db, "tenant", tenant_id, tenant_id=tenant_id, for_update=True
    )
    to_wallet = await coins_mod.get_wallet(
        db, "profile", student_id, tenant_id=tenant_id, for_update=True
    )
    entry = CoinLedger(
        tenant_id=tenant_id,
        from_wallet_id=from_wallet.id,
        to_wallet_id=to_wallet.id,
        amount=amount,
        action=action,
        created_by_profile_id=created_by_profile_id,
        ledger_metadata=metadata or {},
    )
    db.add(entry)
    to_wallet.balance = to_wallet.balance + amount  # falta: from_wallet -= amount
    await db.flush()
    return entry


def test_t1_ledger_descuadrado_rompe_double_entry(integ, monkeypatch) -> None:
    monkeypatch.setattr(coins_mod, "award_coins", _award_sin_debito)
    with pytest.raises(AssertionError):
        tests_monedas.test_award_coins_double_entry(integ)


# =============================================================================
# T2 — racha sin multiplicador
# =============================================================================
def test_t2_racha_sin_multiplicador_rompe_streak_7(integ, monkeypatch) -> None:
    # check_in (attendance.py:302) llama a `streak_multiplier` por nombre global
    # del módulo attendance: ahí se reemplaza.
    monkeypatch.setattr(attendance_mod, "streak_multiplier", lambda _racha: 1.0)
    with pytest.raises(AssertionError):
        tests_asistencia.test_checkin_streak_7_awards_75(integ)


# =============================================================================
# T3 — base sin migrar
# =============================================================================
def test_t3_base_sin_migrar_hace_fallar_el_humo(pg_integ) -> None:
    # Misma preparación que la fixture, en una base aparte del mismo
    # contenedor, pero sin `alembic upgrade head`.
    url = integ_db.preparar_base("engrama_sin_migrar", migrar=False)
    datos = integ_db.medir_humo(url)
    with pytest.raises(AssertionError):
        integ_db.afirmar_humo(datos)
