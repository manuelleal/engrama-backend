"""Reapuntar: pasar las referencias de un nodo fusionado a su vigente.

ESPEC_catalogo_nodos §1.2. Cada tabla que guarde ids de nodo agrega aquí su
función, y su test. Corre DENTRO de la transacción de la carga: o se reapunta
todo, o no cambia nada.

Hoy no hay ninguna tabla que guarde nodos: la lista nace vacía.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

# (nombre de la tabla, función que reapunta `viejo -> nuevo` y dice cuántas filas tocó)
Reapuntador = Callable[[AsyncSession, str, str], Awaitable[int]]
TABLAS: list[tuple[str, Reapuntador]] = []


async def reapuntar(db: AsyncSession, reemplazos: dict[str, str]) -> dict[str, int]:
    """Aplica cada reemplazo a cada tabla registrada. `{tabla: filas tocadas}`."""
    tocadas = {nombre: 0 for nombre, _ in TABLAS}
    for viejo, nuevo in sorted(reemplazos.items()):
        for nombre, funcion in TABLAS:
            tocadas[nombre] += await funcion(db, viejo, nuevo)
    return tocadas
