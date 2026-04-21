"""Infraestructura de base de datos async (SQLAlchemy 2.x + asyncpg).

Fase 1 — Walking Skeleton (ver ARQUITECTURA.md §10):
  El backend se conecta con `service_role` (bypass RLS). La lógica de
  aislamiento por tenant se aplica explícitamente en cada service vía
  filtros `WHERE tenant_id = ...` (defensa en profundidad, WINDSURF §3).

En una fase posterior (ADR-003) se añadirá `user_session` que usa el
JWT del usuario para respetar RLS en queries del cliente. Por ahora
exponemos una sola factory: `get_db`.

Uso típico en un router:

    from fastapi import Depends
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.shared.db import get_db

    @router.get("/items")
    async def list_items(db: AsyncSession = Depends(get_db)): ...
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.shared.config import settings

# Engine global del proceso. `pool_pre_ping` evita conexiones zombi cuando
# Supabase/pgbouncer recicla sockets idle.
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

# Factory de sesiones. `expire_on_commit=False` permite leer atributos de
# objetos ORM después de hacer commit, patrón estándar para APIs async.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: provee una AsyncSession y la cierra al terminar.

    Rollback automático si el handler lanza una excepción no capturada,
    para que transacciones a medio empezar no queden colgadas.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
