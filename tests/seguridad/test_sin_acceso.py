"""D12 y D13: los clientes no tienen acceso directo a `public` (031, decisión 005).

Espec: docs/ESPEC_bug3a9_sin_acceso_directo.md §2.

Los ataques D1-D11 prueban tabla por tabla con una sentencia real. Estos dos
miran el CATÁLOGO, para que nada se escape por no tener un test propio:
  - D12: lo que existe hoy. 0 tablas, vistas o secuencias de `public` con
    algún privilegio para `anon` o `authenticated`, y 0 funciones de `public`
    que ellos puedan ejecutar (una función nueva nace ejecutable por PUBLIC:
    D12 detecta el `REVOKE ... FROM PUBLIC` olvidado).
  - D13: lo que `postgres` cree mañana. Se crea una tabla y una secuencia en
    una transacción que se deshace: sus DEFAULT PRIVILEGES no dan nada a los
    clientes.
Cada uno lleva su control: la misma consulta SÍ ve los privilegios de
`service_role` (el backend). Si el control falla, es PruebaRota (el test está
roto), no un resultado.
Tramposos: tests/tramposos/test_tramposos_seguridad.py (D12, D13).
"""
from __future__ import annotations

from typing import Any

import pytest

from tests.seguridad.veredictos import CLIENTES, PruebaRota

pytestmark = pytest.mark.integ

# Todos los privilegios de tabla de PostgreSQL 17 (MAINTAIN es de la 17) y de
# columna; los de secuencia. `has_*_privilege` con una lista separada por
# comas es verdadero si el rol tiene CUALQUIERA de ellos (directo, por PUBLIC
# o por un rol del que es miembro).
PRIV_TABLA = "SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN"
PRIV_COLUMNA = "SELECT,INSERT,UPDATE,REFERENCES"
PRIV_SECUENCIA = "USAGE,SELECT,UPDATE"

# relkind: r tabla, p tabla particionada, v vista, m vista materializada,
# f tabla foránea, S secuencia.
_CON_PRIVILEGIO = f"""
    case when c.relkind = 'S'
         then has_sequence_privilege(r.rol, c.oid, '{PRIV_SECUENCIA}')
         else has_table_privilege(r.rol, c.oid, '{PRIV_TABLA}')
              or has_any_column_privilege(r.rol, c.oid, '{PRIV_COLUMNA}')
    end
"""

_CLIENTES_SQL = ", ".join(f"('{rol}')" for rol in CLIENTES)

D12_RELACIONES = f"""
    select string_agg(c.relname || '(' || r.rol || ')', ', ' order by c.relname, r.rol)
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    cross join (values {_CLIENTES_SQL}) as r(rol)
    where n.nspname = 'public' and c.relkind in ('r', 'p', 'v', 'm', 'f', 'S')
      and {_CON_PRIVILEGIO}
"""

D12_FUNCIONES = f"""
    select string_agg(p.oid::regprocedure::text || '(' || r.rol || ')', ', '
                      order by p.oid::regprocedure::text, r.rol)
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    cross join (values {_CLIENTES_SQL}) as r(rol)
    where n.nspname = :esquema and has_function_privilege(r.rol, p.oid, 'EXECUTE')
"""


def test_d12_catalogo_sin_privilegios_de_clientes(integ) -> None:
    """D12: 0 relaciones de `public` con privilegios de clientes y 0 funciones ejecutables."""
    # Control 1: la consulta ve las 39 tablas (38 del modelo + alembic_version).
    tablas = integ.valor(
        "select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'public' and c.relkind = 'r'"
    )
    # Control 2: el mismo tipo de chequeo SÍ detecta privilegios: service_role
    # (el backend) tiene SELECT, INSERT, UPDATE y DELETE en las 39.
    del_backend = integ.valor(
        "select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'public' and c.relkind = 'r' "
        "  and has_table_privilege('service_role', c.oid, 'SELECT') "
        "  and has_table_privilege('service_role', c.oid, 'INSERT') "
        "  and has_table_privilege('service_role', c.oid, 'UPDATE') "
        "  and has_table_privilege('service_role', c.oid, 'DELETE')"
    )
    if (tablas, del_backend) != (39, 39):
        raise PruebaRota(f"control D12: {tablas} tablas y service_role con acceso en "
                         f"{del_backend}; se esperaban 39 y 39")
    # Control 3: la consulta de funciones SÍ ve una ejecutable (la de la 030,
    # que `authenticated` ejecuta a propósito, en app_private).
    en_app_private = integ.valor(D12_FUNCIONES, esquema="app_private")
    if en_app_private != "app_private.user_tenant_ids()(authenticated)":
        raise PruebaRota(f"control D12: funciones de app_private = {en_app_private!r}")

    abiertas = integ.valor(D12_RELACIONES)
    assert abiertas is None, f"D12: relaciones de public con privilegios de clientes: {abiertas}"
    ejecutables = integ.valor(D12_FUNCIONES, esquema="public")
    assert ejecutables is None, f"D12: funciones de public ejecutables por clientes: {ejecutables}"


def _privilegios_de_lo_nuevo(integ: Any) -> dict[str, Any]:
    """Crea una tabla y una secuencia como `postgres`, mide y DESHACE todo."""
    from sqlalchemy import text

    columnas = ["current_user as creador"]
    for rol in CLIENTES:
        columnas += [
            f"has_table_privilege('{rol}', 'public.d13_nueva', '{PRIV_TABLA}') "
            f"or has_any_column_privilege('{rol}', 'public.d13_nueva', '{PRIV_COLUMNA}') "
            f"as {rol}_tabla",
            f"has_sequence_privilege('{rol}', 'public.d13_nueva_seq', '{PRIV_SECUENCIA}') "
            f"as {rol}_secuencia",
        ]
    columnas += [
        "has_table_privilege('service_role', 'public.d13_nueva', 'SELECT') "
        "and has_table_privilege('service_role', 'public.d13_nueva', 'INSERT') "
        "and has_table_privilege('service_role', 'public.d13_nueva', 'UPDATE') "
        "and has_table_privilege('service_role', 'public.d13_nueva', 'DELETE') "
        "as service_role_tabla",
        "has_sequence_privilege('service_role', 'public.d13_nueva_seq', 'USAGE') "
        "as service_role_secuencia",
    ]

    async def _medir() -> dict[str, Any]:
        async with integ.engine.connect() as conn:
            tx = await conn.begin()
            try:
                await conn.execute(text("create table public.d13_nueva (id int)"))
                await conn.execute(text("create sequence public.d13_nueva_seq"))
                fila = (await conn.execute(text("select " + ", ".join(columnas)))).mappings()
                return dict(fila.one())
            finally:
                await tx.rollback()  # la tabla y la secuencia no sobreviven

    return integ.run(_medir())  # type: ignore[no-any-return]


def test_d13_lo_nuevo_nace_cerrado(integ) -> None:
    """D13: lo que `postgres` crea en `public` no da nada a los clientes; a service_role sí."""
    fila = _privilegios_de_lo_nuevo(integ)
    control = {k: fila[k] for k in ("creador", "service_role_tabla", "service_role_secuencia")}
    if control != {"creador": "postgres", "service_role_tabla": True,
                   "service_role_secuencia": True}:
        raise PruebaRota(f"control D13: {control}")
    abiertos = sorted(k for k, v in fila.items() if k.startswith(CLIENTES) and v is not False)
    assert not abiertos, f"D13: lo nuevo de postgres nace abierto para: {abiertos}"
    # Control de que la consulta vio lo nuevo (evita un vacío si faltara una columna).
    assert sorted(fila) == sorted(["creador", "service_role_tabla", "service_role_secuencia"]
                                  + [f"{r}_{o}" for r in CLIENTES for o in ("tabla", "secuencia")])
    assert integ.valor("select to_regclass('public.d13_nueva') is null") is True
