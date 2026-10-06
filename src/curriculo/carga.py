"""La carga del catálogo: `Mapa` -> `curriculum_nodes`, todo o nada.

ESPEC_catalogo_nodos §1.2. Quien llama hace el `commit`; si `cargar` lanza
`MapaInvalido`, no escribió nada (valida ANTES de la primera escritura).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.curriculo.mapa import Mapa, MapaInvalido
from src.curriculo.reapuntar import reapuntar
from src.shared.models import CurriculumNode

SIN_DATO = "reemplazado"  # tipo y nivel de un reemplazado que nunca estuvo vigente aquí


async def _existentes(db: AsyncSession) -> dict[str, CurriculumNode]:
    filas = (await db.execute(select(CurriculumNode))).scalars().all()
    return {f.id: f for f in filas}


def exigir_que_nada_desaparezca(existentes: set[str], mapa: Mapa) -> None:
    """Un nodo no se borra (012 §1): lo que la tabla tiene debe venir en el archivo."""
    declarados = {n.id for n in mapa.nodos} | set(mapa.reemplazos)
    faltan = sorted(existentes - declarados)
    if faltan:
        raise MapaInvalido("nodo_desaparecido", faltan)


async def _guardar(db: AsyncSession, valores: dict[str, Any]) -> None:
    cambios = {k: v for k, v in valores.items() if k != "id"}
    await db.execute(pg_insert(CurriculumNode).values(**valores)
                     .on_conflict_do_update(index_elements=["id"], set_=cambios))


def _cambia(fila: CurriculumNode | None, valores: dict[str, Any]) -> bool:
    return fila is not None and any(getattr(fila, k) != v for k, v in valores.items()
                                    if k != "map_version")


def _filas(mapa: Mapa, antes: dict[str, CurriculumNode]) -> list[dict[str, Any]]:
    """Las filas a guardar: los vigentes PRIMERO (`replaced_by` los referencia)."""
    filas: list[dict[str, Any]] = [
        {"id": n.id, "kind": n.tipo, "level": n.nivel, "name_es": n.nombre_es,
         "replaced_by": None, "map_version": mapa.version} for n in mapa.nodos]
    for viejo, destino in sorted(mapa.reemplazos.items()):
        previa = antes.get(viejo)
        filas.append({"id": viejo, "kind": previa.kind if previa else SIN_DATO,
                      "level": previa.level if previa else SIN_DATO,
                      "name_es": previa.name_es if previa else viejo,
                      "replaced_by": destino, "map_version": mapa.version})
    return filas


async def cargar(db: AsyncSession, mapa: Mapa) -> dict[str, Any]:
    """Guarda el mapa y devuelve el resumen. No hace `commit`."""
    antes = await _existentes(db)
    exigir_que_nada_desaparezca(set(antes), mapa)
    nuevos = cambiados = 0
    for valores in _filas(mapa, antes):
        nuevos += int(valores["id"] not in antes)
        cambiados += int(_cambia(antes.get(valores["id"]), valores))
        await _guardar(db, valores)
    await db.flush()
    return {"version": mapa.version, "vigentes": len(mapa.nodos),
            "reemplazados": len(mapa.reemplazos), "nuevos": nuevos, "cambiados": cambiados,
            "reapuntadas": await reapuntar(db, mapa.reemplazos)}
