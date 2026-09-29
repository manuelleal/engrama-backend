"""Tramposos Y7, Y8, Y9 e Y14 (integ) de BUG-14 — `docs/ESPEC_bug13a15.md` §3.

Mismo patrón que `test_tramposos_bug13.py`: una versión ROTA a propósito, se
corre el cuerpo del test real y se exige `AssertionError` con el mensaje del
mecanismo. Aquí se automatiza la DIAGONAL (la celda en negrita de §3); la
matriz completa se mide aparte (columna "Rojo medido"), ERR-15, 19 y 23.

  Y7   `_buscar_sesion` = la búsqueda vieja (solo tenant)             -> A14-1
  Y8   `check_in` con el 410 PRIMERO y después el 404 de grupo        -> A14-2
  Y9   `_buscar_sesion` ignora `es_estudiante`                        -> A14-3
  Y14  `check_in` con un 404 distinto si el código existe en el tenant -> A14-1
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.engrama_core.schemas import CheckInResult
from src.engrama_core.service import attendance as attendance_mod
from src.shared.models import AttendanceSession
from tests.engrama_core import test_bug14_checkin_grupo as b14
from tests.tramposos.test_tramposos_bug13 import correr

pytestmark = pytest.mark.integ

Aplicar = Callable[[Any, pytest.MonkeyPatch], AbstractContextManager[Any]]

_BUSCAR_BUENO = attendance_mod._buscar_sesion
_CHECK_IN_BUENO = attendance_mod.check_in


async def _por_tenant(db: AsyncSession, session_code: str,
                      tenant_id: UUID) -> AttendanceSession | None:
    """La consulta de antes de BUG-14: código + tenant, sin grupo ni rol."""
    stmt = select(AttendanceSession).where(AttendanceSession.session_code == session_code,
                                           AttendanceSession.tenant_id == tenant_id)
    return (await db.execute(stmt)).scalar_one_or_none()


# =============================================================================
# Y7, Y9 — `_buscar_sesion` roto
# =============================================================================
async def _buscar_vieja(db: AsyncSession, *, session_code: str, tenant_id: UUID,
                        group_code: str | None, es_estudiante: bool
                        ) -> AttendanceSession | None:
    """Y7: ignora grupo y rol (la búsqueda de antes)."""
    del group_code, es_estudiante
    return await _por_tenant(db, session_code, tenant_id)


async def _buscar_sin_rol(db: AsyncSession, *, session_code: str, tenant_id: UUID,
                          group_code: str | None, es_estudiante: bool
                          ) -> AttendanceSession | None:
    """Y9: filtra por grupo, pero trata a cualquiera como estudiante."""
    del es_estudiante
    return await _BUSCAR_BUENO(db, session_code=session_code, tenant_id=tenant_id,
                               group_code=group_code, es_estudiante=True)


# =============================================================================
# Y8, Y14 — `check_in` trasplantado
# =============================================================================
async def _check_in_410_primero(db: AsyncSession, *, session_code: str, tenant_id: UUID,
                                **resto: Any) -> CheckInResult:
    """Y8: busca por tenant y responde 410 ANTES de mirar el grupo."""
    sesion = await _por_tenant(db, session_code, tenant_id)
    if sesion is not None and (sesion.status != "active"
                               or sesion.expires_at <= datetime.now(UTC)):
        raise HTTPException(status_code=status.HTTP_410_GONE,
                            detail="Session expired or no longer active")
    return await _CHECK_IN_BUENO(db, session_code=session_code, tenant_id=tenant_id, **resto)


async def _check_in_delata(db: AsyncSession, *, session_code: str, tenant_id: UUID,
                           **resto: Any) -> CheckInResult:
    """Y14: si el código existe en el tenant pero no es visible, un 404 DISTINTO."""
    try:
        return await _CHECK_IN_BUENO(db, session_code=session_code, tenant_id=tenant_id,
                                     **resto)
    except HTTPException as exc:
        if exc.status_code == 404 and await _por_tenant(db, session_code, tenant_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="Session belongs to another group") from exc
        raise


def _parche(nombre: str, valor: Any) -> Aplicar:
    def aplicar(_integ: Any, mp: pytest.MonkeyPatch) -> AbstractContextManager[Any]:
        mp.setattr(attendance_mod, nombre, valor)
        return nullcontext()
    return aplicar


# =============================================================================
# Registro: id -> (cómo romper, [(test real, mensaje con el que debe caer)])
# =============================================================================
TRAMPOSOS: dict[str, tuple[Aplicar, list[tuple[Callable[..., None], str]]]] = {
    "Y7": (_parche("_buscar_sesion", _buscar_vieja), [
        (b14.test_a14_1_checkin_de_otro_grupo_da_404, r"E2 marcó en G1: 200"),
    ]),
    "Y8": (_parche("check_in", _check_in_410_primero), [
        (b14.test_a14_2_sesion_expirada_de_otro_grupo_no_delata_que_existe,
         r"la sesión expirada de G1 se delata: 410"),
    ]),
    "Y9": (_parche("_buscar_sesion", _buscar_sin_rol), [
        (b14.test_a14_3_solo_estudiantes_del_grupo_marcan, r"el docente marcó: 200"),
    ]),
    "Y14": (_parche("check_in", _check_in_delata), [
        (b14.test_a14_1_checkin_de_otro_grupo_da_404,
         r"el 404 delata la sesión: .*Session belongs to another group"),
    ]),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    aplicar, diagonal = TRAMPOSOS[clave]
    with aplicar(integ, monkeypatch):
        for test_real, motivo in diagonal:
            with pytest.raises(AssertionError, match=motivo):
                correr(test_real, integ, monkeypatch)
