"""Endpoints HTTP del módulo leaderboard — SPECS/04-leaderboard.md §5.

Se monta en main.py con prefijo `/leaderboard`:
  GET /leaderboard?group_code=...&limit=...

Resolución de scope (SPECS/04 §4):
  - Sin `group_code`  → grupo activo del usuario (su `auth.group_code`);
    si no tiene grupo, ranking de todo el tenant.
  - Con `group_code`  → teachers/admins pueden ver cualquier grupo de SU
    tenant; un estudiante solo puede ver su propio grupo (403 si pide otro).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.leaderboard import service as leaderboard_service
from src.leaderboard.schemas import LeaderboardOut
from src.shared.db import get_db
from src.shared.deps import get_current_user

router = APIRouter()


def _resolve_scope(auth: AuthContext, requested_group_code: str | None) -> str | None:
    """Decide sobre qué grupo (o todo el tenant) se calcula el ranking.

    Lanza 403 si un estudiante intenta ver un grupo que no es el suyo.
    El aislamiento entre tenants lo garantiza el filtro `tenant_id` del
    service, así que aquí solo controlamos el cruce entre grupos.
    """
    if requested_group_code is None:
        return auth.group_code  # puede ser None → ranking de todo el tenant
    if auth.is_teacher or auth.is_admin:
        return requested_group_code
    if requested_group_code != auth.group_code:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Students can only view their own group leaderboard",
        )
    return requested_group_code


@router.get(
    "",
    response_model=LeaderboardOut,
    status_code=status.HTTP_200_OK,
)
async def read_leaderboard(
    group_code: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeaderboardOut:
    """Ranking de estudiantes por coins, con la posición propia incluida."""
    scope_group = _resolve_scope(auth, group_code)
    return await leaderboard_service.get_leaderboard(
        db,
        tenant_id=auth.tenant_id,
        group_code=scope_group,
        me_profile_id=auth.profile_id,
        limit=limit,
    )
