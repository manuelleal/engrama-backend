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
from src.challenge_engine.schemas import ChallengeOut
from src.challenge_engine.service import challenges as challenges_service
from src.engrama_core.schemas import AttendanceSessionOut
from src.engrama_core.service.attendance import session_to_schema
from src.shared.db import get_db
from src.shared.deps import require_teacher
from src.teachers.schemas import GroupSummaryOut, SessionDurationIn, StudentRosterOut
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


# =============================================================================
# T3 — POST /teachers/groups/{gid}/attendance-sessions
# =============================================================================
@router.post(
    "/groups/{gid}/attendance-sessions",
    response_model=AttendanceSessionOut,
    status_code=status.HTTP_201_CREATED,
)
async def open_attendance_session(
    gid: UUID,
    payload: SessionDurationIn,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> AttendanceSessionOut:
    """Abre una sesión QR para el grupo (reusa `attendance.create_session`)."""
    group = await access_service.authorize_group(db, auth, gid)
    session = await panel_service.open_session(
        db, teacher_id=auth.profile_id, tenant_id=auth.tenant_id,
        group=group, duration_minutes=payload.duration_minutes,
    )
    await db.commit()
    return session_to_schema(session)


# =============================================================================
# T4 — POST /teachers/attendance-sessions/{sid}/close
# =============================================================================
@router.post(
    "/attendance-sessions/{sid}/close",
    response_model=AttendanceSessionOut,
    status_code=status.HTTP_200_OK,
)
async def close_attendance_session(
    sid: UUID,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> AttendanceSessionOut:
    """Cierra la sesión: `status='expired'` (§2, T4). Sesión de otro grupo -> 404."""
    session = await panel_service.close_session(db, auth, sid)
    await db.commit()
    return session_to_schema(session)


# =============================================================================
# T6 — PUT /teachers/groups/{gid}/challenges/{cid}
# =============================================================================
@router.put(
    "/groups/{gid}/challenges/{cid}",
    response_model=ChallengeOut,
    status_code=status.HTTP_200_OK,
)
async def assign_challenge_to_group(
    gid: UUID,
    cid: UUID,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> ChallengeOut:
    """Fija el `group_id` del reto (§2, T6). Reto de un grupo no visible -> 404."""
    group = await access_service.authorize_group(db, auth, gid)
    challenge = await panel_service.assign_challenge(db, auth, group, cid)
    await db.commit()
    return await challenges_service.hydrate(db, challenge)
