"""Lógica de asistencia (attendance) — SPECS/02-engrama-core.md §4.

Flujo general:
  1. Teacher crea una AttendanceSession con un `session_code` corto
     (6 chars alfanuméricos) que se renderiza como QR.
  2. El QR muestra durante `duration_minutes`.
  3. Cada estudiante escanea → el frontend envía `session_code` + GPS.
  4. Backend valida: sesión activa, no expirada, no duplicada; otorga
     coins con multiplicador según streak; actualiza `profiles.streak`.

Reglas clave (spec §11):
  - `session_code` vía `secrets.choice` (criptográficamente seguro).
  - `geo_status` es informativo; NUNCA bloquea check-in.
  - Streak:
      * last_attendance_date = ayer       → current_streak += 1
      * last_attendance_date < ayer       → current_streak = 1 (roto)
      * last_attendance_date = hoy        → UNIQUE constraint bloquea
      * last_attendance_date IS NULL      → current_streak = 1
  - Todo dentro de la misma AsyncSession del request para que un fallo
    reviente la transacción completa (get_db hace rollback).
"""
from __future__ import annotations

import math
import secrets
import string
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.engrama_core.schemas import (
    AttendanceRecordOut,
    AttendanceSessionOut,
    CheckInResult,
)
from src.engrama_core.service import coins as coins_service
from src.shared.models import (
    Attendance,
    AttendanceSession,
    Group,
    Profile,
)


# =============================================================================
# Constantes de negocio (spec §7).
# =============================================================================
ATTENDANCE_COINS_BASE = 50
# Umbral → multiplicador. Ordenado de mayor a menor para buscar "el más alto
# que aplique". Ej: streak 15 matchea 14 (x2.0); streak 8 matchea 7 (x1.5).
_STREAK_MULTIPLIERS: tuple[tuple[int, float], ...] = (
    (14, 2.0),
    (7, 1.5),
)
GEO_MAX_DISTANCE_METERS = 100.0
SESSION_CODE_LENGTH = 6
_SESSION_CODE_ALPHABET = string.ascii_uppercase + string.digits


# =============================================================================
# Helpers puros (unit-testables sin DB).
# =============================================================================
def generate_session_code(length: int = SESSION_CODE_LENGTH) -> str:
    """Genera un código alfanumérico uppercase criptográficamente seguro."""
    return "".join(secrets.choice(_SESSION_CODE_ALPHABET) for _ in range(length))


def haversine_distance(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Distancia en metros entre dos puntos GPS (fórmula de Haversine).

    Precisa a ~0.5% a escala urbana. No corrige altitud ni la elipsoide
    WGS84 real, pero para validar presencia en un aula (<200m) es ideal.
    """
    R = 6_371_000  # radio medio de la Tierra en metros
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


def streak_multiplier(current_streak: int) -> float:
    """Devuelve el multiplicador de coins según la racha (§4.2)."""
    for threshold, mult in _STREAK_MULTIPLIERS:
        if current_streak >= threshold:
            return mult
    return 1.0


def compute_next_streak(
    last_attendance_date: date | None, today: date
) -> int:
    """Nueva racha tras un check-in HOY (spec §11.3)."""
    if last_attendance_date is None:
        return 1
    if last_attendance_date == today - timedelta(days=1):
        return -1  # sentinel: "incrementar el actual" — lo resuelve el caller
    if last_attendance_date < today - timedelta(days=1):
        return 1
    # last_attendance_date == today nunca debería llegar aquí (UNIQUE).
    return 1


# =============================================================================
# 4.1 create_session
# =============================================================================
async def create_session(
    db: AsyncSession,
    *,
    teacher_id: UUID,
    tenant_id: UUID,
    group_code: str,
    duration_minutes: int,
) -> AttendanceSession:
    """Crea una AttendanceSession activa para el grupo del teacher.

    Validaciones:
      - El `group_code` existe dentro de `tenant_id` (si no → 404).
    No revalidamos el rol del teacher porque `require_teacher` ya lo
    garantiza aguas arriba.
    """
    # 1. Resolver group_id por (tenant_id, group_code).
    stmt_group = select(Group).where(
        Group.tenant_id == tenant_id,
        Group.group_code == group_code,
    )
    group = (await db.execute(stmt_group)).scalar_one_or_none()
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group '{group_code}' not found in tenant",
        )

    # 2. Código único y ventana temporal.
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=duration_minutes)
    # Colisiones son extremadamente raras con 36^6 combinaciones, pero
    # reintentamos 3 veces por si el UNIQUE de session_code choca.
    session_code = ""
    for _ in range(3):
        candidate = generate_session_code()
        exists = await db.execute(
            select(AttendanceSession.id).where(
                AttendanceSession.session_code == candidate
            )
        )
        if exists.scalar_one_or_none() is None:
            session_code = candidate
            break
    if not session_code:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not generate unique session code, try again",
        )

    # 3. Payload QR: info mínima para que el frontend reconstruya el flujo.
    qr_payload: dict[str, Any] = {
        "session_code": session_code,
        "tenant_id": str(tenant_id),
        "group_code": group_code,
        "expires_at": expires_at.isoformat(),
    }

    # 4. INSERT. Usamos coords del grupo si existen (última ubicación
    # registrada por el admin) para poder comparar GPS del estudiante.
    session = AttendanceSession(
        tenant_id=tenant_id,
        group_id=group.id,
        session_code=session_code,
        qr_payload=qr_payload,
        admin_lat=group.last_admin_lat,
        admin_lng=group.last_admin_lng,
        starts_at=now,
        expires_at=expires_at,
        created_by=teacher_id,
        status="active",
    )
    db.add(session)
    await db.flush()
    return session


def session_to_schema(session: AttendanceSession) -> AttendanceSessionOut:
    """Mapea ORM → Pydantic para la respuesta HTTP."""
    return AttendanceSessionOut(
        id=session.id,
        session_code=session.session_code,
        qr_payload=session.qr_payload or {},
        starts_at=session.starts_at,
        expires_at=session.expires_at,
        status=session.status,
    )


async def list_active_sessions(
    db: AsyncSession, tenant_id: UUID
) -> list[AttendanceSession]:
    """Sesiones activas y no expiradas del tenant (para dashboard docente)."""
    now = datetime.now(UTC)
    stmt = (
        select(AttendanceSession)
        .where(
            AttendanceSession.tenant_id == tenant_id,
            AttendanceSession.status == "active",
            AttendanceSession.expires_at > now,
        )
        .order_by(AttendanceSession.starts_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


# =============================================================================
# 4.2 check_in
# =============================================================================
async def check_in(
    db: AsyncSession,
    *,
    student_id: UUID,
    tenant_id: UUID,
    session_code: str,
    latitude: float | None,
    longitude: float | None,
) -> CheckInResult:
    """Registra check-in del estudiante; otorga coins y actualiza streak."""
    # 1. Buscar la sesión por código, exige mismo tenant (defensa en profundidad).
    stmt = select(AttendanceSession).where(
        AttendanceSession.session_code == session_code,
        AttendanceSession.tenant_id == tenant_id,
    )
    session = (await db.execute(stmt)).scalar_one_or_none()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session code not found",
        )

    # 2. Validar estado + expiración.
    now = datetime.now(UTC)
    if session.status != "active" or session.expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Session expired or no longer active",
        )

    # 3. Check duplicado (el UNIQUE también protegería, pero el error
    # explícito da mejor UX y evita estallar la transacción).
    dup_stmt = select(Attendance.id).where(
        Attendance.session_id == session.id,
        Attendance.student_id == student_id,
    )
    if (await db.execute(dup_stmt)).scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Student already checked in to this session",
        )

    # 4. Geo — informativo, nunca bloqueante (spec §11.4).
    if latitude is not None and longitude is not None:
        if session.admin_lat is not None and session.admin_lng is not None:
            dist = haversine_distance(
                latitude, longitude, session.admin_lat, session.admin_lng
            )
            geo_status = (
                "valid" if dist <= GEO_MAX_DISTANCE_METERS else "out_of_range"
            )
        else:
            # La sesión no tiene coords de referencia → no podemos validar.
            geo_status = "reference_missing"
    else:
        geo_status = "skipped"

    # 5. Actualizar streak del estudiante.
    profile = await db.get(Profile, student_id)
    if profile is None:
        # Muy raro: el JWT validó pero el perfil no existe. Defensivo.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student profile not found",
        )

    today = now.date()
    delta = compute_next_streak(profile.last_attendance_date, today)
    if delta == -1:  # sentinel: "racha continúa, suma 1"
        new_streak = profile.current_streak + 1
    else:
        new_streak = delta  # 1 (primer check-in o racha rota)

    profile.current_streak = new_streak
    profile.longest_streak = max(profile.longest_streak, new_streak)
    profile.last_attendance_date = today

    # 6. Calcular coins con multiplicador por racha.
    multiplier = streak_multiplier(new_streak)
    coins_awarded = int(ATTENDANCE_COINS_BASE * multiplier)

    # 7. INSERT attendance.
    record = Attendance(
        tenant_id=tenant_id,
        session_id=session.id,
        student_id=student_id,
        attendance_date=today,
        latitude=latitude,
        longitude=longitude,
        geo_status=geo_status,
        coins_awarded=coins_awarded,
    )
    db.add(record)

    # 8. Otorgar coins vía double-entry. Si falla por fondos insuficientes
    # (HTTPException 402) la transacción entera revierte → no queda
    # attendance huérfana ni streak actualizada.
    await coins_service.award_coins(
        db,
        student_id=student_id,
        tenant_id=tenant_id,
        amount=coins_awarded,
        action="attendance",
        metadata={
            "session_id": str(session.id),
            "streak": new_streak,
            "geo_status": geo_status,
            "multiplier": multiplier,
        },
    )

    await db.flush()
    return CheckInResult(
        success=True,
        coins_awarded=coins_awarded,
        streak=new_streak,
        message=f"Check-in exitoso! +{coins_awarded} coins",
    )


# =============================================================================
# 4.3 get_attendance_history
# =============================================================================
async def get_attendance_history(
    db: AsyncSession,
    student_id: UUID,
    tenant_id: UUID,
    limit: int = 30,
) -> list[AttendanceRecordOut]:
    """Historial de asistencias del estudiante, más reciente primero."""
    stmt = (
        select(Attendance)
        .where(
            Attendance.student_id == student_id,
            Attendance.tenant_id == tenant_id,
        )
        .order_by(Attendance.attendance_date.desc(), Attendance.created_at.desc())
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    return [
        AttendanceRecordOut(
            id=r.id,
            student_id=r.student_id,
            attendance_date=r.attendance_date,
            coins_awarded=r.coins_awarded,
            geo_status=r.geo_status,
            created_at=r.created_at,
        )
        for r in rows
    ]


# =============================================================================
# 4.4 expire_sessions
# =============================================================================
async def expire_sessions(db: AsyncSession) -> int:
    """Marca como 'expired' las sesiones active cuya ventana ya pasó.

    Se pensó para correr periódicamente vía Celery (Fase 3). Mientras
    tanto puede invocarse manualmente o desde un endpoint admin.
    """
    now = datetime.now(UTC)
    stmt_old = select(AttendanceSession).where(
        AttendanceSession.status == "active",
        AttendanceSession.expires_at < now,
    )
    sessions = list((await db.execute(stmt_old)).scalars().all())
    for s in sessions:
        s.status = "expired"
    await db.flush()
    return len(sessions)
