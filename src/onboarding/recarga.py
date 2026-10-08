"""`recargar`: el operador emite monedas a la bolsa de UNA institución.

    python -m src.onboarding recargar --slug <slug> --monedas <n> \\
        --operador "<quién>" --motivo "<por qué>" --referencia <id único>

Espec: `docs/ESPEC_economia_oleada0.md` §1.6. Es EMISIÓN de monedas: correrla
con datos reales es producción y necesita el sí de Christiam cada vez.

Qué hace, en UNA transacción (todo o nada):
  1. candado sobre la billetera de la institución (el mismo que toma
     `award_coins`: una recarga y una paga nunca se pisan);
  2. una fila en `coin_ledger`: origen NULL (nadie pierde esas monedas: se
     emiten), destino la billetera de la institución, `action = 'pool_topup'`,
     llave `topup:<referencia>` y, en `metadata`, quién, por qué y los saldos;
  3. `balance += n` en la billetera;
  4. `tenants.coin_pool += n`: desde esta oleada `coin_pool` es LO EMITIDO EN
     TOTAL (lo inicial más las recargas), y de ahí sale el umbral de la alerta.

Idempotente por referencia: repetir la orden con la misma referencia y el mismo
monto no cambia nada (`repetida: true`); con OTRO monto es un error (salida 1).

Este módulo solo calcula y mueve monedas: la guardia estática
(`tests/engrama_core/guardia_monedas.py`) le prohíbe `round`, `float` y `/`.
A propósito NO importa `src.shared.config`: la CLI no necesita el secreto JWT.
"""
from __future__ import annotations

import os
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.engrama_core.service import economia
from src.onboarding.alta import Sesiones
from src.onboarding.cuentas import ErrorDeConfiguracion
from src.shared.models import CoinLedger, CoinWallet, Tenant

ACCION_RECARGA = "pool_topup"
# `tenants.coin_pool` es INTEGER (llega a 2.147.483.647): lo emitido en total no
# puede pasar de aquí, o la base rechazaría la suma a mitad de la transacción.
EMISION_MAXIMA = 2_000_000_000
# El defecto y el rango de `BOLSA_RECARGA_MAXIMA` (los mismos de `Settings`).
RECARGA_MAXIMA_POR_DEFECTO = 1_000_000
RECARGA_MAXIMA_RANGO = (1, 100_000_000)


# =============================================================================
# 1. Antes de abrir la base: la configuración y los argumentos
# =============================================================================
def entero_del_entorno(nombre: str, defecto: int, minimo: int, maximo: int) -> int:
    """Una variable entera del entorno, con su defecto y su rango.

    La CLI lee así sus números (y `DATABASE_URL`): directo del entorno, sin
    cargar la configuración de la aplicación web.
    """
    texto = os.environ.get(nombre, "").strip()
    if not texto:
        return defecto
    try:
        valor = int(texto)
    except ValueError as exc:
        raise ErrorDeConfiguracion(f"{nombre} debe ser un número entero") from exc
    if not minimo <= valor <= maximo:
        raise ErrorDeConfiguracion(f"{nombre} debe estar entre {minimo} y {maximo}")
    return valor


def recarga_maxima() -> int:
    """`BOLSA_RECARGA_MAXIMA`: lo más que se puede recargar en una sola orden."""
    return entero_del_entorno("BOLSA_RECARGA_MAXIMA", RECARGA_MAXIMA_POR_DEFECTO,
                              *RECARGA_MAXIMA_RANGO)


def motivo_de_rechazo(*, slug: str | None, monedas: int | None, operador: str | None,
                      motivo: str | None, referencia: str | None, maximo: int) -> str | None:
    """Por qué la orden NO se corre (salida 2), o None si se puede correr.

    Pura: se decide antes de abrir la base. `--operador`, `--motivo` y
    `--referencia` son obligatorios y no pueden ir en blanco: una emisión de
    monedas sin quién, sin por qué o sin referencia no se puede auditar.
    """
    textos = {"--slug": slug, "--operador": operador, "--motivo": motivo,
              "--referencia": referencia}
    for nombre, valor in textos.items():
        if valor is None or not valor.strip():
            return f"falta {nombre}"
    if monedas is None:
        return "falta --monedas"
    if monedas <= 0:
        return "--monedas debe ser mayor que 0"
    if monedas > maximo:
        return f"--monedas no puede pasar de {maximo} por recarga (BOLSA_RECARGA_MAXIMA)"
    return None


# =============================================================================
# 2. Los tres movimientos (cada uno, una función: así cada uno tiene su tramposo)
# =============================================================================
async def _billetera_con_candado(db: AsyncSession, tenant_id: UUID) -> CoinWallet | None:
    """La billetera de la institución, bloqueada hasta el fin de la transacción."""
    return (await db.execute(
        select(CoinWallet).where(CoinWallet.owner_type == "tenant",
                                 CoinWallet.owner_id == tenant_id,
                                 CoinWallet.currency == "COIN").with_for_update()
    )).scalar_one_or_none()


async def _asentar(db: AsyncSession, tenant_id: UUID, billetera_id: UUID, monedas: int,
                   llave: str, metadata: dict[str, Any]) -> None:
    """La fila del libro. Origen NULL = emisión; el UNIQUE de la llave la protege."""
    db.add(CoinLedger(tenant_id=tenant_id, from_wallet_id=None, to_wallet_id=billetera_id,
                      amount=monedas, action=ACCION_RECARGA, ledger_metadata=metadata,
                      idempotency_key=llave))
    await db.flush()


async def _mover_saldo(db: AsyncSession, billetera: CoinWallet, monedas: int) -> None:
    billetera.balance = billetera.balance + monedas
    await db.flush()


async def _subir_emitido(db: AsyncSession, tenant: Tenant, monedas: int) -> None:
    """`coin_pool` = lo emitido en total. Solo lo cambia una recarga (con el candado)."""
    tenant.coin_pool = tenant.coin_pool + monedas
    await db.flush()


# =============================================================================
# 3. La recarga (una transacción; el commit lo hace `correr_recarga`)
# =============================================================================
def _sin_cambios(slug: str, error: str) -> dict[str, Any]:
    return {"institucion": slug, "recargado": 0, "error": error}


async def _recarga_previa(db: AsyncSession, tenant_id: UUID, llave: str) -> CoinLedger | None:
    return (await db.execute(
        select(CoinLedger).where(CoinLedger.tenant_id == tenant_id,
                                 CoinLedger.idempotency_key == llave)
    )).scalar_one_or_none()


async def _recargar(db: AsyncSession, *, slug: str, monedas: int, operador: str, motivo: str,
                    referencia: str) -> dict[str, Any]:
    """Los pasos 1 a 4 del encabezado. Con `error` o `repetida` no cambió nada."""
    tenant = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if tenant is None:
        return _sin_cambios(slug, f"no existe la institución {slug!r}")
    billetera = await _billetera_con_candado(db, tenant.id)
    if billetera is None:
        return _sin_cambios(slug, "la institución no tiene billetera")
    # Con el candado tomado, lo emitido se relee: otra recarga pudo terminar
    # justo antes y dejar viejo el valor leído arriba.
    await db.refresh(tenant)
    llave = economia.llave_recarga(referencia)
    previa = await _recarga_previa(db, tenant.id, llave)
    if previa is not None:
        if previa.action == ACCION_RECARGA and previa.amount == monedas:
            return {"institucion": slug, "recargado": 0, "saldo": int(billetera.balance),
                    "emitido": int(tenant.coin_pool), "repetida": True}
        return _sin_cambios(slug, f"la referencia {referencia!r} ya se usó con otro monto "
                                  f"({previa.amount}): no se recargó nada")
    if tenant.coin_pool + monedas > EMISION_MAXIMA:
        return _sin_cambios(slug, f"lo emitido pasaría de {EMISION_MAXIMA}: no se recargó nada")
    saldo_antes = int(billetera.balance)
    await _asentar(db, tenant.id, billetera.id, monedas, llave,
                   {"operador": operador, "motivo": motivo, "saldo_antes": saldo_antes,
                    "saldo_despues": saldo_antes + monedas})
    await _mover_saldo(db, billetera, monedas)
    await _subir_emitido(db, tenant, monedas)
    return {"institucion": slug, "recargado": monedas, "saldo": int(billetera.balance),
            "emitido": int(tenant.coin_pool), "repetida": False}


async def correr_recarga(*, slug: str, monedas: int, operador: str, motivo: str,
                         referencia: str, sesiones: Sesiones) -> dict[str, Any]:
    """`recargar` de punta a punta. Si algo revienta a mitad, NADA queda escrito."""
    async with sesiones() as db:
        try:
            datos = await _recargar(db, slug=slug.strip(), monedas=monedas,
                                    operador=operador.strip(), motivo=motivo.strip(),
                                    referencia=referencia.strip())
            if datos.get("recargado"):
                await db.commit()
            else:
                await db.rollback()  # error o repetida: se suelta el candado sin escribir
        except BaseException:
            await db.rollback()
            raise
    return datos
