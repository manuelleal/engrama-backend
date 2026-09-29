"""B1 y B2: la migración 033 (una paga por reto) — `docs/ESPEC_bug13a15.md` §1.1, §2, §3.

Mismo patrón que `test_migracion_032.py`: cada test abre SU conexión, hace
`BEGIN`, prepara, siembra con SQL crudo, ejecuta el SQL de la 033 (las tuplas
`SQL_SUBIR` / `SQL_BAJAR`, importadas del archivo de la migración: es
exactamente lo que corre Alembic) y termina SIEMPRE con ROLLBACK. En
PostgreSQL el DDL también se deshace: la base de la sesión queda como estaba.

`_subir()` y `_bajar()` son el punto que parchean los tramposos Y5 e Y6
(`tests/tramposos/test_tramposos_bug13.py`).

  B1  C7  backfill: sobre un esquema previo a la 033 (preparado con
          `DROP ... IF EXISTS`), la fila de reto MÁS ANTIGUA de (T, R, E1)
          recibe `challenge:R:E1`, la repetida queda NULL, la de E2 recibe la
          suya, asistencia y reto sin `challenge_id` quedan NULL; las demás
          columnas no cambian; subir dos veces no falla ni cambia nada.
  B2  C8  rollback: `SQL_BAJAR` quita la columna y el UNIQUE; volver a subir
          deja la columna, el UNIQUE y el backfill.
"""
from __future__ import annotations

import importlib.util
import json
from collections.abc import Awaitable, Callable
from types import ModuleType
from typing import Any
from uuid import UUID, uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest

from tests.integ_db import RAIZ_BACKEND

pytestmark = pytest.mark.integ

RUTA_033 = RAIZ_BACKEND / "alembic" / "versions" / "033_una_paga_por_reto.py"
UNIQUE = "coin_ledger_idempotency_key"

# Preparación de B1 y B2 (ESPEC §3, ERR-23): SIEMPRE con IF EXISTS, así un
# tramposo que ya quitó algo no rompe la preparación.
PREPARAR_SIN_033 = (
    f"ALTER TABLE coin_ledger DROP CONSTRAINT IF EXISTS {UNIQUE};",
    "ALTER TABLE coin_ledger DROP COLUMN IF EXISTS idempotency_key;",
)

# Columnas del ledger enumeradas (ERR-24): todas menos la llave.
COLUMNAS = ("id, tenant_id, from_wallet_id, to_wallet_id, amount, action, "
            "created_by_profile_id, metadata, created_at")


def _cargar_033() -> ModuleType:
    """El módulo de la migración (su nombre empieza por dígito: no se puede `import`)."""
    spec = importlib.util.spec_from_file_location("migracion_033", RUTA_033)
    assert spec is not None and spec.loader is not None, f"no se pudo cargar {RUTA_033}"
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


M033 = _cargar_033()


async def _subir(conn: asyncpg.Connection) -> None:
    for sql in M033.SQL_SUBIR:
        await conn.execute(sql)


async def _bajar(conn: asyncpg.Connection) -> None:
    for sql in M033.SQL_BAJAR:
        await conn.execute(sql)


async def _correr(paso: Callable[[asyncpg.Connection], Awaitable[None]],
                  conn: asyncpg.Connection, que: str) -> None:
    """Que el SQL de la migración falle ES el criterio roto (C7: "no falla")."""
    try:
        await paso(conn)
    except asyncpg.PostgresError as e:
        raise AssertionError(f"{que} falló: {e.sqlstate} {e}") from e


def en_transaccion(integ: Any, cuerpo: Callable[[asyncpg.Connection], Awaitable[None]]) -> None:
    """BEGIN, `cuerpo(conn)`, ROLLBACK siempre (también si el cuerpo falla)."""
    dsn = integ.url.replace("postgresql+asyncpg://", "postgresql://", 1)

    async def _q() -> None:
        conn = await asyncpg.connect(dsn, timeout=10)
        try:
            tx = conn.transaction()
            await tx.start()
            try:
                await cuerpo(conn)
            finally:
                await tx.rollback()
        finally:
            await conn.close()

    integ.run(_q())


# =============================================================================
# Siembra cruda y lecturas del catálogo
# =============================================================================
async def tenant_crudo(conn: asyncpg.Connection) -> UUID:
    tid = uuid4()
    await conn.execute("insert into tenants (id, name, slug) values ($1, $2, $3)",
                       tid, f"Colegio {tid.hex[:6]}", f"t-{tid.hex[:12]}")
    return tid


async def _billetera(conn: asyncpg.Connection, tenant: UUID, tipo: str, dueno: UUID) -> UUID:
    return await conn.fetchval(
        "insert into coin_wallets (tenant_id, owner_type, owner_id, balance) "
        "values ($1, $2, $3, 0) returning id", tenant, tipo, dueno)


async def _perfil(conn: asyncpg.Connection) -> UUID:
    pid = uuid4()
    await conn.execute("insert into profiles (id, documento_id, full_name, pin_hash) "
                       "values ($1, $2, 'Sintetico B13', '')", pid, f"SINT-B13-{pid.hex[:8]}")
    return pid


async def _fila(conn: asyncpg.Connection, tenant: UUID, desde: UUID, hacia: UUID,
                accion: str, metadata: dict[str, Any], dias: int) -> UUID:
    """Una fila del ledger SIN la columna de llave, con `created_at` explícito.

    En una transacción `now()` empata (ESPEC §3): `dias` la envejece.
    """
    return await conn.fetchval(
        "insert into coin_ledger (tenant_id, from_wallet_id, to_wallet_id, amount, action, "
        "metadata, created_at) values ($1, $2, $3, 20, $4, $5::jsonb, "
        "now() - make_interval(days => $6)) returning id",
        tenant, desde, hacia, accion, json.dumps(metadata), dias)


async def _tiene_columna(conn: asyncpg.Connection) -> bool:
    return bool(await conn.fetchval(
        "select count(*) from information_schema.columns "
        "where table_schema = 'public' and table_name = 'coin_ledger' "
        "and column_name = 'idempotency_key'"))


async def _tiene_unique(conn: asyncpg.Connection) -> bool:
    return bool(await conn.fetchval(
        "select count(*) from pg_constraint where conname = $1 and contype = 'u'", UNIQUE))


async def _llaves(conn: asyncpg.Connection) -> dict[UUID, str | None]:
    return {f["id"]: f["idempotency_key"] for f in
            await conn.fetch("select id, idempotency_key from coin_ledger")}


async def _resto(conn: asyncpg.Connection) -> list[tuple[Any, ...]]:
    return [tuple(f) for f in await conn.fetch(f"select {COLUMNAS} from coin_ledger order by id")]


async def _escena(conn: asyncpg.Connection) -> tuple[dict[str, UUID], dict[UUID, str | None]]:
    """T con E1 y E2; reto R. Devuelve (ids de filas, llaves esperadas tras subir)."""
    t = await tenant_crudo(conn)
    e1, e2 = await _perfil(conn), await _perfil(conn)
    banco = await _billetera(conn, t, "tenant", t)
    w1, w2 = await _billetera(conn, t, "profile", e1), await _billetera(conn, t, "profile", e2)
    r = uuid4()
    meta_r = {"challenge_id": str(r), "attempt_id": str(uuid4())}
    f = {
        # La repetida se inserta PRIMERO y es más nueva: gana la más antigua, no la primera.
        "repetida": await _fila(conn, t, banco, w1, "challenge", meta_r, 1),
        "antigua": await _fila(conn, t, banco, w1, "challenge", meta_r, 2),
        "e2": await _fila(conn, t, banco, w2, "challenge", meta_r, 1),
        "asistencia": await _fila(conn, t, banco, w1, "attendance", {"session_id": str(r)}, 1),
        "sin_reto": await _fila(conn, t, banco, w1, "challenge", {"attempt_id": str(r)}, 1),
    }
    esperado = {f["repetida"]: None, f["antigua"]: f"challenge:{r}:{e1}",
                f["e2"]: f"challenge:{r}:{e2}", f["asistencia"]: None, f["sin_reto"]: None}
    return f, esperado


# =============================================================================
# B1 — backfill (C7)
# =============================================================================
def test_b1_backfill_la_mas_antigua_y_subir_dos_veces(integ) -> None:
    async def cuerpo(conn: asyncpg.Connection) -> None:
        for sql in PREPARAR_SIN_033:
            await conn.execute(sql)
        _, esperado = await _escena(conn)
        resto_antes = await _resto(conn)

        await _correr(_subir, conn, "SQL_SUBIR")
        assert await _llaves(conn) == esperado, "el backfill no dejó las llaves esperadas"
        assert await _resto(conn) == resto_antes, "la 033 cambió otras columnas del ledger"
        assert await _tiene_unique(conn), f"falta {UNIQUE} tras subir"

        await _correr(_subir, conn, "SQL_SUBIR (segunda vez)")
        assert await _llaves(conn) == esperado, "subir dos veces cambió las llaves"
        assert await _resto(conn) == resto_antes, "subir dos veces cambió otras columnas"

    en_transaccion(integ, cuerpo)


# =============================================================================
# B2 — rollback (C8)
# =============================================================================
def test_b2_bajar_quita_columna_y_unique_y_volver_a_subir(integ) -> None:
    async def cuerpo(conn: asyncpg.Connection) -> None:
        for sql in PREPARAR_SIN_033:
            await conn.execute(sql)
        _, esperado = await _escena(conn)
        await _correr(_subir, conn, "SQL_SUBIR")

        await _correr(_bajar, conn, "SQL_BAJAR")
        assert not await _tiene_columna(conn), "bajar no quitó coin_ledger.idempotency_key"
        assert not await _tiene_unique(conn), f"bajar no quitó {UNIQUE}"

        await _correr(_subir, conn, "SQL_SUBIR tras bajar")
        assert await _tiene_columna(conn), "volver a subir no dejó la columna"
        assert await _tiene_unique(conn), "volver a subir no dejó el UNIQUE"
        assert await _llaves(conn) == esperado, "volver a subir no dejó el backfill"

    en_transaccion(integ, cuerpo)
