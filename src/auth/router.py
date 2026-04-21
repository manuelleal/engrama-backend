"""Endpoints HTTP del módulo auth — SPECS/01-auth.md §5.

Expone:
  - POST /auth/session  : perfil + memberships (al iniciar sesión).
  - GET  /auth/me       : mismo payload, para refrescar.
  - POST /auth/logout   : 200 OK + audit log (el logout real es frontend).

Todos requieren un JWT válido vía `get_current_user`. El router no habla
directamente con la DB salvo para logout (audit_logs).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext, ProfileOut
from src.auth.service import (
    get_memberships,
    get_or_create_profile,
    memberships_to_schema,
    profile_to_schema,
)
from src.shared.db import get_db
from src.shared.deps import get_current_user

router = APIRouter()


async def _build_profile_payload(
    auth: AuthContext, db: AsyncSession
) -> ProfileOut:
    """Reusable: carga Profile + memberships del usuario autenticado."""
    profile = await get_or_create_profile(db, auth.profile_id, jwt_payload={})
    rows = await get_memberships(db, auth.profile_id)
    return profile_to_schema(profile, memberships_to_schema(rows))


@router.post("/session", response_model=ProfileOut, status_code=status.HTTP_200_OK)
async def create_session(
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileOut:
    """Inicia la sesión del lado del backend tras login en Supabase Auth.

    El frontend llama este endpoint una vez, justo después de login,
    para obtener el perfil completo y cachearlo.
    """
    return await _build_profile_payload(auth, db)


@router.get("/me", response_model=ProfileOut, status_code=status.HTTP_200_OK)
async def read_me(
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileOut:
    """Retorna el perfil + memberships del usuario autenticado.

    Se usa para refrescar datos (streak, XP, level) en la UI.
    """
    return await _build_profile_payload(auth, db)


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Registra el logout en audit_logs. El cierre real lo hace el frontend.

    Insertamos vía SQL directo para evitar acoplar auth a la tabla
    audit_logs (no queremos un model adicional aquí). La escritura usa
    parámetros — nunca concatenamos strings (WINDSURF §9).
    """
    await db.execute(
        text(
            """
            INSERT INTO audit_logs (tenant_id, user_id, action_type, result, metadata)
            VALUES (:tenant_id, :user_id, :action_type, :result, '{}'::jsonb)
            """
        ),
        {
            "tenant_id": auth.tenant_id,
            "user_id": auth.profile_id,
            "action_type": "logout",
            "result": "success",
        },
    )
    await db.commit()
    return {"status": "ok"}
