"""Helpers locales del módulo tests/auth."""
from __future__ import annotations

import time
from uuid import uuid4

import pytest
from jose import jwt

from tests.conftest import TEST_JWT_SECRET


def make_jwt(
    *,
    sub: str | None = None,
    email: str = "student@engrama.test",
    expires_in: int = 3600,
    audience: str = "authenticated",
    secret: str = TEST_JWT_SECRET,
    algorithm: str = "HS256",
    extra_claims: dict | None = None,
) -> str:
    """Genera un JWT firmado con HS256 imitando el formato de Supabase Auth."""
    now = int(time.time())
    payload = {
        # Usamos `is None` para permitir forzar sub="" en tests de claim vacío.
        "sub": str(uuid4()) if sub is None else sub,
        "email": email,
        "aud": audience,
        "iat": now,
        "exp": now + expires_in,
        "role": "authenticated",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, secret, algorithm=algorithm)


@pytest.fixture
def valid_token() -> str:
    return make_jwt()


@pytest.fixture
def expired_token() -> str:
    return make_jwt(expires_in=-10)


@pytest.fixture
def wrong_signature_token() -> str:
    return make_jwt(secret="otra-llave-que-no-es-la-nuestra")
