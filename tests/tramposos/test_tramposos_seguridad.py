"""Tramposos de la aceptación de seguridad.

Especs: docs/ESPEC_aceptacion_seguridad.md §3 y docs/ESPEC_bug3a9_sin_acceso_directo.md §3.

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
  A7  stmt_reto_del_tenant sin filtro de tenant              -> test_a7
  D1  GRANT SELECT ON profiles TO authenticated              -> test_d1
  D4  GRANT INSERT ON coin_ledger TO authenticated           -> test_d4
  D10 se crea una política `USING (true)`                    -> test_d10
  D12 CREATE FUNCTION public.trampa() (EXECUTE por PUBLIC)   -> test_d12
  D13 los DEFAULT de postgres vuelven a dar ALL ON TABLES    -> test_d13
  regrant-X  GRANT ALL a anon y authenticated en la tabla que
             ataca X (deshace la 031 en esa tabla)           -> test X
             X = D2, D3, D5-D9 y D11 por cada una de sus 8 tablas

Los tramposos de base CAMBIAN la base de verdad (confirmado: `como` usa su
propia conexión y solo ve lo confirmado) y la RESTAURAN en el `finally`. Los
de privilegios comprueban además que las ACL de `public` y los DEFAULT
quedaron exactamente como los dejó la 031. El contenedor es desechable
(tmpfs); si el proceso muriera a mitad, el daño no sobrevive a la sesión.

Fuera de la diagonal (ERR-10): D1, D4 y los regrant también ponen rojo a D12,
que mira todo el catálogo. Está documentado en la espec §3; se verifica a mano
y no se automatiza aquí. Medido a mano el 2026-09-25 (matriz de 506 celdas) y
NO previsto por la espec: D1, regrant-D2 y regrant-D8 se cruzan entre D1, D2
y D8 (los tres atacan `profiles` como `authenticated`); regrant-D7 pone rojo a
bug2_no_filtra (lee `memberships`); y `recursiva` (BUG-2) pone rojo a todo
ataque como `authenticated` sobre una tabla cuyas políticas consultan
`memberships`. Reportado como candidato a ERR.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from functools import partial
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select

import tests.seguridad.test_aceptacion as seg
import tests.seguridad.test_sin_acceso as catalogo
import tests.seguridad.veredictos as veredictos
from src.auth import router as auth_router
from src.auth import service as auth_service
from src.challenge_engine.service import attempts as attempts_mod
from src.challenge_engine.service import challenges as challenges_mod
from src.main import app
from src.shared import deps
from src.shared.models import Challenge, ChallengeAttempt
from tests.seguridad.modulos import INSERTS_MODULOS
from tests.seguridad.veredictos import sembrar

pytestmark = pytest.mark.integ

_QUESTION_TO_SCHEMA = challenges_mod.question_to_schema
_SUBMIT_ATTEMPT = attempts_mod.submit_attempt


# =============================================================================
# Versiones rotas (API)
# =============================================================================
def _perfil_con_hash(profile: Any, memberships: Any) -> Any:
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


def _stmt_reto_sin_tenant(challenge_id: UUID, tenant_id: UUID) -> Any:
    """A7: la barrera de tenant de fuente única (`stmt_reto_del_tenant`) sin el
    filtro de tenant (ESPEC_bug13a15 §1.3, errata ERR-26: el defecto sigue a la
    fuente única; antes se inyectaba en `get_challenge`)."""
    del tenant_id
    return select(Challenge).where(Challenge.id == challenge_id)


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


Aplicar = Callable[[Any, pytest.MonkeyPatch], AbstractContextManager]


@contextmanager
def _politica(integ: Any, tabla: str, nombre: str, cuerpo: str) -> Iterator[None]:
    sembrar(integ, f"create policy {nombre} on {tabla} {cuerpo}")
    try:
        yield
    finally:
        sembrar(integ, f"drop policy if exists {nombre} on {tabla}")


# Las ACL de `public` (relaciones y funciones) y todos los DEFAULT, como texto
# ordenado: sirve para comprobar que un tramposo dejó TODO como estaba.
_ACL = """
    select coalesce(string_agg(x, ';' order by x), '') from (
      select format('rel|%s|%s|%s|%s', c.relname, a.grantee, a.privilege_type,
                    a.is_grantable) as x
      from pg_class c join pg_namespace n on n.oid = c.relnamespace,
           lateral aclexplode(c.relacl) a
      where n.nspname = 'public'
      union all
      select format('proc|%s|%s|%s', p.oid::regprocedure, a.grantee, a.privilege_type)
      from pg_proc p join pg_namespace n on n.oid = p.pronamespace,
           lateral aclexplode(p.proacl) a
      where n.nspname = 'public'
      union all
      select format('def|%s|%s|%s|%s|%s', d.defaclrole, d.defaclnamespace,
                    d.defaclobjtype, a.grantee, a.privilege_type)
      from pg_default_acl d, lateral aclexplode(d.defaclacl) a
    ) as t
"""
_CLIENTES = "anon, authenticated"
_DEFAULT_TABLAS = "alter default privileges for role postgres in schema public {} all on tables "


@contextmanager
def _privilegios(integ: Any, romper: list[str], restaurar: list[str]) -> Iterator[None]:
    """Rompe los privilegios, y al salir los restaura y exige ACL idénticas."""
    antes = integ.valor(_ACL)
    for sql in romper:
        sembrar(integ, sql)
    try:
        yield
    finally:
        for sql in restaurar:
            sembrar(integ, sql)
        assert integ.valor(_ACL) == antes, "el tramposo no dejó las ACL como las dejó la 031"


def _grant(privilegio: str, tabla: str, roles: str) -> Aplicar:
    return lambda i, _mp: _privilegios(i, [f"grant {privilegio} on {tabla} to {roles}"],
                                       [f"revoke {privilegio} on {tabla} from {roles}"])


def _parche(objetivo: Any, nombre: str, valor: Any) -> Callable[..., AbstractContextManager]:
    def aplicar(_integ: Any, mp: pytest.MonkeyPatch) -> AbstractContextManager:
        mp.setattr(objetivo, nombre, valor)
        return nullcontext()
    return aplicar


# =============================================================================
# Registro: id -> (cómo romper, test real, mensaje con el que debe caer)
# =============================================================================
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
    "A7": (_parche(challenges_mod, "stmt_reto_del_tenant", _stmt_reto_sin_tenant),
           seg.test_a7_otro_colegio_no_se_ve, "200 == 404"),
    "D1": (_grant("select", "profiles", "authenticated"), seg.test_d1_anon_no_lee_ni_escribe,
           r"\[authenticated\] SELECT profiles: se esperaba 42501"),
    "D4": (_grant("insert", "coin_ledger", "authenticated"), seg.test_d4_nadie_escribe_el_ledger,
           r"\[authenticated\] alumno INSERT coin_ledger: se esperaba 42501"),
    "D10": (lambda i, _mp: _politica(i, "badges", "trampa_d10",
                                     "for select to authenticated using (true)"),
            seg.test_d10_ninguna_politica_abierta, "políticas abiertas: badges.trampa_d10"),
    "D12": (lambda i, _mp: _privilegios(
                i, ["create function public.trampa() returns int language sql as 'select 1'"],
                ["drop function public.trampa()"]),
            catalogo.test_d12_catalogo_sin_privilegios_de_clientes,
            r"ejecutables por clientes: trampa\(\)\(anon\)"),
    "D13": (lambda i, _mp: _privilegios(
                i, [_DEFAULT_TABLAS.format("grant") + "to " + _CLIENTES],
                [_DEFAULT_TABLAS.format("revoke") + "from " + _CLIENTES]),
            catalogo.test_d13_lo_nuevo_nace_cerrado,
            r"nace abierto para: \['anon_tabla', 'authenticated_tabla'\]"),
}

# regrant-X: la tabla que ataca X y su PRIMER ataque, que es el que debe caer:
# `anon` va primero y, con GRANT ALL, la RLS le da 0 filas o "new row violates
# row-level security policy"; ninguno es el 42501 que exige `sin_acceso`.
_REGRANT: dict[str, tuple[str, Callable[[Any], None], str]] = {
    "D2": ("profiles", seg.test_d2_pin_hash_ajeno_invisible,
           "admin de otro colegio lee pin_hash"),
    "D3": ("coin_wallets", seg.test_d3_alumno_no_edita_saldos, "alumno UPDATE wallet profile"),
    "D5": ("challenge_questions", seg.test_d5_alumno_no_lee_correct_answer,
           "alumno lee correct_answer"),
    "D6": ("challenge_attempts", seg.test_d6_alumno_no_inserta_intentos, "INSERT intento propio"),
    "D7": ("memberships", seg.test_d7_alumno_no_crea_membresia_admin,
           "alumno INSERT memberships admin"),
    "D8": ("profiles", seg.test_d8_alumno_no_edita_racha_xp_ni_rol,
           r"alumno UPDATE profiles\.current_streak"),
    "D9": ("attendance_sessions", seg.test_d9_alumno_no_crea_sesion_ni_marca_asistencia,
           "alumno INSERT attendance_sessions"),
    **{f"D11-{t}": (t, partial(seg.test_d11_alumno_no_escribe_tablas_de_modulos, tabla=t),
                    f"alumno INSERT {t}") for t in sorted(INSERTS_MODULOS)},
}
for _x, (_tabla, _test, _que) in _REGRANT.items():
    TRAMPOSOS[f"regrant-{_x}"] = (_grant("all", _tabla, _CLIENTES), _test,
                                  rf"\[anon\] {_que}: se esperaba 42501")


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    # El humo lo escribe la corrida real; un tramposo no debe ensuciarlo.
    monkeypatch.setattr(veredictos, "registrar_humo", lambda *_a, **_k: None)
    with aplicar(integ, monkeypatch), pytest.raises(AssertionError, match=motivo):
        test_real(integ)
