"""Ataques con RLS: `SET LOCAL ROLE` + `request.jwt.claims` (docs/ESPEC_aceptacion_seguridad.md §3).

Se separó de `tests/integ_db.py` para bajar su tamaño (espec CI y deudas, C2):
  - `ROLES_COMO`, `Resultado` y `_sqlstate` son el vocabulario de un ataque.
  - `ComoMixin` es el método `como` (y su corrutina `_como`) que
    `tests.integ_ayudante.Integ` hereda. Vive aparte porque solo necesita
    `self.engine` (un `AsyncEngine`), no el resto de las fábricas de datos.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

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


def validar_identidad(rol: str, perfil: UUID | None) -> None:
    """Rechaza una identidad que Supabase nunca produce: `anon` con `perfil`.

    Una sesión sin JWT (rol `anon`) nunca trae `sub`: `auth.uid()` da NULL.
    Simular `rol="anon"` con un `perfil` fabricaría un `auth.uid()` que
    Supabase jamás entrega en una sesión anónima. Ninguna llamada real usa
    esa combinación (docs/ESPEC_ci_y_deudas.md, C3).
    """
    if rol == "anon" and perfil is not None:
        raise ValueError(
            f"como: rol 'anon' no admite perfil ({perfil}); "
            "Supabase nunca manda 'sub' sin JWT"
        )


class ComoMixin:
    """`como`: exige que quien lo herede tenga `self.engine` y `self.run` (ver `Integ`)."""

    engine: AsyncEngine

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
        validar_identidad(rol_efectivo, perfil)
        if rol_efectivo not in ROLES_COMO:
            raise ValueError(f"como: rol {rol_efectivo!r} no está en {ROLES_COMO}")
        if rol_efectivo == "authenticated" and perfil is None:
            raise ValueError("como: 'authenticated' exige un perfil")
        claims: dict[str, str] = {"role": rol_efectivo}
        if perfil is not None:
            claims.update(sub=str(perfil), aud="authenticated")

        import asyncio

        return asyncio.run(self._como(rol_efectivo, perfil, claims, sql, params or {}))

    async def _como(
        self,
        rol: str,
        perfil: UUID | None,
        claims: dict[str, str],
        sql: str,
        params: dict[str, Any],
    ) -> Resultado:
        import json

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
