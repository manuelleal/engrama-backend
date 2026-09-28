"""B1, B2 y C9: la migración 032 (nombre por membresía) — `docs/ESPEC_bug11.md` §2, §3.

Por qué no se migra una base aparte (ESPEC §0): una base nueva dentro del
contenedor no tiene el esquema `auth` y la 029 usa `auth.uid()`. Entonces
cada test abre SU conexión, hace `BEGIN`, siembra con SQL crudo, ejecuta el
SQL de la 032 (las tuplas `SQL_SUBIR` / `SQL_BAJAR`, importadas del archivo
de la migración: es exactamente lo que corre Alembic) y termina con
ROLLBACK. En PostgreSQL el DDL también se deshace: la base de la sesión
queda como estaba.

`_subir()` y `_bajar()` son el punto que parchean los tramposos Y5 e Y7
(`tests/tramposos/test_tramposos_bug11.py`).

  B1  C7  backfill: `student` recibe el nombre de su perfil, `teacher` queda
          NULL, `profiles` idéntica, y subir dos veces no falla ni cambia nada.
  B2  C8  rollback: `SQL_BAJAR` restaura el nombre de la membresía MÁS ANTIGUA
          donde el perfil tenía '', y quita la columna y el CHECK; volver a
          subir deja columna, CHECK y backfill (la pérdida de N2 es la declarada).
  C9  C9  el CHECK: `student` sin nombre -> 23514; `teacher` sin nombre entra.
"""
from __future__ import annotations

import importlib.util
from collections.abc import Awaitable, Callable
from types import ModuleType
from typing import Any
from uuid import UUID, uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest

from tests.integ_db import RAIZ_BACKEND

pytestmark = pytest.mark.integ

RUTA_032 = RAIZ_BACKEND / "alembic" / "versions" / "032_nombre_por_membresia.py"
CHECK = "memberships_student_full_name_check"


def _cargar_032() -> ModuleType:
    """El módulo de la migración (su nombre empieza por dígito: no se puede `import`)."""
    spec = importlib.util.spec_from_file_location("migracion_032", RUTA_032)
    assert spec is not None and spec.loader is not None, f"no se pudo cargar {RUTA_032}"
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


M032 = _cargar_032()


async def _subir(conn: asyncpg.Connection) -> None:
    for sql in M032.SQL_SUBIR:
        await conn.execute(sql)


async def _bajar(conn: asyncpg.Connection) -> None:
    for sql in M032.SQL_BAJAR:
        await conn.execute(sql)


async def _correr(paso: Callable[[asyncpg.Connection], Awaitable[None]],
                  conn: asyncpg.Connection, que: str) -> None:
    """Corre `_subir`/`_bajar`. Que el SQL de la migración falle ES el criterio
    roto (C7: "no falla"), así que se reporta como AssertionError con su SQLSTATE."""
    try:
        await paso(conn)
    except asyncpg.PostgresError as e:
        raise AssertionError(f"{que} falló: {e.sqlstate} {e}") from e


def _en_transaccion(integ: Any, cuerpo: Callable[[asyncpg.Connection], Awaitable[None]]) -> None:
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
async def _tenant(conn: asyncpg.Connection) -> UUID:
    tid = uuid4()
    await conn.execute("insert into tenants (id, name, slug) values ($1, $2, $3)",
                       tid, f"Colegio {tid.hex[:6]}", f"t-{tid.hex[:12]}")
    return tid


async def _perfil(conn: asyncpg.Connection, doc: str, nombre: str) -> UUID:
    pid = uuid4()
    await conn.execute("insert into profiles (id, documento_id, full_name, pin_hash) "
                       "values ($1, $2, $3, '')", pid, doc, nombre)
    return pid


async def _tiene_columna(conn: asyncpg.Connection) -> bool:
    return bool(await conn.fetchval(
        "select count(*) from information_schema.columns "
        "where table_schema = 'public' and table_name = 'memberships' "
        "and column_name = 'full_name'"))


async def _tiene_check(conn: asyncpg.Connection) -> bool:
    return bool(await conn.fetchval(
        "select count(*) from pg_constraint where conname = $1", CHECK))


async def _perfiles(conn: asyncpg.Connection) -> list[tuple[Any, ...]]:
    return [tuple(f) for f in await conn.fetch("select * from profiles order by id")]


async def _nombres(conn: asyncpg.Connection) -> dict[tuple[UUID, UUID], str | None]:
    filas = await conn.fetch("select tenant_id, profile_id, full_name from memberships")
    return {(f["tenant_id"], f["profile_id"]): f["full_name"] for f in filas}


# =============================================================================
# B1 — backfill (C7)
# =============================================================================
def test_b1_backfill_solo_estudiantes_profiles_intacta_e_idempotente(integ) -> None:
    async def cuerpo(conn: asyncpg.Connection) -> None:
        # Estado anterior a la 032, sin pasar por SQL_BAJAR (B1 no depende de B2).
        await conn.execute(f"alter table memberships drop constraint {CHECK}")
        await conn.execute("alter table memberships drop column full_name")
        ta, tb = await _tenant(conn), await _tenant(conn)
        s1 = await _perfil(conn, "SINT-B11-0001", "Ana Prueba Alfa")
        s2 = await _perfil(conn, "SINT-B11-0101", "Beto Prueba Alfa")
        doc = await _perfil(conn, "SINT-B11-0201", "Docente Prueba")
        for tenant, pid, rol in ((ta, s1, "student"), (tb, s1, "student"),
                                 (ta, s2, "student"), (ta, doc, "teacher")):
            await conn.execute("insert into memberships (tenant_id, profile_id, role) "
                               "values ($1, $2, $3)", tenant, pid, rol)
        perfiles_antes = await _perfiles(conn)

        await _correr(_subir, conn, "SQL_SUBIR")
        esperado = {(ta, s1): "Ana Prueba Alfa", (tb, s1): "Ana Prueba Alfa",
                    (ta, s2): "Beto Prueba Alfa", (ta, doc): None}
        assert await _nombres(conn) == esperado, "el backfill no dejó lo esperado"
        assert await _perfiles(conn) == perfiles_antes, "la 032 cambió `profiles`"
        assert await _tiene_check(conn), f"falta {CHECK} tras subir"

        await _correr(_subir, conn, "SQL_SUBIR (segunda vez)")
        assert await _nombres(conn) == esperado, "subir dos veces cambió las membresías"
        assert await _perfiles(conn) == perfiles_antes, "subir dos veces cambió `profiles`"

    _en_transaccion(integ, cuerpo)


# =============================================================================
# B2 — rollback (C8)
# =============================================================================
def test_b2_bajar_restaura_la_mas_antigua_y_volver_a_subir(integ) -> None:
    n1, n2 = "Ana Prueba Alfa", "Ana Prueba Beta"

    async def cuerpo(conn: asyncpg.Connection) -> None:
        ta, tb = await _tenant(conn), await _tenant(conn)
        p = await _perfil(conn, "SINT-B11-0001", "")                # nació con la 032
        q = await _perfil(conn, "SINT-B11-0101", "Nombre Propio")   # nombre propio: no se toca
        # `created_at` explícitos: dentro de la transacción now() empata (ESPEC §3).
        insertar = ("insert into memberships (tenant_id, profile_id, role, full_name, created_at) "
                    "values ($1, $2, 'student', $3, now() - make_interval(days => $4))")
        await conn.execute(insertar, tb, p, n2, 0)
        await conn.execute(insertar, ta, p, n1, 1)                  # A: la más antigua
        await conn.execute(insertar, ta, q, "Otro Nombre Alfa", 1)

        await _correr(_bajar, conn, "SQL_BAJAR")
        perfiles = {f["id"]: f["full_name"] for f in
                    await conn.fetch("select id, full_name from profiles")}
        assert perfiles[p] == n1, f"bajar dejó {perfiles[p]!r} en el perfil; se esperaba {n1!r}"
        assert perfiles[q] == "Nombre Propio", "bajar pisó un nombre propio (no era '')"
        assert not await _tiene_columna(conn), "bajar no quitó memberships.full_name"
        assert not await _tiene_check(conn), f"bajar no quitó {CHECK}"

        await _correr(_subir, conn, "SQL_SUBIR tras bajar")
        assert await _tiene_columna(conn) and await _tiene_check(conn), "subir no volvió"
        # La pérdida declarada (ESPEC §1, §7): B hereda el N1 de A; su N2 no vuelve.
        assert await _nombres(conn) == {(ta, p): n1, (tb, p): n1, (ta, q): "Nombre Propio"}, (
            "volver a subir no dejó el backfill"
        )

    _en_transaccion(integ, cuerpo)


# =============================================================================
# C9 — el CHECK en la base
# =============================================================================
def test_c1_check_estudiante_sin_nombre(integ) -> None:
    """C9: `student` sin nombre -> 23514 con el nombre del CHECK; `teacher` sin nombre entra."""
    async def cuerpo(conn: asyncpg.Connection) -> None:
        ta = await _tenant(conn)
        estudiante = await _perfil(conn, "SINT-B11-0001", "")
        docente = await _perfil(conn, "SINT-B11-0101", "")
        sqlstate, mensaje = None, ""
        try:
            async with conn.transaction():  # SAVEPOINT: el error no aborta el resto
                await conn.execute("insert into memberships (tenant_id, profile_id, role) "
                                   "values ($1, $2, 'student')", ta, estudiante)
        except asyncpg.PostgresError as e:
            sqlstate, mensaje = e.sqlstate, str(e)
        assert sqlstate == "23514" and CHECK in mensaje, (
            f"un student sin nombre entró o falló por otra cosa: {sqlstate} {mensaje!r}"
        )
        await conn.execute("insert into memberships (tenant_id, profile_id, role) "
                           "values ($1, $2, 'teacher')", ta, docente)
        assert await conn.fetchval("select count(*) from memberships where profile_id = $1 "
                                   "and full_name is null", docente) == 1

    _en_transaccion(integ, cuerpo)
