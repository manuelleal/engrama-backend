"""MG1: la migración 034 (consentimientos) sube, baja y vuelve a subir idéntica.

`docs/ESPEC_consentimiento.md` §1.5 y C6. Mismo patrón que
`test_migracion_033.py`: una conexión propia, `BEGIN`, el SQL de la migración
(las tuplas `SQL_SUBIR` y `SQL_BAJAR` importadas de su archivo: exactamente lo
que corre Alembic) y SIEMPRE `ROLLBACK`. En PostgreSQL el DDL también se
deshace: la base de la sesión queda como estaba.

Qué se compara entre las dos subidas (ERR-24, los campos enumerados):
columnas (nombre, tipo, nulabilidad y default), la definición de cada
restricción (`pg_get_constraintdef`), los índices (`pg_indexes`) y si la tabla
tiene RLS. NO se compara `ordinal_position` ni `attnum`.
"""
from __future__ import annotations

import importlib.util
from types import ModuleType
from typing import Any

import asyncpg  # type: ignore[import-untyped]
import pytest

from tests.integ.test_migracion_033 import en_transaccion
from tests.integ_db import RAIZ_BACKEND

pytestmark = pytest.mark.integ

RUTA_034 = RAIZ_BACKEND / "alembic" / "versions" / "034_consentimiento.py"
TABLA = "consentimientos"


def _cargar_034() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migracion_034", RUTA_034)
    assert spec is not None and spec.loader is not None, f"no se pudo cargar {RUTA_034}"
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


M034 = _cargar_034()


async def _correr(conn: asyncpg.Connection, sentencias: tuple[str, ...], que: str) -> None:
    """Que el SQL de la migración falle ES el criterio roto (C6)."""
    try:
        for sql in sentencias:
            await conn.execute(sql)
    except asyncpg.PostgresError as e:
        raise AssertionError(f"{que} falló: {e.sqlstate} {e}") from e


async def esquema(conn: asyncpg.Connection) -> dict[str, Any]:
    """Lo que debe coincidir entre dos subidas; `None` si la tabla no existe."""
    if await conn.fetchval("select to_regclass($1)", f"public.{TABLA}") is None:
        return {"existe": False}
    columnas = await conn.fetch(
        "select column_name, data_type, is_nullable, column_default, is_identity, "
        "identity_generation from information_schema.columns "
        "where table_schema = 'public' and table_name = $1 order by column_name", TABLA)
    restricciones = await conn.fetch(
        "select conname, pg_get_constraintdef(oid) as definicion from pg_constraint "
        "where conrelid = $1::regclass order by conname", TABLA)
    indices = await conn.fetch(
        "select indexname, indexdef from pg_indexes "
        "where schemaname = 'public' and tablename = $1 order by indexname", TABLA)
    return {
        "existe": True,
        "columnas": [tuple(c.values()) for c in columnas],
        "restricciones": [tuple(r.values()) for r in restricciones],
        "indices": [tuple(i.values()) for i in indices],
        "rls": await conn.fetchval("select relrowsecurity from pg_class where oid = $1::regclass",
                                   TABLA),
        "politicas": await conn.fetchval(
            "select count(*) from pg_policies where schemaname = 'public' and tablename = $1",
            TABLA),
    }


def test_mg1_sube_baja_y_vuelve_a_subir_identica(integ) -> None:
    """MG1 (C6): up/down/up con el mismo esquema, y subir dos veces no falla."""
    visto: dict[str, Any] = {}

    async def cuerpo(conn: asyncpg.Connection) -> None:
        visto["primera_subida"] = await esquema(conn)  # la que dejó `alembic upgrade head`
        await _correr(conn, M034.SQL_BAJAR, "bajar la 034")
        visto["tras_bajar"] = await esquema(conn)
        await _correr(conn, M034.SQL_SUBIR, "volver a subir la 034")
        visto["segunda_subida"] = await esquema(conn)
        await _correr(conn, M034.SQL_SUBIR, "subir la 034 dos veces")
        visto["subida_repetida"] = await esquema(conn)

    en_transaccion(integ, cuerpo)
    primera = visto["primera_subida"]
    observado = {
        "primera_existe_con_rls_y_sin_politicas":
            (primera.get("existe"), primera.get("rls"), primera.get("politicas")),
        "columnas": [c[0] for c in primera.get("columnas", [])],
        "restricciones": [r[0] for r in primera.get("restricciones", [])],
        "tras_bajar": visto["tras_bajar"],
        "segunda_igual_a_la_primera": visto["segunda_subida"] == primera,
        "repetida_igual_a_la_primera": visto["subida_repetida"] == primera,
    }
    assert observado == {
        "primera_existe_con_rls_y_sin_politicas": (True, True, 0),
        "columnas": ["accepted_at", "id", "profile_id", "version"],
        "restricciones": ["consentimientos_perfil_version", "consentimientos_pkey",
                          "consentimientos_profile_id_fkey", "consentimientos_version_check"],
        "tras_bajar": {"existe": False},
        "segunda_igual_a_la_primera": True,
        "repetida_igual_a_la_primera": True,
    }, f"MG1: {observado}\nprimera: {primera}\nsegunda: {visto['segunda_subida']}"
