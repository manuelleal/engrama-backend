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
