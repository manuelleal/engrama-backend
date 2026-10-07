"""Fixture de integración con Postgres real en Docker (espec: docs/ESPEC_fixture_integracion.md).

Qué hace, en orden (una vez por sesión de pytest):
  1. `docker rm -f engrama-test-pg`  (solo ese nombre exacto; nunca toca coins-mvp).
  2. `docker run` de la imagen de Supabase Postgres en 127.0.0.1:55432, con el
     directorio de datos en tmpfs: la base nace vacía en cada corrida.
  3. Espera a `pg_isready` (máximo 90 s) y a que `auth.uid()` exista.
  4. `python -m alembic upgrade head` en un subproceso con DATABASE_URL explícita.
  5. Humo: mide la base migrada y escribe `tests/_salida/humo_integ.json`.
  6. Al cerrar la sesión: `docker stop` (el contenedor se borra solo por `--rm`).

Por qué la imagen de Supabase y no `postgres:16-alpine`: la migración 029 usa
`TO authenticated` y `auth.uid()`, que solo existen en la imagen de Supabase.

Aislamiento por test (fixture `integ`):
  - TRUNCATE ... RESTART IDENTITY CASCADE de todas las tablas de Base.metadata
    ANTES de cada test (no después): si un test falla, sus datos quedan para
    inspeccionarlos con psql.
  - `get_db` se reemplaza con `app.dependency_overrides` por sesiones de un
    engine con NullPool. No se usa rollback porque los routers hacen commit()
    y TestClient corre la app en otro event loop (asyncpg no comparte
    conexiones entre loops).

Guarda: si la URL no apunta a 127.0.0.1:55432, todo aborta. Así Alembic nunca
lee un `.env` real (alembic/env.py:26 hace load_dotenv).

La contraseña es SINTÉTICA y solo vale para este contenedor desechable, que
escucha únicamente en 127.0.0.1. No es una credencial real.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    # Solo para tipos: el import real vive dentro de la fixture `integ`, más
    # abajo, para no formar un ciclo (integ_ayudante importa de este módulo).
    from tests.integ_ayudante import Integ

# =============================================================================
# Constantes de la infraestructura de prueba
# =============================================================================
RAIZ_BACKEND = Path(__file__).resolve().parent.parent
IMAGEN = "public.ecr.aws/supabase/postgres:17.6.1.167"
CONTENEDOR = "engrama-test-pg"
HOST = "127.0.0.1"
PUERTO = 55432
CLAVE_SINTETICA = "solo_pruebas_locales_engrama"  # sintética, contenedor desechable
BASE_PRINCIPAL = "postgres"
ESPERA_MAXIMA_S = 90

RUTA_HUMO = RAIZ_BACKEND / "tests" / "_salida" / "humo_integ.json"

# Valores exactos que el humo debe encontrar (espec §5). Si uno difiere se
# reporta; NO se ajusta este diccionario para que pase.
HUMO_ESPERADO: dict[str, Any] = {
    "alembic_version": "040_foco_grupo",  # el foco del grupo
    "tablas_con_rls": 39,  # 38 + 1 (040), con RLS y sin políticas
    # 19 x 2 + 13 especiales (029); la 030 reemplaza 2, no suma; la 031 no toca políticas
    "politicas_public": 51,
    "auth_uid_existe": True,
}


def url_sqlalchemy(base: str = BASE_PRINCIPAL) -> str:
    """DSN para SQLAlchemy/Alembic (driver asyncpg)."""
    return f"postgresql+asyncpg://postgres:{CLAVE_SINTETICA}@{HOST}:{PUERTO}/{base}"


def url_asyncpg(base: str = BASE_PRINCIPAL) -> str:
    """DSN para asyncpg directo (sin el '+asyncpg' de SQLAlchemy)."""
    return url_sqlalchemy(base).replace("postgresql+asyncpg://", "postgresql://", 1)


def guarda_url(url: str) -> None:
    """Aborta si la URL no es la del contenedor de pruebas local.

    Defensa contra el peor error posible: migrar o truncar una base real.
    """
    if f"@{HOST}:{PUERTO}/" not in url:
        pytest.fail(
            f"GUARDA: la URL de integración debe apuntar a {HOST}:{PUERTO} "
            f"(contenedor {CONTENEDOR}). Se recibió otra URL; se aborta.",
            pytrace=False,
        )


# =============================================================================
# Docker
# =============================================================================
def _docker(*args: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    """Ejecuta `docker <args>`. Si Docker no existe o no responde, falla claro."""
    try:
        return subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        pytest.fail(
            "Tests 'integ': no se encontró el ejecutable `docker`. "
            "Instala/arranca Docker o corre solo `-m \"not integ\"`.",
            pytrace=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"Tests 'integ': `docker {' '.join(args[:2])}` no respondió en {timeout}s. "
            "¿Docker Desktop está arrancado?",
            pytrace=False,
        )


def levantar_contenedor() -> None:
    """Pasos 1-3 de la espec: rm -f, run y espera activa."""
    # 1. Solo el nombre exacto del contenedor de pruebas.
    _docker("rm", "-f", CONTENEDOR)

    # 2. Base nueva en tmpfs, puerto solo en loopback.
    r = _docker(
        "run", "-d", "--rm",
        "--name", CONTENEDOR,
        "-p", f"{HOST}:{PUERTO}:5432",
        "--tmpfs", "/var/lib/postgresql/data",
        "-e", f"POSTGRES_PASSWORD={CLAVE_SINTETICA}",
        IMAGEN,
    )
    if r.returncode != 0:
        pytest.fail(
            "Tests 'integ': Docker no pudo arrancar el contenedor de pruebas "
            f"{CONTENEDOR}. ¿Docker está apagado?\n"
            f"docker run salió con {r.returncode}: {r.stderr.strip()}",
            pytrace=False,
        )

    # 3. pg_isready por TCP dentro del contenedor + consulta real desde el host.
    limite = time.monotonic() + ESPERA_MAXIMA_S
    while True:
        listo = _docker(
            "exec", CONTENEDOR, "pg_isready", "-h", "127.0.0.1", "-U", "postgres",
            timeout=15,
        )
        if listo.returncode == 0 and _base_responde():
            return
        if time.monotonic() > limite:
            logs = _docker("logs", "--tail", "30", CONTENEDOR).stdout
            pytest.fail(
                f"Tests 'integ': Postgres no quedó listo en {ESPERA_MAXIMA_S}s.\n{logs}",
                pytrace=False,
            )
        time.sleep(1)


def _base_responde() -> bool:
    """True si el host puede conectarse y la imagen ya trae auth.uid()."""
    import asyncpg  # type: ignore[import-untyped]

    async def _probar() -> bool:
        conn = await asyncpg.connect(url_asyncpg(), timeout=5)
        try:
            return bool(
                await conn.fetchval("select to_regprocedure('auth.uid()') is not null")
            )
        finally:
            await conn.close()

    try:
        return asyncio.run(_probar())
    except Exception:  # noqa: BLE001 — cualquier fallo = "todavía no"
        return False


def detener_contenedor() -> None:
    """Paso 5: docker stop. Con --rm el contenedor desaparece de `docker ps -a`."""
    _docker("stop", CONTENEDOR, timeout=60)


# =============================================================================
# Base de datos: creación y migración
# =============================================================================
def preparar_base(base: str = BASE_PRINCIPAL, *, migrar: bool = True) -> str:
    """Deja lista la base `base` y devuelve su URL de SQLAlchemy.

    - Si `base` no es la principal, la (re)crea vacía.
    - Si `migrar`, corre `alembic upgrade head` en un subproceso con
      DATABASE_URL explícita (así env.py nunca usa un .env).
    `migrar=False` existe para el tramposo T3 (base sin migrar).
    """
    url = url_sqlalchemy(base)
    guarda_url(url)

    if base != BASE_PRINCIPAL:
        import asyncpg

        async def _recrear() -> None:
            conn = await asyncpg.connect(url_asyncpg(BASE_PRINCIPAL), timeout=10)
            try:
                await conn.execute(f'DROP DATABASE IF EXISTS "{base}"')
                await conn.execute(f'CREATE DATABASE "{base}"')
            finally:
                await conn.close()

        asyncio.run(_recrear())

    if migrar:
        env = {**os.environ, "DATABASE_URL": url}
        r = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(RAIZ_BACKEND),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if r.returncode != 0:
            pytest.fail(
                "Tests 'integ': `alembic upgrade head` falló.\n"
                f"stdout:\n{r.stdout[-3000:]}\nstderr:\n{r.stderr[-3000:]}",
                pytrace=False,
            )
    return url


# =============================================================================
# Humo
# =============================================================================
def medir_humo(url: str) -> dict[str, Any]:
    """Mide la base: versión de Alembic, RLS, políticas y auth.uid()."""
    guarda_url(url)
    import asyncpg

    async def _medir() -> dict[str, Any]:
        dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)
        conn = await asyncpg.connect(dsn, timeout=10)
        try:
            try:
                version = await conn.fetchval("select version_num from alembic_version")
            except asyncpg.exceptions.UndefinedTableError:
                version = None
            tablas = await conn.fetchval(
                "select count(*) from pg_tables "
                "where schemaname = 'public' and rowsecurity"
            )
            politicas = await conn.fetchval(
                "select count(*) from pg_policies where schemaname = 'public'"
            )
            auth_uid = await conn.fetchval(
                "select to_regprocedure('auth.uid()') is not null"
            )
        finally:
            await conn.close()
        return {
            "alembic_version": version,
            "tablas_con_rls": int(tablas),
            "politicas_public": int(politicas),
            "auth_uid_existe": bool(auth_uid),
        }

    return asyncio.run(_medir())


def escribir_humo(datos: dict[str, Any]) -> None:
    """Escribe el humo en disco (sin marcas de tiempo: la réplica debe ser idéntica)."""
    RUTA_HUMO.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO.write_text(
        json.dumps(datos, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def afirmar_humo(datos: dict[str, Any]) -> None:
    """Cuerpo del humo: cada campo debe ser exactamente el esperado."""
    for clave, esperado in HUMO_ESPERADO.items():
        assert datos.get(clave) == esperado, (
            f"humo: {clave} = {datos.get(clave)!r}, se esperaba {esperado!r}"
        )


# =============================================================================
# Fixtures
# =============================================================================
@pytest.fixture(scope="session")
def pg_integ() -> Iterator[str]:
    """Contenedor + base migrada para toda la sesión. Devuelve la URL."""
    guarda_url(url_sqlalchemy())
    try:
        levantar_contenedor()
        url = preparar_base(BASE_PRINCIPAL, migrar=True)
        yield url
    finally:
        detener_contenedor()


@pytest.fixture(scope="session")
def humo_integ(pg_integ: str) -> dict[str, Any]:
    """Mide la base recién migrada y escribe tests/_salida/humo_integ.json.

    No afirma aquí: escribe primero lo que encontró (para poder reportarlo)
    y el test de humo y la fixture `integ` lo comparan con HUMO_ESPERADO.
    """
    datos = medir_humo(pg_integ)
    escribir_humo(datos)
    return datos


@pytest.fixture
def integ(pg_integ: str, humo_integ: dict[str, Any]) -> Iterator[Integ]:
    """Base limpia + get_db apuntando a ella. Exige el humo escrito y correcto."""
    # "Sin ese archivo no se corren los 24" (espec §5).
    if not RUTA_HUMO.exists():
        pytest.fail(f"No existe {RUTA_HUMO}: sin humo no se corren los tests integ.",
                    pytrace=False)
    en_disco = json.loads(RUTA_HUMO.read_text(encoding="utf-8"))
    if en_disco != HUMO_ESPERADO:
        pytest.fail(
            f"El humo no confirma la base migrada: {en_disco} != {HUMO_ESPERADO}. "
            "No se corren los tests integ.",
            pytrace=False,
        )

    from src.main import app
    from src.shared.db import get_db
    from tests.integ_ayudante import Integ

    ayudante = Integ(pg_integ)
    ayudante.truncar_todo()  # antes, no después: los datos de un fallo quedan
    app.dependency_overrides[get_db] = ayudante._get_db_override
    try:
        yield ayudante
    finally:
        app.dependency_overrides.pop(get_db, None)
