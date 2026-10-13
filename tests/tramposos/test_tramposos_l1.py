"""Tramposos ZL1-ZL15 de la respuesta por pregunta (L1).

`docs/ESPEC_l1_correccion_por_pregunta.md` §10.7. Una versión ROTA a propósito,
inyectada con monkeypatch en el módulo donde se USA; se corre el cuerpo del
test real y se exige `AssertionError` con el mensaje del mecanismo. Aquí se
automatiza la DIAGONAL. ZL1 a ZL4, ZL13 y ZL14 son no-integ.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import any_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.challenge_engine.service import attempts as attempts_mod
from src.challenge_engine.service import calificar as cal_mod
from src.challenge_engine.service import challenges as challenges_mod
from src.challenge_engine.service import intento_formas as formas_mod
from src.challenge_engine.service import por_pregunta as pp_mod
from src.engrama_core.service import economia as economia_mod
from src.refuerzo import cola as cola_mod
from src.refuerzo import formas as vistas_mod
from src.refuerzo.reglas import clave_de_forma
from src.shared.models import ChallengeAttempt, ChallengeAttemptAnswer, ChallengeQuestion
from tests.challenge_engine import test_l1_calificar_unit as tu
from tests.challenge_engine import test_l1_por_pregunta as tp

Aplicar = Callable[[pytest.MonkeyPatch], None]

_QUESTION_TO_SCHEMA = challenges_mod.question_to_schema
_EXPLICACION_PARA = cal_mod.explicacion_para
_VISTAS = vistas_mod.vistas


def _parche(modulo: Any, nombre: str, valor: Any) -> Aplicar:
    return lambda mp: mp.setattr(modulo, nombre, valor)


def _acepta_cualquier_vecina(respuesta: str, aceptadas: Sequence[str], tolerancia: str,
                             vocabulario: Collection[str]) -> bool:
    """ZL2: `1_letra` no mira si la respuesta es OTRA palabra válida (fever/fewer)."""
    if respuesta in aceptadas:
        return True
    return tolerancia == cal_mod.UNA_LETRA and any(
        len(a) >= cal_mod.LARGO_MINIMO_TOLERANTE and cal_mod.a_distancia_uno(respuesta, a)
        for a in aceptadas)


def _hasta_dos_errores(a: str, b: str) -> bool:
    """ZL4: con la pista se perdona un error por la pista y otro por el tipeo (dos)."""
    if a == b:
        return False
    previa = list(range(len(b) + 1))
    for i, x in enumerate(a, start=1):
        fila = [i]
        for j, y in enumerate(b, start=1):
            fila.append(min(previa[j] + 1, fila[j - 1] + 1, previa[j - 1] + (x != y)))
        previa = fila
    return previa[-1] <= 2


async def _gana_la_ultima(db: AsyncSession, attempt: Any, pregunta: Any, respuesta: str,
                          acerto: bool) -> tuple[ChallengeAttemptAnswer, bool]:
    """ZL5: la última respuesta reemplaza a la primera."""
    await db.execute(
        pg_insert(ChallengeAttemptAnswer).values(
            tenant_id=attempt.tenant_id, attempt_id=attempt.id, profile_id=attempt.student_id,
            question_id=pregunta.id, answer=respuesta, is_correct=acerto,
            answered_at=datetime.now(UTC))
        .on_conflict_do_update(constraint="challenge_attempt_answers_attempt_question_key",
                               set_={"answer": respuesta, "is_correct": acerto}))
    return (await pp_mod._guardadas(db, attempt.id))[pregunta.id], False


def _pregunta_con_la_regla(q: Any) -> Any:
    """ZL6: la pregunta que ve el estudiante trae pegada la regla de su explicación."""
    buena = _QUESTION_TO_SCHEMA(q)
    regla = (q.explanation or {}).get("regla", "")
    return buena.model_copy(update={"question_text": f"{buena.question_text} {regla}"})


async def _intento_de_cualquiera(db: AsyncSession, *, attempt_id: UUID, tenant_id: UUID,
                                 student_id: UUID) -> ChallengeAttempt | None:
    """ZL7: el intento se busca solo por su id (sin dueño ni institución)."""
    return (await db.execute(
        select(ChallengeAttempt).where(ChallengeAttempt.id == attempt_id).with_for_update()
    )).scalar_one_or_none()


def _llave_distinta_cada_vez(challenge_id: UUID, student_id: UUID) -> str:
    """ZL8: cada cierre paga con una llave nueva (no la del reto)."""
    return f"challenge:{challenge_id}:{student_id}:{uuid4()}"


def _todas_las_opciones(explicacion: Mapping[str, Any] | None, *, elegida: str, acerto: bool,
                        nivel: str | None = None) -> dict[str, Any] | None:
    """ZL9: la respuesta trae el porqué de TODAS las opciones."""
    buena = _EXPLICACION_PARA(explicacion, elegida=elegida, acerto=acerto, nivel=nivel)
    if buena is None or not isinstance((explicacion or {}).get("por_opcion"), Mapping):
        return buena
    return {**buena, "por_opcion": " | ".join(
        str(t) for t in explicacion["por_opcion"].values())}  # type: ignore[index]


async def _el_cierre_no_avisa(db: AsyncSession, **datos: Any) -> None:
    """ZL10: al cerrar, lo fallado no entra a la cola de refuerzo."""
    return None


async def _las_mismas_preguntas(db: AsyncSession, **datos: Any) -> list[UUID] | None:
    """ZL11: el reintento repite las preguntas del reto aunque haya gemelas."""
    return None


async def _sin_respuestas(db: AsyncSession, attempt_id: UUID) -> bool:
    """ZL12: `/submit` no mira si el intento ya tiene respuestas guardadas."""
    return False


def _paga_siempre_completo(recompensa: int, numero_intento: int,
                           segundo_intento_paga: int | None) -> int:
    """ZL13: el segundo intento ignora la variable."""
    return recompensa


async def _lo_servido_no_cuenta(db: AsyncSession, tenant_id: UUID,
                                profile_ids: Collection[UUID]) -> dict[UUID, set[str]]:
    """ZL15: lo que se sirvió en un reintento no queda como visto."""
    visto = await _VISTAS(db, tenant_id, profile_ids)
    servidas = (await db.execute(
        select(ChallengeAttempt.student_id, ChallengeQuestion.id, ChallengeQuestion.item_ref)
        .join(ChallengeQuestion,
              ChallengeQuestion.id == any_(ChallengeAttempt.served_questions))
        .where(ChallengeAttempt.served_questions.is_not(None)))).all()
    for estudiante, question_id, item_ref in servidas:
        visto[estudiante].discard(clave_de_forma(item_ref, question_id))
    return visto


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[..., None], str]] = {
    "ZL1": (_parche(cal_mod, "_COMILLAS", str.maketrans({})), tu.test_l1u1_la_normalizacion,
            r"'apostrofo_curvo': False"),
    "ZL2": (_parche(cal_mod, "_acierta_texto", _acepta_cualquier_vecina),
            tu.test_l1u2_la_tolerancia_de_una_letra, r"'fever_no_es_fewer': \{'fewer': True"),
    "ZL3": (_parche(cal_mod, "LARGO_MINIMO_TOLERANTE", 0),
            tu.test_l1u2_la_tolerancia_de_una_letra, r"'cat_es_exacta': \{'car': False, 'caat': True"),
    "ZL4": (_parche(cal_mod, "a_distancia_uno", _hasta_dos_errores),
            tu.test_l1u3_la_pista_con_inicial, r"'astl': True, 'stl': True"),
    "ZL5": (_parche(pp_mod, "_guardar_primera", _gana_la_ultima),
            tp.test_l1a2_gana_la_primera_respuesta,
            r"'otra_respuesta_devuelve_la_primera': \(200, True, 'A', False\)"),
    "ZL6": (_parche(challenges_mod, "question_to_schema", _pregunta_con_la_regla),
            tp.test_l1a4_nada_sale_antes_de_responder,
            r"'sin_fugas': \{'feed': False, 'detalle': False, 'tanda': False, 'attempt': False"),
    "ZL7": (_parche(attempts_mod, "_tomar_intento", _intento_de_cualquiera),
            tp.test_l1a3_cada_quien_responde_solo_su_intento,
            r"'beto_responde_el_de_ana': 200"),
    "ZL8": (_parche(attempts_mod, "llave_reto", _llave_distinta_cada_vez),
            tp.test_l1a5_terminar_cierra_como_submit,
            r"'tercero_por_submit_no_paga_otra_vez': \(200, \(True, 10\)\), "
            r"'cuarto_por_finish_tampoco': \(200, \(True, 10\)\)"),
    "ZL9": (_parche(cal_mod, "explicacion_para", _todas_las_opciones),
            tp.test_l1a1_la_respuesta_por_pregunta,
            r"'por_opcion': 'Go es para I, you, we, they. \| Going necesita is.'"),
    "ZL10": (_parche(cola_mod, "desde_intento", _el_cierre_no_avisa),
             tp.test_l1a5_terminar_cierra_como_submit, r"'lo_fallado_entra_a_la_cola': \{\}"),
    "ZL11": (_parche(formas_mod, "formas_del_reintento", _las_mismas_preguntas),
             tp.test_l1a6_el_segundo_intento, r"'carla_reintenta': \{'trae_la_gemela_de_fa': False"),
    "ZL12": (_parche(formas_mod, "tiene_respuestas", _sin_respuestas),
             tp.test_l1a5_terminar_cierra_como_submit,
             r"'submit_con_respuestas_guardadas': \(200, \(True, 10\)\)"),
    "ZL15": (_parche(vistas_mod, "vistas", _lo_servido_no_cuenta),
             tp.test_l1a6_el_segundo_intento,
             r"'la_gemela_servida_queda_vista': \(False, False\)"),
    "ZL13": (_parche(economia_mod, "paga_del_intento", _paga_siempre_completo),
             tu.test_l1u4_opciones_explicacion_y_segundo_intento, r"'segundo con 5': 10"),
    "ZL14": (_parche(cal_mod, "idioma_de", lambda nivel: cal_mod.INGLES),
             tu.test_l1u5_la_oracion_correcta_y_el_idioma, r"'A2 sin idioma': 'en'"),
}
SIN_BASE = ("ZL1", "ZL2", "ZL3", "ZL4", "ZL13", "ZL14")


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
        correr(test_real, {"monkeypatch": monkeypatch})
