"""BUG-14: el check-in exige ser estudiante del grupo de la sesión — `docs/ESPEC_bug13a15.md` §1.2.

El hueco (ESPEC §0): `check_in` busca la sesión solo por `session_code` +
`tenant_id` (`attendance.py:234-244`), y la ruta no tiene guarda de rol. Así
un estudiante de otro grupo que recibe el código marca y cobra, una sesión
expirada de otro grupo le responde 410 (se entera de que el código existe) y
un docente también marca y cobra.

  A14-1  C10  E2 (G2) con el código de una sesión activa de G1 -> 404, cuerpo
              idéntico al de un código inexistente; nada se mueve.
  A14-2  C11  la sesión EXPIRADA de G1, con E2 -> 404 (hoy 410), mismo cuerpo.
  A14-3  C12  un docente con `group_code = G1` en la sesión de G1 -> 404; un
              estudiante sin `group_code` -> 404; mismo cuerpo.
  S14    C13  controles, verdes antes y después: E1 (G1) en G1 -> 200, 5 y
              racha 1; código inexistente -> 404; otro colegio -> 404.

A14-1..3 afirman por la API: por eso corrieron en el commit 1 (508d568),
sobre el código viejo, con `xfail(strict=True, raises=AssertionError)`, y el
hueco se vio en rojo. Con `_buscar_sesion` (filtro de grupo y rol) el xfail
se quitó. El cuerpo de referencia sale, en el mismo test, de un check-in con
un código inexistente. La siembra que no da lo esperado es `PruebaRota`, no
AssertionError.

Tramposos Y7, Y8, Y9 e Y14: `tests/tramposos/test_tramposos_bug14.py`.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.seguridad.veredictos import PruebaRota

pytestmark = pytest.mark.integ
client = TestClient(app)

POOL = 1000
CODIGO_INEXISTENTE = "NOEXST"
RACHA_E2 = 3  # racha sembrada de E2: un check-in rechazado no debe tocarla


class Escena(NamedTuple):
    tenant: UUID
    g1: UUID
    g2: UUID
    docente: UUID  # rol teacher con group_code = G1 (como `_escenario` de test_attendance)
    e1: UUID       # estudiante de G1
    e2: UUID       # estudiante de G2, con racha 3 y última asistencia ayer
    e0: UUID       # estudiante sin group_code


def _sembrar(integ: Any) -> Escena:
    """Tenant (pool 1000), G1 y G2, docente T (G1), E1 (G1), E2 (G2) y E0 (sin grupo)."""
    tenant = integ.crear_tenant(pool=POOL)
    g1 = integ.crear_grupo(tenant, "G1")
    g2 = integ.crear_grupo(tenant, "G2")
    docente = integ.crear_perfil(tenant, rol="teacher", group_code="G1")
    e1 = integ.crear_perfil(tenant, group_code="G1")
    ayer = datetime.now(UTC).date() - timedelta(days=1)
    e2 = integ.crear_perfil(tenant, group_code="G2", racha=RACHA_E2, ultima_asistencia=ayer)
    e0 = integ.crear_perfil(tenant)
    return Escena(tenant, g1, g2, docente, e1, e2, e0)


def _marcar(integ: Any, perfil: UUID, codigo: str) -> httpx.Response:
    return client.post("/core/attendance/check-in", json={"session_code": codigo},
                       headers=integ.headers(perfil))


def _referencia(integ: Any, perfil: UUID) -> bytes:
    """Cuerpo del 404 de un código inexistente, con el mismo actor (ESPEC §3)."""
    r = _marcar(integ, perfil, CODIGO_INEXISTENTE)
    if r.status_code != 404:
        raise PruebaRota(f"referencia: el código inexistente dio {r.status_code}: {r.text}")
    return r.content


def _racha(integ: Any, perfil: UUID) -> dict[str, Any] | None:
    return integ.fila(
        "select current_streak, longest_streak, last_attendance_date "
        "from profiles where id = :p", p=perfil,
    )


def _nada_se_movio(integ: Any, esc: Escena) -> None:
    assert integ.valor("select count(*) from attendance") == 0, "quedó una asistencia"
    assert integ.valor("select count(*) from coin_ledger") == 0, "quedó una fila en el ledger"
    assert integ.saldo("tenant", esc.tenant) == POOL, "el pool del tenant se movió"


# =============================================================================
# A14-1 — C10: sesión activa de otro grupo
# =============================================================================
def test_a14_1_checkin_de_otro_grupo_da_404(integ) -> None:
    """E2 (G2) con el código de una sesión activa de G1: 404 idéntico, nada se mueve."""
    esc = _sembrar(integ)
    codigo = integ.crear_sesion_asistencia(esc.tenant, esc.g1, esc.docente)
    ref = _referencia(integ, esc.e2)
    racha_antes = _racha(integ, esc.e2)

    r = _marcar(integ, esc.e2, codigo)
    assert r.status_code == 404, f"E2 marcó en G1: {r.status_code} {r.text}"
    assert r.content == ref, f"el 404 delata la sesión: {r.content!r} != {ref!r}"
    _nada_se_movio(integ, esc)
    assert _racha(integ, esc.e2) == racha_antes, "la racha de E2 cambió"


# =============================================================================
# A14-2 — C11: sesión expirada de otro grupo
# =============================================================================
def test_a14_2_sesion_expirada_de_otro_grupo_no_delata_que_existe(integ) -> None:
    """La sesión EXPIRADA de G1, con E2: 404 (hoy 410), con el mismo cuerpo."""
    esc = _sembrar(integ)
    codigo = integ.crear_sesion_asistencia(esc.tenant, esc.g1, esc.docente,
                                           expira_en=timedelta(minutes=-1))
    ref = _referencia(integ, esc.e2)

    r = _marcar(integ, esc.e2, codigo)
    assert r.status_code == 404, f"la sesión expirada de G1 se delata: {r.status_code} {r.text}"
    assert r.content == ref, f"cuerpo distinto: {r.content!r} != {ref!r}"


# =============================================================================
# A14-3 — C12: solo estudiantes con grupo
# =============================================================================
def test_a14_3_solo_estudiantes_del_grupo_marcan(integ) -> None:
    """Docente con `group_code = G1` en la sesión de G1 -> 404; E0 (sin grupo) -> 404."""
    esc = _sembrar(integ)
    codigo = integ.crear_sesion_asistencia(esc.tenant, esc.g1, esc.docente)

    ref_docente = _referencia(integ, esc.docente)
    r = _marcar(integ, esc.docente, codigo)
    assert r.status_code == 404, f"el docente marcó: {r.status_code} {r.text}"
    assert r.content == ref_docente, f"cuerpo distinto: {r.content!r} != {ref_docente!r}"

    ref_e0 = _referencia(integ, esc.e0)
    r0 = _marcar(integ, esc.e0, codigo)
    assert r0.status_code == 404, f"E0 (sin grupo) marcó: {r0.status_code} {r0.text}"
    assert r0.content == ref_e0, f"cuerpo distinto: {r0.content!r} != {ref_e0!r}"


# =============================================================================
# S14 — C13: controles (verdes antes y después)
# =============================================================================
def test_s14_controles_del_checkin(integ) -> None:
    """E1 en G1 -> 200, 5, racha 1. Código inexistente -> 404. Otro colegio -> 404."""
    esc = _sembrar(integ)
    codigo = integ.crear_sesion_asistencia(esc.tenant, esc.g1, esc.docente)

    # Otro colegio con un grupo que se llama igual (G1) y un estudiante de ese
    # G1: la única barrera que lo para es el `tenant_id` de la consulta.
    tenant_b = integ.crear_tenant(pool=POOL)
    integ.crear_grupo(tenant_b, "G1")
    ajeno = integ.crear_perfil(tenant_b, group_code="G1")

    assert _marcar(integ, esc.e1, CODIGO_INEXISTENTE).status_code == 404
    assert _marcar(integ, ajeno, codigo).status_code == 404, "otro colegio marcó"

    r = _marcar(integ, esc.e1, codigo)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["coins_awarded"], body["streak"]) == (5, 1), body
    assert integ.saldo("profile", esc.e1) == 5
    assert integ.saldo("tenant", esc.tenant) == POOL - 5
    assert integ.valor("select count(*) from attendance") == 1
