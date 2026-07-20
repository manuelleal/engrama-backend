# engrama-backend — CLAUDE.md

Backend de Engrama: FastAPI 0.115 + Python 3.11 + SQLAlchemy 2 async + Supabase
(Postgres) + Alembic. Monolito modular multitenant. El sistema de gestión del
proyecto completo vive un nivel arriba (`..\CLAUDE.md` + `..\CONTINUAR-AQUI.md`).

## Comandos

```bash
python -m pytest -q                 # tests (no necesita .env ni DB)
python -m pytest tests/shop -q      # tests de un módulo
# uvicorn src.main:app --reload     # API local (necesita .env desde .env.example)
# poetry install                    # deps de dev (ruff/mypy NO están en el Python global)
```

## Reglas duras (violarlas = PR rechazado)

1. **Modelos centralizados:** TODO modelo SQLAlchemy vive en `src/shared/models.py`.
   Los `models.py` por dominio son stubs vacíos y así se quedan.
2. **Cero imports entre dominios:** `src/shop/` no importa de `src/engrama_core/`.
   Lo compartido (mover coins, evaluar badges) va en `src/shared/`.
3. **`tenant_id` en TODA query.** El backend usa service_role (RLS bypasseada):
   el filtro manual es la única defensa multitenant. Sin excepciones.
4. **Pydantic v2 strict** con `extra="forbid"` en todos los schemas.
5. **Lógica pura separada de la DB:** cálculos (recompensas, validación de pujas,
   criterios de badges) en funciones puras unit-testeables; el service las orquesta.
6. **Dinero = double-entry:** todo movimiento de coins escribe en `CoinLedger`
   dentro de la misma transacción. Operaciones concurrentes sobre wallets/subastas:
   `SELECT ... FOR UPDATE` (lección del MVP: optimistic locking falló bajo carga).
7. **Comentarios didácticos** en español explicando el porqué de negocio.

## Workflow de módulo (en orden, sin saltarse pasos)

1. Leer su spec en `SPECS/` (05-shop, 06-teachers, 07-badges, 08-announcements,
   09-challenge-economy-v2 están listos y pendientes de implementar).
2. Si el spec pide migración: revisar `src/shared/models.py`, crear migración Alembic.
3. Implementar: schemas → funciones puras → service → router.
4. Tests en `tests/<modulo>/`: unit (puras) + contract HTTP 401 (sin DB) +
   integration con `@pytest.mark.skip(reason="Needs testcontainers Postgres fixture")`.
5. Wiring en `src/main.py`.
6. Actualizar `ENGRAMA_HANDOFF.md` (sección de estado + registro de la sesión).

## Git

- Rama por módulo: `feat/<modulo>`. Base: `main` (o la rama que indique la bitácora).
- Commits convencionales en español: `feat(shop): ...`, `docs(specs): ...`.
- Nunca pushear a `main` directo; siempre PR.
- Estado actual de ramas: ver `..\CONTINUAR-AQUI.md`.

## Trampas conocidas

- `award_coins` lanza HTTP 402 si el `coin_pool` del tenant no tiene saldo — en dev
  hay que sembrarlo (pendiente script de seed, Fase A).
- `src/shared/celery_app.py` está vacío: NO activar el profile `workers` de
  docker-compose; nada debe depender de Celery todavía.
- Los campos `metadata` de wallet/ledger usan alias (`coin_metadata`/`ledger_metadata`).
- Timezone de negocio: `America/Bogota` (topes diarios, asistencia).
