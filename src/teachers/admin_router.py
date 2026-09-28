"""Endpoints HTTP de `/admin` — ESPEC §2 (M1-M4).

Toda ruta usa `require_admin` (solo admin/super_admin del tenant) más
`access.authorize_group` para M2-M4. Rol equivocado -> 403 exacto; grupo
ajeno o inexistente -> 404 exacto (mismo contrato que `router.py`).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.shared.db import get_db
from src.shared.deps import require_admin
from src.teachers.schemas import (
    GroupCreateIn,
    GroupOut,
    TeacherAssignIn,
    TeacherAssignOut,
)
from src.teachers.service import access as access_service
from src.teachers.service import roster as roster_service

router = APIRouter()


# =============================================================================
# M1 — POST /admin/groups
# =============================================================================
@router.post("/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: GroupCreateIn,
    auth: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> GroupOut:
    """Crea un grupo en el tenant de `auth`. Código repetido -> 409."""
    group = await roster_service.create_group(db, auth.tenant_id, payload)
    await db.commit()
    return GroupOut(id=group.id, group_code=group.group_code, max_capacity=group.max_capacity)


# =============================================================================
# M2 — POST /admin/groups/{gid}/teachers
# =============================================================================
@router.post(
    "/groups/{gid}/teachers",
    response_model=TeacherAssignOut,
    status_code=status.HTTP_201_CREATED,
)
async def assign_teacher(
    gid: UUID,
    payload: TeacherAssignIn,
    response: Response,
    auth: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TeacherAssignOut:
    """Asigna un docente al grupo. 201 si nace la asignación, 200 si ya estaba."""
    group = await access_service.authorize_group(db, auth, gid)
    profile, resultado = await roster_service.assign_teacher(
        db, auth.tenant_id, group, payload.documento_id
    )
    await db.commit()
    if resultado == "ya_estaba":
        response.status_code = status.HTTP_200_OK
    return TeacherAssignOut(
        teacher_id=profile.id, documento_id=profile.documento_id, resultado=resultado
    )
