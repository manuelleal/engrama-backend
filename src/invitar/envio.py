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
from dataclasses import dataclass
from uuid import UUID

from src.onboarding.cuentas import CREADA, ENVIADA, YA_CONFIRMADA, ErrorCuenta
from src.registro.cuentas import CuentasDeInvitacion

logger = logging.getLogger("engrama.invitar")

# Lo que queda en el log (nunca en una respuesta: el admin ve "enviada" igual).
RECUPERACION = "recuperacion"
CUENTA_AJENA = "cuenta_ajena"
FALLO = "fallo"


@dataclass(frozen=True)
class PedidoDeEnvio:
    """Lo que el envío necesita: qué invitación, el perfil y el correo (en minúsculas)."""

    invitacion_id: int
    profile_id: UUID
    correo: str


async def _invitar_o_recuperar(cuentas: CuentasDeInvitacion, correo: str,
                               confirmada: bool) -> str:
    """Cuenta propia sin confirmar: invitación. Ya confirmada (abrió el enlace y no
    terminó, P7): el correo de recuperar, que sí le sirve."""
    if not confirmada:
        resultado = await cuentas.invitar(correo)
        if resultado != YA_CONFIRMADA:
            return resultado
    resultado = await cuentas.recuperar(correo)
    return RECUPERACION if resultado == ENVIADA else resultado


async def _enviar(cuentas: CuentasDeInvitacion, pedido: PedidoDeEnvio) -> str:
    estado = await cuentas.estado_de_cuenta(pedido.profile_id)
    if estado is None:
        if await cuentas.crear_invitado(pedido.profile_id, pedido.correo) != CREADA:
            return CUENTA_AJENA  # el correo ya es de otra cuenta: ni se toca ni se avisa
        return await _invitar_o_recuperar(cuentas, pedido.correo, confirmada=False)
    correo, confirmada = estado
    if correo.lower() != pedido.correo:
        return CUENTA_AJENA  # defensa: con un uuid4 nuevo no debería pasar nunca
    return await _invitar_o_recuperar(cuentas, pedido.correo, confirmada)


async def enviar(cuentas: CuentasDeInvitacion, pedido: PedidoDeEnvio) -> str:
    """Asegura la cuenta y pide el correo. NUNCA lanza: corre después de responder.

    El log lleva el id de la invitación y el resultado; nunca el correo, el
    nombre ni la clave de servicio (UI5).
    """
    try:
        resultado = await _enviar(cuentas, pedido)
    except ErrorCuenta as exc:
        logger.error("invitar: invitacion=%s resultado=%s (%s)", pedido.invitacion_id, FALLO, exc)
        return FALLO
    except Exception as exc:  # noqa: BLE001 — corre tras la respuesta: nada puede escapar
        logger.error("invitar: invitacion=%s resultado=%s (%s)", pedido.invitacion_id, FALLO,
                     type(exc).__name__)
        return FALLO
    nivel = logging.INFO if resultado in (ENVIADA, RECUPERACION, CUENTA_AJENA) else logging.ERROR
    logger.log(nivel, "invitar: invitacion=%s resultado=%s", pedido.invitacion_id, resultado)
    return resultado
