"""Lógica de las rutas de docente (`/teachers/*`) que no es pura autorización.

`access.py` decide QUÉ grupo puede tocar `auth`; este módulo arma la
respuesta de cada ruta T1-T6, en el orden de los commits de la espec (§7).
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.models import Group, Membership
from src.teachers.schemas import GroupSummaryOut


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


__all__ = ["student_count", "group_to_summary"]
