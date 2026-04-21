"""Tests end-to-end de los endpoints /auth/*.

Se concentran en el comportamiento HTTP sin hablar con la DB real:
  - sin header Authorization → 401
  - con token malformado → 401
  - con firma inválida → 401
  - con token expirado → 401

El test "happy path" (200 con perfil + memberships) requiere una DB
con datos seed; se cubrirá en tests de integración de Fase 1 cuando
definamos fixtures de DB (test container o mocking más elaborado).

Uso: `poetry run pytest tests/auth/test_auth_endpoints.py -v`.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.main import app

from .conftest import make_jwt

client = TestClient(app)


def test_me_without_header_returns_401() -> None:
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"
    assert "missing" in response.json()["detail"].lower()


def test_me_with_malformed_header_returns_401() -> None:
    response = client.get("/auth/me", headers={"Authorization": "NotBearer abc"})
    assert response.status_code == 401


def test_me_with_empty_bearer_returns_401() -> None:
    response = client.get("/auth/me", headers={"Authorization": "Bearer "})
    assert response.status_code == 401


def test_me_with_invalid_signature_returns_401() -> None:
    token = make_jwt(secret="otro-secreto-distinto")
    response = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_me_with_expired_token_returns_401() -> None:
    token = make_jwt(expires_in=-60)
    response = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_session_without_header_returns_401() -> None:
    response = client.post("/auth/session")
    assert response.status_code == 401


def test_logout_without_header_returns_401() -> None:
    response = client.post("/auth/logout")
    assert response.status_code == 401


def test_health_is_public() -> None:
    """Sanity check: /health sigue siendo público aunque se añadió auth."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
