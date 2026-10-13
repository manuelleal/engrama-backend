"""Tramposos ZS1-ZS10 de `solo_refuerzo`, la segunda vuelta y el nivel agotado.

`docs/ESPEC_solo_refuerzo.md` §3. Una versión ROTA a propósito, inyectada con
monkeypatch en el módulo donde se USA; se corre el cuerpo del test real y se
exige `AssertionError` con el mensaje del mecanismo. Aquí se automatiza la
DIAGONAL. ZS1 y ZS2 son no-integ.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession

from src.challenge_engine.service import challenges as challenges_mod
from src.engrama_core.service import economia
from src.practica import consultas as consultas_mod
from src.practica import reglas as reglas_mod
from src.practica import service as service_mod
from src.practica.reglas import Candidato, FormaDeReto
from src.racha import reglas as racha_reglas_mod
from src.racha import service as racha_mod
from src.refuerzo import formas as formas_mod
from src.refuerzo.reglas import Forma
from src.shared.config import settings
from src.shared.models import Challenge, ChallengeQuestion
from tests.practica import test_solo_refuerzo as ts
from tests.practica import test_solo_refuerzo_unit as tu

Aplicar = Callable[[pytest.MonkeyPatch], None]

_CANDIDATAS = formas_mod.candidatas


def _parche(modulo: Any, nombre: str, valor: Any) -> Aplicar:
    return lambda mp: mp.setattr(modulo, nombre, valor)


def _sin_esperar(formas: Sequence[FormaDeReto], vistas: Collection[str],
                 original_jugado: Mapping[str, datetime], ahora: datetime, dias: int) -> bool:
    """ZS1: la segunda vuelta no espera los días: basta haber jugado el original."""
    return bool(formas) and all(
        f.rol == "gemela" and f.familia in original_jugado and f.clave not in vistas
        for f in formas)


def _solo_la_membresia(semana_exenta: Any) -> frozenset[date]:
    """ZS2: el cierre solo perdona la semana de la membresía, no las sin contenido."""
    return frozenset({semana_exenta}) if isinstance(semana_exenta, date) else frozenset()


async def _cualquiera_lo_abre(db: AsyncSession, challenge: Any, *, student_id: UUID,
                              es_personal: bool) -> None:
    """ZS5: un estudiante abre cualquier reto `solo_refuerzo`."""
    return None


async def _la_cola_sin_los_de_refuerzo(db: AsyncSession, tenant_id: UUID,
                                       group_code: str | None,
                                       nodos: Collection[str]) -> dict[str, list[Forma]]:
    """ZS6: las candidatas del repaso no incluyen los retos `solo_refuerzo`."""
    por_nodo = await _CANDIDATAS(db, tenant_id, group_code, nodos)
    de_refuerzo = set((await db.execute(
        select(ChallengeQuestion.id)
        .join(Challenge, Challenge.id == ChallengeQuestion.challenge_id)
        .where(Challenge.tenant_id == tenant_id, Challenge.solo_refuerzo.is_(True)))).scalars())
    return {nodo: [f for f in formas if f.question_id not in de_refuerzo]
            for nodo, formas in por_nodo.items()}


def _paga_completa(challenge: Any) -> int:
    """ZS7: un reto `solo_refuerzo` paga su valor completo."""
    return economia.recompensa_del_reto(challenge.coins_reward, settings.reto_monedas_tope)


async def _nada_visto(db: AsyncSession, tenant_id: UUID, profile_id: UUID) -> set[str]:
    """ZS8: la segunda vuelta no mira qué gemelas ya vio."""
    return set()


async def _sin_prestar(db: AsyncSession, tenant_id: UUID, profile_id: UUID,
                       group_code: str | None, nivel: str, fuera: Sequence[UUID], *,
                       ganados: bool) -> list[Candidato]:
    """ZS9: sin retos del nivel, la tanda queda vacía (lo de antes de esta espec)."""
    return []


async def _sin_marcar(db: AsyncSession, *, tenant_id: UUID, profile_id: UUID) -> None:
    """ZS10: el día sin contenido no se marca."""
    return None


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[..., None], str]] = {
    "ZS1": (_parche(reglas_mod, "elegible_segunda_vuelta", _sin_esperar),
            tu.test_us1_la_segunda_vuelta_los_prestados_y_la_paga, r"'a 20 dias': True"),
    "ZS2": (_parche(racha_reglas_mod, "exentas_de", _solo_la_membresia),
            tu.test_us2_la_semana_sin_contenido_no_rompe_la_racha,
            r"'sin_contenido_no_gasta_el_protector': \(4, 6, 14, 0\)"),
    "ZS3": (_parche(challenges_mod, "fuera_de_refuerzo", true),
            ts.test_sr1_fuera_del_feed_y_de_la_tanda, r"SR1: \{'feed': \['gem', 'orig', 'rep'\]"),
    "ZS4": (_parche(service_mod, "_del_feed", true), ts.test_sr1_fuera_del_feed_y_de_la_tanda,
            r"'feed': \['orig'\], 'tanda': \('A2', False, \(1, 'nuevo', 'A2', "
            r"\[\('gem', 'pendiente', 5\)"),
    "ZS5": (_parche(challenges_mod, "exigir_que_pueda_abrirlo", _cualquiera_lo_abre),
            ts.test_sr1_fuera_del_feed_y_de_la_tanda,
            r"'el_estudiante_no_los_ve': \[200, 200, 200\], 'ni_los_abre': \[201, 201\]"),
    "ZS6": (_parche(formas_mod, "candidatas", _la_cola_sin_los_de_refuerzo),
            ts.test_sr2_los_de_refuerzo_alimentan_la_cola,
            r"'la_cola_sirve_la_gemela': \(200, \[\], 1\)"),
    "ZS7": (_parche(challenges_mod, "recompensa_de", _paga_completa),
            ts.test_sr3_la_segunda_vuelta, r"'la_gana': \(200, \(True, 10\)\)"),
    "ZS8": (_parche(consultas_mod, "vistas_de", _nada_visto), ts.test_sr3_la_segunda_vuelta,
            r"'a_22_dias': \('A2', False, \(1, 'segunda_vuelta', 'A2', "
            r"\[\('g1', 'pendiente', 5\), \('g2', 'pendiente', 5\)\]"),
    "ZS9": (_parche(service_mod, "_prestado", _sin_prestar),
            ts.test_sr4_sin_retos_del_nivel_se_presta_de_otro,
            r"'la_1_de_abajo': \('A2', False, None, 0, True, False, True\)"),
    "ZS10": (_parche(racha_mod, "anotar_sin_contenido", _sin_marcar),
             ts.test_sr5_sin_contenido_la_semana_no_rompe_la_racha,
             r"'ana_pide_y_no_hay_nada': \(\('A2', False, None, 0, True, False, True\), "
             r"False, 0\)"),
}
SIN_BASE = ("ZS1", "ZS2")


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
