"""Tests del submódulo attendance — SPECS/02-engrama-core.md §9.

Niveles:
  1. Unit puro (sin DB): haversine, streak_multiplier, compute_next_streak,
     generate_session_code. Corren en CI.
  2. Contract HTTP (sin DB): endpoints /core/attendance/* sin auth → 401,
     check-in con session inválida → responde según la capa de auth.
  3. Integration (con DB): check_in real con sesión activa, multiplicadores
     por racha, geo_status, duplicados. `@pytest.mark.skip` hasta que
     tengamos fixture de Postgres de prueba.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from src.engrama_core.service.attendance import (
    compute_next_streak,
    generate_session_code,
    haversine_distance,
    streak_multiplier,
)
from src.main import app

client = TestClient(app)


# =============================================================================
# 1. Unit puro — helpers sin DB
# =============================================================================
class TestStreakMultiplier:
    """Tabla de multiplicadores per §4.2 del spec."""

    @pytest.mark.parametrize("streak", [0, 1, 3, 6])
    def test_returns_1x_below_7(self, streak: int) -> None:
        assert streak_multiplier(streak) == 1.0

    @pytest.mark.parametrize("streak", [7, 10, 13])
    def test_returns_1_5x_between_7_and_13(self, streak: int) -> None:
        assert streak_multiplier(streak) == 1.5

    @pytest.mark.parametrize("streak", [14, 30, 365])
    def test_returns_2x_from_14(self, streak: int) -> None:
        assert streak_multiplier(streak) == 2.0


class TestComputeNextStreak:
    """Spec §11.3: cómo se actualiza la racha según last_attendance_date."""

    def test_first_time_student_starts_at_1(self) -> None:
        today = date(2026, 4, 20)
        assert compute_next_streak(None, today) == 1

    def test_yesterday_returns_sentinel_to_increment(self) -> None:
        today = date(2026, 4, 20)
        yesterday = today - timedelta(days=1)
        # El service interpreta -1 como "suma 1 al current_streak existente".
        assert compute_next_streak(yesterday, today) == -1

    def test_two_days_ago_resets_to_1(self) -> None:
        today = date(2026, 4, 20)
        two_days_ago = today - timedelta(days=2)
        assert compute_next_streak(two_days_ago, today) == 1

    def test_a_week_ago_resets_to_1(self) -> None:
        today = date(2026, 4, 20)
        a_week_ago = today - timedelta(days=7)
        assert compute_next_streak(a_week_ago, today) == 1


class TestHaversineDistance:
    """Verifica la fórmula con puntos conocidos."""

    def test_same_point_is_zero(self) -> None:
        d = haversine_distance(4.6097, -74.0817, 4.6097, -74.0817)
        assert d == pytest.approx(0, abs=1e-6)

    def test_near_points_bogota(self) -> None:
        # Dos puntos en Bogotá ~1 km apart.
        d = haversine_distance(4.6097, -74.0817, 4.6186, -74.0817)
        assert 900 < d < 1100  # tolerancia ~10%

    def test_far_points_continental(self) -> None:
        # Bogotá → Medellín ≈ 240 km aéreos.
        d = haversine_distance(4.6097, -74.0817, 6.2442, -75.5812)
        assert 230_000 < d < 260_000


class TestSessionCodeGenerator:
    def test_default_length_is_6(self) -> None:
        code = generate_session_code()
        assert len(code) == 6

    def test_custom_length(self) -> None:
        code = generate_session_code(10)
        assert len(code) == 10

    def test_uppercase_alphanumeric(self) -> None:
        for _ in range(50):
            code = generate_session_code()
            assert code.isalnum()
            assert code == code.upper()

    def test_randomness_across_calls(self) -> None:
        codes = {generate_session_code() for _ in range(200)}
        # 200 códigos de 6 chars sobre 36^6 espacio → virtualmente 0 colisión.
        assert len(codes) >= 198


# =============================================================================
# 2. Contract HTTP — sin DB
# =============================================================================
def test_create_session_without_auth_returns_401() -> None:
    response = client.post(
        "/core/attendance/sessions",
        json={"group_code": "FL40556", "duration_minutes": 15},
    )
    assert response.status_code == 401


def test_list_active_sessions_without_auth_returns_401() -> None:
    response = client.get("/core/attendance/sessions/active")
    assert response.status_code == 401


def test_checkin_without_auth_returns_401() -> None:
    response = client.post(
        "/core/attendance/check-in",
        json={"session_code": "ABC123"},
    )
    assert response.status_code == 401


def test_attendance_history_without_auth_returns_401() -> None:
    response = client.get("/core/attendance/history")
    assert response.status_code == 401


# =============================================================================
# 3. Integration DB-bound — skipped hasta fixture de Postgres
# =============================================================================
@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_create_session_as_student_returns_403() -> None:
    """Un JWT de un student NO debe poder crear sesiones (require_teacher)."""
    ...


@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_checkin_invalid_session_code_returns_404() -> None:
    """session_code que no existe → 404."""
    ...


@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_checkin_expired_session_returns_410() -> None:
    """session con expires_at pasado → 410."""
    ...


@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_checkin_duplicate_returns_409() -> None:
    """Dos check-ins del mismo estudiante a la misma sesión → 409."""
    ...


@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_checkin_valid_awards_50_and_streak_1() -> None:
    """Primer check-in del alumno → coins=50, streak=1, success=True."""
    ...


@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_checkin_streak_7_awards_75() -> None:
    """Con current_streak=6 y last_attendance=ayer → nuevo=7 → 50*1.5=75."""
    ...


@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_checkin_streak_14_awards_100() -> None:
    """Con streak=13 y ayer → nuevo=14 → 50*2.0=100."""
    ...


@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_checkin_geo_out_of_range_still_succeeds() -> None:
    """Geo distante no bloquea el check-in, solo marca geo_status."""
    ...
