"""`canonicos`: la ÚNICA función que dice si un id de nodo vale — ESPEC_catalogo_nodos §1.3.

Toda ruta que reciba nodos pasa por aquí (ERR-26: una barrera, una fuente). El
id es texto opaco: vale si está en el catálogo cargado, y nada más.
"""
from __future__ import annotations

from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.models import CurriculumNode

NODO_DESCONOCIDO = "nodo_desconocido"


async def _destinos(db: AsyncSession, ids: list[str]) -> dict[str, str]:
    """`{id: id vigente}` de los que están en el catálogo (la carga ya resolvió las cadenas)."""
    if not ids:
        return {}
    filas = (await db.execute(
        select(CurriculumNode.id, CurriculumNode.replaced_by)
        .where(CurriculumNode.id.in_(ids)))).all()
    return {ident: (destino or ident) for ident, destino in filas}


def _desconocidos(pedidos: list[str], destinos: dict[str, str]) -> list[str]:
    return [i for i in pedidos if i not in destinos]


async def canonicos(db: AsyncSession, ids: Iterable[str]) -> list[str]:
    """Los ids vigentes, en el orden de entrada y sin repetidos. 422 si alguno no existe."""
    pedidos = list(dict.fromkeys(ids))
    destinos = await _destinos(db, pedidos)
    faltan = _desconocidos(pedidos, destinos)
    if faltan:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={"code": NODO_DESCONOCIDO, "nodos": faltan})
    return list(dict.fromkeys(destinos[i] for i in pedidos))


async def vigentes(db: AsyncSession, *, incluir_reemplazados: bool = False) -> list[CurriculumNode]:
    """Los nodos vigentes, por id (el selector del profe)."""
    stmt = select(CurriculumNode).order_by(CurriculumNode.id)
    if not incluir_reemplazados:
        stmt = stmt.where(CurriculumNode.replaced_by.is_(None))
    return list((await db.execute(stmt)).scalars().all())


async def por_id(db: AsyncSession, ids: Iterable[str]) -> dict[str, CurriculumNode]:
    """Las filas de esos ids (para mostrar nombre, tipo y nivel junto a un id guardado)."""
    pedidos = list(dict.fromkeys(ids))
    if not pedidos:
        return {}
    filas = (await db.execute(select(CurriculumNode)
                              .where(CurriculumNode.id.in_(pedidos)))).scalars().all()
    return {f.id: f for f in filas}


async def version(db: AsyncSession) -> str | None:
    """La versión del mapa cargado (la de sus vigentes), o `None` si está vacío."""
    valor = (await db.execute(select(func.max(CurriculumNode.map_version))
                              .where(CurriculumNode.replaced_by.is_(None)))).scalar()
    return None if valor is None else str(valor)
