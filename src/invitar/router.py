"""Rutas de `/admin/invitaciones` — `docs/ESPEC_invitar_profe.md` §3.

Solo el admin de la institución activa (`require_admin`). La respuesta se arma
con la base y se envía; el correo lo pide `envio.enviar` DESPUÉS, en
`BackgroundTasks` (§1.3): la respuesta no espera a GoTrue.
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.invitar import envio, service
from src.invitar.schemas import InvitacionIn, InvitacionOut
from src.registro.cuentas import CuentasDeInvitacion, get_cuentas_de_invitacion
from src.shared.db import get_db
from src.shared.deps import require_admin

router = APIRouter()

NO_CONFIGURADO = "invitar_no_configurado"


def _exigir_cuentas(cuentas: CuentasDeInvitacion | None) -> CuentasDeInvitacion:
    """503 sin GoTrue o sin clave de servicio: depende solo de la configuración."""
    if cuentas is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=NO_CONFIGURADO)
    return cuentas


@router.post("/invitaciones", response_model=InvitacionOut,
             status_code=status.HTTP_201_CREATED)
async def invitar_profe(
    payload: InvitacionIn,
    background: BackgroundTasks,
    auth: AuthContext = Depends(require_admin),
    cuentas: CuentasDeInvitacion | None = Depends(get_cuentas_de_invitacion),
    sesiones: envio.Sesiones = Depends(envio.get_sesiones),
    db: AsyncSession = Depends(get_db),
) -> InvitacionOut:
    """Invita a un profe a un grupo de la institución. El mismo 201 pase lo que pase con el correo."""
    listas = _exigir_cuentas(cuentas)
    resultado = await service.invitar(db, auth, payload)
    await db.commit()
    background.add_task(envio.enviar, listas, resultado.pedido, sesiones)
    return resultado.salida


@router.get("/invitaciones", response_model=list[InvitacionOut],
            status_code=status.HTTP_200_OK)
async def listar_invitaciones(
    auth: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[InvitacionOut]:
    """Las invitaciones de la institución activa, la más reciente primero."""
    return await service.listar(db, auth)


@router.post("/invitaciones/{invitacion_id}/reenviar", response_model=InvitacionOut,
             status_code=status.HTTP_202_ACCEPTED)
async def reenviar_invitacion(
    invitacion_id: int,
    background: BackgroundTasks,
    auth: AuthContext = Depends(require_admin),
    cuentas: CuentasDeInvitacion | None = Depends(get_cuentas_de_invitacion),
    sesiones: envio.Sesiones = Depends(envio.get_sesiones),
    db: AsyncSession = Depends(get_db),
) -> InvitacionOut:
    """Vuelve a mandar el correo de una invitación que no se ha aceptado."""
    listas = _exigir_cuentas(cuentas)
    resultado = await service.reenviar(db, auth, invitacion_id)
    await db.commit()
    background.add_task(envio.enviar, listas, resultado.pedido, sesiones)
    return resultado.salida
