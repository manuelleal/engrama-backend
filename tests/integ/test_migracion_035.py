"""MG35: la migración 035 (autorregistro) sube, baja y vuelve a subir idéntica.

`docs/ESPEC_autorregistro.md` §1.10 y C16. Mismo patrón que `test_migracion_034.py`:
una conexión propia, `BEGIN`, el SQL de la migración (las tuplas `SQL_SUBIR` y
`SQL_BAJAR` importadas de su archivo: exactamente lo que corre Alembic) y
SIEMPRE `ROLLBACK`.

Qué se compara entre las dos subidas (ERR-24, los campos enumerados), por cada
tabla: columnas (nombre, tipo, nulabilidad y default), la definición de cada
restricción (`pg_get_constraintdef`), los índices (`pg_indexes`) y si tiene
RLS. NO se compara `ordinal_position` ni `attnum`.
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

TABLAS = ("codigos_inscripcion", "solicitudes_inscripcion")


def cargar(archivo: str) -> ModuleType:
    ruta = RAIZ_BACKEND / "alembic" / "versions" / archivo
    spec = importlib.util.spec_from_file_location(archivo.removesuffix(".py"), ruta)
    assert spec is not None and spec.loader is not None, f"no se pudo cargar {ruta}"
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


M035 = cargar("035_autorregistro.py")


async def correr(conn: asyncpg.Connection, sentencias: tuple[str, ...], que: str) -> None:
    """Que el SQL de la migración falle ES el criterio roto."""
    try:
        for sql in sentencias:
            await conn.execute(sql)
    except asyncpg.PostgresError as e:
        raise AssertionError(f"{que} falló: {e.sqlstate} {e}") from e


async def esquema_de(conn: asyncpg.Connection, tabla: str) -> dict[str, Any]:
    """Lo que debe coincidir entre dos subidas; `{"existe": False}` si no está."""
    if await conn.fetchval("select to_regclass($1)", f"public.{tabla}") is None:
        return {"existe": False}
    columnas = await conn.fetch(
        "select column_name, data_type, is_nullable, column_default, is_identity, "
        "identity_generation from information_schema.columns "
        "where table_schema = 'public' and table_name = $1 order by column_name", tabla)
    restricciones = await conn.fetch(
        "select conname, pg_get_constraintdef(oid) as definicion from pg_constraint "
        "where conrelid = $1::regclass order by conname", tabla)
    indices = await conn.fetch(
        "select indexname, indexdef from pg_indexes "
        "where schemaname = 'public' and tablename = $1 order by indexname", tabla)
    return {
        "existe": True,
        "columnas": [tuple(c.values()) for c in columnas],
        "restricciones": [tuple(r.values()) for r in restricciones],
        "indices": [tuple(i.values()) for i in indices],
        "rls": await conn.fetchval("select relrowsecurity from pg_class where oid = $1::regclass",
                                   tabla),
        "politicas": await conn.fetchval(
            "select count(*) from pg_policies where schemaname = 'public' and tablename = $1",
            tabla),
    }


async def esquema(conn: asyncpg.Connection, tablas: tuple[str, ...]) -> dict[str, Any]:
    return {t: await esquema_de(conn, t) for t in tablas}


def sube_baja_sube(integ: Any, modulo: ModuleType, tablas: tuple[str, ...]) -> dict[str, Any]:
    """Corre up/down/up/up en una transacción que se deshace y devuelve lo visto."""
    visto: dict[str, Any] = {}

    async def cuerpo(conn: asyncpg.Connection) -> None:
        visto["primera"] = await esquema(conn, tablas)  # la de `alembic upgrade head`
        await correr(conn, modulo.SQL_BAJAR, "bajar")
        visto["tras_bajar"] = await esquema(conn, tablas)
        await correr(conn, modulo.SQL_SUBIR, "volver a subir")
        visto["segunda"] = await esquema(conn, tablas)
        await correr(conn, modulo.SQL_SUBIR, "subir dos veces")
        visto["repetida"] = await esquema(conn, tablas)

    en_transaccion(integ, cuerpo)
    return visto


def resumen(visto: dict[str, Any], tablas: tuple[str, ...]) -> dict[str, Any]:
    primera = visto["primera"]
    return {
        "con_rls_y_sin_politicas": {t: (primera[t].get("existe"), primera[t].get("rls"),
                                        primera[t].get("politicas")) for t in tablas},
        "restricciones": {t: [r[0] for r in primera[t].get("restricciones", [])]
                          for t in tablas},
        "indices": {t: [i[0] for i in primera[t].get("indices", [])] for t in tablas},
        "tras_bajar": visto["tras_bajar"],
        "segunda_igual_a_la_primera": visto["segunda"] == primera,
        "repetida_igual_a_la_primera": visto["repetida"] == primera,
    }


def test_mg35_sube_baja_y_vuelve_a_subir_identica(integ) -> None:
    """MG35 (C16): up/down/up con el mismo esquema, y subir dos veces no falla."""
    visto = sube_baja_sube(integ, M035, TABLAS)
    observado = resumen(visto, TABLAS)
    assert observado == {
        "con_rls_y_sin_politicas": dict.fromkeys(TABLAS, (True, True, 0)),
        "restricciones": {
            "codigos_inscripcion": [
                "codigos_inscripcion_created_by_fkey", "codigos_inscripcion_cupo_check",
                "codigos_inscripcion_group_id_fkey", "codigos_inscripcion_hash_check",
                "codigos_inscripcion_hash_key", "codigos_inscripcion_pkey",
                "codigos_inscripcion_tenant_id_fkey", "codigos_inscripcion_usos_check"],
            "solicitudes_inscripcion": [
                "solicitudes_inscripcion_codigo_id_fkey",
                "solicitudes_inscripcion_decidida_por_fkey",
                "solicitudes_inscripcion_decision_check",
                "solicitudes_inscripcion_estado_check", "solicitudes_inscripcion_group_id_fkey",
                "solicitudes_inscripcion_mayor_check", "solicitudes_inscripcion_perfil_key",
                "solicitudes_inscripcion_pkey", "solicitudes_inscripcion_profile_id_fkey",
                "solicitudes_inscripcion_tenant_id_fkey"],
        },
        "indices": {
            "codigos_inscripcion": ["codigos_inscripcion_hash_key", "codigos_inscripcion_pkey",
                                    "codigos_inscripcion_uno_activo"],
            "solicitudes_inscripcion": ["idx_solicitudes_inscripcion_grupo",
                                        "solicitudes_inscripcion_perfil_key",
                                        "solicitudes_inscripcion_pkey"],
        },
        "tras_bajar": dict.fromkeys(TABLAS, {"existe": False}),
        "segunda_igual_a_la_primera": True, "repetida_igual_a_la_primera": True,
    }, f"MG35: {observado}\nprimera: {visto['primera']}\nsegunda: {visto['segunda']}"
