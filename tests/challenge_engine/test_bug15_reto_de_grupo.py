"""BUG-15: detalle y arranque de un reto solo si es del grupo del estudiante — ESPEC §1.3.

`docs/ESPEC_bug13a15.md`. El hueco (ESPEC §0): `GET /challenges/{id}` y
`POST /challenges/{id}/attempt` pasan por `get_challenge`, que filtra solo por
`tenant_id` (`service/challenges.py:185-198`). El filtro de grupo existe solo
en el feed. Así E1 (G1) abre y arranca el reto de G2 por su id.

  A15-1  C14  E1 `GET` del reto de G2 -> 404 con cuerpo idéntico al de un UUID
              inexistente; E0 (sin grupo) `GET` del reto de G1 -> 404.
  A15-2  C15  E1 `POST .../attempt` del reto de G2 -> 404, mismo cuerpo, y 0
              filas en `challenge_attempts`.
  S15    C16  controles, verdes antes y después: E1 abre el de G1 y el global y
              arranca el de G1; E0 abre el global; un docente sin asignación y
              un admin abren el de G2 (el personal no cambia); otro colegio -> 404.

A15-1 y A15-2 afirman por la API: corren en el commit 1, sobre el código
viejo, con `xfail(strict=True, raises=AssertionError)`. La referencia que no
da 404 es `PruebaRota`, no AssertionError.
"""
from __future__ import annotations

from typing import Any, NamedTuple
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.seguridad.veredictos import PruebaRota

pytestmark = pytest.mark.integ
client = TestClient(app)

XFAIL_BUG15 = pytest.mark.xfail(strict=True, raises=AssertionError, reason="BUG-15")


class Escena(NamedTuple):
    tenant: UUID
    docente: UUID    # teacher SIN filas en teacher_groups
    admin: UUID
    e1: UUID         # estudiante de G1
    e0: UUID         # estudiante sin group_code
    ajeno: UUID      # estudiante de G1 en OTRO colegio
    r_global: UUID
    r_g1: UUID
    r_g2: UUID


def _sembrar(integ: Any) -> Escena:
    """G1 y G2; retos global, de G1 y de G2; E1, E0, docente, admin y un ajeno."""
    tenant = integ.crear_tenant()
    g1 = integ.crear_grupo(tenant, "G1")
    g2 = integ.crear_grupo(tenant, "G2")
    autor = integ.crear_perfil(tenant, rol="teacher")  # solo crea los retos
    docente = integ.crear_perfil(tenant, rol="teacher")
    admin = integ.crear_perfil(tenant, rol="admin")
    e1 = integ.crear_perfil(tenant, group_code="G1")
    e0 = integ.crear_perfil(tenant)
    r_global, _ = integ.crear_challenge(tenant, autor)
    r_g1, _ = integ.crear_challenge(tenant, autor, group_id=g1)
    r_g2, _ = integ.crear_challenge(tenant, autor, group_id=g2)

    # Otro colegio con un grupo que se llama igual (G1): la única barrera que
    # lo para es el `tenant_id` de la consulta (ESPEC §3).
    tenant_b = integ.crear_tenant()
    integ.crear_grupo(tenant_b, "G1")
    ajeno = integ.crear_perfil(tenant_b, group_code="G1")
    return Escena(tenant, docente, admin, e1, e0, ajeno, r_global, r_g1, r_g2)


def _abrir(integ: Any, perfil: UUID, reto: UUID) -> httpx.Response:
    return client.get(f"/challenges/{reto}", headers=integ.headers(perfil))


def _arrancar(integ: Any, perfil: UUID, reto: UUID) -> httpx.Response:
    return client.post(f"/challenges/{reto}/attempt", headers=integ.headers(perfil))


def _referencia(r: httpx.Response, que: str) -> bytes:
    """El 404 de un UUID inexistente; si no es 404, el arnés está roto."""
    if r.status_code != 404:
        raise PruebaRota(f"referencia {que}: el UUID inexistente dio {r.status_code}: {r.text}")
    return r.content


# =============================================================================
# A15-1 — C14: detalle de un reto de otro grupo
# =============================================================================
@XFAIL_BUG15
def test_a15_1_detalle_de_reto_de_otro_grupo_da_404(integ) -> None:
    """E1 (G1) abre el reto de G2 -> 404 idéntico; E0 abre el de G1 -> 404."""
    esc = _sembrar(integ)
    ref = _referencia(_abrir(integ, esc.e1, uuid4()), "GET")

    r = _abrir(integ, esc.e1, esc.r_g2)
    assert r.status_code == 404, f"E1 abrió el reto de G2: {r.status_code}"
    assert r.content == ref, f"el 404 delata el reto: {r.content!r} != {ref!r}"

    r0 = _abrir(integ, esc.e0, esc.r_g1)
    assert r0.status_code == 404, f"E0 (sin grupo) abrió el reto de G1: {r0.status_code}"
    assert r0.content == ref, f"cuerpo distinto: {r0.content!r} != {ref!r}"


# =============================================================================
# A15-2 — C15: arranque de un reto de otro grupo
# =============================================================================
@XFAIL_BUG15
def test_a15_2_arrancar_reto_de_otro_grupo_da_404(integ) -> None:
    """E1 arranca el reto de G2 -> 404, mismo cuerpo, y ningún intento en la base."""
    esc = _sembrar(integ)
    ref = _referencia(_arrancar(integ, esc.e1, uuid4()), "POST")

    r = _arrancar(integ, esc.e1, esc.r_g2)
    assert r.status_code == 404, f"E1 arrancó el reto de G2: {r.status_code}"
    assert r.content == ref, f"el 404 delata el reto: {r.content!r} != {ref!r}"
    assert integ.valor("select count(*) from challenge_attempts") == 0, "quedó un intento"


# =============================================================================
# S15 — C16: controles (verdes antes y después)
# =============================================================================
def test_s15_controles_de_retos(integ) -> None:
    """Lo visible sigue visible; el personal no cambia; otro colegio no ve nada."""
    esc = _sembrar(integ)

    assert _abrir(integ, esc.e1, esc.r_g1).status_code == 200, "E1 no abre el de G1"
    assert _abrir(integ, esc.e1, esc.r_global).status_code == 200, "E1 no abre el global"
    assert _abrir(integ, esc.e0, esc.r_global).status_code == 200, "E0 no abre el global"
    assert _abrir(integ, esc.docente, esc.r_g2).status_code == 200, "el docente no abre G2"
    assert _abrir(integ, esc.admin, esc.r_g2).status_code == 200, "el admin no abre G2"
    assert _abrir(integ, esc.ajeno, esc.r_g1).status_code == 404, "otro colegio abre G1"
    assert _abrir(integ, esc.ajeno, esc.r_global).status_code == 404, "otro colegio abre el global"

    r = _arrancar(integ, esc.e1, esc.r_g1)
    assert r.status_code == 201, r.text
    assert r.json()["challenge"]["id"] == str(esc.r_g1)
