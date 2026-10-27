"""El envío del correo, DESPUÉS de responder — `docs/ESPEC_invitar_profe.md` §3.4.

La ruta deja `enviar` en `BackgroundTasks`: la respuesta al admin no espera a
GoTrue, y así no se distingue por el tiempo un correo nuevo de uno que ya tenía
cuenta en otra institución (§1.3). Aquí solo se habla con GoTrue y se escribe al
log: ninguna fila de la base cambia.

La regla que cierra P9 (`/invite` a un correo sin cuenta CREA una cuenta con un
id que elige GoTrue): `/invite` y `/recover` se llaman SOLO sobre una cuenta
cuyo `id` es el perfil de ESTA invitación y cuyo correo es el de ESTA
invitación. Un correo que ya era de otra cuenta queda como `cuenta_ajena`: no
se le manda nada y no se toca esa cuenta.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.onboarding.cuentas import CREADA, ENVIADA, YA_CONFIRMADA, ErrorCuenta
from src.registro.cuentas import CuentasDeInvitacion
from src.shared.db import AsyncSessionLocal
from src.shared.models import InvitacionDocente

logger = logging.getLogger("engrama.invitar")

# Lo que queda en el log (nunca en una respuesta: el admin ve "enviada" igual).
RECUPERACION = "recuperacion"
CUENTA_AJENA = "cuenta_ajena"
FALLO = "fallo"
CANCELADA = "cancelada"  # solo para el log: la fila ya no existe


@dataclass(frozen=True)
class PedidoDeEnvio:
    """Lo que el envío necesita: qué invitación, el perfil y el correo (en minúsculas)."""

    invitacion_id: int
    profile_id: UUID
    correo: str


Sesiones = async_sessionmaker[AsyncSession]


async def _sigue(sesiones: "Sesiones | None", invitacion_id: int) -> bool:
    """¿La invitación sigue existiendo? (auditoría del delta, H-2). Con una sesión PROPIA:
    el envío corre después de responder, y el admin pudo cancelarla mientras tanto.
    Sin `sesiones` (las pruebas sin base) se supone que sí."""
    if sesiones is None:
        return True
    async with sesiones() as db:
        return (await db.execute(select(InvitacionDocente.id).where(
            InvitacionDocente.id == invitacion_id))).first() is not None


async def _invitar_o_recuperar(cuentas: CuentasDeInvitacion, correo: str,
                               confirmada: bool, sigue: "Callable[[], Awaitable[bool]]") -> str:
    """Cuenta propia sin confirmar: invitación. Ya confirmada (abrió el enlace y no
    terminó, P7): el correo de recuperar, que sí le sirve."""
    if not await sigue():
        return CANCELADA
    if not confirmada:
        resultado = await cuentas.invitar(correo)
        if resultado != YA_CONFIRMADA:
            return resultado
    resultado = await cuentas.recuperar(correo)
    return RECUPERACION if resultado == ENVIADA else resultado


async def _enviar(cuentas: CuentasDeInvitacion, pedido: PedidoDeEnvio,
                  sesiones: "Sesiones | None" = None) -> str:
    def sigue() -> Awaitable[bool]:
        return _sigue(sesiones, pedido.invitacion_id)

    estado = await cuentas.estado_de_cuenta(pedido.profile_id)
    if estado is None:
        if not await sigue():
            return CANCELADA  # se canceló mientras tanto: ni cuenta ni correo
        if await cuentas.crear_invitado(pedido.profile_id, pedido.correo) != CREADA:
            return CUENTA_AJENA  # el correo ya es de otra cuenta: ni se toca ni se avisa
        return await _invitar_o_recuperar(cuentas, pedido.correo, False, sigue)
    correo, confirmada = estado
    if correo.lower() != pedido.correo:
        return CUENTA_AJENA  # defensa: con un uuid4 nuevo no debería pasar nunca
    return await _invitar_o_recuperar(cuentas, pedido.correo, confirmada, sigue)


def get_sesiones() -> Sesiones:
    """Dependencia: con qué abrir una sesión PROPIA después de responder (la de la
    petición ya se cerró). Las pruebas la reemplazan por la del arnés."""
    return AsyncSessionLocal


async def _guardar_resultado(sesiones: Sesiones, invitacion_id: int, resultado: str) -> None:
    """`ultimo_resultado` de la fila (H-3): interno, solo para el operador."""
    try:
        async with sesiones() as db:
            await db.execute(update(InvitacionDocente)
                             .where(InvitacionDocente.id == invitacion_id)
                             .values(ultimo_resultado=resultado,
                                     ultimo_resultado_en=func.now()))
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — corre tras la respuesta: nada puede escapar
        logger.error("invitar: invitacion=%s no se guardó el resultado (%s)", invitacion_id,
                     type(exc).__name__)


async def _intentar(cuentas: CuentasDeInvitacion, pedido: PedidoDeEnvio,
                    sesiones: Sesiones | None = None) -> str:
    try:
        resultado = await _enviar(cuentas, pedido, sesiones)
    except ErrorCuenta as exc:
        logger.error("invitar: invitacion=%s resultado=%s (%s)", pedido.invitacion_id, FALLO, exc)
        return FALLO
    except Exception as exc:  # noqa: BLE001 — corre tras la respuesta: nada puede escapar
        logger.error("invitar: invitacion=%s resultado=%s (%s)", pedido.invitacion_id, FALLO,
                     type(exc).__name__)
        return FALLO
    nivel = logging.INFO if resultado in (ENVIADA, RECUPERACION, CUENTA_AJENA, CANCELADA) else logging.ERROR
    logger.log(nivel, "invitar: invitacion=%s resultado=%s", pedido.invitacion_id, resultado)
    return resultado


async def enviar(cuentas: CuentasDeInvitacion, pedido: PedidoDeEnvio,
                 sesiones: Sesiones | None = None) -> str:
    """Asegura la cuenta y pide el correo. NUNCA lanza: corre después de responder.

    El log lleva el id de la invitación y el resultado; nunca el correo, el
    nombre ni la clave de servicio (UI5). Con `sesiones`, el resultado queda
    también en la fila (`ultimo_resultado`, H-3), que ninguna ruta devuelve.
    """
    resultado = await _intentar(cuentas, pedido, sesiones)
    if sesiones is not None and resultado != CANCELADA:
        await _guardar_resultado(sesiones, pedido.invitacion_id, resultado)
    return resultado
