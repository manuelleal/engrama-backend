"""Lógica de negocio del módulo auth — validación JWT y lookup de perfil.

Implementa las funciones de SPECS/01-auth.md §3 (con el cambio de
docs/ESPEC_login_piloto.md §1.2: ya no hay respaldo que cree perfiles):
  - validate_jwt            : decodifica y verifica un JWT de Supabase.
  - get_profile             : busca el Profile en DB; nunca lo crea.
  - exigir_perfil           : 403 si el `sub` no tiene perfil.
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
# 3.2 get_profile y exigir_perfil (ESPEC_login_piloto §1.2)
# =============================================================================
# El 403 de "sin perfil" vive SOLO aquí (una sola fuente, ERR-26): lo usan
# `get_current_user` y el payload de `/auth/me` y `/auth/session`.
SIN_PERFIL = "Account has no ENGRAMA profile"


async def get_profile(db: AsyncSession, profile_id: UUID) -> Profile | None:
    """Busca `profiles.id = profile_id`. NUNCA escribe.

    Antes existía un respaldo "solo desarrollo" (`get_or_create_profile`) que
    creaba un perfil stub con `documento_id = sub[:8]` para cualquier `sub`
    desconocido. Tenía dos defectos (ESPEC_login_piloto §0):
      - cualquiera con una cuenta de GoTrue quedaba con perfil en ENGRAMA;
      - si `sub[:8]` coincidía con el `documento_id` de otra persona, el
        INSERT violaba el UNIQUE y la API respondía 500.
    Ahora el perfil lo crea solo el alta (M3, M4 o el operador) y la cuenta
    de GoTrue nace con `id = profiles.id` (§1.1): el `sub` ES el perfil.
    """
    stmt = select(Profile).where(Profile.id == profile_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def exigir_perfil(profile: Profile | None) -> Profile:
    """403 `Account has no ENGRAMA profile` si el `sub` no tiene perfil.

    Es un 403 y no un 401: el JWT es válido (la identidad está probada), lo
    que falta es la cuenta en ENGRAMA. El cliente lo distingue del 403 "sin
    membresía" por el `detail`.
    """
    if profile is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=SIN_PERFIL)
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
