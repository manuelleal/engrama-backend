"""Tramposos ZW1-ZW13 de la racha semanal — `docs/ESPEC_racha_semanal.md` §3.

Una versión ROTA a propósito, inyectada con monkeypatch en el módulo donde se
USA; se corre el cuerpo del test real y se exige `AssertionError` con el
mensaje del mecanismo. Aquí se automatiza la DIAGONAL. ZW1 a ZW5 son no-integ.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import date
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.challenge_engine.service import attempts as attempts_mod
from src.engrama_core.service import attendance as attendance_mod
from src.engrama_core.service import coins as coins_mod
from src.racha import reglas as reglas_mod
from src.racha import service as service_mod
from src.racha.reglas import Dia, Racha, Umbrales
from src.shared.config import Settings
from src.webhooks import efectos as efectos_mod
from tests.racha import test_racha as tr
from tests.racha import test_unit as tu

Aplicar = Callable[[pytest.MonkeyPatch], None]

_CERRAR = reglas_mod.cerrar
_AL_ACTIVARSE = reglas_mod.al_activarse_un_dia


def _parche(modulo: Any, nombre: str, valor: Any) -> Aplicar:
    return lambda mp: mp.setattr(modulo, nombre, valor)


def _abrir_cuenta(dia: Dia, u: Umbrales) -> bool:
    """ZW1: con una sola respuesta, del resultado que sea, el día ya es activo."""
    return dia.via_asistencia or dia.respuestas >= 1


def _nunca_se_rompe(racha: Racha, lunes_actual: date, activos: Mapping[date, int],
                    exenta: date | None, u: Umbrales) -> Racha:
    """ZW2: la racha de Lingo: el cierre no gasta protector ni vuelve a 0."""
    buena = _CERRAR(racha, lunes_actual, activos, exenta, u)
    return replace(buena, racha_semanas=racha.racha_semanas, protectores=racha.protectores)


def _romper_baja_el_record(racha: Racha, lunes_actual: date, activos: Mapping[date, int],
                           exenta: date | None, u: Umbrales) -> Racha:
    """ZW3: al romperse, también se pierde `mejor_racha`."""
    buena = _CERRAR(racha, lunes_actual, activos, exenta, u)
    return replace(buena, mejor_racha=buena.racha_semanas)


def _cada_respuesta_cuenta(dia: Dia, clave: str, acerto: bool, origen: str) -> Dia:
    """ZW4: la misma pregunta suma cada vez que se responde."""
    return replace(dia, respuestas=dia.respuestas + 1, correctas=dia.correctas + int(acerto),
                   primeras_correctas=dia.primeras_correctas + int(acerto),
                   preguntas={**dia.preguntas, clave: int(acerto)},
                   por_origen={**dia.por_origen, origen: int(dia.por_origen.get(origen, 0)) + 1})


class _SemanaDeDosDias(Settings):
    """ZW5: por defecto la semana se cumple al 2.º día."""

    racha_dias_por_semana: int = 2


def _nadie_respondio(questions: Any, details: Any) -> list[tuple[str, bool]]:
    """ZW6: `/submit` no le cuenta nada a la racha."""
    return []


def _cada_dia_cumple(racha: Racha, dias_activos: int, u: Umbrales) -> tuple[Racha, bool]:
    """ZW7: del 3.er día en adelante, CADA día activo vuelve a cumplir la semana."""
    return _AL_ACTIVARSE(racha, min(dias_activos, u.dias_por_semana), u)


async def _bono_sin_red(db: AsyncSession, tenant_id: UUID, profile_id: UUID, lunes: date,
                        monto: int) -> None:
    """ZW8: sin SAVEPOINT ni captura: la bolsa agotada tumba la respuesta (402)."""
    await coins_mod.award_coins(db, student_id=profile_id, tenant_id=tenant_id, amount=monto,
                                action=service_mod.ACCION_BONO,
                                idempotency_key=reglas_mod.llave_bono(tenant_id, profile_id, lunes))


def _solo_por_persona(modelo: Any, tenant_id: UUID, profile_id: UUID) -> Any:
    """ZW9: la racha se busca sin institución (global, como BUG-12)."""
    return modelo.profile_id == profile_id


class _RachaSorda:
    """ZW10: el check-in no le avisa a la racha."""

    @staticmethod
    async def anotar_asistencia(db: AsyncSession, **datos: Any) -> None:
        return None


async def _sin_cerrar(db: AsyncSession, tenant_id: UUID, profile_id: UUID, racha: Racha,
                      lunes: date, u: Umbrales) -> Racha:
    """ZW11: nadie cierra las semanas: se muestra la racha vieja."""
    return racha


async def _cada_evento_es_otra_pregunta(db: AsyncSession, evento: Any) -> None:
    """ZW12: EVA cuenta por evento, no por ítem: el mismo ítem suma otra vez."""
    correcta = evento.payload.get("correct")
    if evento.subject_id is None or not isinstance(correcta, bool):
        return
    await service_mod.anotar_respuestas(
        db, tenant_id=evento.tenant_id, profile_id=evento.subject_id,
        respuestas=[(evento.event_id, correcta)], origen=reglas_mod.ORIGEN_EVA)


def _protector_sin_tope(racha: Racha, dias_activos: int, u: Umbrales) -> tuple[Racha, bool]:
    """ZW13: cada 5.º día suma un protector, sin tope."""
    buena, cumplida = _AL_ACTIVARSE(racha, dias_activos, u)
    if dias_activos == u.dias_protector:
        buena = replace(buena, protectores=racha.protectores + 1)
    return buena, cumplida


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[..., None], str]] = {
    "ZW1": (_parche(reglas_mod, "dia_activo", _abrir_cuenta),
            tu.test_uw1_dia_activo_semana_y_protector, r"'una respuesta correcta': True"),
    "ZW2": (_parche(reglas_mod, "cerrar", _nunca_se_rompe), tu.test_uw2_el_cierre_perezoso,
            r"'no_cumplida_gasta_el_protector': \(4, 6, 14, 1\)"),
    "ZW3": (_parche(reglas_mod, "cerrar", _romper_baja_el_record),
            tu.test_uw2_el_cierre_perezoso, r"'sin_protector_vuelve_a_cero': \(0, 0, 14, 0\)"),
    "ZW4": (_parche(reglas_mod, "anotar_respuesta", _cada_respuesta_cuenta),
            tu.test_uw3_cada_pregunta_cuenta_una_vez_al_dia, r"'la_misma_tres_veces': \(3, 3, 3"),
    "ZW5": (_parche(tu, "Settings", _SemanaDeDosDias), tu.test_uw1_dia_activo_semana_y_protector,
            r"UW1: \{'por_defecto': \(2, 5, 6, 4, 1, 2, 5\)"),
    "ZW6": (_parche(attempts_mod, "respondidas", _nadie_respondio),
            tr.test_rw1_el_dia_activo_por_respuestas,
            r"'gana_r1': \(\(200, \(True, 10\)\), \(0, 0, False\)\)"),
    "ZW7": (_parche(reglas_mod, "al_activarse_un_dia", _cada_dia_cumple),
            tr.test_rw3_la_semana_cumplida_y_su_bono, r"\(200, \(2, 2, 2, 1, 4, True\)"),
    "ZW8": (_parche(service_mod, "_pagar_bono", _bono_sin_red),
            tr.test_rw3_la_semana_cumplida_y_su_bono, r"'sin_bolsa': .*\(402, "),
    "ZW9": (_parche(service_mod, "_del_dueno", _solo_por_persona),
            tr.test_rw5_la_racha_es_por_institucion, r"'en_b': \(1, 1, 1, 1, 3, True\)"),
    "ZW10": (_parche(attendance_mod, "racha_service", _RachaSorda),
             tr.test_rw2_la_asistencia_marca_el_dia_y_el_checkin_no_cambia,
             r"'el_martes': \{'fecha': '2026-10-13', 'activo': False"),
    "ZW11": (_parche(service_mod, "_cerrada", _sin_cerrar),
             tr.test_rw4_el_cierre_perezoso_por_http,
             r"'semana_3_gasto_el_protector': \(\(1, 1, 1, 1, 0, False\)"),
    "ZW12": (_parche(efectos_mod, "contar_respuesta", _cada_evento_es_otra_pregunta),
             tr.test_rw6_las_respuestas_de_eva_cuentan, r"'sin_sumar': \(7, 5, True\)"),
    "ZW13": (_parche(reglas_mod, "al_activarse_un_dia", _protector_sin_tope),
             tr.test_rw7_el_protector_se_gana_al_quinto_dia_con_tope,
             r"'otra_semana_de_cinco': \(2, 2, 2, 3, 5, True\)"),
}
SIN_BASE = ("ZW1", "ZW2", "ZW3", "ZW4", "ZW5")


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
