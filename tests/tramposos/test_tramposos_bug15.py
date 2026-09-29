"""Tramposos Y10-Y13 (integ) de BUG-15 — `docs/ESPEC_bug13a15.md` §3.

Mismo patrón que `test_tramposos_bug13.py`: una versión ROTA a propósito, se
corre el cuerpo del test real y se exige `AssertionError` con el mensaje del
mecanismo. Aquí se automatiza la DIAGONAL (la negrita de §3); la matriz
completa se mide aparte (columna "Rojo medido"), ERR-15, 19 y 23.

  Y10  `filtro_grupo_estudiante` = `true()`                -> A15-1 y el feed
       (`test_list_challenges_student_filters_by_group`: C17, una sola fuente)
  Y11  `start_attempt` con `get_challenge` (solo tenant)   -> A15-2
  Y12  `get_challenge_for` ignora `es_personal`            -> S15
  Y13  `get_challenge_for` responde 403 si el reto existe en el tenant pero
       no es del grupo                                     -> A15-1
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from typing import Any
from uuid import UUID

import pytest
from fastapi import HTTPException, status
from sqlalchemy import true
from sqlalchemy.ext.asyncio import AsyncSession

from src.challenge_engine.schemas import AttemptStartOut
from src.challenge_engine.service import attempts as attempts_mod
from src.challenge_engine.service import challenges as challenges_mod
from src.shared.models import Challenge
from tests.challenge_engine import test_bug15_reto_de_grupo as b15
from tests.challenge_engine import test_challenges as tc
from tests.tramposos.test_tramposos_bug13 import correr

pytestmark = pytest.mark.integ

Aplicar = Callable[[Any, pytest.MonkeyPatch], AbstractContextManager[Any]]

_START_BUENO = attempts_mod.start_attempt
_GET_FOR_BUENO = challenges_mod.get_challenge_for


async def _start_solo_tenant(db: AsyncSession, **kw: Any) -> AttemptStartOut:
    """Y11: `start_attempt` que busca el reto solo por tenant (`get_challenge`).

    `es_personal=True` hace que `get_challenge_for` delegue en `get_challenge`:
    es exactamente la búsqueda de antes de BUG-15.
    """
    return await _START_BUENO(db, **{**kw, "es_personal": True})


async def _get_for_sin_personal(db: AsyncSession, challenge_id: UUID, *, tenant_id: UUID,
                                group_code: str | None, es_personal: bool) -> Challenge:
    """Y12: trata a TODOS como estudiantes (filtra también al personal)."""
    del es_personal
    return await _GET_FOR_BUENO(db, challenge_id, tenant_id=tenant_id,
                                group_code=group_code, es_personal=False)


async def _get_for_403(db: AsyncSession, challenge_id: UUID, *, tenant_id: UUID,
                       group_code: str | None, es_personal: bool) -> Challenge:
    """Y13: si el reto existe en el tenant pero no es visible, 403 (delata que existe)."""
    try:
        return await _GET_FOR_BUENO(db, challenge_id, tenant_id=tenant_id,
                                    group_code=group_code, es_personal=es_personal)
    except HTTPException as exc:
        existe = await db.get(Challenge, challenge_id) if exc.status_code == 404 else None
        if existe is not None and existe.tenant_id == tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Challenge belongs to another group") from exc
        raise


def _parche(objetivo: Any, nombre: str, valor: Any) -> Aplicar:
    def aplicar(_integ: Any, mp: pytest.MonkeyPatch) -> AbstractContextManager[Any]:
        mp.setattr(objetivo, nombre, valor)
        return nullcontext()
    return aplicar


# =============================================================================
# Registro: id -> (cómo romper, [(test real, mensaje con el que debe caer)])
# =============================================================================
TRAMPOSOS: dict[str, tuple[Aplicar, list[tuple[Callable[..., None], str]]]] = {
    "Y10": (_parche(challenges_mod, "filtro_grupo_estudiante", lambda *_: true()), [
        (b15.test_a15_1_detalle_de_reto_de_otro_grupo_da_404, r"E1 abrió el reto de G2: 200"),
        (tc.test_list_challenges_student_filters_by_group, r"assert \{"),
    ]),
    "Y11": (_parche(attempts_mod, "start_attempt", _start_solo_tenant), [
        (b15.test_a15_2_arrancar_reto_de_otro_grupo_da_404, r"E1 arrancó el reto de G2: 201"),
    ]),
    "Y12": (_parche(challenges_mod, "get_challenge_for", _get_for_sin_personal), [
        (b15.test_s15_controles_de_retos, r"el docente no abre G2"),
    ]),
    "Y13": (_parche(challenges_mod, "get_challenge_for", _get_for_403), [
        (b15.test_a15_1_detalle_de_reto_de_otro_grupo_da_404, r"E1 abrió el reto de G2: 403"),
    ]),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    aplicar, diagonal = TRAMPOSOS[clave]
    with aplicar(integ, monkeypatch):
        for test_real, motivo in diagonal:
            with pytest.raises(AssertionError, match=motivo):
                correr(test_real, integ, monkeypatch)
