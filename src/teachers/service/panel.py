"""Lógica de las rutas de docente (`/teachers/*`) que no es pura autorización.

`access.py` decide QUÉ grupo puede tocar `auth`; este módulo arma la
respuesta de cada ruta T1-T6, en el orden de los commits de la espec (§7).
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.challenge_engine.service import challenges as challenges_service
from src.engrama_core.service import attendance as attendance_service
from src.shared.models import Attendance, AttendanceSession, Challenge, Group, Membership, Profile
from src.teachers.schemas import ConsistencyOut, GroupSummaryOut, StudentRosterOut
from src.teachers.service import access as access_service


# =============================================================================
# T1 — GET /teachers/groups
# =============================================================================
async def student_count(db: AsyncSession, tenant_id: UUID, group_code: str) -> int:
    """Cuántos estudiantes activos tiene un grupo (por `group_code`, como
    `attendance.create_session` y `challenges.list_challenges_for_student`)."""
    stmt = select(func.count()).select_from(Membership).where(
        Membership.tenant_id == tenant_id,
        Membership.group_code == group_code,
        Membership.role == "student",
        Membership.is_active.is_(True),
    )
    return int((await db.execute(stmt)).scalar_one())


async def group_to_summary(db: AsyncSession, group: Group) -> GroupSummaryOut:
    """Proyecta un `Group` a `GroupSummaryOut` con su conteo de estudiantes."""
    n = await student_count(db, group.tenant_id, group.group_code)
    return GroupSummaryOut(id=group.id, group_code=group.group_code, student_count=n)


# =============================================================================
# T2 — GET /teachers/groups/{gid}/students
# =============================================================================
async def roster(db: AsyncSession, group: Group) -> list[StudentRosterOut]:
    """Estudiantes del grupo, alfabético — ESPEC §2, §2.2.

    SIN saldo (X9 lo prohíbe explícitamente: §2.2 lo quita del roster).
    `last_attendance_date` es la última asistencia a una sesión de ESTE
    grupo (`AttendanceSession.group_id = group.id`), no de cualquier sesión
    del estudiante.
    """
    ultima_asistencia = (
        select(func.max(Attendance.attendance_date))
        .select_from(Attendance)
        .join(AttendanceSession, AttendanceSession.id == Attendance.session_id)
        .where(
            AttendanceSession.group_id == group.id,
            Attendance.student_id == Profile.id,
        )
        .correlate(Profile)
        .scalar_subquery()
    )
    stmt = (
        # El nombre sale de la membresía de ESTE colegio, no de `profiles`
        # (BUG-11): el perfil es global y otro colegio pudo matricularlo.
        select(Profile.id, Membership.full_name, Profile.current_streak, ultima_asistencia)
        .select_from(Membership)
        .join(Profile, Profile.id == Membership.profile_id)
        .where(
            Membership.tenant_id == group.tenant_id,
            Membership.group_code == group.group_code,
            Membership.role == "student",
            Membership.is_active.is_(True),
        )
        .order_by(Membership.full_name, Profile.id)
    )
    rows = (await db.execute(stmt)).all()
    return [
        StudentRosterOut(
            profile_id=pid,
            full_name=full_name,
            consistency=ConsistencyOut(current_streak=streak),
            last_attendance_date=ultima,
        )
        for pid, full_name, streak, ultima in rows
    ]


__all__ = [
    "student_count", "group_to_summary", "roster",
    "open_session", "close_session", "assign_challenge",
]


# =============================================================================
# T3 — POST /teachers/groups/{gid}/attendance-sessions
# =============================================================================
async def open_session(
    db: AsyncSession, *, teacher_id: UUID, tenant_id: UUID, group: Group, duration_minutes: int
) -> AttendanceSession:
    """T3: reusa `attendance.create_session` SIN tocarla (ESPEC §2, "sin tocarla")."""
    return await attendance_service.create_session(
        db,
        teacher_id=teacher_id,
        tenant_id=tenant_id,
        group_code=group.group_code,
        duration_minutes=duration_minutes,
    )


# =============================================================================
# T4 — POST /teachers/attendance-sessions/{sid}/close
# =============================================================================
async def close_session(
    db: AsyncSession, auth: AuthContext, session_id: UUID
) -> AttendanceSession:
    """Cierra una sesión: `status='expired'`, `expires_at=now()` (ESPEC T4).

    Doble 404: la sesión debe existir en el tenant de `auth`, Y su grupo
    debe estar entre los visibles para `auth` (`access.authorize_group`) —
    así "sesión de otro grupo" da 404 aunque el `session_id` sea real.
    """
    stmt = select(AttendanceSession).where(
        AttendanceSession.id == session_id,
        AttendanceSession.tenant_id == auth.tenant_id,
    )
    session = (await db.execute(stmt)).scalar_one_or_none()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attendance session not found"
        )
    await access_service.authorize_group(db, auth, session.group_id)

    session.status = "expired"
    session.expires_at = datetime.now(UTC)
    await db.flush()
    return session


# =============================================================================
# T6 — PUT /teachers/groups/{gid}/challenges/{cid}
# =============================================================================
async def assign_challenge(
    db: AsyncSession, auth: AuthContext, group: Group, challenge_id: UUID
) -> Challenge:
    """Fija `challenge.group_id = group.id` — ESPEC T6.

    El reto debe ser del colegio (`get_challenge` ya filtra por tenant) y
    estar sin grupo o en un grupo VISIBLE para `auth`; si está en un grupo
    que `auth` no ve, 404 — sin este chequeo (X7), un docente podría
    "robarle" a otro un reto ya asignado a un grupo que no puede ver.
    """
    challenge = await challenges_service.get_challenge(db, challenge_id, auth.tenant_id)
    if challenge.group_id is not None:
        visibles = await access_service.visible_groups(db, auth)
        if challenge.group_id not in {g.id for g in visibles}:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found"
            )
    challenge.group_id = group.id
    await db.flush()
    return challenge
