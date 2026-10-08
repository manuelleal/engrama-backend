"""Tramposos ZT (integ) de la economía, oleada 0 — `docs/ESPEC_economia_oleada0.md` §3.2.

Mismo patrón que `test_tramposos_bug13.py`: una versión ROTA a propósito, se
corre el cuerpo del test real y se exige `AssertionError` con el mensaje del
mecanismo. Aquí se automatiza la DIAGONAL (la columna "Rojo predicho"); la
matriz completa se mide aparte (ERR-15, 19 y 23).

  ZT1  vuelve el multiplicador de racha (×1,5 y ×2)  -> los dos `..._paga_lo_mismo`
       (releva a T2, que parcheaba `streak_multiplier` y ya no tiene blanco)
  ZT2  la base es 50 fija en el código               -> EA1
  ZT3  la puntualidad nunca se paga                  -> EA1
  ZT4  el día es el UTC                              -> ER2
  ZT5  la paga de asistencia va sin llave            -> ED1, ED2, ED3
  ZT6  la llave no lleva el día                      -> ED2
  ZT7  la llave no lleva al estudiante               -> ED1
  ZT8  la segunda sesión del día reinicia la racha a 1 -> ER1
  ZT9  la segunda sesión del día suma racha          -> ER1
  ZT10 la segunda sesión del día responde 409 y no registra -> ED1
  ZT11 al pagar no se aplica el tope                 -> ET1 (recibe 50)
  ZT12 al crear no se valida el tope                 -> ET1 (201 con 21)

Los demás (ZT13-ZT19) entran con el commit que crea su pieza.
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import date, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.engrama_core.service import attendance as attendance_mod
from src.engrama_core.service import coins as coins_mod
from src.engrama_core.service import economia as economia_mod
from src.foco import fechas as fechas_mod
from src.shared.config import settings
from src.shared.models import Attendance
from tests.challenge_engine import test_economia_retos as er
from tests.engrama_core import test_attendance as ta
from tests.engrama_core import test_economia_asistencia as ea
from tests.tramposos.test_tramposos_bug13 import correr

pytestmark = pytest.mark.integ

Aplicar = Callable[[Any, pytest.MonkeyPatch], AbstractContextManager[Any]]

_AWARD_BUENO = coins_mod.award_coins
_DESGLOSE_BUENO = economia_mod.desglose_asistencia
_SIGUIENTE_RACHA_BUENA = attendance_mod.compute_next_streak


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


# =============================================================================
# ZT4 — el día es el UTC
# =============================================================================
def _hoy_utc(ahora_utc: datetime, desfase_horas: int) -> date:
    """ZT4: ignora el desfase de la institución; el día es el de UTC."""
    del desfase_horas
    return ahora_utc.date()


# =============================================================================
# ZT8, ZT9 — la segunda sesión del día toca la racha
# =============================================================================
def _misma_fecha_reinicia(last_attendance_date: date | None, today: date) -> int:
    """ZT8: con la misma fecha la racha vuelve a 1."""
    bueno = _SIGUIENTE_RACHA_BUENA(last_attendance_date, today)
    return 1 if bueno == 0 else bueno


def _misma_fecha_suma(last_attendance_date: date | None, today: date) -> int:
    """ZT9: con la misma fecha la racha suma 1 (el sentinel -1)."""
    bueno = _SIGUIENTE_RACHA_BUENA(last_attendance_date, today)
    return -1 if bueno == 0 else bueno


# =============================================================================
# ZT5, ZT6, ZT7 — la llave de la paga rota
# =============================================================================
async def _award_sin_llave(db: AsyncSession, *, idempotency_key: str | None = None,
                           **resto: Any) -> Any:
    """ZT5: la paga de asistencia va sin llave (acepta la llave y la descarta)."""
    del idempotency_key
    return await _AWARD_BUENO(db, idempotency_key=None, **resto)


async def _award_llave_sin_dia(db: AsyncSession, *, idempotency_key: str | None = None,
                               **resto: Any) -> Any:
    """ZT6: la llave `attendance:<grupo>:<estudiante>:<día>` pierde el día."""
    llave = idempotency_key.rsplit(":", 1)[0] if idempotency_key else None
    return await _AWARD_BUENO(db, idempotency_key=llave, **resto)


async def _award_llave_sin_estudiante(db: AsyncSession, *, idempotency_key: str | None = None,
                                      **resto: Any) -> Any:
    """ZT7: la llave pierde al estudiante: un solo pago por grupo y día para todos."""
    llave = None
    if idempotency_key:
        accion, grupo, _estudiante, dia = idempotency_key.split(":")
        llave = f"{accion}:{grupo}:{dia}"
    return await _AWARD_BUENO(db, idempotency_key=llave, **resto)


# =============================================================================
# ZT10 — la segunda sesión del día responde 409 y no registra nada
# =============================================================================
_CHECK_IN_BUENO = attendance_mod.check_in


async def _check_in_409_si_ya_marco_hoy(db: AsyncSession, *, student_id: UUID, tenant_id: UUID,
                                        **resto: Any) -> Any:
    """ZT10: si el estudiante ya tiene una asistencia HOY, 409 (y no se registra la segunda)."""
    hoy = fechas_mod.hoy(attendance_mod._ahora(), settings.engrama_utc_offset_hours)
    ya = (await db.execute(select(func.count()).select_from(Attendance).where(
        Attendance.student_id == student_id, Attendance.tenant_id == tenant_id,
        Attendance.attendance_date == hoy))).scalar_one()
    if ya:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Student already checked in today")
    return await _CHECK_IN_BUENO(db, student_id=student_id, tenant_id=tenant_id, **resto)


# =============================================================================
# ZT11, ZT12 — el tope roto
# =============================================================================
def _paga_lo_guardado(coins_reward: int, tope: int) -> int:
    """ZT11: al pagar (y mostrar) no se aplica el tope."""
    del tope
    return coins_reward


def _no_valida_el_tope(coins_reward: int, tope: int) -> int:
    """ZT12: al crear no se valida el tope."""
    del tope
    return coins_reward


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
    "ZT4": (_parche(fechas_mod, "hoy", _hoy_utc), [
        (ea.test_er2_el_dia_es_el_de_la_institucion,
         r"ER2: ayer local \+ hoy local dio racha 1"),
    ]),
    "ZT5": (_parche(coins_mod, "award_coins", _award_sin_llave), [
        (ea.test_ed1_una_segunda_sesion_del_dia_se_registra_pero_no_paga,
         r"ED1: 2 asientos de asistencia, esperado 1"),
        (ea.test_ed2_el_dia_de_la_paga_es_el_local, r"ED2: las pagas fueron \[10, 10, 10\]"),
        (ea.test_ed3_dos_checkins_a_la_vez_pagan_una_vez,
         r"ED3: dos check-ins a la vez: \{'estados': \[200, 200\], 'pagos': \[10, 10\]"),
    ]),
    "ZT6": (_parche(coins_mod, "award_coins", _award_llave_sin_dia), [
        (ea.test_ed2_el_dia_de_la_paga_es_el_local, r"ED2: las pagas fueron \[10, 0, 0\]"),
    ]),
    "ZT7": (_parche(coins_mod, "award_coins", _award_llave_sin_estudiante), [
        (ea.test_ed1_una_segunda_sesion_del_dia_se_registra_pero_no_paga,
         r"ED1: el control cobró 0, no 10"),
    ]),
    "ZT8": (_parche(attendance_mod, "compute_next_streak", _misma_fecha_reinicia), [
        (ea.test_er1_la_segunda_sesion_del_dia_no_cambia_la_racha,
         r"ER1: la 2\.ª sesión dio racha 1, no 6"),
    ]),
    "ZT9": (_parche(attendance_mod, "compute_next_streak", _misma_fecha_suma), [
        (ea.test_er1_la_segunda_sesion_del_dia_no_cambia_la_racha,
         r"ER1: la 2\.ª sesión dio racha 7, no 6"),
    ]),
    "ZT10": (_parche(attendance_mod, "check_in", _check_in_409_si_ya_marco_hoy), [
        (ea.test_ed1_una_segunda_sesion_del_dia_se_registra_pero_no_paga,
         r"ED1: 1 filas en attendance, esperadas 2"),
    ]),
    "ZT11": (_parche(economia_mod, "recompensa_del_reto", _paga_lo_guardado), [
        (er.test_et1_el_tope_al_crear_al_pagar_y_al_mostrar,
         r"ET1: quien lo gana recibe 50, no 20"),
    ]),
    "ZT12": (_parche(economia_mod, "exigir_tope_del_reto", _no_valida_el_tope), [
        (er.test_et1_el_tope_al_crear_al_pagar_y_al_mostrar,
         r"ET1: crear con 21 respondió 201"),
    ]),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    aplicar, diagonal = TRAMPOSOS[clave]
    with aplicar(integ, monkeypatch):
        for test_real, motivo in diagonal:
            with pytest.raises(AssertionError, match=motivo):
                correr(test_real, integ, monkeypatch)
