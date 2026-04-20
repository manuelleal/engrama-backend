# Alembic — engrama-backend

Migraciones de base de datos async (asyncpg) con Alembic.

## Guía completa (en español, nivel principiante)

👉 **Lee primero: [`docs/DATABASE.md`](../docs/DATABASE.md)**

Ese documento explica qué es cada archivo, cómo correr los comandos, y cómo
arreglar los errores típicos. Está escrito para alguien que nunca vio código.

## Comandos rápidos

```bash
cd ~/projects/engrama/engrama-backend

poetry run alembic current          # Ver estado actual
poetry run alembic upgrade head     # Aplicar todo
poetry run alembic downgrade base   # Borrar todo (solo dev)
poetry run alembic history          # Ver historial
```

## Configuración

- `alembic.ini` — config mínima, sin secretos.
- `env.py` — lee `DATABASE_URL` del `.env`, normaliza el scheme a
  `postgresql+asyncpg://` automáticamente, y conecta vía AsyncEngine.
- `versions/` — 29 migraciones (000 extensions + 001–026 tablas + 027 índices
  + 028 enable RLS).

## Referencia del schema

El "plano del arquitecto" está en `SPECS/00-database-schema.md`.
Las migraciones reflejan ese documento al pie de la letra.
