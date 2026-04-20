"""Alembic environment — async + asyncpg + DATABASE_URL del .env.

Flujo:
1. Carga .env desde la raíz de engrama-backend.
2. Inyecta DATABASE_URL en la config de Alembic.
3. Importa Base desde src.shared.models para autogenerate.
4. Ejecuta las migraciones con un AsyncEngine (asyncpg).
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# --- bootstrap de paths y .env -------------------------------------------------
BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_ROOT / ".env")

# Permite `from src.shared.models import Base` sin instalar el paquete.
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.shared.models import Base  # noqa: E402  (requiere sys.path ajustado)

# --- config Alembic ------------------------------------------------------------
config = context.config

database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL no está definido. Debe estar en engrama-backend/.env "
        "con formato postgresql+asyncpg://user:pass@host:port/db"
    )

# Normaliza el scheme para forzar el driver async asyncpg aunque el .env
# contenga sólo `postgresql://` (formato canónico que da Supabase en el
# dashboard). Así evitamos que SQLAlchemy intente cargar psycopg2.
if database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)

config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# --- runners -------------------------------------------------------------------
def run_migrations_offline() -> None:
    """Modo offline: genera SQL sin abrir conexión."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Modo online: abre AsyncEngine con asyncpg y corre migraciones."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
