"""Lógica de negocio del módulo auth — validación JWT y lookup de perfil.

Implementa las funciones de SPECS/01-auth.md §3 (con el cambio de
docs/ESPEC_login_piloto.md §1.2: ya no hay respaldo que cree perfiles):
  - validate_jwt            : decodifica y verifica un JWT de Supabase.
  - get_profile             : busca el Profile en DB; nunca lo crea.
  - exigir_perfil           : 403 si el `sub` no tiene perfil.
  - exigir_clave_definitiva : 403 si la contraseña es temporal (salvo 4 rutas).
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

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select, update
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
# 3.2b Contraseña temporal (ESPEC_login_piloto §1.5)
# =============================================================================
# La bandera vive en `profiles.force_password_reset` (existe desde la 002).
# NO en `user_metadata` de GoTrue: el propio usuario lo reescribe con
# `PUT /user` y se saltaría el cambio. NO en `app_metadata`: el JWT viejo la
# conserva hasta que vence. En la BD se lee en cada request y la escriben solo
# el alta del operador (true) y `quitar_contrasena_temporal` (false).
DEBE_CAMBIAR = "must_change_password"

# Lista de PERMITIDAS, por (path de la ruta, método): una ruta nueva queda
# bloqueada por defecto. El método importa: con solo el path, una ruta futura
# `DELETE /auth/me` heredaría el permiso sin que nadie lo decida (H-4).
RUTAS_CON_CONTRASENA_TEMPORAL: frozenset[tuple[str, str]] = frozenset({
    ("/auth/me", "GET"), ("/auth/session", "POST"),
    ("/auth/logout", "POST"), ("/auth/contrasena", "POST"),
})


def puede_con_contrasena_temporal(path: str, metodo: str) -> bool:
    """¿Esta ruta se puede usar mientras la contraseña es temporal? (pura)."""
    return (path, metodo.upper()) in RUTAS_CON_CONTRASENA_TEMPORAL


def debe_cambiar_clave(profile: Profile) -> bool:
    """La bandera, SIEMPRE de la BD (una sola fuente: el bloqueo y `/auth/me`)."""
    return bool(profile.force_password_reset)


def exigir_clave_definitiva(profile: Profile, path: str | None, metodo: str) -> None:
    """403 `must_change_password` si la clave es temporal y la ruta no está permitida.

    `path` es la plantilla de la ruta (`request.scope["route"].path`); si no
    se conoce, no se permite: falla cerrado.
    """
    if not debe_cambiar_clave(profile):
        return
    if path is None or not puede_con_contrasena_temporal(path, metodo):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=DEBE_CAMBIAR)


async def quitar_contrasena_temporal(db: AsyncSession, profile_id: UUID) -> None:
    """`force_password_reset = false`, después de que GoTrue aceptó la clave nueva.

    No hace commit: lo hace la ruta. El mismo token sigue sirviendo, porque
    la bandera se lee de la BD en cada request.
    """
    await db.execute(
        update(Profile).where(Profile.id == profile_id).values(force_password_reset=False)
    )


# =============================================================================
# 3.3 get_memberships
# =============================================================================
def orden_membresias() -> tuple[Any, ...]:
    """El orden de las membresías: la más antigua primero (ESPEC_login_piloto §1.3).

    Una sola fuente del ORDER BY (ERR-26). Importa porque, sin `X-Tenant-ID`,
    `build_auth_context` toma la primera: sin orden, el docente de dos
    instituciones caía en cualquiera de las dos (y un reto sin grupo podía
    crearse en la institución equivocada). `Membership.id` desempata dos
    membresías creadas en el mismo instante: así el orden es determinista.
    """
    return (Membership.created_at.asc(), Membership.id.asc())


async def get_memberships(
    db: AsyncSession, profile_id: UUID
) -> list[tuple[Membership, Tenant]]:
    """Devuelve (Membership, Tenant) para cada membership activo del profile.

    Se hace JOIN explícito para traer `tenant.name` y `tenant.slug` en
    una sola query. El llamador mapea a `MembershipOut`. El orden es el de
    `orden_membresias`: la primera es el colegio por defecto.
    """
    stmt = (
        select(Membership, Tenant)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(
            Membership.profile_id == profile_id,
            Membership.is_active.is_(True),
        )
        .order_by(*orden_membresias())
    )
    result = await db.execute(stmt)
    return [(m, t) for m, t in result.all()]


def memberships_to_schema(
    rows: list[tuple[Membership, Tenant]],
) -> list[MembershipOut]:
    """Helper: convierte filas ORM a la respuesta Pydantic.

    `full_name` es el nombre que escribió ESA institución (BUG-11, 032): cada
    colegio pone el suyo y el usuario ve el de cada una en su membresía.
    """
    return [
        MembershipOut(
            tenant_id=m.tenant_id,
            tenant_name=t.name,
            tenant_slug=t.slug,
            role=m.role,
            group_code=m.group_code,
            is_active=m.is_active,
            full_name=m.full_name,
        )
        for m, t in rows
    ]


@dataclass(frozen=True)
class Membresias:
    """Las membresías del usuario y cuál quedó activa en ESTA request.

    `activo` es el `tenant_id` que resolvió `build_auth_context` (con
    `X-Tenant-ID` o, sin él, la membresía más antigua). Viajan juntas para
    que `profile_to_schema` conserve su firma de dos argumentos.
    """

    todas: list[MembershipOut]
    activo: UUID


def nombre_visible(profile: Profile, membresias: Membresias) -> str:
    """El nombre que ve el usuario: el de su membresía ACTIVA (§1.4).

    Si esa membresía no tiene nombre (docentes y admins creados antes de la
    espec del login piloto tienen NULL), se usa `profiles.full_name`, que
    desde la 032 es el nombre propio de la cuenta. No reabre BUG-11: es el
    propio usuario viendo su nombre, y ningún colegio ve el que puso otro.
    """
    for m in membresias.todas:
        if m.tenant_id == membresias.activo and m.full_name is not None:
            return m.full_name
    return profile.full_name


def profile_to_schema(profile: Profile, membresias: Membresias) -> ProfileOut:
    """Helper: arma el ProfileOut combinando perfil + memberships + colegio activo.

    `role`, en la raíz, sigue siendo `profiles.role`: el rol que cuenta para
    los permisos es el de la membresía activa (`AuthContext.role`).
    """
    return ProfileOut(
        id=profile.id,
        documento_id=profile.documento_id,
        full_name=nombre_visible(profile, membresias),
        role=profile.role,
        current_streak=profile.current_streak,
        longest_streak=profile.longest_streak,
        xp=profile.xp,
        level=profile.level,
        is_active=profile.is_active,
        last_attendance_date=profile.last_attendance_date,
        memberships=membresias.todas,
        active_tenant_id=membresias.activo,
        must_change_password=debe_cambiar_clave(profile),
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
      - Si no viene, se usa el primer membership activo: el más antiguo,
        por el orden de `get_memberships` (`orden_membresias`).
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
