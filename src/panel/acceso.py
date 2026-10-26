"""Quién entra a `/super/*`: SOLO `profiles.role = 'super_admin'` (ESPEC_panel_super_admin §1.1).

Por qué una dependencia propia y no `require_admin`: el super admin ve TODOS los
clientes, así que su permiso no puede salir de una membresía (que es de UN
tenant, y cuyo CHECK ni siquiera admite `super_admin`). Sale del perfil, que es
global y que ningún camino del backend escribe con ese rol: solo se pone a mano.

Repite las barreras de `get_current_user` que no dependen del tenant: JWT
válido, perfil existente, cuenta activa (H-8) y clave definitiva. NO exige
membresía ni mira `X-Tenant-ID`.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.service import (
    exigir_clave_definitiva,
    exigir_cuenta_activa,
    exigir_perfil,
    get_profile,
    validate_jwt,
)
from src.shared.db import get_db
from src.shared.deps import _extract_bearer_token

ROL_SUPER = "super_admin"
SOLO_SUPER = "Super admin role required"


def exigir_super(rol_del_perfil: str) -> None:
    """403 si el perfil no es super admin. Pura: los tramposos la reemplazan."""
    if rol_del_perfil != ROL_SUPER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=SOLO_SUPER)


async def require_super_admin(
    request: Request,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> UUID:
    """El id del perfil del super admin, o 401/403. Mismo orden que `get_current_user`."""
    payload = validate_jwt(_extract_bearer_token(authorization))
    try:
        profile_id = UUID(str(payload["sub"]))
    except (ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT 'sub' claim is not a valid UUID",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    profile = exigir_perfil(await get_profile(db, profile_id))
    exigir_cuenta_activa(profile)  # una cuenta suspendida no entra ni siendo super admin
    ruta = request.scope.get("route")
    exigir_clave_definitiva(profile, getattr(ruta, "path", None), request.method)
    exigir_super(profile.role)
    return profile_id
