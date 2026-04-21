"""Schemas Pydantic del módulo engrama_core — SPECS/02-engrama-core.md §2.

Cubre dos sub-dominios:
  - Coins        : WalletOut, LedgerEntryOut, CoinHistoryOut, BalanceOut.
  - Attendance   : AttendanceSessionCreate/Out, CheckInRequest/Result,
                   AttendanceRecordOut.

Todos los schemas son Pydantic v2 strict con `extra="forbid"` per WINDSURF §4.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


_STRICT = ConfigDict(strict=True, extra="forbid")


# =============================================================================
# COINS
# =============================================================================
class WalletOut(BaseModel):
    """Snapshot de una wallet (propia del estudiante)."""

    model_config = _STRICT

    id: UUID
    owner_type: str
    balance: int
    currency: str
    updated_at: datetime


class LedgerEntryOut(BaseModel):
    """Una entrada del libro contable doble partida."""

    model_config = _STRICT

    id: UUID
    amount: int
    action: str
    from_wallet_id: UUID | None = None
    to_wallet_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class CoinHistoryOut(BaseModel):
    """Wallet + últimas N transacciones para el dashboard del estudiante."""

    model_config = _STRICT

    wallet: WalletOut
    entries: list[LedgerEntryOut]
    total: int


class BalanceOut(BaseModel):
    """Respuesta reducida de GET /core/coins/balance."""

    model_config = _STRICT

    balance: int
    currency: str = "COIN"


# =============================================================================
# ATTENDANCE
# =============================================================================
class AttendanceSessionCreate(BaseModel):
    """Body de POST /core/attendance/sessions (teacher only)."""

    model_config = _STRICT

    group_code: str
    duration_minutes: int = Field(default=15, ge=1, le=180)


class AttendanceSessionOut(BaseModel):
    """Sesión QR activa (respuesta para teacher)."""

    model_config = _STRICT

    id: UUID
    session_code: str
    qr_payload: dict[str, Any] = Field(default_factory=dict)
    starts_at: datetime
    expires_at: datetime
    status: str


class CheckInRequest(BaseModel):
    """Body de POST /core/attendance/check-in (student)."""

    model_config = _STRICT

    session_code: str
    latitude: float | None = None
    longitude: float | None = None


class CheckInResult(BaseModel):
    """Respuesta de check-in: cuántas coins + estado del streak."""

    model_config = _STRICT

    success: bool
    coins_awarded: int
    streak: int
    message: str


class AttendanceRecordOut(BaseModel):
    """Una fila de attendance para historial."""

    model_config = _STRICT

    id: UUID
    student_id: UUID
    attendance_date: date
    coins_awarded: int
    geo_status: str | None = None
    created_at: datetime
