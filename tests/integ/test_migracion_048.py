"""MG46: la migración 048 (el límite compartido; era la 046, ERR-45) sube, baja y vuelve a subir idéntica.

`docs/ESPEC_limites_registro.md` §1.2 y C6. Usa las funciones de
`test_migracion_035.py` (ERR-24): una conexión propia, `BEGIN`, el SQL de la
migración (las tuplas importadas de su archivo) y SIEMPRE `ROLLBACK`.

Además de lo que compara `esquema_de`, mira la persistencia de la tabla
(`relpersistence = 'u'`: UNLOGGED), que es parte de la decisión de la espec.

El cuerpo recibe el módulo de la migración para que el tramposo ZR43
(`tests/tramposos/test_tramposos_limite_compartido.py`) le pase uno roto.
"""
from __future__ import annotations

from types import ModuleType, SimpleNamespace
from typing import Any

import asyncpg  # type: ignore[import-untyped]
import pytest

from tests.integ.test_migracion_033 import en_transaccion
from tests.integ.test_migracion_035 import cargar, correr, esquema_de

pytestmark = pytest.mark.integ

TABLA = "limite_intentos"
M046 = cargar("048_limite_compartido.py")


async def _persistencia(conn: asyncpg.Connection) -> str | None:
    if await conn.fetchval("select to_regclass($1)", f"public.{TABLA}") is None:
        return None
    return str(await conn.fetchval(
        "select relpersistence::text from pg_class where oid = $1::regclass", TABLA))


def cuerpo_mg46(integ: Any, modulo: ModuleType | SimpleNamespace) -> None:
    visto: dict[str, Any] = {}

    async def cuerpo(conn: asyncpg.Connection) -> None:
        visto["primera"] = await esquema_de(conn, TABLA)  # la de `alembic upgrade head`
        visto["persistencia"] = await _persistencia(conn)
        await correr(conn, modulo.SQL_BAJAR, "bajar")
        visto["tras_bajar"] = await esquema_de(conn, TABLA)
        await correr(conn, modulo.SQL_SUBIR, "volver a subir")
        visto["segunda"] = await esquema_de(conn, TABLA)
        visto["persistencia_segunda"] = await _persistencia(conn)
        await correr(conn, modulo.SQL_SUBIR, "subir dos veces")
        visto["repetida"] = await esquema_de(conn, TABLA)

    en_transaccion(integ, cuerpo)
    primera = visto["primera"]
    observado = {
        "con_rls_y_sin_politicas": (primera.get("existe"), primera.get("rls"),
                                    primera.get("politicas")),
        "unlogged": (visto["persistencia"], visto["persistencia_segunda"]),
        "columnas": [c[:4] for c in primera.get("columnas", [])],
        "restricciones": [r[0] for r in primera.get("restricciones", [])],
        "indices": [i[0] for i in primera.get("indices", [])],
        "tras_bajar": {"la_tabla": visto["tras_bajar"]},
        "segunda_igual_a_la_primera": visto["segunda"] == primera,
        "repetida_igual_a_la_primera": visto["repetida"] == primera,
    }
    assert observado == {
        "con_rls_y_sin_politicas": (True, True, 0),
        "unlogged": ("u", "u"),
        "columnas": [("contador", "text", "NO", None), ("id", "bigint", "NO", None),
                     ("llave", "text", "NO", None), ("momento", "double precision", "NO", None)],
        "restricciones": ["limite_intentos_contador_check", "limite_intentos_pkey"],
        "indices": ["idx_limite_intentos_llave", "idx_limite_intentos_purga",
                    "limite_intentos_pkey"],
        "tras_bajar": {"la_tabla": {"existe": False}},
        "segunda_igual_a_la_primera": True, "repetida_igual_a_la_primera": True,
    }, f"MG46: {observado}"


def test_mg46_sube_baja_y_vuelve_a_subir_identica(integ) -> None:
    """MG46 (C6): up/down/up con el mismo esquema, UNLOGGED, con RLS y sin políticas."""
    cuerpo_mg46(integ, M046)
