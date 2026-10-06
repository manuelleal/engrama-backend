"""Registro del consentimiento (aviso de datos, Ley 1581) — `docs/ESPEC_consentimiento.md`.

El backend NO decide si el aviso es válido ni cuál es la versión vigente: solo
guarda que ESTA persona aceptó ESTA versión, y cuándo (la fecha la pone la
base, nunca el cliente). La versión vigente la define el cliente
(`AVISO_VERSION`), que compara por igualdad con `consent_version` de `/auth/me`.

Es por PERSONA (perfil), no por institución: quien está en dos instituciones
tiene una sola cuenta y acepta una vez.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.config import settings
from src.shared.models import Consentimiento

ACCION_DE_AUDITORIA = "consent_accept"
VERSION_NO_PERMITIDA = "aviso_version_no_permitida"


def versiones_validas() -> frozenset[str]:
    """Las versiones de `AVISO_VERSIONES_VALIDAS`; vacío = sin restricción."""
    return frozenset(v.strip() for v in settings.aviso_versiones_validas.split(",")
                     if v.strip())


def version_permitida(version: str) -> bool:
    """¿Se puede registrar esa versión? Con la lista vacía, cualquiera bien formada."""
    validas = versiones_validas()
    return not validas or version in validas


def exigir_version_permitida(version: str) -> None:
    """422 `aviso_version_no_permitida` (H-13): sin esto, cualquiera crea filas sin tope."""
    if not version_permitida(version):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=VERSION_NO_PERMITIDA)


async def registrar_consentimiento(db: AsyncSession, *, profile_id: UUID, tenant_id: UUID,
                                   version: str) -> datetime:
    """Guarda (perfil, versión) y devuelve su `accepted_at`. No hace commit.

    Idempotente: si esa persona ya aceptó esa versión, no se crea otra fila,
    no cambia la fecha y no se agrega auditoría; se devuelve la fecha de la
    primera vez. El `ON CONFLICT` deja la decisión a la base (el UNIQUE), así
    que dos pedidos simultáneos tampoco crean dos filas.
    """
    nueva = (await db.execute(
        insert(Consentimiento)
        .values(profile_id=profile_id, version=version)
        .on_conflict_do_nothing(constraint="consentimientos_perfil_version")
        .returning(Consentimiento.accepted_at)
    )).scalar_one_or_none()
    if nueva is None:
        previa: datetime = (await db.execute(
            select(Consentimiento.accepted_at).where(
                Consentimiento.profile_id == profile_id, Consentimiento.version == version)
        )).scalar_one()
        return previa
    # Auditoría solo de las aceptaciones NUEVAS. `tenant_id` es contexto (la
    # institución activa al aceptar), no parte del consentimiento.
    await db.execute(
        text("""
            INSERT INTO audit_logs (tenant_id, user_id, action_type, result, metadata)
            VALUES (:tenant_id, :user_id, :accion, 'success',
                    jsonb_build_object('version', CAST(:version AS text)))
        """),
        {"tenant_id": tenant_id, "user_id": profile_id, "accion": ACCION_DE_AUDITORIA,
         "version": version},
    )
    return nueva


async def ultima_version(db: AsyncSession, profile_id: UUID) -> str | None:
    """La versión de la ÚLTIMA fila creada para ese perfil, o `None`.

    "Última" es la de mayor `id` (identidad creciente), no la de mayor
    `accepted_at`: la fecha sale del reloj de la base, y un reloj puede
    retroceder (medido en el contenedor de pruebas, ESPEC_login_piloto §3).
    """
    return (await db.execute(
        select(Consentimiento.version)
        .where(Consentimiento.profile_id == profile_id)
        .order_by(Consentimiento.id.desc())
        .limit(1)
    )).scalar_one_or_none()
