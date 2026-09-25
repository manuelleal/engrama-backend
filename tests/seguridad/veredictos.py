"""Cómo se juzga un ataque contra la base.

Espec: docs/ESPEC_aceptacion_seguridad.md §3 y, desde la 031,
docs/ESPEC_bug3a9_sin_acceso_directo.md §2 (decisión 005: los clientes no
tienen NINGÚN acceso directo a `public`).

Regla anti-vacío: un "sin acceso" solo vale si en la misma prueba hay un
control que demuestra que la sentencia era válida (como `postgres`) y que el
backend sí la puede correr (como `service_role`), y que la identidad del
atacante llegó a la base (`identidad`).

`sin_acceso(res, tabla, que)`:
  42501 "permission denied for table <tabla>" : el único resultado válido.
  42P17, otro 42501 o sin error               : AssertionError. "0 filas" NO
      vale: la RLS también las produce, y un GRANT devuelto a mano dejaría
      pasar el test. Otro 42501 (p. ej. "permission denied for table
      memberships" o "new row violates row-level security policy") significa
      que el cliente SÍ tiene permiso sobre `tabla` y lo paró otra cosa.
  Otro SQLSTATE                               : PruebaRota (FK, sintaxis,
      NOT NULL...). NO es AssertionError: un tramposo que espera
      AssertionError no puede confundirlo con un rechazo.

Este módulo no empieza por `test_`: pytest no lo recolecta.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any
from uuid import UUID

from tests.integ_ayudante import Integ
from tests.integ_db import RAIZ_BACKEND
from tests.seguridad.como import Resultado

RECHAZO = "42501"   # insufficient_privilege: la RLS (o un GRANT) dijo que no
RLS_ROTA = "42P17"  # infinite_recursion: la política se consulta a sí misma

# Roles de cliente de Supabase, en el orden en que se ataca (031: ninguno
# tiene acceso directo a `public`).
CLIENTES = ("anon", "authenticated")

RUTA_HUMO_SEGURIDAD = RAIZ_BACKEND / "tests" / "_salida" / "humo_seguridad.json"

# Réplica (espec §6): con ENGRAMA_REPLICA=1 se invierte el sentido del ataque.
# Normal: ataca el primero que se crea (perfil A, colegio T1).
# Réplica: ataca el segundo (B ataca a A, T2 ataca a T1). Los uuid4 son nuevos
# en cada corrida; los conteos deben salir idénticos.
REPLICA = os.environ.get("ENGRAMA_REPLICA") == "1"


class PruebaRota(RuntimeError):
    """El test mismo está mal: su sentencia o su arnés no hacen lo que dicen."""


def par(primero: Any, segundo: Any) -> tuple[Any, Any]:
    """(atacante, víctima) según el sentido de la corrida."""
    return (segundo, primero) if REPLICA else (primero, segundo)


def colegios(integ: Integ, *, pool: int = 1000) -> tuple[UUID, UUID]:
    """(colegio del atacante, colegio ajeno)."""
    t1 = integ.crear_tenant(pool=pool)
    t2 = integ.crear_tenant(pool=pool)
    return par(t1, t2)


def sembrar(integ: Integ, sql: str, **params: Any) -> None:
    """Escritura de preparación como `postgres`, confirmada (no es un ataque)."""
    from sqlalchemy import text

    async def _s() -> None:
        async with integ.engine.begin() as conn:
            await conn.execute(text(sql), params)

    integ.run(_s())


def _describir(res: Resultado) -> str:
    if res.sqlstate is None:
        return f"sin error, {res.afectadas} fila(s)"
    return f"SQLSTATE {res.sqlstate}: {res.mensaje}"


def sin_acceso(res: Resultado, tabla: str, que: str) -> None:
    """Afirma que el cliente no tiene privilegio sobre `tabla` (031, espec §2).

    Único válido: 42501 con "permission denied for table <tabla>" (la palabra
    completa: `groups` no se confunde con `teacher_groups`).
    """
    if res.sqlstate == RLS_ROTA:
        raise AssertionError(f"{que}: 42P17, la RLS se rompe (BUG-2) -> {_describir(res)}")
    if res.sqlstate is not None and res.sqlstate != RECHAZO:
        raise PruebaRota(f"{que}: error que no es de privilegios -> {_describir(res)}")
    patron = rf"permission denied for table {re.escape(tabla)}\b"
    if res.sqlstate == RECHAZO and re.search(patron, res.mensaje):
        return
    raise AssertionError(
        f"{que}: se esperaba 42501 'permission denied for table {tabla}' "
        f"y llegó {_describir(res)}"
    )


def control_postgres(res: Resultado, que: str, *, filas: int = 1, rol: str = "postgres") -> None:
    """La misma sentencia como `rol` funciona. Si no, el test está roto."""
    if res.sqlstate is not None or res.afectadas != filas:
        raise PruebaRota(
            f"control '{que}' como {rol}: {_describir(res)}; se esperaban {filas} fila(s)"
        )


def controles(integ: Integ, sql: str, params: dict[str, Any], que: str,
              *, filas: int = 1) -> None:
    """Control positivo (espec §2): `postgres` y `service_role` corren la sentencia.

    `postgres` prueba que la sentencia es válida; `service_role` (el backend)
    prueba que la 031 no le quitó el acceso. Se deshace (`como` hace ROLLBACK).
    """
    for rol in ("postgres", "service_role"):
        control_postgres(integ.como(None, sql, params, rol=rol), que, filas=filas, rol=rol)


def atacar(integ: Integ, perfil: UUID, sql: str, params: dict[str, Any], *, tabla: str,
           que: str, filas: int = 1, humo: tuple[str, str] | None = None) -> None:
    """Controles y el ataque como `anon` y como `authenticated` (con `perfil`).

    `humo` = (id, rol): registra en humo_seguridad.json el resultado de ese
    rol ANTES de juzgarlo, para que un rojo también quede escrito.
    """
    controles(integ, sql, params, f"{que} ({tabla})", filas=filas)
    for rol in CLIENTES:
        res = integ.como(None if rol == "anon" else perfil, sql, params)
        if humo is not None and humo[1] == rol:
            registrar_humo(humo[0], rol, res)
        sin_acceso(res, tabla, f"[{rol}] {que}")


def identidad(integ: Integ, perfil: UUID | None) -> None:
    """La identidad llegó a la base: `auth.uid()` y `current_user` son los del atacante.

    Sin este control, un `como` que no fijara el claim daría auth.uid() = NULL
    y TODO parecería "rechazado" (ERR-8: test que pasa vacío).
    """
    res = integ.como(perfil, "select auth.uid() as uid, current_user as rol")
    esperado = {
        "uid": perfil,
        "rol": "anon" if perfil is None else "authenticated",
    }
    if res.sqlstate is not None or res.filas != [esperado]:
        raise PruebaRota(f"identidad: se esperaba {esperado}, llegó {_describir(res)} {res.filas}")


def veredicto(res: Resultado) -> str:
    if res.sqlstate == RLS_ROTA:
        return "rota (42P17)"
    if res.sqlstate == RECHAZO or (res.sqlstate is None and res.afectadas == 0):
        return "rechaza"
    if res.sqlstate is not None:
        return f"error {res.sqlstate}"
    return "pasa"


def registrar_humo(id_: str, rol: str, res: Resultado) -> None:
    """Agrega una entrada a tests/_salida/humo_seguridad.json (espec §6).

    Sin uuids ni horas: la réplica debe escribir un archivo idéntico.
    """
    datos: dict[str, Any] = {}
    if RUTA_HUMO_SEGURIDAD.exists():
        datos = json.loads(RUTA_HUMO_SEGURIDAD.read_text(encoding="utf-8"))
    datos[id_] = {
        "id": id_,
        "rol": rol,
        "sqlstate": res.sqlstate,
        "filas": res.afectadas,
        "veredicto": veredicto(res),
    }
    RUTA_HUMO_SEGURIDAD.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO_SEGURIDAD.write_text(
        json.dumps(datos, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def xfail_bug(motivo: str) -> Any:
    """xfail ESTRICTO que solo acepta AssertionError (espec §3).

    Si el ataque se rechaza, el test pasa y el xfail estricto se pone rojo
    (XPASS): hay que quitarlo en la espec del BUG. Si el test cae por otra
    excepción (PruebaRota, error de SQL), tampoco cuenta como xfail: rojo.
    """
    import pytest

    return pytest.mark.xfail(strict=True, raises=AssertionError, reason=motivo)
