"""Tramposos de la aceptación de seguridad (docs/ESPEC_aceptacion_seguridad.md §3).

Mismo patrón que test_tramposos_integ.py: se pone una versión ROTA a propósito,
se corre el cuerpo del test real y se exige AssertionError con el mensaje del
ataque (`match`): el test tiene que ponerse rojo por la razón correcta, no por
cualquier cosa. Si el test real pasara con el tramposo, este queda en rojo.

  A1  profile_to_schema copia pin_hash en full_name        -> test_a1
  A2  se agrega PATCH /core/coins/balance                    -> test_a2
  A3  question_to_schema pone correct_answer en el texto     -> test_a3
  A4  is_attempt_correct devuelve siempre True               -> test_a4
  A5  submit usa al dueño del intento, no al que envía       -> test_a5
  A6  build_auth_context toma profiles.role                  -> test_a6
  A7  get_challenge sin filtro de tenant                     -> test_a7
  D1  política `TO anon USING (true)` en profiles            -> test_d1
  D4  política `WITH CHECK (true)` en coin_ledger            -> test_d4
  D10 se crea una política `USING (true)`                    -> test_d10

Los tramposos de base CREAN una política real (confirmada) y la BORRAN en el
`finally`: `como` usa su propia conexión y solo ve lo confirmado. El contenedor
es desechable (tmpfs); si el proceso muriera a mitad, la política no sobrevive
a la siguiente sesión. Los xfail (D2, D5-D9, D11) llevan su tramposo en la
espec de su BUG (§3), no aquí.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from typing import Any
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import select

import tests.seguridad.test_aceptacion as seg
from src.auth import router as auth_router
from src.auth import service as auth_service
from src.challenge_engine.service import attempts as attempts_mod
from src.challenge_engine.service import challenges as challenges_mod
from src.main import app
from src.shared import deps
from src.shared.models import Challenge, ChallengeAttempt
from tests.seguridad.veredictos import sembrar

pytestmark = pytest.mark.integ

_QUESTION_TO_SCHEMA = challenges_mod.question_to_schema
_SUBMIT_ATTEMPT = attempts_mod.submit_attempt


# =============================================================================
# Versiones rotas (API)
# =============================================================================
def _perfil_con_hash(profile: Any, memberships: list[Any]) -> Any:
    return auth_service.profile_to_schema(profile, memberships).model_copy(
        update={"full_name": profile.pin_hash})


def _pregunta_con_clave(q: Any) -> Any:
    return _QUESTION_TO_SCHEMA(q).model_copy(
        update={"question_text": f"{q.question_text} [{q.correct_answer}]"})


async def _submit_con_el_dueno(db: Any, *, student_id: UUID, tenant_id: UUID,
                               attempt_id: UUID, answers: list[Any]) -> Any:
    dueno = (await db.execute(select(ChallengeAttempt.student_id)
                              .where(ChallengeAttempt.id == attempt_id))).scalar_one_or_none()
    return await _SUBMIT_ATTEMPT(db, student_id=dueno or student_id, tenant_id=tenant_id,
                                 attempt_id=attempt_id, answers=answers)


def _contexto_con_rol_del_perfil(profile: Any, memberships: list[Any],
                                 tenant_id_header: str | None = None) -> Any:
    ctx = auth_service.build_auth_context(profile, memberships, tenant_id_header)
    rol = profile.role
    return ctx.model_copy(update={"role": rol,
                                  "is_teacher": rol in {"teacher", "admin", "super_admin"},
                                  "is_admin": rol in {"admin", "super_admin"}})


async def _get_challenge_sin_tenant(db: Any, challenge_id: UUID, tenant_id: UUID) -> Any:
    reto = (await db.execute(select(Challenge).where(Challenge.id == challenge_id))
            ).scalar_one_or_none()
    if reto is None:
        raise HTTPException(status_code=404, detail="Challenge not found")
    return reto


@contextmanager
def _ruta_patch_saldo() -> Iterator[None]:
    async def _editar_saldo() -> dict[str, bool]:
        return {"ok": True}

    app.router.add_api_route("/core/coins/balance", _editar_saldo, methods=["PATCH"])
    ruta = app.router.routes[-1]
    try:
        yield
    finally:
        app.router.routes.remove(ruta)


@contextmanager
def _politica(integ: Any, tabla: str, nombre: str, cuerpo: str) -> Iterator[None]:
    sembrar(integ, f"create policy {nombre} on {tabla} {cuerpo}")
    try:
        yield
    finally:
        sembrar(integ, f"drop policy if exists {nombre} on {tabla}")


def _parche(objetivo: Any, nombre: str, valor: Any) -> Callable[..., AbstractContextManager]:
    def aplicar(_integ: Any, mp: pytest.MonkeyPatch) -> AbstractContextManager:
        mp.setattr(objetivo, nombre, valor)
        return nullcontext()
    return aplicar


# =============================================================================
# Registro: id -> (cómo romper, test real, mensaje con el que debe caer)
# =============================================================================
Aplicar = Callable[[Any, pytest.MonkeyPatch], AbstractContextManager]
TRAMPOSOS: dict[str, tuple[Aplicar, Callable[[Any], None], str]] = {
    "A1": (_parche(auth_router, "profile_to_schema", _perfil_con_hash),
           seg.test_a1_auth_me_no_expone_pin_hash, "el hash del PIN sale"),
    "A2": (lambda _i, _mp: _ruta_patch_saldo(),
           seg.test_a2_core_coins_es_solo_lectura, "rutas de /core/coins"),
    "A3": (_parche(challenges_mod, "question_to_schema", _pregunta_con_clave),
           seg.test_a3_reto_no_revela_correct_answer, "la respuesta correcta sale"),
    "A4": (_parche(attempts_mod, "is_attempt_correct", lambda *_a: True),
           seg.test_a4_submit_no_acepta_premios_del_cliente, r"\[True, 20, 15\]"),
    "A5": (_parche(attempts_mod, "submit_attempt", _submit_con_el_dueno),
           seg.test_a5_no_se_envia_el_intento_ajeno, "200 == 404"),
    "A6": (_parche(deps, "build_auth_context", _contexto_con_rol_del_perfil),
           seg.test_a6_rol_del_perfil_no_da_permisos, "/challenges/all -> 200"),
    "A7": (_parche(challenges_mod, "get_challenge", _get_challenge_sin_tenant),
           seg.test_a7_otro_colegio_no_se_ve, "200 == 404"),
    "D1": (lambda i, _mp: _politica(i, "profiles", "trampa_d1",
                                    "for select to anon using (true)"),
           seg.test_d1_anon_no_lee_ni_escribe, "anon SELECT profiles: el ataque PASA"),
    "D4": (lambda i, _mp: _politica(i, "coin_ledger", "trampa_d4",
                                    "for insert to authenticated with check (true)"),
           seg.test_d4_nadie_escribe_el_ledger, "INSERT coin_ledger: el ataque PASA"),
    "D10": (lambda i, _mp: _politica(i, "badges", "trampa_d10",
                                     "for select to authenticated using (true)"),
            seg.test_d10_ninguna_politica_abierta, "políticas abiertas: badges.trampa_d10"),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    # El humo lo escribe la corrida real; un tramposo no debe ensuciarlo.
    monkeypatch.setattr(seg, "registrar_humo", lambda *_a, **_k: None)
    with aplicar(integ, monkeypatch), pytest.raises(AssertionError, match=motivo):
        test_real(integ)
