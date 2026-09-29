"""R1-R3 — réplica de BUG-13, 14 y 15 — `docs/ESPEC_bug13a15.md` §5.

Entradas que no se usaron al desarrollar. Solo corren con la bandera
`ENGRAMA_REPLICA_BUG13A15=1`; sin ella se saltan (3 skipped).

  R1  10 envíos simultáneos del mismo intento (10 hilos, sin barrera): un 200
      con 20 monedas y nueve 409, 1 fila y saldo 20. Además, 5 estudiantes
      ganan 3 intentos cada uno por la API: 5 filas y 20 monedas cada uno.
  R2  E marca en G1 y abre el reto de G1. Se le cambia el `group_code` a G2
      EN LA BASE (no hay ruta para mover estudiantes; se declara así).
      Después: sesión nueva de G1 -> 404, reto de G1 -> 404, reto de G2 -> 200
      y sesión de G2 -> 200.
  R3  códigos iguales en dos colegios: P tiene membresía en A (G1) y en B (G1).
      Con `X-Tenant-ID: B`, la sesión y el reto de A-G1 -> 404; con A -> 200.
      Una membresía con `group_code = "g1"` (minúscula) frente al grupo `G1`
      -> 404 en los dos: la comparación es exacta y falla cerrada.
"""
from __future__ import annotations

import os
import threading
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.main import app
from src.shared.models import Membership
from tests.challenge_engine import test_bug13_una_paga as b13
from tests.seguridad.veredictos import PruebaRota

REPLICA = os.environ.get("ENGRAMA_REPLICA_BUG13A15") == "1"
pytestmark = [
    pytest.mark.integ,
    pytest.mark.skipif(not REPLICA, reason="réplica de BUG-13a15: ENGRAMA_REPLICA_BUG13A15=1"),
]
client = TestClient(app)


def _sql(integ: Any, sql: str, **params: Any) -> None:
    async def _q() -> None:
        async with integ.engine.begin() as conn:
            await conn.execute(text(sql), params)

    integ.run(_q())


def _marcar(integ: Any, perfil: UUID, codigo: str,
            tenant: UUID | None = None) -> httpx.Response:
    h = integ.headers(perfil)
    if tenant is not None:
        h = {**h, "X-Tenant-ID": str(tenant)}
    return client.post("/core/attendance/check-in", json={"session_code": codigo}, headers=h)


def _abrir(integ: Any, perfil: UUID, reto: UUID, tenant: UUID | None = None) -> int:
    h = integ.headers(perfil)
    if tenant is not None:
        h = {**h, "X-Tenant-ID": str(tenant)}
    return client.get(f"/challenges/{reto}", headers=h).status_code


# =============================================================================
# R1 — 10 envíos simultáneos y 5 estudiantes con 3 victorias
# =============================================================================
def test_r1_diez_envios_simultaneos_y_tres_victorias(integ) -> None:
    tenant, alumno, cid, qids = b13._sembrar(integ)
    intento = integ.crear_intento(tenant, cid, alumno, status="in_progress")

    respuestas: list[httpx.Response] = []
    errores: list[BaseException] = []
    candado = threading.Lock()

    def enviar() -> None:
        try:
            r = b13._enviar(TestClient(app), integ, alumno, intento, qids)
            with candado:
                respuestas.append(r)
        except BaseException as exc:  # noqa: BLE001 — se re-lanza en el hilo principal
            errores.append(exc)

    hilos = [threading.Thread(target=enviar) for _ in range(10)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=b13.ESPERA_HILO_S)
    if any(h.is_alive() for h in hilos):
        raise PruebaRota("R1: un envío no volvió a tiempo")
    if errores:
        raise errores[0]
    estados = sorted(r.status_code for r in respuestas)
    assert estados == [200] + [409] * 9, f"R1: {estados}"
    assert [r.json()["coins_earned"] for r in respuestas if r.status_code == 200] == [20]
    assert b13._filas_reto(integ, cid) == 1
    assert integ.saldo("profile", alumno) == 20

    # 5 estudiantes, 3 victorias cada uno por la API, en un reto de 3 intentos.
    docente = integ.crear_perfil(tenant, rol="teacher")
    reto, preguntas = integ.crear_challenge(tenant, docente, respuestas=("A", "B"),
                                            max_attempts=3)
    for _ in range(5):
        e = integ.crear_perfil(tenant, saldo=0)
        monedas = []
        for _vez in range(3):
            inicio = client.post(f"/challenges/{reto}/attempt", headers=integ.headers(e))
            b13._exigir(inicio, 201, "R1, arrancar")
            r = b13._enviar(client, integ, e, UUID(inicio.json()["attempt_id"]), preguntas)
            b13._exigir(r, 200, "R1, enviar")
            monedas.append(r.json()["coins_earned"])
        assert monedas == [20, 0, 0], f"R1: {monedas}"
        assert integ.saldo("profile", e) == 20
    assert b13._filas_reto(integ, reto) == 5


# =============================================================================
# R2 — el estudiante cambia de grupo (en la base)
# =============================================================================
def test_r2_cambio_de_grupo_en_la_base(integ) -> None:
    tenant = integ.crear_tenant()
    g1, g2 = integ.crear_grupo(tenant, "G1"), integ.crear_grupo(tenant, "G2")
    docente = integ.crear_perfil(tenant, rol="teacher")
    e = integ.crear_perfil(tenant, group_code="G1")
    reto_g1, _ = integ.crear_challenge(tenant, docente, group_id=g1)
    reto_g2, _ = integ.crear_challenge(tenant, docente, group_id=g2)

    assert _marcar(integ, e, integ.crear_sesion_asistencia(tenant, g1, docente)).status_code \
        == 200
    assert _abrir(integ, e, reto_g1) == 200

    # No hay ruta para mover estudiantes de grupo: se cambia en la base.
    _sql(integ, "update memberships set group_code = 'G2' "
                "where tenant_id = :t and profile_id = :p", t=tenant, p=e)

    assert _marcar(integ, e, integ.crear_sesion_asistencia(tenant, g1, docente)).status_code \
        == 404, "R2: tras el cambio, una sesión nueva de G1 no da 404"
    assert _abrir(integ, e, reto_g1) == 404, "R2: tras el cambio, el reto de G1 no da 404"
    assert _abrir(integ, e, reto_g2) == 200, "R2: tras el cambio, el reto de G2 no da 200"
    assert _marcar(integ, e, integ.crear_sesion_asistencia(tenant, g2, docente)).status_code \
        == 200, "R2: tras el cambio, la sesión de G2 no da 200"


# =============================================================================
# R3 — códigos de grupo iguales en dos colegios; mayúsculas
# =============================================================================
def test_r3_mismo_codigo_en_dos_colegios_y_mayusculas(integ) -> None:
    ta, tb = integ.crear_tenant(), integ.crear_tenant()
    ga = integ.crear_grupo(ta, "G1")
    integ.crear_grupo(tb, "G1")
    docente = integ.crear_perfil(ta, rol="teacher")
    p = integ.crear_perfil(ta, group_code="G1")
    integ._insertar(Membership(tenant_id=tb, profile_id=p, role="student", group_code="G1",
                               is_active=True, full_name="Persona R3 en B"))
    reto_a, _ = integ.crear_challenge(ta, docente, group_id=ga)
    codigo = integ.crear_sesion_asistencia(ta, ga, docente)

    assert _marcar(integ, p, codigo, tenant=tb).status_code == 404, "R3: sesión de A desde B"
    assert _abrir(integ, p, reto_a, tenant=tb) == 404, "R3: reto de A desde B"
    assert _marcar(integ, p, codigo, tenant=ta).status_code == 200, "R3: sesión de A desde A"
    assert _abrir(integ, p, reto_a, tenant=ta) == 200, "R3: reto de A desde A"

    minuscula = integ.crear_perfil(ta, group_code="g1")
    assert _marcar(integ, minuscula, codigo).status_code == 404, "R3: 'g1' marcó en 'G1'"
    assert _abrir(integ, minuscula, reto_a) == 404, "R3: 'g1' abrió el reto de 'G1'"
