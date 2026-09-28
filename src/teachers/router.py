"""Endpoints HTTP de `/teachers` — ESPEC §2 (T1-T6).

Toda ruta usa `require_teacher` (admins también pasan, WINDSURF: un admin es
staff) y, salvo T1 (que lista), `access.authorize_group` para resolver el
grupo. Rol equivocado -> 403 exacto; grupo ajeno o inexistente -> 404 exacto
(ESPEC §2, línea "Toda la autorización pasa por un solo punto").
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.shared.db import get_db
from src.shared.deps import require_teacher
from src.teachers.schemas import GroupSummaryOut, StudentRosterOut
from src.teachers.service import access as access_service
from src.teachers.service import panel as panel_service

router = APIRouter()


# =============================================================================
# T1 — GET /teachers/groups
# =============================================================================
@router.get(
    "/groups",
    response_model=list[GroupSummaryOut],
    status_code=status.HTTP_200_OK,
)
async def list_groups(
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> list[GroupSummaryOut]:
    """Grupos visibles para `auth` (`access.visible_groups`), con su conteo."""
    groups = await access_service.visible_groups(db, auth)
    return [await panel_service.group_to_summary(db, g) for g in groups]


# =============================================================================
# T2 — GET /teachers/groups/{gid}/students
# =============================================================================
@router.get(
    "/groups/{gid}/students",
    response_model=list[StudentRosterOut],
    status_code=status.HTTP_200_OK,
)
async def list_students(
    gid: UUID,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> list[StudentRosterOut]:
    """Roster del grupo (`access.authorize_group` + `panel.roster`, §2.2)."""
    group = await access_service.authorize_group(db, auth, gid)
    return await panel_service.roster(db, group)
