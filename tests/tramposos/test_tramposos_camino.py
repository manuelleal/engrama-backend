"""Tramposos ZC1-ZC10 del camino de nivel — docs/ESPEC_camino_progreso.md §3.

Una versión ROTA a propósito, inyectada con monkeypatch en el módulo donde se
USA; se corre el cuerpo del test real y se exige `AssertionError` con el
mensaje del mecanismo (la diagonal). ZC1 a ZC6 son puros (sin base).
"""
from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import true
from sqlalchemy.ext.asyncio import AsyncSession

from src.camino import reglas as reglas_mod
from src.camino import service as service_mod
from src.camino.reglas import Demorada, Estacion, EstadoDeUnidad, Umbrales
from src.engrama_core.service import coins as coins_service
from tests.camino import test_camino as tc
from tests.camino import test_unit as tu

Aplicar = Callable[[pytest.MonkeyPatch], None]

_LEER = service_mod.leer


def _parche(modulo: Any, nombre: str, valor: Any) -> Aplicar:
    return lambda mp: mp.setattr(modulo, nombre, valor)


def _completada_sin_jugarlas(estaciones: Sequence[Estacion], aciertos: int, preguntas: int,
                             u: Umbrales) -> bool:
    """ZC1: Completada con el 70 % aunque falten estaciones por jugar."""
    return bool(estaciones) and reglas_mod._alcanza(aciertos, preguntas, u.completada)


def _completada_al_50(estaciones: Sequence[Estacion], aciertos: int, preguntas: int,
                      u: Umbrales) -> bool:
    """ZC2: el umbral de Completada es 50 % y no 70 %."""
    return bool(estaciones) and all(e.jugada for e in estaciones) and reglas_mod._alcanza(
        aciertos, preguntas, 50)


_DOMINADA = reglas_mod._dominada


def _dominada_sin_esperar(estaciones: Sequence[Estacion], demoradas: Sequence[Demorada],
                          completada_en: datetime, u: Umbrales) -> bool:
    """ZC3: cualquier respuesta posterior cuenta como demorada (sin los 7 días)."""
    return _DOMINADA(estaciones, demoradas, completada_en,
                     Umbrales(u.completada, u.dominada, u.dias_atasco, 0, u.minimo_demoradas))


def _atasco_a_los_6(e: EstadoDeUnidad, hay_siguiente: bool, ahora: datetime,
                    u: Umbrales) -> bool:
    """ZC4: la siguiente se abre a los 6 días."""
    return (hay_siguiente and e.estado == reglas_mod.EN_CURSO and e.empezada_en is not None
            and ahora >= e.empezada_en + timedelta(days=u.dias_atasco - 1))


def _bloqueo_duro(e: EstadoDeUnidad, hay_siguiente: bool, ahora: datetime,
                  u: Umbrales) -> bool:
    """ZC5: bloqueo duro: nunca hay atasco, nunca se abre con apoyo."""
    return False


def _recomienda_lo_primero(estados: Sequence[EstadoDeUnidad],
                           acc: Sequence[reglas_mod.Acceso]) -> int | None:
    """ZC6: la recomendada es la primera sin completar, bloqueada o atascada da igual."""
    return next((i for i, e in enumerate(estados) if e.estado not in reglas_mod.COMPLETAS),
                None)


def _todo_el_mundo_ve_todo(tenant_id: UUID, group_code: str | None) -> Any:
    """ZC7: el camino no pasa por la visibilidad del estudiante."""
    return true()


def _con_refuerzo() -> Any:
    """ZC8: el camino incluye los retos `solo_refuerzo` como estaciones."""
    return true()


async def _leer_y_pagar(db: AsyncSession, *, tenant_id: UUID, profile_id: UUID,
                        group_code: str | None) -> Any:
    """ZC9: leer el camino paga 5 monedas por cada unidad completada (y lo guarda)."""
    salida = await _LEER(db, tenant_id=tenant_id, profile_id=profile_id, group_code=group_code)
    for u in salida.unidades:
        if u.estado in reglas_mod.COMPLETAS:
            await coins_service.award_coins(
                db, student_id=profile_id, tenant_id=tenant_id, amount=5, action="challenge",
                metadata={"camino": u.topic}, idempotency_key=f"camino:{profile_id}:{u.topic}")
    await db.commit()
    return salida


def _de_cualquiera(profile_id: UUID) -> Any:
    """ZC10: los intentos de cualquier estudiante de la institución."""
    return true()


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[..., None], str]] = {
    "ZC1": (_parche(reglas_mod, "_completada", _completada_sin_jugarlas),
            tu.test_cu1_los_estados, r"'una_jugada_al_100_y_otra_sin_jugar': 'completada'"),
    "ZC2": (_parche(reglas_mod, "_completada", _completada_al_50),
            tu.test_cu1_los_estados, r"'todas_6_de_10': 'completada'"),
    "ZC3": (_parche(reglas_mod, "_dominada", _dominada_sin_esperar),
            tu.test_cu2_dominada_solo_con_evidencia_demorada,
            r"'tres_a_6_dias_23_h': 'dominada'"),
    "ZC4": (_parche(reglas_mod, "atascada", _atasco_a_los_6), tu.test_cu3_el_bloqueo_suave,
            r"'en_curso_6_dias_23_h': \[\('en_curso', 'abierta'\), \('sin_empezar', "
            r"'abierta_con_apoyo'\)"),
    "ZC5": (_parche(reglas_mod, "atascada", _bloqueo_duro), tu.test_cu3_el_bloqueo_suave,
            r"'en_curso_7_dias': \(\[\('en_curso', 'abierta'\), \('sin_empezar', 'bloqueada'\)"),
    "ZC6": (_parche(reglas_mod, "recomendada", _recomienda_lo_primero),
            tu.test_cu3_el_bloqueo_suave,
            r"'en_curso_7_dias': \(\[.*\], \(0, \[None, None, None\], \[True, False, False\]\)"),
    "ZC7": (_parche(service_mod, "_visibles", _todo_el_mundo_ve_todo),
            tc.test_cm1_forma_y_orden, r"'Ajeno 1'"),
    "ZC8": (_parche(service_mod, "_del_feed", _con_refuerzo),
            tc.test_cm1_forma_y_orden, r"'Refuerzo 1'"),
    "ZC9": (_parche(service_mod, "leer", _leer_y_pagar),
            tc.test_cm4_el_get_no_escribe_y_el_camino_no_paga,
            r"'leer_tres_veces_no_paga': False"),
    "ZC10": (_parche(service_mod, "_del_estudiante", _de_cualquiera),
             tc.test_cm5_por_institucion_y_por_estudiante,
             r"'ana': \('A2', False, 'a2-u02', \[\('a2-u01', 1, 'Uno', 'completada'"),
}
SIN_BASE = ("ZC1", "ZC2", "ZC3", "ZC4", "ZC5", "ZC6")


def correr(test_real: Callable[..., None], disponibles: dict[str, Any]) -> None:
    pedidas = inspect.signature(test_real).parameters
    test_real(**{nombre: disponibles[nombre] for nombre in pedidas})


@pytest.mark.integ
@pytest.mark.parametrize("clave", [c for c in TRAMPOSOS if c not in SIN_BASE])
def test_tramposo_camino_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        correr(test_real, {"integ": integ, "monkeypatch": monkeypatch})


@pytest.mark.parametrize("clave", SIN_BASE)
def test_tramposo_camino_puro_pone_rojo_su_test(monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        correr(test_real, {"monkeypatch": monkeypatch})
