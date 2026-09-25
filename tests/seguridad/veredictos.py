"""Cómo se juzga un ataque contra la base (docs/ESPEC_aceptacion_seguridad.md §3).

Regla anti-vacío: un "rechazo" solo vale si en la misma prueba hay un control
que demuestra que la sentencia era válida y que la identidad llegó a la base.

  Rechazo válido  : 0 filas, UPDATE 0 con el valor intacto, o SQLSTATE 42501.
  42P17 (recursión infinita en la RLS, BUG-2): es ROTURA, nunca rechazo
                    -> AssertionError (un xfail de BUG-2 lo espera así).
  Otro SQLSTATE   : el test está mal escrito (FK, sintaxis, NOT NULL...)
                    -> PruebaRota, que NO es AssertionError: un xfail con
                    `raises=AssertionError` no puede esconderlo y queda en rojo.

Este módulo no empieza por `test_`: pytest no lo recolecta.
"""
from __future__ import annotations

import json
import os
from typing import Any
from uuid import UUID

from tests.integ_db import RAIZ_BACKEND, Integ, Resultado

RECHAZO = "42501"   # insufficient_privilege: la RLS (o un GRANT) dijo que no
RLS_ROTA = "42P17"  # infinite_recursion: la política se consulta a sí misma

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


def rechazado(res: Resultado, que: str, *, solo_42501: bool = False) -> None:
    """Afirma el rechazo. `solo_42501`: en un INSERT, 0 filas no es un rechazo."""
    if res.sqlstate == RLS_ROTA:
        raise AssertionError(f"{que}: 42P17, la RLS se rompe en vez de rechazar (BUG-2)")
    if res.sqlstate is not None and res.sqlstate != RECHAZO:
        raise PruebaRota(f"{que}: error que no es rechazo ni BUG-2 -> {_describir(res)}")
    if res.sqlstate == RECHAZO:
        return
    assert not solo_42501 and res.afectadas == 0, (
        f"{que}: el ataque PASA ({_describir(res)})"
    )


def control_postgres(res: Resultado, que: str, *, filas: int = 1) -> None:
    """La misma sentencia como `postgres` (sin RLS) funciona. Si no, el test está roto."""
    if res.sqlstate is not None or res.afectadas != filas:
        raise PruebaRota(
            f"control '{que}' como postgres: {_describir(res)}; se esperaban {filas} fila(s)"
        )


def control_dueno(res: Resultado, que: str, *, filas: int = 1) -> None:
    """Lo legítimo funciona con RLS. 42P17 o 0 filas aquí es un bug, no un test roto."""
    if res.sqlstate == RLS_ROTA:
        raise AssertionError(f"control '{que}': 42P17, la RLS rompe lo legítimo (BUG-2)")
    if res.sqlstate is not None:
        raise PruebaRota(f"control '{que}': {_describir(res)}")
    assert res.afectadas == filas, (
        f"control '{que}': {res.afectadas} fila(s), se esperaban {filas}"
    )


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
