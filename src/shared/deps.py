"""FastAPI dependencies compartidas por todos los dominios.

Expone las 3 dependencias de autenticación descritas en SPECS/01-auth.md §4:
  - get_current_user : valida JWT + carga Profile + arma AuthContext.
  - require_teacher  : 403 si el usuario no es teacher/admin/super_admin.
  - require_admin    : 403 si el usuario no es admin/super_admin.

Importar siempre desde aquí en los routers:

    from src.shared.deps import get_current_user, require_teacher, require_admin

NOTA: este archivo importa del módulo `auth` porque concentra la lógica
de validación. No es una violación de la dependency rule (WINDSURF §2)
porque `shared/deps.py` es la capa de infraestructura expuesta a TODOS
los dominios — igual que `shared/events.py`.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.auth.service import (
    build_auth_context,
    get_memberships,
    get_or_create_profile,
    validate_jwt,
)
from src.shared.db import get_db


def _extract_bearer_token(authorization: str | None) -> str:
    """Extrae `<token>` del header `Authorization: Bearer <token>`.

    Lanza 401 si el header falta o no sigue el formato Bearer.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return parts[1].strip()


async def get_current_user(
    authorization: str | None = Header(default=None),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    """Dependency: valida JWT y devuelve AuthContext del usuario.

    Secuencia:
      1. Extrae el Bearer token del header.
      2. Valida el JWT con `validate_jwt`.
      3. Lookup del Profile (fallback dev: lo crea si falta).
      4. Carga memberships activos.
      5. Resuelve tenant activo (X-Tenant-ID si viene, sino el primero).
    """
    token = _extract_bearer_token(authorization)
    payload = validate_jwt(token)

    try:
        profile_id = UUID(str(payload["sub"]))
    except (ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT 'sub' claim is not a valid UUID",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    profile = await get_or_create_profile(db, profile_id, payload)
    memberships = await get_memberships(db, profile_id)
    return build_auth_context(profile, memberships, tenant_id_header=x_tenant_id)


async def require_teacher(
    auth: AuthContext = Depends(get_current_user),
) -> AuthContext:
    """Solo permite teachers, admins y super_admins. Lanza 403 si no."""
    if not auth.is_teacher and not auth.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Teacher role required",
        )
    return auth


async def require_admin(
    auth: AuthContext = Depends(get_current_user),
) -> AuthContext:
    """Solo permite admins y super_admins. Lanza 403 si no."""
    if not auth.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return auth
