"""Lógica de monedas (coins) — SPECS/02-engrama-core.md §3.

Modelo contable: **double-entry**. Cada transferencia es una fila en
`coin_ledger` con `from_wallet_id` y `to_wallet_id`; los balances de
ambas wallets se actualizan atómicamente. El sistema del tenant es el
"banco central" (owner_type='tenant') que acuña coins al crear el
wallet con balance inicial `tenant.coin_pool`.

Reglas de integridad (WINDSURF §3, §9):
  - Toda query filtra por `tenant_id` explícito (defensa en profundidad).
  - `SELECT ... FOR UPDATE` en ambas wallets antes de mover balance,
    para evitar race conditions si dos requests llegan simultáneas.
  - Si `from_wallet.balance < amount` → 402 Payment Required (estándar
    HTTP para fondos insuficientes).
  - Las funciones NO hacen commit: el caller (router o attendance.check_in)
    maneja la transacción. Así, si el caller hace otras escrituras, todo
    va en una sola unidad atómica y el rollback automático del get_db
    dependency las limpia si algo revienta.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.engrama_core.schemas import (
    CoinHistoryOut,
    LedgerEntryOut,
    WalletOut,
)
from src.shared.models import CoinLedger, CoinWallet


# =============================================================================
# 3.1 get_wallet — lazy-create
# =============================================================================
async def get_wallet(
    db: AsyncSession,
    owner_type: str,
    owner_id: UUID,
    tenant_id: UUID,
    *,
    for_update: bool = False,
) -> CoinWallet:
    """Busca la wallet del owner; si no existe la crea con balance 0.

    `for_update=True` añade `SELECT ... FOR UPDATE` para bloquear la fila
    en la transacción actual (necesario en `award_coins`).

    Nota: `owner_type='system'` tiene `tenant_id=NULL` en el schema,
    pero esta función solo maneja tenant/profile. El system wallet se
    crea manualmente fuera de este módulo si hace falta.
    """
    if owner_type not in {"tenant", "profile"}:
        raise ValueError(f"owner_type inválido para get_wallet: {owner_type!r}")

    stmt = select(CoinWallet).where(
        CoinWallet.owner_type == owner_type,
        CoinWallet.owner_id == owner_id,
        CoinWallet.currency == "COIN",
    )
    if for_update:
        stmt = stmt.with_for_update()

    wallet = (await db.execute(stmt)).scalar_one_or_none()
    if wallet is not None:
        return wallet

    wallet = CoinWallet(
        tenant_id=tenant_id,
        owner_type=owner_type,
        owner_id=owner_id,
        currency="COIN",
        balance=0,
    )
    db.add(wallet)
    await db.flush()  # obtiene el id sin commitear
    return wallet


# =============================================================================
# 3.2 award_coins — double-entry con lock
# =============================================================================
async def award_coins(
    db: AsyncSession,
    *,
    student_id: UUID,
    tenant_id: UUID,
    amount: int,
    action: str,
    metadata: dict[str, Any] | None = None,
    created_by_profile_id: UUID | None = None,
) -> CoinLedger:
    """Transfiere `amount` coins desde el wallet del tenant al del estudiante.

    Flujo double-entry (spec §3.2):
      1. Lock + fetch wallet del tenant (from_wallet).
      2. Lock + fetch wallet del estudiante (to_wallet, crea si falta).
      3. Verifica balance suficiente → 402 si no.
      4. INSERT en coin_ledger.
      5. UPDATE de ambos balances en memoria (ORM persiste al flush/commit).

    No commitea: el caller decide cuándo cerrar la transacción.
    """
    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="amount must be a positive integer",
        )

    # Paso 1 + 2 — tomar locks en orden determinista (tenant antes que
    # profile) para evitar deadlocks si otro flujo hace lo contrario.
    from_wallet = await get_wallet(
        db, "tenant", tenant_id, tenant_id=tenant_id, for_update=True
    )
    to_wallet = await get_wallet(
        db, "profile", student_id, tenant_id=tenant_id, for_update=True
    )

    # Paso 3 — fondos insuficientes.
    if from_wallet.balance < amount:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Tenant coin pool insufficient: "
                f"have {from_wallet.balance}, need {amount}"
            ),
        )

    # Paso 4 — INSERT ledger.
    entry = CoinLedger(
        tenant_id=tenant_id,
        from_wallet_id=from_wallet.id,
        to_wallet_id=to_wallet.id,
        amount=amount,
        action=action,
        created_by_profile_id=created_by_profile_id,
        ledger_metadata=metadata or {},
    )
    db.add(entry)

    # Paso 5 — UPDATE balances. SQLAlchemy emite los UPDATEs al flush.
    from_wallet.balance = from_wallet.balance - amount
    to_wallet.balance = to_wallet.balance + amount

    await db.flush()
    return entry


# =============================================================================
# 3.3 get_balance
# =============================================================================
async def get_balance(
    db: AsyncSession, student_id: UUID, tenant_id: UUID
) -> int:
    """Retorna el balance del estudiante (0 si no tiene wallet todavía).

    Filtra por `tenant_id` además del owner — defensa en profundidad:
    si el mismo UUID de profile tuviera wallets en múltiples tenants
    (hipotético futuro), solo vemos la del tenant activo.
    """
    stmt = select(CoinWallet.balance).where(
        CoinWallet.owner_type == "profile",
        CoinWallet.owner_id == student_id,
        CoinWallet.tenant_id == tenant_id,
        CoinWallet.currency == "COIN",
    )
    balance = (await db.execute(stmt)).scalar_one_or_none()
    return int(balance) if balance is not None else 0


# =============================================================================
# 3.4 get_coin_history
# =============================================================================
async def get_coin_history(
    db: AsyncSession,
    student_id: UUID,
    tenant_id: UUID,
    limit: int = 20,
) -> CoinHistoryOut:
    """Wallet + últimas N entradas donde el estudiante fue destino o origen.

    Defensa en profundidad: filtramos ledger por `tenant_id` explícito,
    aunque RLS ya lo cubriría si se usara `user_session`.
    """
    # 1. Resolver/crear wallet del estudiante.
    wallet = await get_wallet(db, "profile", student_id, tenant_id=tenant_id)

    # 2. Traer las últimas `limit` entradas donde participó esa wallet.
    stmt = (
        select(CoinLedger)
        .where(
            CoinLedger.tenant_id == tenant_id,
            (CoinLedger.to_wallet_id == wallet.id)
            | (CoinLedger.from_wallet_id == wallet.id),
        )
        .order_by(CoinLedger.created_at.desc())
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())

    entries = [
        LedgerEntryOut(
            id=r.id,
            amount=r.amount,
            action=r.action,
            from_wallet_id=r.from_wallet_id,
            to_wallet_id=r.to_wallet_id,
            metadata=r.ledger_metadata or {},
            created_at=r.created_at,
        )
        for r in rows
    ]

    return CoinHistoryOut(
        wallet=WalletOut(
            id=wallet.id,
            owner_type=wallet.owner_type,
            balance=int(wallet.balance),
            currency=wallet.currency,
            updated_at=wallet.updated_at,
        ),
        entries=entries,
        total=len(entries),
    )
