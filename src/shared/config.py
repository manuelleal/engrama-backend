"""Configuración global de la aplicación — carga desde .env.

Usa pydantic-settings para tipar y validar las variables de entorno.
Se expone una sola instancia singleton `settings` que los demás módulos
importan:

    from src.shared.config import settings
    secret = settings.supabase_jwt_secret

Diseño:
  - Solo cargamos variables realmente usadas por el backend; si falta
    una obligatoria, la app falla al arranque con un error claro.
  - `DATABASE_URL` se normaliza a `postgresql+asyncpg://` igual que en
    `alembic/env.py`, para aceptar tanto el formato canónico de Supabase
    (`postgresql://...`) como el formato async explícito.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración runtime del backend Engrama 2.0."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignora variables del .env que no usemos aquí
        case_sensitive=False,
    )

    # --- App ---
    app_env: str = Field(default="development", description="development | production")
    app_debug: bool = Field(default=True)
    app_port: int = Field(default=8000)

    # --- Supabase ---
    supabase_url: str = Field(default="", description="URL del proyecto Supabase")
    supabase_jwt_secret: str = Field(
        ..., description="Secreto HS256 para validar JWTs emitidos por Supabase Auth"
    )
    supabase_service_role_key: str = Field(default="")
    supabase_anon_key: str = Field(default="")

    # --- Database ---
    database_url: str = Field(
        ..., description="DSN Postgres; se normaliza a postgresql+asyncpg:// internamente"
    )

    # --- Redis / Celery (no usado todavía, pero declarado) ---
    redis_url: str = Field(default="redis://redis:6379/0")

    # --- External APIs (opcional en dev) ---
    anthropic_api_key: str = Field(default="")
    stripe_secret_key: str = Field(default="")
    stripe_webhook_secret: str = Field(default="")

    # ---------------------------------------------------------------- helpers
    @field_validator("database_url")
    @classmethod
    def _normalize_async_scheme(cls, value: str) -> str:
        """Garantiza que SQLAlchemy use el driver asyncpg."""
        if value.startswith("postgresql+asyncpg://"):
            return value
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton cacheado. Se usa tanto en deps FastAPI como en tests."""
    return Settings()  # type: ignore[call-arg]


# Exportamos una instancia lista para usar en imports directos.
# En tests, se puede invalidar con `get_settings.cache_clear()`.
settings = get_settings()
