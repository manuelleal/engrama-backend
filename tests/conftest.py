"""Fixtures globales para pytest.

Propósito:
  1. Sobreescribir variables de entorno ANTES de que `src.shared.config`
     se importe, para que los tests no dependan del `.env` real y no
     toquen Supabase. El truco es setear `os.environ[...]` al nivel de
     módulo (se ejecuta al cargar conftest.py, antes de los tests).
  2. Limpiar el caché `lru_cache` de `get_settings` si otro test lo
     invalidó.
  3. Exponer el secreto compartido para generar JWTs en los tests.
"""
from __future__ import annotations

import os

import pytest

# Valores deterministas para tests. Se setean ANTES de importar
# src.shared.config (que sucede cuando un test importa cualquier cosa
# bajo src/).
TEST_JWT_SECRET = "test-jwt-secret-super-seguro-solo-para-pytest"

os.environ.setdefault("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/test",
)
os.environ.setdefault("APP_ENV", "test")

# Fixture de integración con Postgres en Docker (docs/ESPEC_fixture_integracion.md).
# Solo se activa en los tests marcados `integ`; `-m "not integ"` no necesita Docker.
pytest_plugins = ["tests.integ_db"]


@pytest.fixture(autouse=True)
def _registro_sin_piso_de_tiempo(monkeypatch: pytest.MonkeyPatch) -> None:
    """El registro de los tests no espera el piso de 250 ms (ESPEC_autorregistro §12.2).

    Cada registro de la suite (los 40 de HA1, los de AR10...) esperaría un
    cuarto de segundo. Los tests que miden el tiempo (AR18, UP1, UP2) lo
    vuelven a poner por su cuenta.
    """
    from src.shared.config import settings

    monkeypatch.setattr(settings, "registro_piso_ms", 0)
