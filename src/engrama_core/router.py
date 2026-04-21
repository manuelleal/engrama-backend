"""Endpoints HTTP del módulo engrama_core — SPECS/02-engrama-core.md §5.

Se monta en main.py con prefijo `/core`, así que las rutas finales son:
  GET  /core/coins/balance
  GET  /core/coins/history
  POST /core/attendance/sessions
  GET  /core/attendance/sessions/active
  POST /core/attendance/check-in
  GET  /core/attendance/history
  GET  /core/attendance/history/{student_id}

Todos los handlers comparten el patrón:
  1. Dep de auth (get_current_user o require_teacher) inyecta AuthContext.
  2. Llama al service correspondiente pasando `auth.tenant_id`.
  3. Commit explícito al final si hubo escrituras (post/check-in).
  4. Serializa la respuesta a Pydantic.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.engrama_core.schemas import (
    AttendanceRecordOut,
    AttendanceSessionCreate,
    AttendanceSessionOut,
    BalanceOut,
    CheckInRequest,
    CheckInResult,
    CoinHistoryOut,
)
from src.engrama_core.service import attendance as attendance_service
from src.engrama_core.service import coins as coins_service
from src.shared.db import get_db
from src.shared.deps import get_current_user, require_teacher

router = APIRouter()


# =============================================================================
# COINS
# =============================================================================
@router.get(
    "/coins/balance",
    response_model=BalanceOut,
    status_code=status.HTTP_200_OK,
)
async def read_balance(
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BalanceOut:
    """Balance actual del estudiante en la currency por defecto (COIN)."""
    balance = await coins_service.get_balance(db, auth.profile_id, auth.tenant_id)
    return BalanceOut(balance=balance, currency="COIN")


@router.get(
    "/coins/history",
    response_model=CoinHistoryOut,
    status_code=status.HTTP_200_OK,
)
async def read_history(
    limit: int = Query(default=20, ge=1, le=100),
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CoinHistoryOut:
    """Wallet + últimas N entradas del ledger relacionadas con el estudiante."""
    history = await coins_service.get_coin_history(
        db, auth.profile_id, auth.tenant_id, limit=limit
    )
    # get_coin_history crea la wallet si no existe → commit para persistir.
    await db.commit()
    return history


# =============================================================================
# ATTENDANCE — teacher
# =============================================================================
@router.post(
    "/attendance/sessions",
    response_model=AttendanceSessionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_attendance_session(
    payload: AttendanceSessionCreate,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> AttendanceSessionOut:
    """Teacher/admin crea una sesión QR para que alumnos hagan check-in."""
    session = await attendance_service.create_session(
        db,
        teacher_id=auth.profile_id,
        tenant_id=auth.tenant_id,
        group_code=payload.group_code,
        duration_minutes=payload.duration_minutes,
    )
    await db.commit()
    return attendance_service.session_to_schema(session)


@router.get(
    "/attendance/sessions/active",
    response_model=list[AttendanceSessionOut],
    status_code=status.HTTP_200_OK,
)
async def list_active_attendance_sessions(
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> list[AttendanceSessionOut]:
    """Lista de sesiones activas y no expiradas en el tenant del teacher."""
    sessions = await attendance_service.list_active_sessions(db, auth.tenant_id)
    return [attendance_service.session_to_schema(s) for s in sessions]


# =============================================================================
# ATTENDANCE — student
# =============================================================================
@router.post(
    "/attendance/check-in",
    response_model=CheckInResult,
    status_code=status.HTTP_200_OK,
)
async def check_in(
    payload: CheckInRequest,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CheckInResult:
    """Registra asistencia del estudiante y otorga coins con multiplicador."""
    result = await attendance_service.check_in(
        db,
        student_id=auth.profile_id,
        tenant_id=auth.tenant_id,
        session_code=payload.session_code,
        latitude=payload.latitude,
        longitude=payload.longitude,
    )
    # Persistimos attendance + ledger + balances + streak en una sola tx.
    await db.commit()
    return result


@router.get(
    "/attendance/history",
    response_model=list[AttendanceRecordOut],
    status_code=status.HTTP_200_OK,
)
async def read_attendance_history(
    limit: int = Query(default=30, ge=1, le=100),
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AttendanceRecordOut]:
    """Historial propio del estudiante."""
    return await attendance_service.get_attendance_history(
        db, auth.profile_id, auth.tenant_id, limit=limit
    )


@router.get(
    "/attendance/history/{student_id}",
    response_model=list[AttendanceRecordOut],
    status_code=status.HTTP_200_OK,
)
async def read_student_attendance_history(
    student_id: UUID,
    limit: int = Query(default=30, ge=1, le=100),
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> list[AttendanceRecordOut]:
    """Historial de un estudiante específico (solo teacher/admin).

    Defensa en profundidad: `get_attendance_history` filtra por
    `tenant_id` además del `student_id`, así un teacher no puede
    consultar estudiantes fuera de su propio tenant aunque pase un UUID.
    """
    return await attendance_service.get_attendance_history(
        db, student_id, auth.tenant_id, limit=limit
    )
