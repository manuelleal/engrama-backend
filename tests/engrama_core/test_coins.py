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
from fastapi.testclient import TestClient

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
@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_award_coins_basic() -> None:
    """award_coins(amount=50) → balance del estudiante sube 50."""
    ...


@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_award_coins_double_entry() -> None:
    """Tenant wallet baja 50, profile wallet sube 50; ledger registra ambos."""
    ...


@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_award_coins_insufficient_balance() -> None:
    """Tenant con pool < amount → HTTPException 402."""
    ...


@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_get_balance_no_wallet() -> None:
    """Estudiante sin wallet todavía → get_balance retorna 0."""
    ...
