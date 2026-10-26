"""Tramposos ZP1-ZP13 del nivel de práctica y la tanda — `docs/ESPEC_practica_y_tanda.md` §3.

Una versión ROTA a propósito, inyectada con monkeypatch en el módulo donde se
USA; se corre el cuerpo del test real y se exige `AssertionError` con el
mensaje del mecanismo. Aquí se automatiza la DIAGONAL. ZP1 a ZP4 son no-integ.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import true
from sqlalchemy.ext.asyncio import AsyncSession

from src.engrama_core.service import level as level_mod
from src.practica import reglas as reglas_mod
from src.practica import service as service_mod
from src.practica.reglas import Candidato, Escalera, Tamano
from src.shared.config import Settings, settings
from tests.practica import test_tanda as tt
from tests.practica import test_unit as tu

Aplicar = Callable[[pytest.MonkeyPatch], None]

_TRAS_INTENTO = service_mod.tras_intento


def _parche(modulo: Any, nombre: str, valor: Any) -> Aplicar:
    return lambda mp: mp.setattr(modulo, nombre, valor)


class _ArrancaEnB2(Settings):
    """ZP1: sin SET, la práctica arranca en B2."""

    # A propósito un str fuera del Literal de Settings: es el tramposo ZP1 (mypy lo marcaría).
    practica_nivel_inicial: str = "B2"  # type: ignore[assignment]


def _sin_limites(ancla: str | None) -> tuple[int, int]:
    """ZP2: el ancla de SET no limita nada."""
    return 0, len(reglas_mod.NIVELES) - 1


def _decide_con_todo(nivel: str, resultados: Sequence[bool], ancla: str | None,
                     decisiones: int, e: Escalera) -> str:
    """ZP3: mira TODAS las respuestas, no las últimas de la ventana."""
    tamano, sube, baja = reglas_mod.ventana_vigente(ancla, decisiones, e)
    if len(resultados) < tamano:
        return nivel
    correctas = sum(1 for r in resultados if r) * tamano // len(resultados)
    if correctas >= sube:
        return reglas_mod.mover(nivel, +1, ancla)
    if correctas <= baja:
        return reglas_mod.mover(nivel, -1, ancla)
    return nivel


def _sin_tope_de_retos(candidatos: Iterable[Candidato], t: Tamano) -> list[Candidato]:
    """ZP4: sigue sumando retos hasta llegar a las preguntas, sin máximo."""
    elegidos: list[Candidato] = []
    for c in sorted(candidatos, key=reglas_mod.orden_fijo):
        if sum(x.preguntas for x in elegidos) >= t.preguntas_min:
            break
        elegidos.append(c)
    return elegidos


def _de_cualquier_nivel(nivel: str) -> Any:
    """ZP5: la tanda no mira el nivel de práctica."""
    return true()


def _todo_el_mundo_ve_todo(tenant_id: UUID, group_code: str | None) -> Any:
    """ZP6: la tanda no pasa por la visibilidad del estudiante."""
    return true()


async def _el_nivel_va_al_escudo(db: AsyncSession, *, tenant_id: UUID, student_id: UUID,
                                 challenge: Any) -> None:
    """ZP10: tras cada intento, el nivel de práctica se escribe como nivel confirmado."""
    await _TRAS_INTENTO(db, tenant_id=tenant_id, student_id=student_id, challenge=challenge)
    nivel, _ancla = await service_mod.nivel_vigente(db, tenant_id, student_id)
    await level_mod.record_confirmed_level(
        db, tenant_id=tenant_id, profile_id=student_id, cefr=nivel, source="teacher",
        provisional=True, score=None, assessed_at=datetime.now(UTC), event_row_id=None)


def _solo_por_persona(modelo: Any, tenant_id: UUID, profile_id: UUID) -> Any:
    """ZP11: el nivel y la tanda se buscan sin institución."""
    return modelo.profile_id == profile_id


async def _sin_repaso(db: AsyncSession, tenant_id: UUID, profile_id: UUID,
                      group_code: str | None) -> list[Any]:
    """ZP12: la tanda no pone el repaso."""
    return []


async def _solo_lo_nuevo(db: AsyncSession, fila: Any, tenant_id: UUID, profile_id: UUID,
                         group_code: str | None, fuera: Sequence[UUID],
                         ) -> tuple[str, list[Candidato], str | None]:
    """ZP13: si el nivel se agota, la tanda queda vacía (ni sube ni repite)."""
    nuevos = await service_mod._candidatos(db, tenant_id, profile_id, group_code, fila.nivel,
                                           fuera, ganados=False)
    return reglas_mod.MODO_NUEVO, reglas_mod.armar(nuevos, service_mod.tamano()), None


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[..., None], str]] = {
    "ZP1": (_parche(tu, "Settings", _ArrancaEnB2), tu.test_up1_el_arranque_y_los_limites,
            r"UP1: \{'por_defecto': \('B2', 12"),
    "ZP2": (_parche(reglas_mod, "limites", _sin_limites), tu.test_up2_la_escalera,
            r"'B2 no pasa de B2': 'C1'"),
    "ZP3": (_parche(reglas_mod, "decidir", _decide_con_todo), tu.test_up2_la_escalera,
            r"'viejas buenas, las 12 ultimas malas': 'B1'"),
    "ZP4": (_parche(reglas_mod, "armar", _sin_tope_de_retos), tu.test_up3_armar_la_tanda,
            r"'de_una_pregunta_tope_4_retos': \['r0', 'r1', 'r2', 'r3', 'r4', 'r5'\]"),
    "ZP5": (_parche(service_mod, "_del_nivel", _de_cualquier_nivel),
            tt.test_td1_la_tanda_sale_del_nivel_de_practica,
            r"'primera': \('A2', False, \(1, 'nuevo', 'A2', \[\('de-b1', 'pendiente', 10\)"),
    "ZP6": (_parche(service_mod, "_visibles", _todo_el_mundo_ve_todo),
            tt.test_td1_la_tanda_sale_del_nivel_de_practica,
            r"'primera': \('A2', False, \(1, 'nuevo', 'A2', \[\('de-otro-grupo', 'pendiente'"),
    "ZP7": (_parche(service_mod, "_completa", lambda estados: True),
            tt.test_td1_la_tanda_sale_del_nivel_de_practica,
            r"'repetir_devuelve_la_misma': False"),
    "ZP8": (_parche(settings, "tanda_max_al_dia", 99), tt.test_td2_el_tope_de_dos_tandas_al_dia,
            r"'tras_la_2': .*6, 0, True\), 2, True, False, False\)"),
    "ZP9": (_parche(service_mod, "_es_el_primero", true),
            tt.test_td4_la_escalera_solo_mira_el_primer_intento,
            r"'baja_antes_del_segundo_intento': \('A2', False\)"),
    "ZP10": (_parche(service_mod, "tras_intento", _el_nivel_va_al_escudo),
             tt.test_td4_la_escalera_solo_mira_el_primer_intento,
             r"'nivel_confirmado_intacto': False"),
    "ZP11": (_parche(service_mod, "_del_dueno", _solo_por_persona),
             tt.test_td6_el_nivel_y_la_tanda_son_por_institucion,
             r"'en_b_antes': \('B1', False\)"),
    "ZP12": (_parche(service_mod, "_repaso_que_toca", _sin_repaso),
             tt.test_td3_el_repaso_va_primero_y_no_paga,
             r"\[\('nuevo', 'pendiente', 10\)\], 6, 0, False\)"),
    "ZP13": (_parche(service_mod, "_elegir", _solo_lo_nuevo),
             tt.test_td5_cuando_el_nivel_se_agota,
             r"'hoy_la_2_sube_de_nivel': \('A2', False, \(1, 'nuevo', 'A2'"),
}
SIN_BASE = ("ZP1", "ZP2", "ZP3", "ZP4")


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
