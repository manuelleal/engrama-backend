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
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

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
    "alembic_version": "030_rls_sin_recursion",  # BUG-2: la 030 corta la recursión
    "tablas_con_rls": 26,
    "politicas_public": 51,  # 19 x 2 + 13 especiales (029); la 030 reemplaza 2, no suma
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
# Resultado de `Integ.como` (docs/ESPEC_aceptacion_seguridad.md §3)
# =============================================================================
# Roles con los que `como` puede ejecutar. `anon` y `authenticated` son los de
# Supabase (la RLS aplica); `postgres` es el de la fixture (ignora la RLS) y se
# usa solo para los controles: "la misma sentencia, sin RLS, sí funciona".
ROLES_COMO = ("anon", "authenticated", "postgres")


@dataclass(frozen=True)
class Resultado:
    """Lo que devolvió una sentencia ejecutada con `Integ.como`.

    - `filas`: lo que devolvió el SELECT (o el RETURNING); [] si hubo error.
    - `afectadas`: filas devueltas (SELECT) o tocadas (INSERT/UPDATE/DELETE).
    - `sqlstate`: None si no hubo error; si lo hubo, su código (42501 =
      rechazo de la RLS; 42P17 = recursión infinita, es ROTURA, no rechazo).
    """

    filas: list[dict[str, Any]] = field(default_factory=list)
    afectadas: int = 0
    sqlstate: str | None = None
    mensaje: str = ""


def _sqlstate(exc: Exception) -> str:
    """SQLSTATE de un error de SQLAlchemy+asyncpg (o 'desconocido')."""
    orig = getattr(exc, "orig", None)
    for candidato in (orig, getattr(orig, "__cause__", None)):
        codigo = getattr(candidato, "sqlstate", None) or getattr(candidato, "pgcode", None)
        if codigo:
            return str(codigo)
    return "desconocido"


# =============================================================================
# Helper que recibe cada test integ
# =============================================================================
class Integ:
    """Acceso a la base de prueba + fábricas de datos sintéticos.

    Todas las fábricas son síncronas (usan asyncio.run) para que los tests
    puedan mezclar llamadas HTTP con TestClient y consultas a la base sin
    pelear con el event loop de pytest-asyncio.
    """

    def __init__(self, url: str) -> None:
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )
        from sqlalchemy.pool import NullPool

        guarda_url(url)
        self.url = url
        self.engine = create_async_engine(url, poolclass=NullPool)
        # Mismos parámetros que src/shared/db.py para no cambiar el comportamiento.
        self.Session = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    # ------------------------------------------------------------ utilidades
    @staticmethod
    def run(coro: Any) -> Any:
        """Corre una corrutina en un loop propio y devuelve su resultado."""
        return asyncio.run(coro)

    @asynccontextmanager
    async def sesion(self):  # type: ignore[no-untyped-def]
        async with self.Session() as db:
            yield db

    async def _get_db_override(self):  # type: ignore[no-untyped-def]
        """Reemplazo de src.shared.db.get_db (misma semántica de rollback)."""
        async with self.Session() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    def valor(self, sql: str, **params: Any) -> Any:
        """Primer valor de la primera fila de una consulta SQL."""
        from sqlalchemy import text

        async def _q() -> Any:
            async with self.Session() as db:
                return (await db.execute(text(sql), params)).scalar()

        return self.run(_q())

    def fila(self, sql: str, **params: Any) -> dict[str, Any] | None:
        """Primera fila como dict (o None)."""
        from sqlalchemy import text

        async def _q() -> dict[str, Any] | None:
            async with self.Session() as db:
                row = (await db.execute(text(sql), params)).mappings().first()
                return dict(row) if row is not None else None

        return self.run(_q())

    def _insertar(self, *objs: Any) -> None:
        async def _ins() -> None:
            async with self.Session() as db:
                for o in objs:
                    db.add(o)
                    await db.flush()
                await db.commit()

        self.run(_ins())

    def truncar_todo(self) -> None:
        """TRUNCATE de todas las tablas del modelo (antes de cada test)."""
        from sqlalchemy import text

        from src.shared.models import Base

        tablas = ", ".join(t.name for t in Base.metadata.sorted_tables)

        async def _t() -> None:
            async with self.engine.begin() as conn:
                await conn.execute(text(f"TRUNCATE {tablas} RESTART IDENTITY CASCADE"))

        self.run(_t())

    # ------------------------------------------------------------ fábricas
    def crear_tenant(self, *, pool: int = 1000) -> UUID:
        """Tenant + su wallet (banco central) con `pool` monedas."""
        from src.shared.models import CoinWallet, Tenant

        tid = uuid4()
        self._insertar(
            Tenant(id=tid, name=f"Colegio {tid.hex[:6]}", slug=f"t-{tid.hex[:12]}",
                   coin_pool=pool),
            CoinWallet(tenant_id=tid, owner_type="tenant", owner_id=tid,
                       currency="COIN", balance=pool),
        )
        return tid

    def crear_perfil(
        self,
        tenant_id: UUID,
        *,
        rol: str = "student",
        group_code: str | None = None,
        racha: int = 0,
        ultima_asistencia: date | None = None,
        saldo: int | None = None,
    ) -> UUID:
        """Perfil + membership activa en el tenant. `saldo` crea su wallet."""
        from src.shared.models import CoinWallet, Membership, Profile

        pid = uuid4()
        objs: list[Any] = [
            Profile(
                id=pid,
                documento_id=f"doc-{pid.hex[:12]}",
                full_name=f"Persona {pid.hex[:6]}",
                pin_hash="sintetico",
                role=rol,
                current_streak=racha,
                longest_streak=racha,
                last_attendance_date=ultima_asistencia,
            ),
            Membership(tenant_id=tenant_id, profile_id=pid, role=rol,
                       group_code=group_code, is_active=True),
        ]
        if saldo is not None:
            objs.append(CoinWallet(tenant_id=tenant_id, owner_type="profile",
                                   owner_id=pid, currency="COIN", balance=saldo))
        self._insertar(*objs)
        return pid

    def crear_grupo(
        self,
        tenant_id: UUID,
        codigo: str,
        *,
        lat: float | None = None,
        lng: float | None = None,
    ) -> UUID:
        from src.shared.models import Group

        gid = uuid4()
        self._insertar(Group(id=gid, tenant_id=tenant_id, group_code=codigo,
                             last_admin_lat=lat, last_admin_lng=lng))
        return gid

    def crear_sesion_asistencia(
        self,
        tenant_id: UUID,
        group_id: UUID,
        creador_id: UUID,
        *,
        expira_en: timedelta = timedelta(minutes=15),
        lat: float | None = None,
        lng: float | None = None,
    ) -> str:
        """Sesión QR 'active'. `expira_en` negativo = ya expirada. Devuelve el código."""
        from src.engrama_core.service.attendance import generate_session_code
        from src.shared.models import AttendanceSession

        ahora = datetime.now(UTC)
        codigo = generate_session_code()
        self._insertar(
            AttendanceSession(
                tenant_id=tenant_id,
                group_id=group_id,
                session_code=codigo,
                qr_payload={"session_code": codigo},
                admin_lat=lat,
                admin_lng=lng,
                starts_at=ahora - timedelta(hours=1),
                expires_at=ahora + expira_en,
                created_by=creador_id,
                status="active",
            )
        )
        return codigo

    def crear_challenge(
        self,
        tenant_id: UUID,
        creador_id: UUID,
        *,
        respuestas: tuple[str, ...] = ("A", "B"),
        coins: int = 20,
        xp: int = 15,
        max_attempts: int = 2,
        max_winners: int = 10,
        current_winners: int = 0,
        group_id: UUID | None = None,
        status: str = "active",
        tipo: str = "multiple_choice",
        titulo: str | None = None,
    ) -> tuple[UUID, list[UUID]]:
        """Challenge + una pregunta por respuesta correcta. Devuelve (id, [ids preguntas])."""
        from src.shared.models import Challenge, ChallengeQuestion

        cid = uuid4()
        qids = [uuid4() for _ in respuestas]
        objs: list[Any] = [
            Challenge(
                id=cid, tenant_id=tenant_id, group_id=group_id, created_by=creador_id,
                title=titulo or f"Reto {cid.hex[:6]}", description="sintético",
                challenge_type=tipo, coins_reward=coins, xp_reward=xp,
                max_attempts=max_attempts, max_winners=max_winners,
                current_winners=current_winners, status=status,
            )
        ]
        for i, (qid, resp) in enumerate(zip(qids, respuestas, strict=True), start=1):
            objs.append(
                ChallengeQuestion(
                    id=qid, challenge_id=cid, question_type=tipo,
                    question_text=f"Pregunta {i}",
                    # Opciones fijas que NO contienen la respuesta: así un test
                    # puede buscar el valor de correct_answer en el JSON sin
                    # confundirlo con el texto de una opción.
                    options_json=[{"label": "A", "value": "opcion uno"},
                                  {"label": "B", "value": "opcion dos"}],
                    correct_answer=resp, order_index=i,
                )
            )
        self._insertar(*objs)
        return cid, qids

    def crear_intento(
        self,
        tenant_id: UUID,
        challenge_id: UUID,
        alumno_id: UUID,
        *,
        status: str = "completed",
    ) -> UUID:
        """Intento ya registrado (por defecto 'completed', sin premio)."""
        from src.shared.models import ChallengeAttempt

        aid = uuid4()
        self._insertar(
            ChallengeAttempt(
                id=aid, tenant_id=tenant_id, challenge_id=challenge_id,
                student_id=alumno_id, status=status, score_percent=0,
                is_correct=False if status == "completed" else None,
                completed_at=datetime.now(UTC) if status == "completed" else None,
            )
        )
        return aid

    @staticmethod
    def headers(profile_id: UUID) -> dict[str, str]:
        """Authorization: Bearer <JWT HS256 firmado con el secreto de pruebas>."""
        from jose import jwt

        from tests.conftest import TEST_JWT_SECRET

        ahora = int(time.time())
        token = jwt.encode(
            {
                "sub": str(profile_id),
                "email": f"{str(profile_id)[:8]}@engrama.test",
                "aud": "authenticated",
                "iat": ahora,
                "exp": ahora + 3600,
                "role": "authenticated",
            },
            TEST_JWT_SECRET,
            algorithm="HS256",
        )
        return {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------ lecturas comunes
    def saldo(self, owner_type: str, owner_id: UUID) -> int | None:
        """Balance de la wallet (None si no existe)."""
        v = self.valor(
            "select balance from coin_wallets "
            "where owner_type = :t and owner_id = :o and currency = 'COIN'",
            t=owner_type, o=owner_id,
        )
        return None if v is None else int(v)

    # ------------------------------------------------------------ ataques con RLS
    def como(
        self,
        perfil: UUID | None,
        sql: str,
        params: dict[str, Any] | None = None,
        *,
        rol: str | None = None,
    ) -> Resultado:
        """Ejecuta `sql` con la identidad de un usuario de Supabase y lo DESHACE.

        Por qué existe: la fixture conecta como `postgres`, que ignora la RLS.
        Para saber qué puede hacer un usuario real hay que hablar como él:
          1. `SET LOCAL ROLE authenticated` (o `anon` si `perfil` es None);
          2. `request.jwt.claim.sub` y `request.jwt.claims` con su id, que es
             lo que lee `auth.uid()` en la imagen de Supabase;
          3. ejecuta y devuelve filas o SQLSTATE (nunca lanza por error SQL);
          4. ROLLBACK siempre: el ataque no deja rastro en la base.
        `rol="postgres"` corre la misma sentencia sin cambiar de rol: es el
        control de "la sentencia es válida; si falla, fue la RLS".
        """
        rol_efectivo = rol or ("anon" if perfil is None else "authenticated")
        if rol_efectivo not in ROLES_COMO:
            raise ValueError(f"como: rol {rol_efectivo!r} no está en {ROLES_COMO}")
        if rol_efectivo == "authenticated" and perfil is None:
            raise ValueError("como: 'authenticated' exige un perfil")
        claims: dict[str, str] = {"role": rol_efectivo}
        if perfil is not None:
            claims.update(sub=str(perfil), aud="authenticated")
        return self.run(self._como(rol_efectivo, perfil, claims, sql, params or {}))

    async def _como(
        self,
        rol: str,
        perfil: UUID | None,
        claims: dict[str, str],
        sql: str,
        params: dict[str, Any],
    ) -> Resultado:
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError

        async with self.engine.connect() as conn:
            tx = await conn.begin()
            try:
                if rol != "postgres":
                    # `rol` viene de ROLES_COMO (lista cerrada): no hay inyección.
                    await conn.execute(text(f"SET LOCAL ROLE {rol}"))
                    await conn.execute(
                        text(
                            "select set_config('request.jwt.claim.sub', :sub, true), "
                            "set_config('request.jwt.claims', :claims, true)"
                        ),
                        {"sub": str(perfil) if perfil else "", "claims": json.dumps(claims)},
                    )
                try:
                    res = await conn.execute(text(sql), params)
                except DBAPIError as exc:
                    return Resultado(sqlstate=_sqlstate(exc), mensaje=str(exc.orig)[:300])
                if res.returns_rows:
                    filas = [dict(f) for f in res.mappings()]
                    return Resultado(filas=filas, afectadas=len(filas))
                return Resultado(afectadas=int(res.rowcount))
            finally:
                await tx.rollback()


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

    ayudante = Integ(pg_integ)
    ayudante.truncar_todo()  # antes, no después: los datos de un fallo quedan
    app.dependency_overrides[get_db] = ayudante._get_db_override
    try:
        yield ayudante
    finally:
        app.dependency_overrides.pop(get_db, None)
