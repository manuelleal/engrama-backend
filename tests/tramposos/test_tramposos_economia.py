"""Tramposos ZT (integ) de la economía, oleada 0 — `docs/ESPEC_economia_oleada0.md` §3.2.

Mismo patrón que `test_tramposos_bug13.py`: una versión ROTA a propósito, se
corre el cuerpo del test real y se exige `AssertionError` con el mensaje del
mecanismo. Aquí se automatiza la DIAGONAL (la columna "Rojo predicho"); la
matriz completa se mide aparte (ERR-15, 19 y 23).

  ZT1  vuelve el multiplicador de racha (×1,5 y ×2)  -> los dos `..._paga_lo_mismo`
       (releva a T2, que parcheaba `streak_multiplier` y ya no tiene blanco)
  ZT2  la base es 50 fija en el código               -> EA1
  ZT3  la puntualidad nunca se paga                  -> EA1

Los demás (ZT4-ZT19) entran con el commit que crea su pieza.
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.engrama_core.service import coins as coins_mod
from src.engrama_core.service import economia as economia_mod
from tests.engrama_core import test_attendance as ta
from tests.engrama_core import test_economia_asistencia as ea
from tests.tramposos.test_tramposos_bug13 import correr

pytestmark = pytest.mark.integ

Aplicar = Callable[[Any, pytest.MonkeyPatch], AbstractContextManager[Any]]

_AWARD_BUENO = coins_mod.award_coins
_DESGLOSE_BUENO = economia_mod.desglose_asistencia


# =============================================================================
# ZT1 — vuelve el multiplicador
# =============================================================================
async def _award_con_multiplicador(db: AsyncSession, *, student_id: UUID, tenant_id: UUID,
                                   amount: int, action: str, metadata: dict[str, Any] | None = None,
                                   **resto: Any) -> Any:
    """ZT1: como el código de antes, la asistencia paga ×1,5 con racha >= 7 y ×2 con >= 14."""
    racha = int((metadata or {}).get("streak", 0))
    factor = 2.0 if racha >= 14 else 1.5 if racha >= 7 else 1.0
    return await _AWARD_BUENO(db, student_id=student_id, tenant_id=tenant_id,
                              amount=int(amount * factor), action=action,
                              metadata=metadata, **resto)


# =============================================================================
# ZT2, ZT3 — la regla de la asistencia rota
# =============================================================================
def _base_50_fija(llegada: datetime, apertura: datetime, *, base: int, bono: int,
                  minutos: int) -> economia_mod.DesgloseAsistencia:
    """ZT2: ignora la configuración de la base y paga 50 como antes."""
    del base
    return _DESGLOSE_BUENO(llegada, apertura, base=50, bono=bono, minutos=minutos)


def _nunca_puntual(llegada: datetime, apertura: datetime, *, base: int, bono: int,
                   minutos: int) -> economia_mod.DesgloseAsistencia:
    """ZT3: la puntualidad nunca se paga."""
    del llegada, apertura, bono, minutos
    return economia_mod.DesgloseAsistencia(base=base, puntualidad=0, puntual=False)


def _parche(objetivo: Any, nombre: str, valor: Any) -> Aplicar:
    def aplicar(_integ: Any, mp: pytest.MonkeyPatch) -> AbstractContextManager[Any]:
        mp.setattr(objetivo, nombre, valor)
        return nullcontext()
    return aplicar


# =============================================================================
# Registro: id -> (cómo romper, [(test real, mensaje con el que debe caer)])
# =============================================================================
TRAMPOSOS: dict[str, tuple[Aplicar, list[tuple[Callable[..., None], str]]]] = {
    "ZT1": (_parche(coins_mod, "award_coins", _award_con_multiplicador), [
        (ta.test_checkin_streak_7_paga_lo_mismo, r"assert 7 == 5"),
        (ta.test_checkin_streak_14_paga_lo_mismo, r"assert 10 == 5"),
    ]),
    "ZT2": (_parche(economia_mod, "desglose_asistencia", _base_50_fija), [
        (ea.test_ea1_checkin_puntual_paga_10, r"EA1: la respuesta dice 55, no 10"),
    ]),
    "ZT3": (_parche(economia_mod, "desglose_asistencia", _nunca_puntual), [
        (ea.test_ea1_checkin_puntual_paga_10, r"EA1: la respuesta dice 5, no 10"),
    ]),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    aplicar, diagonal = TRAMPOSOS[clave]
    with aplicar(integ, monkeypatch):
        for test_real, motivo in diagonal:
            with pytest.raises(AssertionError, match=motivo):
                correr(test_real, integ, monkeypatch)
