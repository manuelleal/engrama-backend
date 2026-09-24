# ESPEC · Fixture de integración con Postgres (frente F4)

Creador · 2026-09-24 · se commitea antes del código.

## 0. Hallazgo que corrige el encargo
Los 24 tests saltados **no tienen cuerpo**: son `...` con un docstring (por ejemplo, `tests/engrama_core/test_coins.py:49-70`). Si solo se quitara el `skip`, darían 24 verdes vacíos, es decir, tests que pasan con cualquier cosa (regla 5). Por eso **el nombre y el docstring de cada uno son el contrato congelado**, y el cuerpo se escribe. Candidato a ERR: el handoff y la decisión 002 los contaban como tests.

## 1. Qué cambia (una cosa)
Una fixture que levanta Postgres en Docker, aplica Alembic y aísla cada test. Va en commits separados:
- **C1:** la fixture, el humo y los tramposos.
- **C2 a C5:** los cuerpos de los tests, un archivo por commit.

## 2. Cómo se levanta Postgres

| Opción | Veredicto |
|---|---|
| testcontainers | Hay ruedas para 3.14 (4.15.0 y pywin32-312-cp314), pero no se probó en Windows. Suma el SDK de docker y pywin32 para ganar solo un puerto dinámico, que aquí no hace falta. **Rechazada.** |
| `postgres:16-alpine` | La 029 usa `TO authenticated` y `auth.uid()`, que esta imagen no trae, así que falla. Habría que inventar un stub distinto de Supabase. **Rechazada.** |
| `npx supabase start` propio | Son unos 12 contenedores y choca con coins-mvp. **Rechazada.** |
| **`docker run` de `public.ecr.aws/supabase/postgres:17.6.1.167`** | **Elegida.** Ya está descargada. Trae `auth.uid()` y los roles `anon`, `authenticated` y `service_role`: las 29 migraciones corren sin inventar nada. |

**Levantar (fixture de sesión en `tests/integ_db.py`, registrada con `pytest_plugins` en `tests/conftest.py`):**
1. `docker rm -f engrama-test-pg`. Solo ese nombre exacto.
2. `docker run -d --rm --name engrama-test-pg -p 127.0.0.1:55432:5432 --tmpfs /var/lib/postgresql/data -e POSTGRES_PASSWORD=<sintética> <imagen>`.
3. `pg_isready`, con un máximo de 90 s.
4. `python -m alembic upgrade head` en un subproceso, con `DATABASE_URL` explícita.
5. Al cerrar la sesión: `docker stop`.

**Guarda:** si la URL no es `127.0.0.1:55432`, la fixture aborta. Así Alembic nunca usa un `.env` real (`alembic/env.py:26`).

**Aislamiento:** base nueva por sesión, así que las migraciones corren desde cero en cada corrida. Además, antes de cada test `integ` se hace `TRUNCATE … RESTART IDENTITY CASCADE` de las tablas de `Base.metadata`. Se trunca antes y no después, para que un fallo deje los datos inspeccionables.

**Por qué no rollback:** los routers hacen `commit()` (`src/engrama_core/router.py:75`), y `TestClient` corre la app en otro event loop, donde asyncpg no comparte conexiones. `get_db` se reemplaza con `app.dependency_overrides` por un engine con `NullPool`.

**RLS:** el backend se conecta sin RLS (`src/shared/db.py:3-8`). **Ninguno de los 24 prueba RLS**, así que no hay tramposo de RLS aquí; va a "Después".

## 3. Qué debe pasar (medible)

| Id | Comando | Esperado |
|---|---|---|
| A | `python -m pytest` | Los 95 originales pasan, o cada fallo se reporta como **BUG-n** con el test, el mensaje y el archivo:línea. Ni el test ni `src/` se tocan para ponerlo verde. 0 skips. |
| B | `python -m pytest -m "not integ" -q -rA` | Los mismos 71 ids en PASSED. El `diff` contra `tests/_salida/ids_71_antes.txt`, capturado **antes** de C1, sale vacío. |
| C | cada uno de los 24 | Afirma el valor exacto de su docstring: estado HTTP, monedas (50, 75 o 100), filas del ledger o balance. |
| D | Docker apagado | Los tests `integ` dan **ERROR** con un mensaje claro, nunca skip. |

## 4. Cómo sabremos que FALLÓ: los tramposos
`tests/tramposos/test_tramposos_integ.py` aplica `monkeypatch` en el módulo donde se usa la función, corre el cuerpo del test real y exige `AssertionError`. Si el tramposo pasa, el test queda rojo.
- **T1, ledger descuadrado:** `award_coins` acredita al estudiante sin debitar la billetera del tenant. Debe fallar `test_award_coins_double_entry`.
- **T2, racha:** `streak_multiplier` (usado en `attendance.py:302`) devuelve siempre 1.0. Debe fallar `test_checkin_streak_7_awards_75`.
- **T3, base sin migrar:** la fixture sin `upgrade head` hace que el humo falle.

## 5. Humo
`tests/integ/test_humo_integ.py` escribe `tests/_salida/humo_integ.json` (en `.gitignore`) con estos campos y valores:
- `alembic_version`: `"029_rls_policies"`;
- `tablas_con_rls`: `26`;
- `politicas_public`: `51`, que sale de 19×2 + 13 en la 029;
- `auth_uid_existe`: `true`.

**Sin ese archivo no se corren los 24.** Si un valor difiere, se reporta; no se ajusta.

## 6. Réplica
Correr `python -m pytest` dos veces seguidas debe dar:
- los mismos conteos en las dos corridas;
- un `humo_integ.json` idéntico;
- ningún `engrama-test-pg` en `docker ps -a` al terminar;
- los contenedores `*_coins-mvp` en `Up` antes y después.

Entradas nuevas: `uuid4()` distintos en cada corrida.

## 7. Qué NO se toca
- `src/**` y `alembic/versions/**`.
- Los 71 tests que ya pasan.
- El nombre y el docstring de los 24. De cada uno solo se cambia el `skip` por `@pytest.mark.integ` y se escribe el cuerpo; puede pasar a `async def`.
- Las líneas existentes de `tests/conftest.py`: solo se agrega.
- Los contenedores y los puertos 54321-54327 de coins-mvp.
- Todo Supabase remoto y cualquier `.env`.

## 8. Comando y dependencias
- **Único:** `python -m pytest`, que incluye `integ`.
- **Parciales:** `-m integ` y `-m "not integ"` (este último, sin Docker).
- El marcador se registra en `[tool.pytest.ini_options] markers`.
- **Dependencia de desarrollo:** solo `alembic>=1.13,<2`. Ya está en `pyproject.toml`, pero **no está instalado** en el Python global. No se agrega testcontainers.

**Después:**
- tests de RLS entre tenants, con `SET ROLE authenticated`;
- `pytest-asyncio` instalado 1.4.0 frente a `^0.24` en `pyproject.toml`;
- `ruff` y `mypy` sin instalar.
