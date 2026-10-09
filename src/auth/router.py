"""Endpoints HTTP del módulo auth — SPECS/01-auth.md §5.

Expone:
  - POST /auth/session  : perfil + memberships (al iniciar sesión).
  - GET  /auth/me       : mismo payload, para refrescar.
  - POST /auth/logout   : 200 OK + audit log (el logout real es frontend).
  - POST /auth/contrasena : cambia la contraseña temporal (ESPEC_login_piloto §1.5).
  - POST /auth/consentimiento : registra la aceptación del aviso de datos
    (ESPEC_consentimiento).

Todos requieren un JWT válido vía `get_current_user`. El router no habla
directamente con la DB salvo para logout (audit_logs).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.cuentas import CambioDeClave, CambioFallido, ClaveRechazada, get_cambio_de_clave
from src.auth import consentimiento
from src.auth.consentimiento import registrar_consentimiento, ultima_version
from src.auth.schemas import (
    AuthContext,
    ConfirmedLevelOut,
    CambioDeClaveIn,
    ConsentimientoIn,
    ConsentimientoOut,
    ProfileOut,
)
from src.auth.service import (
    Membresias,
    exigir_perfil,
    get_memberships,
    get_profile,
    memberships_to_schema,
    profile_to_schema,
    quitar_contrasena_temporal,
)
from src.engrama_core.service import level
from src.shared.db import get_db
from src.shared.deps import _extract_bearer_token, get_current_user
from src.shared.validacion import RutaSinEco

router = APIRouter()


async def _build_profile_payload(
    auth: AuthContext, db: AsyncSession
) -> ProfileOut:
    """Reusable: carga Profile + memberships del usuario autenticado.

    El colegio activo es el que ya resolvió `get_current_user` (`auth.tenant_id`).
    """
    profile = exigir_perfil(await get_profile(db, auth.profile_id))
    rows = await get_memberships(db, auth.profile_id)
    payload = profile_to_schema(profile, Membresias(memberships_to_schema(rows), auth.tenant_id))
    # El consentimiento es de la persona: no depende del colegio activo.
    return payload.model_copy(update={
        "consent_version": await ultima_version(db, auth.profile_id),
        "confirmed_level": await _nivel_confirmado(auth, db)})


async def _nivel_confirmado(auth: AuthContext, db: AsyncSession) -> ConfirmedLevelOut | None:
    """El nivel confirmado en la institución ACTIVA (cada institución tiene el suyo)."""
    nivel = await level.read_confirmed_level(db, auth.profile_id, auth.tenant_id)
    if nivel is None:
        return None
    return ConfirmedLevelOut(cefr=nivel.cefr, source=nivel.source,
                             provisional=nivel.provisional, assessed_at=nivel.assessed_at)


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


async def cambiar_contrasena(
    payload: CambioDeClaveIn,
    auth: AuthContext = Depends(get_current_user),
    authorization: str | None = Header(default=None),
    cambio: CambioDeClave | None = Depends(get_cambio_de_clave),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Cambia la contraseña en GoTrue y, si GoTrue la acepta, quita la bandera.

    Es una de las 4 rutas que se pueden usar con la contraseña temporal. Un
    `nueva` de menos de 10 o más de 72 caracteres ya dio 422 antes de llegar
    aquí (sin llamar a GoTrue).
      - GoTrue 200            -> bandera en false, commit y 204.
      - GoTrue 422            -> 422 `password_rejected` (bandera igual).
      - sin respuesta, 5xx... -> 502 `password_change_failed` (bandera igual).
      - sin URL de GoTrue     -> 503 `password_change_not_configured`.
    """
    if cambio is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="password_change_not_configured")
    # El mismo Bearer que ya validó `get_current_user`: GoTrue lo valida otra vez.
    token = _extract_bearer_token(authorization)
    try:
        await cambio.cambiar(token, payload.nueva)
    except ClaveRechazada as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="password_rejected") from exc
    except CambioFallido as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="password_change_failed") from exc
    await quitar_contrasena_temporal(db, auth.profile_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Se registra con `RutaSinEco` (y no con el decorador, que no admite la clase de
# ruta): el 422 de una contraseña inválida no devuelve la contraseña en `input`
# (ESPEC_autorregistro §13.1). Solo esta ruta; el resto de /auth no cambia.
router.add_api_route("/contrasena", cambiar_contrasena, methods=["POST"],
                     status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
                     route_class_override=RutaSinEco)


@router.post("/consentimiento", response_model=ConsentimientoOut, status_code=status.HTTP_200_OK)
async def aceptar_consentimiento(
    payload: ConsentimientoIn,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConsentimientoOut:
    """Registra que el usuario autenticado aceptó esa versión del aviso de datos.

    La persona sale del token (nadie registra por otro) y la fecha la pone la
    base. Repetir la misma versión devuelve la fecha de la primera vez.
    Con la contraseña temporal responde 403 `must_change_password`, como toda
    ruta que no está en la lista de permitidas.
    """
    consentimiento.exigir_version_permitida(payload.version)
    accepted_at = await registrar_consentimiento(
        db, profile_id=auth.profile_id, tenant_id=auth.tenant_id, version=payload.version)
    await db.commit()
    return ConsentimientoOut(version=payload.version, accepted_at=accepted_at)
