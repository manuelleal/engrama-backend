"""Tests unitarios de `validate_jwt` (sin FastAPI, sin DB).

Cubre los 4 casos listados en SPECS/01-auth.md §7:
  - JWT válido → retorna payload con sub correcto.
  - JWT expirado → 401.
  - Firma inválida → 401.
  - Claim 'sub' faltante → 401.

(El caso 'missing header' se cubre en test_auth_endpoints.py porque
ahí es donde aplica el header, no en validate_jwt per se.)
"""
from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import HTTPException

from src.auth.service import validate_jwt

from .conftest import make_jwt


def test_valid_jwt_returns_payload(valid_token: str) -> None:
    payload = validate_jwt(valid_token)
    # El 'sub' debe ser un UUID válido generado por make_jwt.
    assert UUID(payload["sub"])
    assert payload["aud"] == "authenticated"
    assert payload["email"] == "student@engrama.test"


def test_expired_jwt_raises_401(expired_token: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_jwt(expired_token)
    assert exc_info.value.status_code == 401
    assert "expired" in str(exc_info.value.detail).lower() or "invalid" in str(
        exc_info.value.detail
    ).lower()


def test_invalid_signature_raises_401(wrong_signature_token: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_jwt(wrong_signature_token)
    assert exc_info.value.status_code == 401


def test_malformed_jwt_raises_401() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_jwt("this.is.not.a.jwt")
    assert exc_info.value.status_code == 401


def test_missing_sub_claim_raises_401() -> None:
    # Generamos un JWT con sub explícitamente vacío.
    token = make_jwt(sub="")
    with pytest.raises(HTTPException) as exc_info:
        validate_jwt(token)
    assert exc_info.value.status_code == 401
