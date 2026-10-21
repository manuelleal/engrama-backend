"""El libro de doble entrada de la ola 1: UNA función para trasladar monedas.

docs/ESPEC_ola1_economia.md §1.1. Hasta la ola 1 la única función que movía
monedas era `coins.award_coins`, y siempre de la bolsa al estudiante. La ola 1
necesita seis caminos más (recargar y devolver el bolsillo del profe, Dar,
Corregir, comprar y devolver una compra) y todos son lo mismo: sacar de una
billetera y poner en otra, con su asiento. Por eso viven aquí juntos, y
`award_coins` NO se toca (sus pagos quedan idénticos).

Reglas de la casa que se repiten aquí:
  - Doble entrada: cada traslado es UNA fila de `coin_ledger` con origen y
    destino; los dos saldos se mueven en la misma transacción. Así, la suma de
    la bolsa, los bolsillos y los saldos de una institución nunca cambia.
  - Nada se commitea aquí: quien llama cierra la transacción (y si algo
    revienta, el rollback del request deshace todo, también el reclamo de la llave).
  - Orden de bloqueo de toda la ola: `tenant` → `membership`/`auction` → `profile` (el
    mismo de `award_coins`: tenant antes que profile). Quien llama toma los
    `FOR UPDATE` en ese orden, con `billetera(..., bloquear=True)`, ANTES de
    llamar a `transferir`. Dos flujos que bloquean en el mismo orden no se
    traban entre sí.
  - La llave de idempotencia la garantiza el UNIQUE `(tenant_id,
    idempotency_key)` de la 033, no este código.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.models import CoinLedger, CoinWallet

# Los dueños que maneja la ola 1. `membership` es el bolsillo del profe en UNA
# institución (owner_id = memberships.id) y `auction` lo retenido del líder de una
# subasta (owner_id = auctions.id); los dos llegan con la migración 047.
DUENOS = ("tenant", "membership", "auction", "profile")


class SaldoInsuficiente(Exception):
    """El origen no alcanza. Cada ruta la traduce a su código (402 o 409)."""

    def __init__(self, saldo: int, monto: int) -> None:
        super().__init__(f"saldo {saldo} < monto {monto}")
        self.saldo = saldo
        self.monto = monto


async def billetera(
    db: AsyncSession,
    dueno: str,
    owner_id: UUID,
    tenant_id: UUID,
    *,
    bloquear: bool = False,
    crear: bool = True,
) -> CoinWallet | None:
    """La billetera COIN de ese dueño; si no existe y `crear`, nace con saldo 0.

    La bolsa (`tenant`) y el bolsillo (`membership`) se buscan además por
    institución: nunca se toma la de otra. La del estudiante (`profile`) se
    busca como en `coins.get_wallet` (es global por perfil, ESPEC §8).
    """
    if dueno not in DUENOS:
        raise ValueError(f"dueño inválido: {dueno!r}")
    stmt = select(CoinWallet).where(
        CoinWallet.owner_type == dueno,
        CoinWallet.owner_id == owner_id,
        CoinWallet.currency == "COIN",
    )
    if dueno != "profile":
        stmt = stmt.where(CoinWallet.tenant_id == tenant_id)
    if bloquear:
        stmt = stmt.with_for_update()
    encontrada = (await db.execute(stmt)).scalar_one_or_none()
    if encontrada is not None or not crear:
        return encontrada
    nueva = CoinWallet(tenant_id=tenant_id, owner_type=dueno, owner_id=owner_id,
                       currency="COIN", balance=0)
    db.add(nueva)
    await db.flush()  # el id, sin commitear
    return nueva


async def billetera_por_id(
    db: AsyncSession, wallet_id: Any, *, bloquear: bool = False
) -> CoinWallet:
    """La billetera de un asiento ya hecho (Corregir vuelve por el mismo camino)."""
    stmt = select(CoinWallet).where(CoinWallet.id == wallet_id)
    if bloquear:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one()


async def _reclamar(db: AsyncSession, valores: dict[str, Any]) -> CoinLedger | None:
    """INSERT ... ON CONFLICT DO NOTHING de la llave. None = ya estaba."""
    reclamo = (
        pg_insert(CoinLedger)
        .values(**valores)
        .on_conflict_do_nothing(index_elements=["tenant_id", "idempotency_key"])
        .returning(CoinLedger)
    )
    return (await db.execute(reclamo)).scalar_one_or_none()


async def asiento_por_llave(db: AsyncSession, tenant_id: UUID, llave: str) -> CoinLedger | None:
    stmt = select(CoinLedger).where(CoinLedger.tenant_id == tenant_id,
                                    CoinLedger.idempotency_key == llave)
    return (await db.execute(stmt)).scalar_one_or_none()


async def transferir(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    desde: CoinWallet,
    hacia: CoinWallet,
    monto: int,
    accion: str,
    creado_por: UUID | None,
    metadata: dict[str, Any] | None = None,
    llave: str | None = None,
) -> tuple[CoinLedger, bool]:
    """Saca `monto` de `desde` y lo pone en `hacia`. Devuelve (asiento, ¿nuevo?).

    Con `llave`: si ya existía un asiento con ella, lo devuelve con `False` y
    no mueve nada (repetir no es "falta de saldo"). Sin saldo: `SaldoInsuficiente`.
    Las dos billeteras deben venir ya bloqueadas por quien llama.
    """
    if monto <= 0:
        raise ValueError("el monto de un traslado es un entero positivo")
    valores = {"tenant_id": tenant_id, "from_wallet_id": desde.id, "to_wallet_id": hacia.id,
               "amount": monto, "action": accion, "created_by_profile_id": creado_por,
               "ledger_metadata": metadata or {}}
    asiento: CoinLedger | None = None
    if llave is not None:
        asiento = await _reclamar(db, {**valores, "idempotency_key": llave})
        if asiento is None:
            existente = await asiento_por_llave(db, tenant_id, llave)
            if existente is None:  # no debería pasar: el UNIQUE acaba de chocar
                raise RuntimeError("la llave chocó pero su asiento no aparece")
            return existente, False
    if int(desde.balance) < monto:
        raise SaldoInsuficiente(int(desde.balance), monto)
    if asiento is None:
        asiento = CoinLedger(**valores)
        db.add(asiento)
    desde.balance = desde.balance - monto
    hacia.balance = hacia.balance + monto
    await db.flush()
    return asiento, True
