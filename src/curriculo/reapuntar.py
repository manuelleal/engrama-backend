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


async def _la_cola_de_refuerzo(db: AsyncSession, viejo: str, nuevo: str) -> int:
    """La cola guarda UN nodo por fila, único por estudiante (ESPEC_refuerzo §1.7).

    Si un estudiante tiene el nodo viejo y el nuevo, se conserva la fila del
    nuevo y se borra la del viejo; las demás pasan al nuevo.
    """
    datos = {"viejo": viejo, "nuevo": nuevo}
    borradas: CursorResult[tuple[()]] = await db.execute(text(  # type: ignore[assignment]
        "DELETE FROM reinforcement_queue v USING reinforcement_queue n "
        "WHERE v.node_id = :viejo AND n.node_id = :nuevo "
        "AND n.tenant_id = v.tenant_id AND n.profile_id = v.profile_id"), datos)
    movidas: CursorResult[tuple[()]] = await db.execute(text(  # type: ignore[assignment]
        "UPDATE reinforcement_queue SET node_id = :nuevo WHERE node_id = :viejo"), datos)
    return int(borradas.rowcount or 0) + int(movidas.rowcount or 0)


TABLAS: list[tuple[str, Reapuntador]] = [
    # Los ítems de los exámenes del Grader (ESPEC_grader_anillo §9.2).
    ("grader_exam_items", _en_arreglo("grader_exam_items", "nodos")),
    # Las preguntas de los retos y los focos de los grupos (ESPEC_foco_grupo §1.2).
    ("challenge_questions", _en_arreglo("challenge_questions", "nodes")),
    ("group_focus", _en_arreglo("group_focus", "nodes")),
    ("reinforcement_queue", _la_cola_de_refuerzo),
]


async def reapuntar(db: AsyncSession, reemplazos: dict[str, str]) -> dict[str, int]:
    """Aplica cada reemplazo a cada tabla registrada. `{tabla: filas tocadas}`."""
    tocadas = {nombre: 0 for nombre, _ in TABLAS}
    for viejo, nuevo in sorted(reemplazos.items()):
        for nombre, funcion in TABLAS:
            tocadas[nombre] += await funcion(db, viejo, nuevo)
    return tocadas
