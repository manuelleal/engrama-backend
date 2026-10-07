"""Los periodos del foco de un grupo, el vigente y el feed priorizado.

ESPEC_foco_grupo §1.2 y §1.3. El foco es de UN grupo: quien llama ya resolvió
el grupo por la barrera de siempre (`access.authorize_group`), o es el
estudiante y su grupo sale de su propia membresía (`auth.group_code`).
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.curriculo import service as curriculo_service
from src.curriculo.router import NodoOut, nodo_a_esquema
from src.foco import fechas
from src.foco.schemas import FocoEstudianteOut, FocoIn, FocoOut, FocoVigenteOut
from src.shared.config import settings
from src.shared.models import Challenge, ChallengeQuestion, Group, GroupFocus

FOCO_SOLAPADO = "foco_solapado"
FECHAS_INVALIDAS = "fechas_invalidas"
MAX_PERIODOS = 50


def _ahora() -> datetime:
    return datetime.now(UTC)


def hoy() -> date:
    """El día de hoy en la hora de la institución (`ENGRAMA_UTC_OFFSET_HOURS`)."""
    return fechas.hoy(_ahora(), settings.engrama_utc_offset_hours)


def es_vigente(periodo: GroupFocus, dia: date) -> bool:
    return periodo.starts_on <= dia <= periodo.ends_on


async def periodos(db: AsyncSession, group_ids: Iterable[UUID], *,
                   limite: int | None = MAX_PERIODOS) -> list[GroupFocus]:
    """Los periodos de esos grupos, del más nuevo al más viejo."""
    stmt = (select(GroupFocus).where(GroupFocus.group_id.in_(list(group_ids)))
            .order_by(GroupFocus.starts_on.desc()).limit(limite))
    return list((await db.execute(stmt)).scalars().all())


def vigente_entre(candidatos: Sequence[GroupFocus], dia: date) -> GroupFocus | None:
    """El periodo vigente ese día. Como no se solapan, hay a lo sumo uno por grupo."""
    return next((p for p in candidatos if es_vigente(p, dia)), None)


async def vigente_del_grupo(db: AsyncSession, group_id: UUID, dia: date) -> GroupFocus | None:
    return vigente_entre(await periodos(db, [group_id]), dia)


# --------------------------------------------------------------------- escribir
def _exigir_fechas(desde: date, hasta: date) -> None:
    if not fechas.duracion_valida(desde, hasta):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=FECHAS_INVALIDAS)


def _exigir_sin_solape(otros: Sequence[GroupFocus], desde: date, hasta: date) -> None:
    """409 si el periodo nuevo comparte algún día con OTRO periodo del grupo."""
    for otro in otros:
        if otro.starts_on != desde and fechas.se_solapan(desde, hasta, otro.starts_on,
                                                         otro.ends_on):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=FOCO_SOLAPADO)


async def fijar(db: AsyncSession, grupo: Group, profe_id: UUID, datos: FocoIn) -> GroupFocus:
    """Crea el periodo que empieza en `desde`, o reemplaza el que ya empezaba ese día."""
    hasta = datos.hasta if datos.hasta is not None else fechas.hasta_por_defecto(datos.desde)
    _exigir_fechas(datos.desde, hasta)
    nodos = await curriculo_service.canonicos(db, datos.nodos)
    # Candado sobre el grupo: dos `PUT` a la vez no dejan dos periodos cruzados.
    await db.execute(select(Group.id).where(Group.id == grupo.id).with_for_update())
    existentes = await periodos(db, [grupo.id], limite=None)  # TODOS: el solape no se recorta
    _exigir_sin_solape(existentes, datos.desde, hasta)
    periodo = next((p for p in existentes if p.starts_on == datos.desde), None)
    if periodo is None:
        periodo = GroupFocus(tenant_id=grupo.tenant_id, group_id=grupo.id,
                             starts_on=datos.desde, ends_on=hasta, nodes=nodos, set_by=profe_id)
        db.add(periodo)
    else:
        periodo.ends_on, periodo.nodes, periodo.set_by = hasta, nodos, profe_id
        periodo.updated_at = _ahora()
    await db.flush()
    return periodo


async def borrar(db: AsyncSession, grupo: Group, desde: date) -> None:
    """Borra el periodo que empieza ese día. 404 si no existe."""
    borrados = (await db.execute(
        delete(GroupFocus).where(GroupFocus.group_id == grupo.id, GroupFocus.starts_on == desde)
        .returning(GroupFocus.id))).scalars().all()
    if not borrados:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Focus not found")


# ----------------------------------------------------------------------- salida
async def nodos_a_esquema(db: AsyncSession, ids: Sequence[str]) -> list[NodoOut]:
    """Los nodos con su nombre, en el orden guardado."""
    filas = await curriculo_service.por_id(db, ids)
    return [nodo_a_esquema(filas[i]) if i in filas
            else NodoOut(id=i, tipo="", nivel="", nombre_es=i) for i in ids]


async def a_esquema(db: AsyncSession, periodo: GroupFocus, dia: date) -> FocoOut:
    return FocoOut(desde=periodo.starts_on, hasta=periodo.ends_on,
                   vigente=es_vigente(periodo, dia),
                   nodos=await nodos_a_esquema(db, periodo.nodes))


# --------------------------------------------------------------- el estudiante
async def _focos_del_estudiante(db: AsyncSession, tenant_id: UUID,
                                group_code: str | None) -> list[GroupFocus]:
    """Los periodos del grupo DEL ESTUDIANTE (su `group_code` en su institución)."""
    if not group_code:
        return []
    grupos = (await db.execute(select(Group.id).where(
        Group.tenant_id == tenant_id, Group.group_code == group_code))).scalars().all()
    return await periodos(db, grupos)


async def foco_del_estudiante(db: AsyncSession, tenant_id: UUID,
                              group_code: str | None) -> GroupFocus | None:
    return vigente_entre(await _focos_del_estudiante(db, tenant_id, group_code), hoy())


async def retos_en_foco(db: AsyncSession, ids: Sequence[UUID],
                        nodos: Sequence[str]) -> set[UUID]:
    """De ESOS retos, los que tienen alguna pregunta con un nodo del foco."""
    if not ids or not nodos:
        return set()
    stmt = (select(ChallengeQuestion.challenge_id)
            .where(ChallengeQuestion.challenge_id.in_(list(ids)),
                   ChallengeQuestion.nodes.overlap(list(nodos)))
            .distinct())
    return set((await db.execute(stmt)).scalars().all())


def priorizar(retos: Sequence[Challenge], en_foco: set[UUID]) -> list[Challenge]:
    """Primero los del foco y después el resto; cada mitad conserva su orden."""
    return ([r for r in retos if r.id in en_foco] + [r for r in retos if r.id not in en_foco])


async def priorizar_feed(db: AsyncSession, *, tenant_id: UUID, group_code: str | None,
                         retos: list[Challenge]) -> list[Challenge]:
    """El feed con los retos del foco delante. Sin foco vigente, el MISMO feed."""
    foco = await foco_del_estudiante(db, tenant_id, group_code)
    if foco is None:
        return retos
    return priorizar(retos, await retos_en_foco(db, [r.id for r in retos], foco.nodes))


async def para_el_estudiante(db: AsyncSession, *, tenant_id: UUID, group_code: str | None,
                             feed: list[Challenge]) -> FocoEstudianteOut:
    """El foco vigente del grupo del estudiante y cuáles retos DE SU FEED están en él."""
    foco = await foco_del_estudiante(db, tenant_id, group_code)
    if foco is None:
        return FocoEstudianteOut(vigente=None, retos_en_foco=[])
    en_foco = await retos_en_foco(db, [r.id for r in feed], foco.nodes)
    return FocoEstudianteOut(
        vigente=FocoVigenteOut(desde=foco.starts_on, hasta=foco.ends_on,
                               nodos=await nodos_a_esquema(db, foco.nodes)),
        retos_en_foco=[r.id for r in feed if r.id in en_foco])
