"""Lógica de las rutas de docente (`/teachers/*`) que no es pura autorización.

`access.py` decide QUÉ grupo puede tocar `auth`; este módulo arma la
respuesta de cada ruta T1-T6, en el orden de los commits de la espec (§7).
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.models import Attendance, AttendanceSession, Group, Membership, Profile
from src.teachers.schemas import ConsistencyOut, GroupSummaryOut, StudentRosterOut


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
        select(Profile.id, Profile.full_name, Profile.current_streak, ultima_asistencia)
        .select_from(Membership)
        .join(Profile, Profile.id == Membership.profile_id)
        .where(
            Membership.tenant_id == group.tenant_id,
            Membership.group_code == group.group_code,
            Membership.role == "student",
            Membership.is_active.is_(True),
        )
        .order_by(Profile.full_name, Profile.id)
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


__all__ = ["student_count", "group_to_summary", "roster"]
