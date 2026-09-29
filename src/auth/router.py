"""Endpoints HTTP del módulo auth — SPECS/01-auth.md §5.

Expone:
  - POST /auth/session  : perfil + memberships (al iniciar sesión).
  - GET  /auth/me       : mismo payload, para refrescar.
  - POST /auth/logout   : 200 OK + audit log (el logout real es frontend).
  - POST /auth/contrasena : cambia la contraseña temporal (ESPEC_login_piloto §1.5).

Todos requieren un JWT válido vía `get_current_user`. El router no habla
directamente con la DB salvo para logout (audit_logs).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.cuentas import CambioDeClave, CambioFallido, ClaveRechazada, get_cambio_de_clave
from src.auth.schemas import AuthContext, CambioDeClaveIn, ProfileOut
from src.auth.service import (
    Membresias,
    exigir_perfil,
    get_memberships,
    get_profile,
    memberships_to_schema,
    profile_to_schema,
    quitar_contrasena_temporal,
)
from src.shared.db import get_db
from src.shared.deps import _extract_bearer_token, get_current_user

router = APIRouter()


async def _build_profile_payload(
    auth: AuthContext, db: AsyncSession
) -> ProfileOut:
    """Reusable: carga Profile + memberships del usuario autenticado.

    El colegio activo es el que ya resolvió `get_current_user` (`auth.tenant_id`).
    """
    profile = exigir_perfil(await get_profile(db, auth.profile_id))
    rows = await get_memberships(db, auth.profile_id)
    return profile_to_schema(profile, Membresias(memberships_to_schema(rows), auth.tenant_id))


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


@router.post("/contrasena", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
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
