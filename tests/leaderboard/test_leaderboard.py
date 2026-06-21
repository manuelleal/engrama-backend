"""Tests del módulo leaderboard — SPECS/04-leaderboard.md §6.

Tres niveles (igual que engrama_core):
  1. Contract HTTP (sin DB): /leaderboard sin auth → 401.
  2. Unit (sin DB):          build_leaderboard — ranks, is_me, me fuera del
                             top-N, truncado y lista vacía. Lógica pura.
  3. Integration (con DB):   get_leaderboard con wallets/memberships reales.
                             Marcados skip hasta el fixture de testcontainers.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.leaderboard.service import RankRow, build_leaderboard
from src.main import app

client = TestClient(app)


def _row(profile_id: UUID, coins: int, *, name: str = "Student", xp: int = 0) -> RankRow:
    return RankRow(
        profile_id=profile_id,
        full_name=name,
        coins=coins,
        xp=xp,
        level=1,
        current_streak=0,
    )


# =============================================================================
# Contract HTTP — pasan en CI sin DB real
# =============================================================================
def test_leaderboard_without_auth_returns_401() -> None:
    response = client.get("/leaderboard")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


def test_leaderboard_with_group_without_auth_returns_401() -> None:
    response = client.get("/leaderboard?group_code=40556")
    assert response.status_code == 401


# =============================================================================
# Unit — build_leaderboard (lógica pura, sin DB)
# =============================================================================
def test_build_leaderboard_assigns_sequential_ranks() -> None:
    rows = [_row(uuid4(), 30), _row(uuid4(), 20), _row(uuid4(), 10)]
    entries, _, total = build_leaderboard(rows, me_profile_id=uuid4(), limit=20)

    assert [e.rank for e in entries] == [1, 2, 3]
    assert [e.coins for e in entries] == [30, 20, 10]
    assert total == 3


def test_build_leaderboard_flags_is_me() -> None:
    me = uuid4()
    rows = [_row(uuid4(), 30), _row(me, 20), _row(uuid4(), 10)]
    entries, me_entry, _ = build_leaderboard(rows, me_profile_id=me, limit=20)

    assert me_entry is not None
    assert me_entry.rank == 2
    assert me_entry.is_me is True
    assert sum(1 for e in entries if e.is_me) == 1


def test_build_leaderboard_me_outside_top_limit_still_returned() -> None:
    me = uuid4()
    # me queda en el puesto 4, pero pedimos solo top-3.
    rows = [_row(uuid4(), 40), _row(uuid4(), 30), _row(uuid4(), 20), _row(me, 10)]
    entries, me_entry, total = build_leaderboard(rows, me_profile_id=me, limit=3)

    assert len(entries) == 3
    assert all(e.is_me is False for e in entries)  # no entró al top-3
    assert me_entry is not None
    assert me_entry.rank == 4  # conserva su puesto real
    assert total == 4


def test_build_leaderboard_truncates_to_limit() -> None:
    rows = [_row(uuid4(), 100 - i) for i in range(10)]
    entries, _, total = build_leaderboard(rows, me_profile_id=uuid4(), limit=5)

    assert len(entries) == 5
    assert total == 10
    assert [e.rank for e in entries] == [1, 2, 3, 4, 5]


def test_build_leaderboard_empty() -> None:
    entries, me_entry, total = build_leaderboard([], me_profile_id=uuid4(), limit=20)

    assert entries == []
    assert me_entry is None
    assert total == 0


def test_build_leaderboard_me_not_in_rows_returns_none() -> None:
    # Caso típico: un teacher (no rankeado) consulta el ranking de un grupo.
    rows = [_row(uuid4(), 30), _row(uuid4(), 20)]
    _, me_entry, _ = build_leaderboard(rows, me_profile_id=uuid4(), limit=20)

    assert me_entry is None


# =============================================================================
# Integration DB-bound — placeholder hasta el fixture de Postgres
# =============================================================================
@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_get_leaderboard_orders_by_coins() -> None:
    """Estudiantes ordenados por balance DESC, con LEFT JOIN a coin_wallets."""
    ...


@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_get_leaderboard_group_filter_isolates() -> None:
    """group_code filtra solo a miembros de ese grupo dentro del tenant."""
    ...


@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_get_leaderboard_excludes_other_tenants() -> None:
    """Un estudiante de otro tenant nunca aparece en el ranking."""
    ...
