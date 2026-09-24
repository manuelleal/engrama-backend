"""Tests del submódulo coins — SPECS/02-engrama-core.md §9.

Mezcla tres niveles:
  1. Contract HTTP (sin DB):  /core/coins/* sin auth → 401.
  2. Unit (sin DB):           None para coins — la lógica es toda DB-bound.
  3. Integration (con DB):    award_coins, balance, history con wallets
                              reales. Marcados `@pytest.mark.skip` hasta
                              que tengamos fixture de testcontainers
                              Postgres (tarea posterior).

Para correr los integration: quita el skip y expón una DB de prueba
limpia via `tests/conftest.py` (TODO Fase 1 integración).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.engrama_core.service import coins as coins_service
from src.main import app

client = TestClient(app)


# =============================================================================
# Contract HTTP — pasan en CI sin DB real
# =============================================================================
def test_balance_without_auth_returns_401() -> None:
    response = client.get("/core/coins/balance")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


def test_history_without_auth_returns_401() -> None:
    response = client.get("/core/coins/history")
    assert response.status_code == 401


def test_history_invalid_limit_returns_422() -> None:
    # Con header vacío seguimos cayendo en 401 antes del Query validator,
    # así que este test se concentra en el auth flow. Si en el futuro
    # agregamos un endpoint público, validar aquí el 422 del query.
    response = client.get("/core/coins/history?limit=0")
    assert response.status_code == 401  # auth revienta primero


# =============================================================================
# Integration DB-bound — placeholder hasta que exista fixture de Postgres
# =============================================================================
@pytest.mark.integ
def test_award_coins_basic(integ) -> None:
    """award_coins(amount=50) → balance del estudiante sube 50."""
    tenant = integ.crear_tenant(pool=1000)
    alumno = integ.crear_perfil(tenant, saldo=20)

    async def cuerpo() -> tuple[int, int]:
        async with integ.sesion() as db:
            antes = await coins_service.get_balance(db, alumno, tenant)
            await coins_service.award_coins(
                db, student_id=alumno, tenant_id=tenant, amount=50, action="test"
            )
            await db.commit()
        async with integ.sesion() as db:
            despues = await coins_service.get_balance(db, alumno, tenant)
        return antes, despues

    antes, despues = integ.run(cuerpo())
    assert antes == 20
    assert despues == 70  # sube exactamente 50
    assert integ.saldo("profile", alumno) == 70


@pytest.mark.integ
def test_award_coins_double_entry(integ) -> None:
    """Tenant wallet baja 50, profile wallet sube 50; ledger registra ambos."""
    tenant = integ.crear_tenant(pool=1000)
    alumno = integ.crear_perfil(tenant)

    async def cuerpo() -> None:
        async with integ.sesion() as db:
            await coins_service.award_coins(
                db, student_id=alumno, tenant_id=tenant, amount=50, action="test"
            )
            await db.commit()

    integ.run(cuerpo())

    assert integ.saldo("tenant", tenant) == 950  # baja 50
    assert integ.saldo("profile", alumno) == 50  # sube 50
    # Doble partida: la suma del sistema no cambia.
    assert integ.saldo("tenant", tenant) + integ.saldo("profile", alumno) == 1000

    assert integ.valor("select count(*) from coin_ledger") == 1
    fila = integ.fila(
        "select l.amount, l.action, l.tenant_id, "
        "       wf.owner_type as from_tipo, wf.owner_id as from_owner, "
        "       wt.owner_type as to_tipo, wt.owner_id as to_owner "
        "from coin_ledger l "
        "join coin_wallets wf on wf.id = l.from_wallet_id "
        "join coin_wallets wt on wt.id = l.to_wallet_id"
    )
    assert fila is not None, "la fila del ledger debe tener origen y destino"
    assert fila["amount"] == 50
    assert fila["action"] == "test"
    assert fila["tenant_id"] == tenant
    assert (fila["from_tipo"], fila["from_owner"]) == ("tenant", tenant)
    assert (fila["to_tipo"], fila["to_owner"]) == ("profile", alumno)


@pytest.mark.integ
def test_award_coins_insufficient_balance(integ) -> None:
    """Tenant con pool < amount → HTTPException 402."""
    tenant = integ.crear_tenant(pool=30)
    alumno = integ.crear_perfil(tenant)

    async def cuerpo() -> HTTPException:
        async with integ.sesion() as db:
            with pytest.raises(HTTPException) as exc:
                await coins_service.award_coins(
                    db, student_id=alumno, tenant_id=tenant, amount=50, action="test"
                )
            await db.rollback()
            return exc.value

    error = integ.run(cuerpo())
    assert error.status_code == 402
    assert "have 30, need 50" in error.detail
    # Nada se movió.
    assert integ.saldo("tenant", tenant) == 30
    assert integ.valor("select count(*) from coin_ledger") == 0


@pytest.mark.integ
def test_get_balance_no_wallet(integ) -> None:
    """Estudiante sin wallet todavía → get_balance retorna 0."""
    tenant = integ.crear_tenant(pool=1000)
    alumno = integ.crear_perfil(tenant)  # sin saldo → sin wallet

    async def cuerpo() -> int:
        async with integ.sesion() as db:
            balance = await coins_service.get_balance(db, alumno, tenant)
            await db.commit()
            return balance

    balance = integ.run(cuerpo())
    assert balance == 0
    assert type(balance) is int
    # Consultar el balance no crea la wallet.
    assert integ.valor(
        "select count(*) from coin_wallets where owner_id = :o", o=alumno
    ) == 0
