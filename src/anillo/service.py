"""El pase acotado del anillo: emitirlo y canjearlo — `docs/ESPEC_pase_acotado.md`.

El problema que resuelve (auditoría 03, S-10): hasta ahora, cuando el estudiante
tocaba «Clase en vivo» o «Examen de nivel», la web mandaba a EVA y a SET el token
de sesión COMPLETO. Si EVA o SET lo dejaban escapar, ese token abría la cuenta en
ENGRAMA durante lo que le quedara de la hora.

Ahora lo que viaja es un PASE ACOTADO:
  - corto: vence a los `ANILLO_PASE_TTL_S` segundos (300 por defecto);
  - de un solo uso: el primer intento de canje lo gasta, salga bien o mal;
  - con audiencia: `eva` o `set`; quien canjea declara la suya;
  - atado a la institución activa de quien lo pidió;
  - y que no sirve para nada más: no es un JWT, así que ninguna ruta lo acepta
    como `Authorization: Bearer`.

La base guarda solo `sha256(pase)`: quien lea la tabla no puede usar lo que ve.
La hora la pone siempre la base (`now()`), al emitir y al canjear.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.consentimiento import ultima_version
from src.auth.schemas import AuthContext
from src.auth.service import (
    DEBE_CAMBIAR,
    Membresias,
    build_auth_context,
    debe_cambiar_clave,
    exigir_cuenta_activa,
    exigir_perfil,
    get_memberships,
    get_profile,
    memberships_to_schema,
    nombre_visible,
)
from src.registro.pendiente import ESPERA_APROBACION, espera_aprobacion
from src.shared.config import settings
from src.teachers.service import access as access_service

from .schemas import CarneOut

# El prefijo deja a EVA y a SET distinguir un pase de un JWT (que empieza por
# `eyJ` y lleva puntos) sin preguntarle a nadie. 32 bytes al azar = 256 bits:
# adivinarlo no es un ataque posible, y por eso basta un sha256 sin sal.
PREFIJO = "pa1_"
BYTES_AL_AZAR = 32

# Los `detail` propios de este módulo. El 401 es UNO solo para "no existe",
# "ya se usó", "venció" y "es de otra audiencia": quien prueba pases no aprende
# nada de la respuesta.
PASE_INVALIDO = "pase_invalido"
DEMASIADOS_PASES = "demasiados_pases"

# Cada emisión borra los vencidos hace más de un día (de cualquiera): la tabla
# queda acotada a un día de uso, sin tarea programada.
SQL_LIMPIAR = "DELETE FROM anillo_pases WHERE expira_en < now() - interval '1 day'"
SQL_VIVOS = (
    "SELECT count(*) FROM anillo_pases "
    "WHERE profile_id = :p AND usado_en IS NULL AND expira_en > now()"
)
SQL_INSERTAR = (
    "INSERT INTO anillo_pases (hash, profile_id, tenant_id, audiencia, expira_en) "
    "VALUES (:h, :p, :t, :a, now() + make_interval(secs => :s))"
)
# EL corazón del solo uso: gastar y leer en UNA sentencia. Si dos canjes llegan a
# la vez, Postgres bloquea la fila para el segundo; cuando el primero hace commit,
# el segundo vuelve a evaluar `usado_en IS NULL`, ya es falso, y no obtiene nada.
# `vigente` se calcula aquí mismo con el `now()` de la base.
SQL_GASTAR = (
    "UPDATE anillo_pases SET usado_en = now() "
    "WHERE hash = :h AND usado_en IS NULL "
    "RETURNING profile_id, tenant_id, audiencia, (expira_en > now()) AS vigente"
)


def generar_pase() -> str:
    """Un pase nuevo: `pa1_` + 43 caracteres url-safe (256 bits al azar)."""
    return PREFIJO + secrets.token_urlsafe(BYTES_AL_AZAR)


def huella(pase: str) -> str:
    """Lo único que se guarda del pase: su sha256 en hexadecimal (64 caracteres)."""
    return hashlib.sha256(pase.encode("utf-8")).hexdigest()


def _invalido() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=PASE_INVALIDO)


# =============================================================================
# Emitir (POST /anillo/pases)
# =============================================================================
async def emitir(db: AsyncSession, auth: AuthContext, audiencia: str) -> str:
    """Crea un pase para `auth` (su institución ACTIVA) y esa audiencia. No hace commit.

    429 `demasiados_pases` si ya tiene `ANILLO_PASES_VIVOS_MAX` vivos (sin usar y
    sin vencer). Dos emisiones simultáneas pueden pasar el tope por una: es un
    freno contra el abuso, no una cuenta exacta.
    """
    await db.execute(text(SQL_LIMPIAR))
    vivos = (await db.execute(text(SQL_VIVOS), {"p": auth.profile_id})).scalar_one()
    if vivos >= settings.anillo_pases_vivos_max:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail=DEMASIADOS_PASES)
    pase = generar_pase()
    await db.execute(text(SQL_INSERTAR), {
        "h": huella(pase), "p": auth.profile_id, "t": auth.tenant_id, "a": audiencia,
        "s": float(settings.anillo_pase_ttl_s),  # make_interval pide double precision
    })
    return pase


# =============================================================================
# Canjear (POST /anillo/canje)
# =============================================================================
@dataclass(frozen=True)
class PaseGastado:
    """Lo que dice la fila de un pase recién gastado y válido."""

    profile_id: UUID
    tenant_id: UUID
    audiencia: str


def es_canjeable(fila: Any, audiencia: str) -> bool:
    """La fila recién gastada vale si no había vencido y es de la audiencia de quien canjea."""
    return bool(fila["vigente"]) and fila["audiencia"] == audiencia


def solo_la_institucion(filas: list[Any], tenant_id: UUID) -> list[Any]:
    """De las membresías, solo la de la institución del pase: las otras no viajan."""
    return [(m, t) for m, t in filas if m.tenant_id == tenant_id]


async def gastar(db: AsyncSession, pase: str, audiencia: str) -> PaseGastado:
    """Gasta el pase y HACE COMMIT antes de revisar nada más.

    El commit va primero a propósito: si después la cuenta resulta suspendida (o
    cualquier otro 403), la excepción haría rollback de la sesión y el pase
    quedaría sin gastar, listo para otro intento. Así, el primer intento lo gasta
    siempre. 401 `pase_invalido` si no existía, ya estaba usado, venció o es de
    otra audiencia (en los dos últimos casos también queda gastado).
    """
    fila = (await db.execute(text(SQL_GASTAR), {"h": huella(pase)})).mappings().first()
    await db.commit()
    if fila is None or not es_canjeable(fila, audiencia):
        raise _invalido()
    return PaseGastado(profile_id=fila["profile_id"], tenant_id=fila["tenant_id"],
                       audiencia=fila["audiencia"])


async def carne(db: AsyncSession, gastado: PaseGastado) -> CarneOut:
    """Las mismas revisiones de `get_current_user` y el carné mínimo para la pieza.

    Los 403 llevan el mismo `detail` que hoy devuelve `/auth/me`: EVA y SET ya
    saben explicarlos. La institución activa es la del pase (como si llegara en
    `X-Tenant-ID`): si la persona ya no es miembro activo de ella, 403.
    """
    profile = exigir_perfil(await get_profile(db, gastado.profile_id))
    exigir_cuenta_activa(profile)
    if debe_cambiar_clave(profile):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=DEBE_CAMBIAR)
    filas = await get_memberships(db, gastado.profile_id)
    if not filas and await espera_aprobacion(db, gastado.profile_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ESPERA_APROBACION)
    auth = build_auth_context(profile, filas, tenant_id_header=str(gastado.tenant_id))

    propias = memberships_to_schema(solo_la_institucion(filas, auth.tenant_id))
    datos: dict[str, Any] = {
        "id": profile.id,
        "full_name": nombre_visible(profile, Membresias(propias, auth.tenant_id)),
        "is_active": profile.is_active,
        "must_change_password": False,  # con la temporal ya respondió 403 arriba
        "consent_version": await ultima_version(db, profile.id),
        "active_tenant_id": auth.tenant_id,
        "memberships": propias,
        "audiencia": gastado.audiencia,
        "grupos_docente": await _grupos_docente(db, auth, gastado.audiencia),
    }
    return CarneOut(**datos)


async def _grupos_docente(db: AsyncSession, auth: AuthContext, audiencia: str) -> list[str] | None:
    """Los grupos del docente, SOLO para SET: con ellos SET deja de llamar a
    `/teachers/groups` con la credencial del docente. `None` en todo lo demás
    (para un admin, SET ya entiende `None` como "toda la institución")."""
    if audiencia != "set" or auth.role != "teacher":
        return None
    return [g.group_code for g in await access_service.visible_groups(db, auth)]
