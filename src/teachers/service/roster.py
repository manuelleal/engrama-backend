"""Lógica de `/admin/*` (M1-M4) — ESPEC §2.

`access.py` decide qué grupo puede tocar el admin (`authorize_group`); este
módulo arma M1 (crear grupo), M2 (asignar docente), M3 (matricular un
estudiante) y M4 (importar CSV), en el orden de los commits de la espec (§7).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.models import Group, Membership, Profile, TeacherGroup
from src.teachers.schemas import GroupCreateIn


# =============================================================================
# M1 — POST /admin/groups
# =============================================================================
async def create_group(db: AsyncSession, tenant_id: UUID, data: GroupCreateIn) -> Group:
    """Crea un grupo. `group_code` repetido en el mismo tenant -> 409."""
    exists = await db.execute(
        select(Group.id).where(Group.tenant_id == tenant_id, Group.group_code == data.group_code)
    )
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"group_code {data.group_code!r} already exists in this tenant",
        )
    group = Group(tenant_id=tenant_id, group_code=data.group_code, max_capacity=data.max_capacity)
    db.add(group)
    await db.flush()
    return group


# =============================================================================
# M2 — POST /admin/groups/{gid}/teachers
# =============================================================================
async def assign_teacher(
    db: AsyncSession, tenant_id: UUID, group: Group, documento_id: str
) -> tuple[Profile, str]:
    """Asigna un docente al grupo. Devuelve (perfil, 'asignado' | 'ya_estaba').

    Exige una `Membership` `teacher` ACTIVA en el tenant (ESPEC M2); si no,
    404 — no delata si el `documento_id` existe en otro colegio o con otro rol.
    """
    profile = (
        await db.execute(select(Profile).where(Profile.documento_id == documento_id))
    ).scalar_one_or_none()
    membership = None
    if profile is not None:
        membership = (
            await db.execute(
                select(Membership).where(
                    Membership.tenant_id == tenant_id, Membership.profile_id == profile.id
                )
            )
        ).scalar_one_or_none()
    if (
        profile is None
        or membership is None
        or membership.role != "teacher"
        or not membership.is_active
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active teacher membership for that documento_id in this tenant",
        )

    existing = (
        await db.execute(
            select(TeacherGroup).where(
                TeacherGroup.teacher_id == profile.id, TeacherGroup.group_id == group.id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return profile, "ya_estaba"

    db.add(TeacherGroup(tenant_id=tenant_id, teacher_id=profile.id, group_id=group.id))
    await db.flush()
    return profile, "asignado"


__all__ = ["create_group", "assign_teacher"]
