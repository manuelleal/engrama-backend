"""MG50 (IP13): la migración 050 (invitaciones de profes) sube, baja y vuelve a subir idéntica.

`docs/ESPEC_invitar_profe.md` §3.6 e IP13. Mismo patrón que `test_migracion_035.py`
(se reusan sus ayudas): una conexión propia, `BEGIN`, el SQL de la migración
(las tuplas `SQL_SUBIR` y `SQL_BAJAR` de su archivo) y SIEMPRE `ROLLBACK`.

Además: RLS activa sin políticas y NINGÚN privilegio para los roles de cliente
(`anon`, `authenticated`) sobre la tabla nueva.
"""
from __future__ import annotations

from typing import Any

import pytest

import asyncpg  # type: ignore[import-untyped]

from tests.integ.test_migracion_033 import en_transaccion
from tests.integ.test_migracion_035 import cargar, correr, resumen, sube_baja_sube

pytestmark = pytest.mark.integ

TABLAS = ("invitaciones_docente",)
M050 = cargar("050_invitaciones_docente.py")

PRIVILEGIOS_DE_CLIENTES = """
    select string_agg(r.rolname || ':' || p.priv, ',' order by r.rolname, p.priv)
    from (values ('anon'), ('authenticated')) as r(rolname)
    cross join (values ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE')) as p(priv)
    where has_table_privilege(r.rolname, 'public.invitaciones_docente', p.priv)
"""


def test_mg50_sube_baja_y_vuelve_a_subir_identica(integ: Any) -> None:
    visto = sube_baja_sube(integ, M050, TABLAS)
    observado = resumen(visto, TABLAS)
    observado["privilegios_de_clientes"] = integ.valor(PRIVILEGIOS_DE_CLIENTES)
    observado["cabeza"] = integ.valor("select version_num from alembic_version")
    assert observado == {
        "con_rls_y_sin_politicas": {"invitaciones_docente": (True, True, 0)},
        "restricciones": {"invitaciones_docente": [
            "invitaciones_docente_correo_check", "invitaciones_docente_correo_key",
            "invitaciones_docente_envios_check", "invitaciones_docente_group_id_fkey",
            "invitaciones_docente_invitada_por_fkey", "invitaciones_docente_perfil_key",
            "invitaciones_docente_pkey", "invitaciones_docente_profile_id_fkey",
            "invitaciones_docente_tenant_id_fkey"]},
        "indices": {"invitaciones_docente": [
            "invitaciones_docente_correo_key", "invitaciones_docente_perfil_key",
            "invitaciones_docente_pkey"]},
        "tras_bajar": {"invitaciones_docente": {"existe": False}},
        "segunda_igual_a_la_primera": True, "repetida_igual_a_la_primera": True,
        "privilegios_de_clientes": None,
        "cabeza": "050_invitaciones_docente",
    }, f"MG50: {observado}"


def test_mg50b_cerrada_aunque_los_privilegios_por_defecto_la_abran(integ: Any) -> None:
    """IP13b (H-1): con privilegios por defecto que SÍ darían todo a los clientes,
    la tabla nace cerrada igual (el REVOKE de la 050). Todo en una transacción que se deshace."""
    visto: dict[str, Any] = {}

    async def cuerpo(conn: asyncpg.Connection) -> None:
        await correr(conn, M050.SQL_BAJAR, "bajar")
        await conn.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                           "GRANT ALL ON TABLES TO anon, authenticated")
        await correr(conn, M050.SQL_SUBIR, "subir con privilegios por defecto abiertos")
        visto["privilegios_de_clientes"] = await conn.fetchval(PRIVILEGIOS_DE_CLIENTES)

    en_transaccion(integ, cuerpo)
    assert visto == {"privilegios_de_clientes": None}, f"MG50b: {visto}"
