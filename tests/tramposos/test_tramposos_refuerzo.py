"""Tramposos ZC1-ZC16 de la cola de refuerzo — `docs/ESPEC_refuerzo.md` §3.

Una versión ROTA a propósito, inyectada con monkeypatch en el módulo donde se
USA; se corre el cuerpo del test real y se exige `AssertionError` con el
mensaje del mecanismo. Aquí se automatiza la DIAGONAL; la matriz completa se
mide aparte (ERR-15, 19 y 23). ZC16 es no-integ.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession

from src.curriculo import reapuntar as reapuntar_mod
from src.engrama_core.service import coins as coins_mod
from src.refuerzo import cola as cola_mod
from src.refuerzo import formas as formas_mod
from src.refuerzo import reglas as reglas_mod
from src.refuerzo import service as service_mod
from src.refuerzo.reglas import Estado, Forma, Regla
from src.shared.config import Settings
from src.shared.models import ReinforcementQueue
from src.teachers.service import access as access_mod
from tests.refuerzo import test_ciclo as tc
from tests.refuerzo import test_entrada as te
from tests.refuerzo import test_unit as tu

Aplicar = Callable[[pytest.MonkeyPatch], None]

_RESPONDER = service_mod.responder
_TRANSICION = reglas_mod.transicion
_ELEGIR = reglas_mod.elegir
_TABLAS = list(reapuntar_mod.TABLAS)


def _parche(modulo: Any, nombre: str, valor: Any) -> Aplicar:
    return lambda mp: mp.setattr(modulo, nombre, valor)


def _todas(candidatas: Iterable[Forma], vistas: set[str]) -> list[Forma]:
    """ZC1: las ya vistas también se sirven."""
    return list(candidatas)


async def _responder_y_pagar(db: AsyncSession, **datos: Any) -> Any:
    """ZC2: cada respuesta nueva del refuerzo acredita una moneda."""
    salida = await _RESPONDER(db, **datos)
    if not salida.repetida:
        await coins_mod.award_coins(db, student_id=datos["profile_id"],
                                    tenant_id=datos["tenant_id"], amount=1, action="challenge",
                                    metadata={"refuerzo": salida.entrada_id})
    return salida


def _superado_al_primer_acierto(estado: Estado, acerto: bool, ahora: datetime,
                                regla: Regla) -> Estado:
    """ZC3: sin repaso."""
    if acerto:
        return Estado(reglas_mod.SUPERADO, 0, None, ahora)
    return _TRANSICION(estado, acerto, ahora, regla)


def _el_repaso_toca_ya(status: str, next_due_at: datetime | None, ahora: datetime) -> bool:
    """ZC4: el repaso no se espacia."""
    return status != reglas_mod.SUPERADO


async def _sin_respuesta_previa(db: AsyncSession, entrada_id: int, question_id: UUID) -> None:
    """ZC5: no recuerda que ya respondió."""
    return None


async def _entrada_de_cualquiera(db: AsyncSession, tenant_id: UUID, profile_id: UUID,
                                 entrada_id: int) -> ReinforcementQueue | None:
    """ZC7: la entrada se busca solo por su id."""
    return (await db.execute(select(ReinforcementQueue).where(
        ReinforcementQueue.id == entrada_id))).scalar_one_or_none()


def _todos_los_items(hoja: Any) -> list[str]:
    """ZC8: todo ítem de la hoja entra, acertado o no."""
    return [item.item_id for item in hoja.items]


def _siempre(nueva: Any) -> Any:
    """ZC9: la misma hoja vuelve a contar."""
    return true()


async def _el_reto_no_mete_nada(db: AsyncSession, **datos: Any) -> None:
    """ZC10."""


def _rellenar_con_una_vista(candidatas: Iterable[Forma], vistas: set[str], *,
                            familia: str | None, etapa: str, usadas: set[str]) -> Forma | None:
    """ZC11: si no queda ninguna no vista, repite una vista."""
    todas = list(candidatas)
    forma = _ELEGIR(todas, vistas, familia=familia, etapa=etapa, usadas=usadas)
    return forma if forma is not None else (todas[0] if todas else None)


def _todo_el_mundo_ve_todo(tenant_id: UUID, group_code: str | None) -> Any:
    """ZC13: las candidatas no pasan por la visibilidad del estudiante."""
    return true()


async def _no_reapunta(db: AsyncSession, viejo: str, nuevo: str) -> int:
    return 0


def _sin_reapuntar_la_cola() -> list[tuple[str, Any]]:
    return [(nombre, _no_reapunta if nombre == "reinforcement_queue" else funcion)
            for nombre, funcion in _TABLAS]


def _fallar_el_repaso_no_devuelve(estado: Estado, acerto: bool, ahora: datetime,
                                  regla: Regla) -> Estado:
    """ZC15: quien falla el repaso sigue `por_repasar` con la misma fecha."""
    if estado.status == reglas_mod.POR_REPASAR and not acerto:
        return estado
    return _TRANSICION(estado, acerto, ahora, regla)


class _RepasoACeroDias(Settings):
    """ZC16: el valor por defecto del repaso es 0 días."""

    refuerzo_dias_repaso: int = 0


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[..., None], str]] = {
    "ZC1": (_parche(reglas_mod, "no_vistas", _todas), tc.test_cr3_el_ciclo_completo_sin_monedas,
            r"'segunda': \(\[\('refuerzo', 'it-2'\)\]"),
    "ZC2": (_parche(service_mod, "responder", _responder_y_pagar),
            tc.test_cr3_el_ciclo_completo_sin_monedas, r"'dinero_identico': False"),
    "ZC3": (_parche(reglas_mod, "transicion", _superado_al_primer_acierto),
            tc.test_cr3_el_ciclo_completo_sin_monedas,
            r"'acierta': \(200, \(True, 'A', 'superado', None, False, 0\)\)"),
    "ZC4": (_parche(reglas_mod, "toca", _el_repaso_toca_ya),
            tc.test_cr3_el_ciclo_completo_sin_monedas,
            r"'despues_de_acertar': \(\[\('repaso', 'it-9'\)\], 0, 0, 0\)"),
    "ZC5": (_parche(service_mod, "_respuesta_previa", _sin_respuesta_previa),
            tc.test_cr3_el_ciclo_completo_sin_monedas,
            r"'repite_con_otra_respuesta': \(409, 'forma_no_vigente'\)"),
    "ZC6": (_parche(service_mod, "_exigir_forma_vigente", lambda *_: None),
            tc.test_cr3_el_ciclo_completo_sin_monedas,
            r"'responder_el_item_del_examen': \(200, "),
    "ZC7": (_parche(service_mod, "_entrada_del_estudiante", _entrada_de_cualquiera),
            tc.test_cr6_el_panel_es_del_profe_y_la_cola_de_cada_uno,
            r"'el_companero_responde_la_de_e': 409"),
    "ZC8": (_parche(cola_mod, "fallados_de_la_hoja", _todos_los_items),
            te.test_cr1_desde_una_hoja_del_grader,
            r"'tras_primera': \{'fn.a2.tres': \('en_refuerzo', 1, 'grader', 0\), "
            r"'gr.a1.dos': .*'lx.b1.cuatro'"),
    "ZC9": (_parche(cola_mod, "_solo_si_es_otro_origen", _siempre),
            te.test_cr1_desde_una_hoja_del_grader, r"'reenviar_no_cambia_nada': False"),
    "ZC10": (_parche(cola_mod, "desde_intento", _el_reto_no_mete_nada),
             te.test_cr2_desde_un_reto, r"'tras_primero': \{\}"),
    "ZC11": (_parche(reglas_mod, "elegir", _rellenar_con_una_vista),
             tc.test_cr4_sin_forma_no_vista_queda_en_espera,
             r"CR4: \{'sin_formas': \(200, \(\[\('refuerzo', 'gr.a1.dos', "),
    "ZC12": (_parche(access_mod, "_requiere_asignacion", lambda auth, *, only_assigned: False),
             tc.test_cr6_el_panel_es_del_profe_y_la_cola_de_cada_uno,
             r"'prohibidos': \{'E': 403, 'DO': 200"),
    "ZC13": (_parche(formas_mod, "_visibles", _todo_el_mundo_ve_todo),
             tc.test_cr3_el_ciclo_completo_sin_monedas,
             r"CR3: \{'primera': \(\[\('refuerzo', 'it-0'\)\]"),
    "ZC14": (lambda mp: mp.setattr(reapuntar_mod, "TABLAS", _sin_reapuntar_la_cola()),
             te.test_cr7_una_fusion_del_mapa_reapunta_la_cola, r"'reapuntadas': 0"),
    "ZC15": (_parche(reglas_mod, "transicion", _fallar_el_repaso_no_devuelve),
             tc.test_cr5_retrocesos_y_configuracion,
             r"'falla_el_repaso': \('por_repasar', '2026-10-13T15:00:00Z'\)"),
    "ZC16": (_parche(tu, "Settings", _RepasoACeroDias), tu.test_ur1_reglas_puras_del_refuerzo,
             r"UR1: \{'por_defecto': \(1, 0, 5\)"),
}
SIN_BASE = ("ZC16",)


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
        test_real(monkeypatch)
