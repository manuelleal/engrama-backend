"""Tramposos ZK1-ZK4 y ZH1: la concurrencia, el reancla y el humo del reto del día.

`docs/ESPEC_humo_reto_del_dia.md` §4.1. Una versión ROTA a propósito, inyectada
con monkeypatch en el módulo donde se USA; se corre el cuerpo del test real y
se exige `AssertionError` con el mensaje del mecanismo. Todos son integ.
"""
from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.challenge_engine.service import attempts as attempts_mod
from src.challenge_engine.service import challenges as challenges_mod
from src.practica import reglas as reglas_mod
from src.practica import service as service_mod
from src.racha import service as racha_mod
from src.shared.config import settings
from src.shared.models import ChallengeAttempt, PracticeLevel
from tests.integ import test_humo_reto_del_dia as th
from tests.practica import test_concurrencia as tc

Aplicar = Callable[[pytest.MonkeyPatch], None]

_FILA = service_mod._fila
_PEDIR = service_mod.pedir_tanda


def _varios(*parches: tuple[Any, str, Any]) -> Aplicar:
    def _aplicar(mp: pytest.MonkeyPatch) -> None:
        for modulo, nombre, valor in parches:
            mp.setattr(modulo, nombre, valor)
    return _aplicar


async def _fila_sin_candado(db: AsyncSession, tenant_id: UUID, profile_id: UUID, *,
                            bloquear: bool = False) -> PracticeLevel | None:
    """ZK1 (a): la fila del nivel de práctica se lee sin bloquear."""
    return await _FILA(db, tenant_id, profile_id, bloquear=False)


async def _sin_reservar(db: AsyncSession, *, tenant_id: UUID, profile_id: UUID) -> None:
    """ZK1 (b): la tanda tampoco toma el candado de la racha."""
    return None


async def _intento_sin_bloqueo(db: AsyncSession, *, attempt_id: UUID, tenant_id: UUID,
                               student_id: UUID) -> ChallengeAttempt | None:
    """ZK2: el intento se lee sin `FOR UPDATE`: dos envíos a la vez pasan los dos."""
    return (await db.execute(select(ChallengeAttempt).where(
        ChallengeAttempt.id == attempt_id, ChallengeAttempt.tenant_id == tenant_id,
        ChallengeAttempt.student_id == student_id))).scalar_one_or_none()


async def _candados_al_reves(db: AsyncSession, *, tenant_id: UUID, profile_id: UUID,
                             group_code: str | None) -> Any:
    """ZK3: la tanda toma primero el nivel de práctica y después la racha (al revés que
    `/submit`). La pausa deja que el otro pedido tome su primer candado: abrazo mortal."""
    await service_mod.tomar(db, tenant_id, profile_id)
    await asyncio.sleep(1.5)
    return await _PEDIR(db, tenant_id=tenant_id, profile_id=profile_id, group_code=group_code)


async def _tomar_sin_reanclar(db: AsyncSession, tenant_id: UUID,
                              profile_id: UUID) -> PracticeLevel:
    """ZK4: la escritura no mira si SET confirmó un nivel después."""
    nivel, ancla = reglas_mod.inicial(None, settings.practica_nivel_inicial)
    await db.execute(pg_insert(PracticeLevel).values(
        tenant_id=tenant_id, profile_id=profile_id, nivel=nivel, ancla=ancla, decisiones=0,
        ventana_desde=service_mod.VENTANA_ABIERTA,
    ).on_conflict_do_nothing(constraint="practice_levels_owner_key"))
    fila = await _FILA(db, tenant_id, profile_id, bloquear=True)
    assert fila is not None
    return fila


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[..., None], str]] = {
    "ZK1": (_varios((service_mod, "_fila", _fila_sin_candado),
                    (racha_mod, "reservar", _sin_reservar)),
            tc.test_cc1_dos_tandas_a_la_vez, r"CC1: \{'estados': \[200, 500\]"),
    "ZK2": (_varios((attempts_mod, "_tomar_intento", _intento_sin_bloqueo)),
            tc.test_cc2_dos_submit_del_mismo_intento_a_la_vez,
            r"CC2: \{'estados': \[200, 200\]"),
    "ZK3": (_varios((service_mod, "pedir_tanda", _candados_al_reves)),
            tc.test_cc3_una_tanda_y_un_submit_a_la_vez, r"CC3: \{'estados': \[200, 500\]"),
    "ZK4": (_varios((service_mod, "tomar", _tomar_sin_reanclar)),
            tc.test_ra1_set_confirma_despues_y_la_practica_se_reancla,
            r"'la_tanda_sale_del_nivel_de_set': \('A1', True, \(1, 'nuevo', 'B1'"),
    "ZH1": (_varios((challenges_mod, "fuera_de_refuerzo", true)),
            th.test_hrd1_humo_del_reto_del_dia,
            r"HRD1, criterios: \{.*'retos_de_refuerzo_fuera_de_lugar': [1-9]"),
}


def correr(test_real: Callable[..., None], disponibles: dict[str, Any]) -> None:
    pedidas = inspect.signature(test_real).parameters
    test_real(**{nombre: disponibles[nombre] for nombre in pedidas})


@pytest.mark.integ
@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, tmp_path, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    # El humo del tramposo no pisa el archivo del humo bueno.
    monkeypatch.setattr(th, "RUTA_HUMO", tmp_path / "humo_del_tramposo.json")
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        correr(test_real, {"integ": integ, "monkeypatch": monkeypatch})
