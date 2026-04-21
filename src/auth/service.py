"""Lógica de negocio del módulo auth — validación JWT y lookup de perfil.

Implementa las 4 funciones de SPECS/01-auth.md §3:
  - validate_jwt            : decodifica y verifica un JWT de Supabase.
  - get_or_create_profile   : busca/crea fallback del Profile en DB.
  - get_memberships         : carga memberships+tenant del usuario.
  - build_auth_context      : resuelve el tenant activo y construye AuthContext.

Diseño:
  - NINGUNA de estas funciones habla HTTP; las excepciones HTTP se lanzan
    a propósito (FastAPI las captura) pero la lógica pura no importa
    starlette/fastapi salvo `HTTPException` (tolerado por WINDSURF §5
    porque son utilidades de capa de servicio ligadas al framework web).
  - Los queries filtran por `tenant_id` cuando aplica y el `is_active`
    de memberships es obligatorio (WINDSURF §3).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.config import settings
from src.shared.models import Membership, Profile, Tenant

from .schemas import AuthContext, MembershipOut, ProfileOut


# =============================================================================
# 3.1 validate_jwt
# =============================================================================
_JWT_ALGORITHM = "HS256"


def validate_jwt(token: str) -> dict[str, Any]:
    """Decodifica un JWT de Supabase y retorna su payload.

    Verifica firma HS256 con `settings.supabase_jwt_secret` y expiración.
    Supabase emite el claim `aud='authenticated'`, por eso pasamos esa
    audiencia. El claim `iss` puede variar entre proyectos (suele ser
    "supabase" o la URL del proyecto) por lo que NO lo verificamos
    contra un valor fijo.

    Lanza HTTPException(401) en cualquier error — firma inválida, token
    expirado, claim faltante.

    Retorna el payload como dict. `payload["sub"]` es el UUID del Profile
    (= auth.uid() en Supabase).
    """
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=[_JWT_ALGORITHM],
            audience="authenticated",
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired JWT: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT payload missing 'sub' claim",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


# =============================================================================
# 3.2 get_or_create_profile
# =============================================================================
async def get_or_create_profile(
    db: AsyncSession,
    profile_id: UUID,
    jwt_payload: dict[str, Any],
) -> Profile:
    """Busca `profiles.id = profile_id`; si no existe crea un stub mínimo.

    El perfil "real" se crea en el flujo de onboarding (otra spec); este
    fallback solo existe para desarrollo y para escenarios en los que
    Supabase Auth creó al usuario pero el backend aún no registró el
    Profile espejo.

    Campos del stub:
      - documento_id: primeros 8 caracteres del sub (único por UUID)
      - full_name:    email del JWT o 'User <sub[:8]>' si no hay email
      - pin_hash:     '' (el usuario debe definirlo en onboarding)
      - role:         'student' (default de la tabla)
    """
    stmt = select(Profile).where(Profile.id == profile_id)
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()
    if profile is not None:
        return profile

    short = str(profile_id).replace("-", "")[:8]
    email = jwt_payload.get("email")
    full_name = str(email) if email else f"User {short}"

    profile = Profile(
        id=profile_id,
        documento_id=short,
        full_name=full_name,
        pin_hash="",  # stub: se completa en onboarding real
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


# =============================================================================
# 3.3 get_memberships
# =============================================================================
async def get_memberships(
    db: AsyncSession, profile_id: UUID
) -> list[tuple[Membership, Tenant]]:
    """Devuelve (Membership, Tenant) para cada membership activo del profile.

    Se hace JOIN explícito para traer `tenant.name` y `tenant.slug` en
    una sola query. El llamador mapea a `MembershipOut`.
    """
    stmt = (
        select(Membership, Tenant)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(
            Membership.profile_id == profile_id,
            Membership.is_active.is_(True),
        )
    )
    result = await db.execute(stmt)
    return [(m, t) for m, t in result.all()]


def memberships_to_schema(
    rows: list[tuple[Membership, Tenant]],
) -> list[MembershipOut]:
    """Helper: convierte filas ORM a la respuesta Pydantic."""
    return [
        MembershipOut(
            tenant_id=m.tenant_id,
            tenant_name=t.name,
            tenant_slug=t.slug,
            role=m.role,
            group_code=m.group_code,
            is_active=m.is_active,
        )
        for m, t in rows
    ]


def profile_to_schema(
    profile: Profile, memberships: list[MembershipOut]
) -> ProfileOut:
    """Helper: arma el ProfileOut combinando perfil + memberships."""
    return ProfileOut(
        id=profile.id,
        documento_id=profile.documento_id,
        full_name=profile.full_name,
        role=profile.role,
        current_streak=profile.current_streak,
        longest_streak=profile.longest_streak,
        xp=profile.xp,
        level=profile.level,
        is_active=profile.is_active,
        last_attendance_date=profile.last_attendance_date,
        memberships=memberships,
    )


# =============================================================================
# 3.4 build_auth_context
# =============================================================================
_STAFF_ROLES = {"teacher", "admin", "super_admin"}
_ADMIN_ROLES = {"admin", "super_admin"}


def build_auth_context(
    profile: Profile,
    memberships: list[tuple[Membership, Tenant]],
    tenant_id_header: str | None = None,
) -> AuthContext:
    """Construye el contexto autenticado resolviendo el tenant activo.

    Reglas:
      - Si `tenant_id_header` viene, debe coincidir con alguno de los
        memberships del usuario; si no, 403.
      - Si no viene, se usa el primer membership activo.
      - Si el usuario no tiene memberships activos, 403.
    """
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no active tenant memberships",
        )

    chosen: tuple[Membership, Tenant] | None = None
    if tenant_id_header:
        try:
            wanted = UUID(tenant_id_header)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="X-Tenant-ID header is not a valid UUID",
            ) from exc
        for m, t in memberships:
            if m.tenant_id == wanted:
                chosen = (m, t)
                break
        if chosen is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not a member of the requested tenant",
            )
    else:
        chosen = memberships[0]

    membership, _tenant = chosen
    role = membership.role
    return AuthContext(
        profile_id=profile.id,
        role=role,
        tenant_id=membership.tenant_id,
        group_code=membership.group_code,
        is_teacher=role in _STAFF_ROLES,
        is_admin=role in _ADMIN_ROLES,
    )
