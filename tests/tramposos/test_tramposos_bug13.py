"""Tramposos Y1-Y6 (integ) de BUG-13 — `docs/ESPEC_bug13a15.md` §3.

Mismo patrón que `test_tramposos_bug11.py`: una versión ROTA a propósito, se
corre el cuerpo del test real y se exige `AssertionError` con el mensaje del
mecanismo. Aquí se automatiza la DIAGONAL (las celdas en negrita de §3); la
matriz completa se mide aparte y se escribe en la espec (columna "Rojo
medido"), ERR-15, ERR-19 y ERR-23.

  Y1  `award_coins` = cuerpo viejo (acepta la llave y la descarta) -> A13-1 y A13-3
      (A13-3 prueba que el `FOR UPDATE` solo no basta)
  Y2  `_tomar_intento` sin `.with_for_update()`                    -> A13-2
      (prueba que la llave sola no basta: [200, 200] con una fila)
  Y3  DROP del UNIQUE en la base de la sesión, restaurado al salir -> C13
  Y4  `award_coins` sin llave deduplica con `<action>:<estudiante>` -> K2
  Y5  `_subir()` sin el UPDATE del backfill                        -> B1
  Y6  `_bajar()` sin `DROP COLUMN`                                 -> B2
"""
from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from typing import Any
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
import pytest
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.challenge_engine.service import attempts as attempts_mod
from src.engrama_core.service import coins as coins_mod
from src.shared.models import ChallengeAttempt, CoinLedger
from tests.challenge_engine import test_bug13_una_paga as b13
from tests.integ import test_migracion_033 as mig

pytestmark = pytest.mark.integ

Aplicar = Callable[[Any, pytest.MonkeyPatch], AbstractContextManager[Any]]


# =============================================================================
# Y1, Y4 — `award_coins` roto
# =============================================================================
async def _award_viejo(db: AsyncSession, *, student_id: UUID, tenant_id: UUID, amount: int,
                       action: str, metadata: dict[str, Any] | None = None,
                       created_by_profile_id: UUID | None = None,
                       idempotency_key: str | None = None) -> CoinLedger:
    """Y1: el cuerpo de antes de BUG-13. Acepta `idempotency_key` y la DESCARTA."""
    del idempotency_key
    if amount <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="amount must be a positive integer")
    desde = await coins_mod.get_wallet(db, "tenant", tenant_id, tenant_id=tenant_id,
                                       for_update=True)
    hacia = await coins_mod.get_wallet(db, "profile", student_id, tenant_id=tenant_id,
                                       for_update=True)
    if desde.balance < amount:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED,
                            detail="Tenant coin pool insufficient")
    entry = CoinLedger(tenant_id=tenant_id, from_wallet_id=desde.id, to_wallet_id=hacia.id,
                       amount=amount, action=action,
                       created_by_profile_id=created_by_profile_id,
                       ledger_metadata=metadata or {})
    db.add(entry)
    desde.balance = desde.balance - amount
    hacia.balance = hacia.balance + amount
    await db.flush()
    return entry


_AWARD_BUENO = coins_mod.award_coins


async def _award_deduplica(db: AsyncSession, *, student_id: UUID, action: str,
                           idempotency_key: str | None = None, **resto: Any) -> Any:
    """Y4: sin llave, inventa una: `<action>:<estudiante>` (deduplica lo que no debe)."""
    return await _AWARD_BUENO(db, student_id=student_id, action=action,
                              idempotency_key=idempotency_key or f"{action}:{student_id}",
                              **resto)


# =============================================================================
# Y2 — el intento sin bloqueo
# =============================================================================
async def _tomar_sin_bloqueo(db: AsyncSession, *, attempt_id: UUID, tenant_id: UUID,
                             student_id: UUID) -> ChallengeAttempt | None:
    """Y2: el mismo SELECT de `_tomar_intento`, SIN `.with_for_update()`."""
    stmt = select(ChallengeAttempt).where(ChallengeAttempt.id == attempt_id,
                                          ChallengeAttempt.tenant_id == tenant_id,
                                          ChallengeAttempt.student_id == student_id)
    return (await db.execute(stmt)).scalar_one_or_none()


# =============================================================================
# Y3 — sin el UNIQUE en la base de la sesión
# =============================================================================
_DEF_UNIQUE = f"select pg_get_constraintdef(oid) from pg_constraint where conname = '{mig.UNIQUE}'"


def _sql(integ: Any, sql: str) -> None:
    from sqlalchemy import text

    async def _q() -> None:
        async with integ.engine.begin() as conn:
            await conn.execute(text(sql))

    integ.run(_q())


@contextmanager
def _sin_unique(integ: Any) -> Iterator[None]:
    """Quita el UNIQUE (commit), y al salir lo repone y exige la MISMA definición."""
    antes = integ.valor(_DEF_UNIQUE)
    assert antes is not None, "control Y3: el UNIQUE no existe antes de romperlo"
    _sql(integ, f"alter table coin_ledger drop constraint {mig.UNIQUE}")
    try:
        yield
    finally:
        _sql(integ, f"alter table coin_ledger add constraint {mig.UNIQUE} {antes}")
        assert integ.valor(_DEF_UNIQUE) == antes, "Y3 no dejó el UNIQUE como estaba"


# =============================================================================
# Y5, Y6 — el SQL de la migración sin una sentencia
# =============================================================================
async def _subir_sin_backfill(conn: asyncpg.Connection) -> None:
    """Y5: SQL_SUBIR sin la sentencia del backfill (la que hace el UPDATE)."""
    for sql in mig.M033.SQL_SUBIR:
        if "UPDATE coin_ledger" not in sql:
            await conn.execute(sql)


async def _bajar_sin_drop_column(conn: asyncpg.Connection) -> None:
    """Y6: SQL_BAJAR sin `DROP COLUMN`."""
    for sql in mig.M033.SQL_BAJAR:
        if "DROP COLUMN" not in sql:
            await conn.execute(sql)


def _parche(objetivo: Any, nombre: str, valor: Any) -> Aplicar:
    def aplicar(_integ: Any, mp: pytest.MonkeyPatch) -> AbstractContextManager[Any]:
        mp.setattr(objetivo, nombre, valor)
        return nullcontext()
    return aplicar


def correr(test_real: Callable[..., None], integ: Any, mp: pytest.MonkeyPatch) -> None:
    """Corre el cuerpo de un test real; le pasa `monkeypatch` si lo pide (A13-2, A13-3)."""
    if "monkeypatch" in inspect.signature(test_real).parameters:
        test_real(integ, mp)
    else:
        test_real(integ)


# =============================================================================
# Registro: id -> (cómo romper, [(test real, mensaje con el que debe caer)])
# =============================================================================
TRAMPOSOS: dict[str, tuple[Aplicar, list[tuple[Callable[..., None], str]]]] = {
    "Y1": (_parche(coins_mod, "award_coins", _award_viejo), [
        (b13.test_a13_1_segunda_victoria_del_mismo_reto_no_paga,
         r"la 2\.ª victoria pagó 20 monedas y 15 XP"),
        (b13.test_a13_3_dos_intentos_en_vuelo_pagan_una_vez,
         r"dos intentos en vuelo cobran de más: \{'estados': \[200, 200\], "
         r"'monedas': \[20, 20\], 'filas': 2"),
    ]),
    "Y2": (_parche(attempts_mod, "_tomar_intento", _tomar_sin_bloqueo), [
        (b13.test_a13_2_doble_toque_del_mismo_intento,
         r"doble toque: \{'estados': \[200, 200\], 'monedas': \[0, 20\], 'filas': 1"),
    ]),
    "Y3": (lambda i, _mp: _sin_unique(i), [
        (b13.test_c13_unique_de_la_llave_en_la_bd,
         r"dos filas con la misma \(tenant, llave\) entraron o fallaron por otra cosa: None"),
    ]),
    "Y4": (_parche(coins_mod, "award_coins", _award_deduplica), [
        (b13.test_k2_sin_llave_paga_cada_vez, r"sin llave, una paga no devolvió su fila"),
    ]),
    "Y5": (_parche(mig, "_subir", _subir_sin_backfill), [
        (mig.test_b1_backfill_la_mas_antigua_y_subir_dos_veces,
         r"el backfill no dejó las llaves esperadas"),
    ]),
    "Y6": (_parche(mig, "_bajar", _bajar_sin_drop_column), [
        (mig.test_b2_bajar_quita_columna_y_unique_y_volver_a_subir,
         r"bajar no quitó coin_ledger\.idempotency_key"),
    ]),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    aplicar, diagonal = TRAMPOSOS[clave]
    with aplicar(integ, monkeypatch):
        for test_real, motivo in diagonal:
            with pytest.raises(AssertionError, match=motivo):
                correr(test_real, integ, monkeypatch)
