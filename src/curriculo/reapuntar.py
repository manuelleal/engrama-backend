"""Reapuntar: pasar las referencias de un nodo fusionado a su vigente.

ESPEC_catalogo_nodos §1.2. Cada tabla que guarde ids de nodo agrega aquí su
función, y su test. Corre DENTRO de la transacción de la carga: o se reapunta
todo, o no cambia nada.

Las tablas con una columna `TEXT[]` de nodos se reapuntan con `_en_arreglo`:
cambia el id viejo por el nuevo y quita el repetido si ya estaban los dos.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

# (nombre de la tabla, función que reapunta `viejo -> nuevo` y dice cuántas filas tocó)
Reapuntador = Callable[[AsyncSession, str, str], Awaitable[int]]


def _en_arreglo(tabla: str, columna: str) -> Reapuntador:
    """Reapuntador de una columna `TEXT[]`. `tabla` y `columna` son constantes del código."""
    sql = text(
        f"UPDATE {tabla} SET {columna} = ARRAY(SELECT DISTINCT e FROM "
        f"unnest(array_replace({columna}, :viejo, :nuevo)) AS e ORDER BY e) "
        f"WHERE {columna} @> ARRAY[:viejo]::text[]")

    async def reapuntar_tabla(db: AsyncSession, viejo: str, nuevo: str) -> int:
        resultado: CursorResult[tuple[()]] = await db.execute(  # type: ignore[assignment]
            sql, {"viejo": viejo, "nuevo": nuevo})
        return int(resultado.rowcount or 0)

    return reapuntar_tabla


TABLAS: list[tuple[str, Reapuntador]] = [
    # Los ítems de los exámenes del Grader (ESPEC_grader_anillo §9.2).
    ("grader_exam_items", _en_arreglo("grader_exam_items", "nodos")),
]


async def reapuntar(db: AsyncSession, reemplazos: dict[str, str]) -> dict[str, int]:
    """Aplica cada reemplazo a cada tabla registrada. `{tabla: filas tocadas}`."""
    tocadas = {nombre: 0 for nombre, _ in TABLAS}
    for viejo, nuevo in sorted(reemplazos.items()):
        for nombre, funcion in TABLAS:
            tocadas[nombre] += await funcion(db, viejo, nuevo)
    return tocadas
