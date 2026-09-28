"""Tramposos Y1-Y7 (integ) de BUG-11 — `docs/ESPEC_bug11.md` §3.

Mismo patrón que `test_tramposos_grupos.py`: una versión ROTA a propósito,
se corre el cuerpo del test real y se exige `AssertionError` con el mensaje
del mecanismo. Aquí se automatiza la DIAGONAL (la celda en negrita de §3);
la matriz completa (136 celdas) se mide aparte y se escribe en la espec
(columna "Rojo medido"), ERR-15 y ERR-19.

  Y1  `panel.roster` vuelve a leer `Profile.full_name`      -> A1
  Y2  `enroll_student` viejo (nombre en el perfil, la membresía lo copia) -> A1
  Y3  el perfil nuevo guarda el nombre (la membresía bien)  -> A1 (parte de base)
  Y4  `ya_estaba` pisa el nombre de la membresía            -> F9
  Y5  `_subir()` sin el UPDATE del backfill                 -> B1
  Y6  DROP del CHECK en la base de la sesión                -> C9
  Y7  `_bajar()` sin el UPDATE de `profiles`                -> B2

Y8 (validador estático) vive en `test_tramposos_bug11_estatico.py` (commit 3).
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from typing import Any
from uuid import UUID, uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.models import Attendance, AttendanceSession, Group, Membership, Profile
from src.teachers.schemas import ConsistencyOut, StudentRosterOut
from src.teachers.service import panel as panel_mod
from src.teachers.service import roster as roster_mod
from tests.integ import test_migracion_032 as mig
from tests.teachers import test_bug11_nombre_por_colegio as b11
from tests.teachers import test_m3_students as m3

pytestmark = pytest.mark.integ

Aplicar = Callable[[Any, pytest.MonkeyPatch], AbstractContextManager[Any]]


# =============================================================================
# Y1 — T2/T5 leen el nombre global
# =============================================================================
async def _roster_lee_perfil(db: AsyncSession, group: Group) -> list[StudentRosterOut]:
    """Y1: el `roster` de antes de BUG-11 (`Profile.full_name` en select y order_by)."""
    ultima = (
        select(func.max(Attendance.attendance_date))
        .select_from(Attendance)
        .join(AttendanceSession, AttendanceSession.id == Attendance.session_id)
        .where(AttendanceSession.group_id == group.id, Attendance.student_id == Profile.id)
        .correlate(Profile)
        .scalar_subquery()
    )
    stmt = (
        select(Profile.id, Profile.full_name, Profile.current_streak, ultima)
        .select_from(Membership)
        .join(Profile, Profile.id == Membership.profile_id)
        .where(Membership.tenant_id == group.tenant_id,
               Membership.group_code == group.group_code,
               Membership.role == "student", Membership.is_active.is_(True))
        .order_by(Profile.full_name, Profile.id)
    )
    return [StudentRosterOut(profile_id=pid, full_name=nombre,
                             consistency=ConsistencyOut(current_streak=racha),
                             last_attendance_date=fecha)
            for pid, nombre, racha, fecha in (await db.execute(stmt)).all()]


# =============================================================================
# Y2, Y3, Y4 — M3/M4 escriben el nombre donde no va
# =============================================================================
def _enroll_roto(*, perfil_con_nombre: bool, membresia_copia_perfil: bool,
                 pisa_ya_estaba: bool) -> Callable[..., Any]:
    """`enroll_student` con UN defecto elegido; el resto igual al código bueno."""

    async def enroll(db: AsyncSession, tenant_id: UUID, group: Group, documento_id: str,
                     nombre_completo: str) -> tuple[Profile, str]:
        profile = await roster_mod.get_profile_by_documento(db, documento_id)
        if profile is None:
            profile = Profile(id=uuid4(), documento_id=documento_id, pin_hash="",
                              role="student",
                              full_name=nombre_completo if perfil_con_nombre else "")
            db.add(profile)
            await db.flush()
        membership = (await db.execute(select(Membership).where(
            Membership.tenant_id == tenant_id, Membership.profile_id == profile.id,
        ))).scalar_one_or_none()
        if membership is None:
            nombre = profile.full_name if membresia_copia_perfil else nombre_completo
            db.add(Membership(tenant_id=tenant_id, profile_id=profile.id, role="student",
                              group_code=group.group_code, is_active=True, full_name=nombre))
            await db.flush()
            return profile, "inscrito"
        if (membership.role != "student" or not membership.is_active
                or membership.group_code != group.group_code):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="conflicto")
        if pisa_ya_estaba:
            membership.full_name = nombre_completo
            await db.flush()
        return profile, "ya_estaba"

    return enroll


# =============================================================================
# Y5, Y7 — el SQL de la migración sin su UPDATE
# =============================================================================
async def _subir_sin_backfill(conn: asyncpg.Connection) -> None:
    """Y5: SQL_SUBIR sin el UPDATE del backfill."""
    for sql in mig.M032.SQL_SUBIR:
        if not sql.strip().upper().startswith("UPDATE"):
            await conn.execute(sql)


async def _bajar_sin_restaurar(conn: asyncpg.Connection) -> None:
    """Y7: SQL_BAJAR sin el UPDATE que restaura `profiles.full_name`."""
    for sql in mig.M032.SQL_BAJAR:
        if not sql.strip().upper().startswith("UPDATE"):
            await conn.execute(sql)


# =============================================================================
# Y6 — sin el CHECK en la base de la sesión
# =============================================================================
_DEF_CHECK = ("select pg_get_constraintdef(oid) from pg_constraint "
              "where conname = 'memberships_student_full_name_check'")


@contextmanager
def _sin_check(integ: Any) -> Iterator[None]:
    """Quita el CHECK (commit), y al salir lo repone y exige la MISMA definición."""
    antes = integ.valor(_DEF_CHECK)
    assert antes is not None, "control Y6: el CHECK no existe antes de romperlo"
    _sql(integ, f"alter table memberships drop constraint {mig.CHECK}")
    try:
        yield
    finally:
        _sql(integ, f"alter table memberships add constraint {mig.CHECK} check ({_cuerpo(antes)})")
        assert integ.valor(_DEF_CHECK) == antes, "Y6 no dejó el CHECK como estaba"


def _cuerpo(definicion: str) -> str:
    """'CHECK ((...))' -> '(...)'."""
    return definicion.strip()[len("CHECK"):].strip()


def _sql(integ: Any, sql: str) -> None:
    from sqlalchemy import text

    async def _q() -> None:
        async with integ.engine.begin() as conn:
            await conn.execute(text(sql))

    integ.run(_q())


def _parche(objetivo: Any, nombre: str, valor: Any) -> Aplicar:
    def aplicar(_integ: Any, mp: pytest.MonkeyPatch) -> AbstractContextManager[Any]:
        mp.setattr(objetivo, nombre, valor)
        return nullcontext()
    return aplicar


# =============================================================================
# Registro: id -> (cómo romper, test real, mensaje con el que debe caer)
# =============================================================================
TRAMPOSOS: dict[str, tuple[Aplicar, Callable[[Any], None], str]] = {
    "Y1": (_parche(panel_mod, "roster", _roster_lee_perfil),
           b11.test_a1_t2_cada_colegio_ve_su_nombre,
           r"T2 de GA: muestra '' en lugar de 'Ana Prueba Alfa'"),
    "Y2": (_parche(roster_mod, "enroll_student", _enroll_roto(
               perfil_con_nombre=True, membresia_copia_perfil=True, pisa_ya_estaba=False)),
           b11.test_a1_t2_cada_colegio_ve_su_nombre,
           r"T2 de GB: muestra 'Ana Prueba Alfa' en lugar de 'Ana Prueba Beta'"),
    "Y3": (_parche(roster_mod, "enroll_student", _enroll_roto(
               perfil_con_nombre=True, membresia_copia_perfil=False, pisa_ya_estaba=False)),
           b11.test_a1_t2_cada_colegio_ve_su_nombre,
           r"un nombre puesto por un colegio qued. en profiles\.full_name"),
    "Y4": (_parche(roster_mod, "enroll_student", _enroll_roto(
               perfil_con_nombre=False, membresia_copia_perfil=False, pisa_ya_estaba=True)),
           m3.test_f9_aa_matricula_idempotente_y_detecta_conflictos,
           r"'OTRO NOMBRE' == 'Ana Nueva'"),
    "Y5": (_parche(mig, "_subir", _subir_sin_backfill),
           mig.test_b1_backfill_solo_estudiantes_profiles_intacta_e_idempotente,
           r"SQL_SUBIR fall.: 23514 .*memberships_student_full_name_check"),
    "Y6": (lambda i, _mp: _sin_check(i),
           mig.test_c1_check_estudiante_sin_nombre,
           r"un student sin nombre entr. o fall. por otra cosa: None"),
    "Y7": (_parche(mig, "_bajar", _bajar_sin_restaurar),
           mig.test_b2_bajar_restaura_la_mas_antigua_y_volver_a_subir,
           r"bajar dej. '' en el perfil; se esperaba 'Ana Prueba Alfa'"),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    with aplicar(integ, monkeypatch), pytest.raises(AssertionError, match=motivo):
        test_real(integ)
