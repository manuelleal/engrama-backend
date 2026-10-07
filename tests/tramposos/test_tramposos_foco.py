"""Tramposos ZF1-ZF13 del foco del grupo — `docs/ESPEC_foco_grupo.md` §3.

Una versión ROTA a propósito, inyectada con monkeypatch en el módulo donde se
USA; se corre el cuerpo del test real y se exige `AssertionError` con el
mensaje del mecanismo. Aquí se automatiza la DIAGONAL; la matriz completa se
mide aparte (ERR-15, 19 y 23). ZF2 es no-integ.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.challenge_engine.schemas import ChallengeQuestionOut
from src.challenge_engine.service import challenges as challenges_mod
from src.curriculo import reapuntar as reapuntar_mod
from src.foco import etiquetas as etiquetas_mod
from src.foco import fechas as fechas_mod
from src.foco import logro as logro_mod
from src.foco import service as service_mod
from src.shared.models import ChallengeQuestion, Group, GroupFocus
from src.teachers.service import access as access_mod
from tests.foco import test_etiquetas_y_foco as te
from tests.foco import test_feed_y_logro as tf
from tests.foco import test_unit as tu

Aplicar = Callable[[pytest.MonkeyPatch], None]

_PRIORIZAR_FEED = service_mod.priorizar_feed
_TABLAS = list(reapuntar_mod.TABLAS)


def _parche(modulo: Any, nombre: str, valor: Any) -> Aplicar:
    return lambda mp: mp.setattr(modulo, nombre, valor)


def _varios(*aplicar: Aplicar) -> Aplicar:
    def todos(mp: pytest.MonkeyPatch) -> None:
        for uno in aplicar:
            uno(mp)
    return todos


async def _nodos_sin_resolver(db: AsyncSession, preguntas: list[Any]) -> list[list[str]]:
    """ZF1: lo que mandó el cliente, tal cual."""
    return [list(q.nodos) for q in preguntas]


class _PreguntaConNodos:
    """ZF2: la pregunta que ve el estudiante gana `nodos`."""

    model_fields = {**ChallengeQuestionOut.model_fields, "nodos": None}


async def _cualquiera_etiqueta(db: AsyncSession, auth: Any, reto: Any) -> bool:
    """ZF3: no mira el grupo del reto."""
    return True


async def _focos_de_toda_la_institucion(db: AsyncSession, tenant_id: UUID,
                                        group_code: str | None) -> list[GroupFocus]:
    """ZF7: el foco se busca sin el grupo del estudiante."""
    grupos = (await db.execute(select(Group.id).where(Group.tenant_id == tenant_id))
              ).scalars().all()
    return await service_mod.periodos(db, grupos)


async def _feed_reordenado(db: AsyncSession, *, tenant_id: UUID, group_code: str | None,
                           retos: list[Any]) -> list[Any]:
    """ZF8: reordena (por título) aunque no haya foco."""
    return sorted(await _PRIORIZAR_FEED(db, tenant_id=tenant_id, group_code=group_code,
                                        retos=retos), key=lambda r: r.title)


def _todos_los_intentos(por_estudiante: dict[UUID, list[Any]],
                        now: datetime) -> list[tuple[UUID, Any]]:
    """ZF9: cuenta todos los intentos, no el primero de cada reto."""
    return [(est, intento) for est, intentos in por_estudiante.items() for intento in intentos]


async def _retos_con_esos_nodos(db: AsyncSession, ids: Sequence[UUID],
                                nodos: Sequence[str]) -> set[UUID]:
    """ZF12: cualquier reto con esos nodos, esté o no en el feed del estudiante."""
    filas = (await db.execute(select(ChallengeQuestion.challenge_id).where(
        ChallengeQuestion.nodes.overlap(list(nodos))))).scalars().all()
    return set(filas)


async def _para_el_estudiante_sin_feed(db: AsyncSession, *, tenant_id: UUID,
                                       group_code: str | None, feed: list[Any]) -> Any:
    """ZF12: `retos_en_foco` sale de todos los retos de la institución, no del feed."""
    from src.foco.schemas import FocoEstudianteOut, FocoVigenteOut
    from src.shared.models import Challenge

    foco = await service_mod.foco_del_estudiante(db, tenant_id, group_code)
    if foco is None:
        return FocoEstudianteOut(vigente=None, retos_en_foco=[])
    todos = (await db.execute(select(Challenge).where(Challenge.tenant_id == tenant_id)
                              .order_by(Challenge.created_at.desc()))).scalars().all()
    en_foco = await _retos_con_esos_nodos(db, [], foco.nodes)
    return FocoEstudianteOut(
        vigente=FocoVigenteOut(desde=foco.starts_on, hasta=foco.ends_on,
                               nodos=await service_mod.nodos_a_esquema(db, foco.nodes)),
        retos_en_foco=[r.id for r in todos if r.id in en_foco])


async def _no_reapunta(db: AsyncSession, viejo: str, nuevo: str) -> int:
    return 0


def _sin_reapuntar_retos_ni_focos() -> list[tuple[str, Any]]:
    """ZF13: la tabla del Grader sigue reapuntando; las dos de este bloque, no."""
    propias = ("challenge_questions", "group_focus")
    return [(nombre, _no_reapunta if nombre in propias else funcion)
            for nombre, funcion in _TABLAS]


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[..., None], str]] = {
    "ZF1": (_parche(challenges_mod, "nodos_de_las_preguntas", _nodos_sin_resolver),
            te.test_fg1_las_preguntas_llevan_nodos,
            r"'guardados': \(200, \[\['gr.a1.dos'\], \['gr.a1.viejo', 'gr.a1.uno'\], \[\]\]\), "
            r"'desconocido': \(201, "),
    "ZF2": (_parche(tu, "ChallengeQuestionOut", _PreguntaConNodos),
            tu.test_uf1_piezas_puras_del_foco,
            r"'campos_de_la_pregunta_del_estudiante': \['id', 'nodos', 'options_json'"),
    "ZF3": (_parche(etiquetas_mod, "puede_etiquetar", _cualquiera_etiqueta),
            te.test_fg1_las_preguntas_llevan_nodos,
            r"'quien_no_puede': \{'E': \(403, 403\), 'DO': \(200, 200\)"),
    "ZF4": (_parche(etiquetas_mod, "exigir_que_sean_del_reto", lambda *_: None),
            te.test_fg1_las_preguntas_llevan_nodos,
            r"'con_una_pregunta_ajena': \(200, "),
    "ZF5": (_parche(fechas_mod, "se_solapan", lambda *_: False),
            te.test_fg2_el_foco_del_grupo,
            r"'solapado': \(200, \('2026-10-08', '2026-10-13'"),
    "ZF6": (_parche(service_mod, "es_vigente", lambda periodo, dia: True),
            tf.test_fg3_el_feed_prioriza_el_foco, r"'el_dia_antes': 'dbac'"),
    "ZF7": (_parche(service_mod, "_focos_del_estudiante", _focos_de_toda_la_institucion),
            tf.test_fg3_el_feed_prioriza_el_foco, r"'con_el_foco_de_otro_grupo': 'cadb'"),
    "ZF8": (_parche(service_mod, "priorizar_feed", _feed_reordenado),
            tf.test_fg3_el_feed_prioriza_el_foco, r"FG3: \{'sin_foco': 'abcd'"),
    "ZF9": (_parche(logro_mod, "calificados", _todos_los_intentos),
            tf.test_fg5_logro_del_grupo_por_nodo, r"'gr.a1.uno': \(6, 19, 15, 2, "),
    "ZF10": (_varios(_parche(logro_mod, "MIN_STUDENTS", 0), _parche(logro_mod, "MIN_ITEMS", 0)),
             tf.test_fg5_logro_del_grupo_por_nodo,
             r"'fn.a2.tres': \(4, 4, 4, 1, 'logrado', 'logrado'\)"),
    "ZF11": (_parche(access_mod, "_requiere_asignacion", lambda auth, *, only_assigned: False),
             te.test_fg4_aislamiento_del_foco,
             r"FG4: \{'prohibidos': \{'E': \(403, 403, 403, 403\), 'DO': \(200, 200, 204, 200\)"),
    "ZF12": (_parche(service_mod, "para_el_estudiante", _para_el_estudiante_sin_feed),
             tf.test_fg3_el_feed_prioriza_el_foco,
             r"'api': \(200, '2026-10-05', \['gr.a1.dos', 'gr.a1.uno'\], 'edba'\)"),
    "ZF13": (lambda mp: mp.setattr(reapuntar_mod, "TABLAS", _sin_reapuntar_retos_ni_focos()),
             te.test_fg1_las_preguntas_llevan_nodos,
             r"'reapuntadas': 0, 'tras_la_fusion': \['gr.a1.dos'\]"),
}
SIN_BASE = ("ZF2",)


def correr(test_real: Callable[..., None], disponibles: dict[str, Any]) -> None:
    pedidas = inspect.signature(test_real).parameters
    test_real(**{nombre: disponibles[nombre] for nombre in pedidas})


@pytest.mark.integ
@pytest.mark.parametrize("clave", [c for c in TRAMPOSOS if c not in SIN_BASE])
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        correr(test_real, {"integ": integ, "monkeypatch": monkeypatch})


@pytest.mark.parametrize("clave", SIN_BASE)
def test_tramposo_puro_pone_rojo_su_test(monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        test_real()
