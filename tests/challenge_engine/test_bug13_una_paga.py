"""BUG-13: una sola paga por (reto, estudiante) — `docs/ESPEC_bug13a15.md` §1.1, §2, §3.

El hueco (ESPEC §0): `submit_attempt` paga si `is_correct` y hay cupo, sin
mirar si el estudiante ya cobró ese reto (`attempts.py:229`), y lee el intento
sin `FOR UPDATE`, así que dos envíos simultáneos del mismo intento ven los dos
`in_progress` y los dos pagan.

  A13-1  C1  en secuencia: la 2.ª victoria del mismo reto da 200 con 0 monedas y 0 XP.
  A13-2  C2  doble toque simultáneo del MISMO intento: exactamente [200, 409].
  A13-3  C3  dos intentos DISTINTOS en vuelo, a la vez: [200, 200] y una sola paga.
             Control: la barrera no se rompió (si se rompió, `PruebaRota`).
  S13    C9  identidad de la primera paga, byte a byte, contra el snapshot
             congelado en el commit 1 (`snapshot_bug13_primera_paga.json`).
  K1     C4  `award_coins` con llave: fila y luego None (en 2 transacciones y
             en una); la repetición con el banco en 0 da None, no 402.
  K2     C5  sin llave, idéntico a hoy: 2 llamadas, 2 filas, saldos x2.
  C13    C6  el UNIQUE en la BD: misma (tenant, llave) -> 23505; otro tenant
             y dos NULL entran.

A13-1..3 afirman por la API y cuentan filas del ledger por
`action = 'challenge' AND metadata->>'challenge_id'`: NUNCA nombran
`idempotency_key` (ESPEC §3). Por eso corrieron en el commit 1 (508d568),
sobre el código viejo, con `xfail(strict=True, raises=AssertionError)`: el
hueco se vio en rojo. Con la 033 y el código nuevo el xfail se quitó.

ERR-9: cada intento se siembra `in_progress` en la base (`crear_intento`), así
que cada A depende solo de `/submit`. Estudiantes con `saldo=0`: la billetera
ya existe y la concurrencia no choca con su creación perezosa.

Concurrencia (A13-2 y A13-3, ESPEC §3): `challenges_mod.get_questions` se
envuelve con una espera en `threading.Barrier(2, timeout=3)`; si la barrera se
rompe, la envoltura sigue. Los dos envíos van en 2 hilos, cada uno con su
propio `TestClient(app)` SIN `with` (portal y event loop por request): la
concurrencia es real. Con el código bueno, A13-2 cuesta unos 3 s: el primero
espera en la barrera hasta el timeout mientras el segundo está bloqueado en el
`FOR UPDATE` del intento.

Tramposos Y1-Y6: `tests/tramposos/test_tramposos_bug13.py`.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.challenge_engine.service import challenges as challenges_mod
from src.engrama_core.service import coins as coins_mod
from src.main import app
from src.shared.models import CoinLedger
from tests.integ import test_migracion_033 as mig
from tests.seguridad.veredictos import PruebaRota

pytestmark = pytest.mark.integ
client = TestClient(app)

RUTA_SNAPSHOT = Path(__file__).with_name("snapshot_bug13_primera_paga.json")
POOL = 1000
MONEDAS = 20
XP = 15
BARRERA_S = 3       # timeout de la barrera (ESPEC §3)
ESPERA_HILO_S = 60  # si un hilo no vuelve en este tiempo, el arnés está roto


# =============================================================================
# Siembra y llamadas
# =============================================================================
def _sembrar(integ: Any) -> tuple[UUID, UUID, UUID, list[UUID]]:
    """Tenant (pool 1000), docente, E con `saldo=0` y un reto ("A","B") de 20 y 15 XP."""
    tenant = integ.crear_tenant(pool=POOL)
    docente = integ.crear_perfil(tenant, rol="teacher")
    alumno = integ.crear_perfil(tenant, saldo=0)
    cid, qids = integ.crear_challenge(tenant, docente, respuestas=("A", "B"),
                                      coins=MONEDAS, xp=XP)
    return tenant, alumno, cid, qids


def _exigir(r: httpx.Response, status: int, que: str) -> None:
    """Arnés: otro status es `PruebaRota`, NO AssertionError.

    Así una siembra rota no se confunde con el hueco (ni con el xfail estricto
    del commit 1, ni con el `AssertionError` que exigen los tramposos).
    """
    if r.status_code != status:
        raise PruebaRota(f"{que}: se esperaba {status} y llegó {r.status_code}: {r.text}")


def _enviar(cliente: TestClient, integ: Any, alumno: UUID, intento: UUID,
            qids: list[UUID]) -> httpx.Response:
    """`/submit` con las dos respuestas correctas ("A", "B")."""
    cuerpo = {"answers": [{"question_id": str(q), "answer": a}
                          for q, a in zip(qids, ("A", "B"), strict=True)]}
    return cliente.post(f"/challenges/attempts/{intento}/submit", json=cuerpo,
                        headers=integ.headers(alumno))


def _filas_reto(integ: Any, cid: UUID) -> int:
    """Filas del ledger de ESTE reto, sin nombrar `idempotency_key` (ESPEC §3)."""
    return int(integ.valor(
        "select count(*) from coin_ledger "
        "where action = 'challenge' and metadata->>'challenge_id' = :r",
        r=str(cid),
    ))


def _a_la_vez(integ: Any, monkeypatch: pytest.MonkeyPatch, alumno: UUID,
              intentos: list[UUID], qids: list[UUID]
              ) -> tuple[list[httpx.Response], threading.Barrier, float]:
    """Dos `/submit` simultáneos, cada uno en su hilo y con su `TestClient`.

    La barrera va en `get_questions`, que `submit_attempt` llama DESPUÉS de
    leer el intento y ANTES de pagar (ESPEC §1.1, el orden no cambia). Si se
    rompe (timeout), la envoltura sigue: con el código bueno de A13-2 el otro
    envío está bloqueado en el `FOR UPDATE` y nunca llega. Devuelve las
    respuestas, la barrera (para el control de A13-3) y los segundos.
    """
    barrera = threading.Barrier(2, timeout=BARRERA_S)
    original = challenges_mod.get_questions

    async def con_barrera(db: Any, challenge_id: UUID) -> Any:
        try:
            barrera.wait()
        except threading.BrokenBarrierError:
            pass
        return await original(db, challenge_id)

    monkeypatch.setattr(challenges_mod, "get_questions", con_barrera)

    respuestas: list[httpx.Response | None] = [None] * len(intentos)
    errores: list[BaseException] = []

    def enviar(i: int, intento: UUID) -> None:
        try:
            respuestas[i] = _enviar(TestClient(app), integ, alumno, intento, qids)
        except BaseException as exc:  # noqa: BLE001 — se re-lanza en el hilo principal
            errores.append(exc)

    hilos = [threading.Thread(target=enviar, args=(i, a)) for i, a in enumerate(intentos)]
    inicio = time.monotonic()
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=ESPERA_HILO_S)
    segundos = round(time.monotonic() - inicio, 2)
    if any(h.is_alive() for h in hilos):
        raise PruebaRota(f"un envío no volvió en {ESPERA_HILO_S} s (¿bloqueo?)")
    if errores:
        raise errores[0]  # la excepción real del servidor, tal cual (ESPEC §3: "ex")
    listas = [r for r in respuestas if r is not None]
    if len(listas) != len(intentos):
        raise PruebaRota(f"faltan respuestas: {respuestas}")
    return listas, barrera, segundos


def _medir(integ: Any, rs: list[httpx.Response], barrera: threading.Barrier,
           segundos: float, tenant: UUID, alumno: UUID, cid: UUID) -> dict[str, Any]:
    """Los números crudos de una corrida concurrente (van en cada mensaje de assert)."""
    return {
        "estados": sorted(r.status_code for r in rs),
        "monedas": sorted(r.json().get("coins_earned", -1) for r in rs
                          if r.status_code == 200),
        "filas": _filas_reto(integ, cid),
        "saldo": integ.saldo("profile", alumno),
        "tenant": integ.saldo("tenant", tenant),
        "barrera_rota": barrera.broken,
        "segundos": segundos,
    }


# =============================================================================
# A13-1 — C1: en secuencia
# =============================================================================
def test_a13_1_segunda_victoria_del_mismo_reto_no_paga(integ) -> None:
    """E gana el intento 1 (20 y 15 XP) y gana un intento 2: 200 con 0 y 0, una fila."""
    tenant, alumno, cid, qids = _sembrar(integ)

    intento1 = integ.crear_intento(tenant, cid, alumno, status="in_progress")
    primero = _enviar(client, integ, alumno, intento1, qids)
    _exigir(primero, 200, "A13-1, 1.ª victoria")
    if (primero.json()["coins_earned"], primero.json()["xp_earned"]) != (MONEDAS, XP):
        raise PruebaRota(f"A13-1: la 1.ª victoria no pagó 20 y 15: {primero.text}")

    intento2 = integ.crear_intento(tenant, cid, alumno, status="in_progress")
    segundo = _enviar(client, integ, alumno, intento2, qids)
    assert segundo.status_code == 200, segundo.text
    body = segundo.json()
    assert body["is_correct"] is True, body
    assert (body["coins_earned"], body["xp_earned"]) == (0, 0), (
        f"la 2.ª victoria pagó {body['coins_earned']} monedas y {body['xp_earned']} XP"
    )

    assert _filas_reto(integ, cid) == 1, "más de una fila de paga para (reto, E)"
    assert integ.saldo("profile", alumno) == MONEDAS
    assert integ.saldo("tenant", tenant) == POOL - MONEDAS
    assert integ.valor("select xp from profiles where id = :p", p=alumno) == XP
    assert integ.valor(
        "select current_winners from challenges where id = :c", c=cid) == 1
    assert integ.fila(
        "select status, coins_earned from challenge_attempts where id = :a", a=intento2
    ) == {"status": "completed", "coins_earned": 0}


# =============================================================================
# A13-2 — C2: doble toque del mismo intento
# =============================================================================
def test_a13_2_doble_toque_del_mismo_intento(integ, monkeypatch) -> None:
    """Dos `/submit` simultáneos del MISMO intento: [200, 409], 20 monedas, una fila."""
    tenant, alumno, cid, qids = _sembrar(integ)
    intento = integ.crear_intento(tenant, cid, alumno, status="in_progress")

    rs, barrera, segundos = _a_la_vez(integ, monkeypatch, alumno, [intento, intento], qids)
    m = _medir(integ, rs, barrera, segundos, tenant, alumno, cid)

    assert m["estados"] == [200, 409], f"doble toque: {m}"
    assert m["monedas"] == [MONEDAS], f"el 200 no trae 20 monedas: {m}"
    assert m["filas"] == 1, f"doble toque: {m}"
    assert m["saldo"] == MONEDAS, f"doble toque: {m}"


# =============================================================================
# A13-3 — C3: dos intentos distintos en vuelo
# =============================================================================
def test_a13_3_dos_intentos_en_vuelo_pagan_una_vez(integ, monkeypatch) -> None:
    """Dos intentos `in_progress` del mismo E y reto, a la vez: [200, 200] y UNA paga."""
    tenant, alumno, cid, qids = _sembrar(integ)
    intento_a = integ.crear_intento(tenant, cid, alumno, status="in_progress")
    intento_b = integ.crear_intento(tenant, cid, alumno, status="in_progress")

    rs, barrera, segundos = _a_la_vez(integ, monkeypatch, alumno,
                                      [intento_a, intento_b], qids)
    m = _medir(integ, rs, barrera, segundos, tenant, alumno, cid)
    if barrera.broken:
        # Control: si la barrera se rompió, los dos no llegaron a la vez y el
        # test no midió la carrera que dice medir.
        raise PruebaRota(f"A13-3: la barrera se rompió, no hubo concurrencia: {m}")

    assert m["estados"] == [200, 200], f"dos intentos en vuelo: {m}"
    assert sum(m["monedas"]) == MONEDAS, f"dos intentos en vuelo cobran de más: {m}"
    assert m["filas"] == 1, f"dos intentos en vuelo: {m}"
    assert m["saldo"] == MONEDAS, f"dos intentos en vuelo: {m}"


# =============================================================================
# S13 — C9: identidad de la primera paga
# =============================================================================
def capturar_s13(integ: Any) -> dict[str, Any]:
    """Primera victoria por `/submit`: respuesta cruda, filas del ledger y saldos.

    Ids normalizados por posición (ESPEC §2, C9): el intento es `I1` y las
    preguntas `Q1`, `Q2` en su orden. Del ledger, `amount`, `action` y las
    claves de `metadata` (sus valores son ids); NO selecciona `idempotency_key`.
    """
    tenant, alumno, cid, qids = _sembrar(integ)
    intento = integ.crear_intento(tenant, cid, alumno, status="in_progress")
    r = _enviar(client, integ, alumno, intento, qids)
    _exigir(r, 200, "S13, primera victoria")

    texto = r.text.replace(str(intento), "I1")
    for i, q in enumerate(qids, start=1):
        texto = texto.replace(str(q), f"Q{i}")

    ledger = json.loads(integ.valor(
        "select coalesce(json_agg(json_build_object("
        "  'amount', l.amount, 'action', l.action,"
        "  'metadata_claves', (select json_agg(k order by k)"
        "                        from jsonb_object_keys(l.metadata) k))"
        "  order by l.created_at, l.id), '[]')::text "
        "from coin_ledger l"
    ))
    return {
        "respuesta": texto,
        "ledger": ledger,
        "saldos": {"estudiante": integ.saldo("profile", alumno),
                   "tenant": integ.saldo("tenant", tenant)},
    }


def test_s13_primera_paga_identica_al_snapshot(integ) -> None:
    """S13 (C9): la primera victoria, byte a byte, contra `snapshot_bug13_primera_paga.json`."""
    congelado = json.loads(RUTA_SNAPSHOT.read_text(encoding="utf-8"))
    actual = capturar_s13(integ)
    assert actual["respuesta"] == congelado["respuesta"], "la respuesta de /submit cambió"
    assert actual["ledger"] == congelado["ledger"], "la fila del ledger cambió"
    assert actual["saldos"] == congelado["saldos"], "los saldos cambiaron"


# =============================================================================
# K1, K2 — `award_coins` con y sin llave (C4, C5)
# =============================================================================
def _pagar(integ: Any, tenant: UUID, alumno: UUID, *, llave: str | None,
           veces: int = 1) -> list[Any]:
    """`veces` llamadas a `award_coins` (20) en UNA transacción, con commit.

    Devuelve lo que devolvió cada llamada; una HTTPException (p. ej. el 402)
    se guarda en la lista en vez de subir, para afirmarla con `assert`.
    Se llama por `coins_mod.award_coins`: es el punto que parchean Y1 e Y4.
    """
    async def _q() -> list[Any]:
        salida: list[Any] = []
        async with integ.sesion() as db:
            for _ in range(veces):
                try:
                    salida.append(await coins_mod.award_coins(
                        db, student_id=alumno, tenant_id=tenant, amount=MONEDAS,
                        action="challenge", metadata={}, idempotency_key=llave))
                except HTTPException as exc:
                    salida.append(exc)
            await db.commit()
        return salida

    return list(integ.run(_q()))


def _con_llave(integ: Any, llave: str) -> int:
    return int(integ.valor(
        "select count(*) from coin_ledger where idempotency_key = :k", k=llave))


def _es_fila(x: Any) -> bool:
    return isinstance(x, CoinLedger)


def test_k1_award_coins_con_llave_es_idempotente(integ) -> None:
    """Misma llave: fila y luego None (2 transacciones o una); con el banco en 0, None."""
    tenant = integ.crear_tenant(pool=POOL)
    e_a = integ.crear_perfil(tenant, saldo=0)
    e_b = integ.crear_perfil(tenant, saldo=0)

    primera = _pagar(integ, tenant, e_a, llave="k1:a")
    segunda = _pagar(integ, tenant, e_a, llave="k1:a")
    assert _es_fila(primera[0]), f"la primera paga con llave no devolvió la fila: {primera}"
    assert segunda == [None], f"la misma llave en otra transacción pagó otra vez: {segunda}"
    assert _con_llave(integ, "k1:a") == 1
    assert integ.saldo("profile", e_a) == MONEDAS, "los saldos se movieron dos veces"

    misma_tx = _pagar(integ, tenant, e_b, llave="k1:b", veces=2)
    assert _es_fila(misma_tx[0]) and misma_tx[1] is None, (
        f"la misma llave dos veces en una transacción: {misma_tx}")
    assert _con_llave(integ, "k1:b") == 1
    assert integ.saldo("profile", e_b) == MONEDAS
    assert integ.saldo("tenant", tenant) == POOL - 2 * MONEDAS

    # El banco queda en 0 tras la primera paga: repetirla NO es "falta de fondos".
    tenant0 = integ.crear_tenant(pool=MONEDAS)
    e_c = integ.crear_perfil(tenant0, saldo=0)
    assert _es_fila(_pagar(integ, tenant0, e_c, llave="k1:c")[0])
    assert integ.saldo("tenant", tenant0) == 0
    repetida = _pagar(integ, tenant0, e_c, llave="k1:c")
    assert repetida == [None], f"la repetición con el banco en 0 no dio None: {repetida}"
    assert integ.saldo("profile", e_c) == MONEDAS


def test_k2_sin_llave_paga_cada_vez(integ) -> None:
    """Sin llave, idéntico a hoy: dos llamadas, dos filas, saldos movidos dos veces."""
    tenant = integ.crear_tenant(pool=POOL)
    alumno = integ.crear_perfil(tenant, saldo=0)

    pagos = _pagar(integ, tenant, alumno, llave=None) + _pagar(integ, tenant, alumno, llave=None)
    assert all(_es_fila(p) for p in pagos), f"sin llave, una paga no devolvió su fila: {pagos}"
    assert integ.valor("select count(*) from coin_ledger") == 2, "sin llave se deduplicó"
    assert integ.saldo("profile", alumno) == 2 * MONEDAS
    assert integ.saldo("tenant", tenant) == POOL - 2 * MONEDAS


# =============================================================================
# C13 — el UNIQUE en la BD (C6)
# =============================================================================
def test_c13_unique_de_la_llave_en_la_bd(integ) -> None:
    """Misma (tenant, llave) -> 23505 con el nombre del UNIQUE; otro tenant y dos NULL entran."""
    async def cuerpo(conn: asyncpg.Connection) -> None:
        ta, tb = await mig.tenant_crudo(conn), await mig.tenant_crudo(conn)

        async def insertar(tenant: UUID, llave: str | None) -> str | None:
            """INSERT en su SAVEPOINT; devuelve 'SQLSTATE mensaje' o None si entró."""
            try:
                async with conn.transaction():
                    await conn.execute(
                        "insert into coin_ledger (tenant_id, amount, action, idempotency_key) "
                        "values ($1, 20, 'challenge', $2)", tenant, llave)
            except asyncpg.PostgresError as e:
                return f"{e.sqlstate} {e}"
            return None

        assert await insertar(ta, "c13") is None, "la primera fila con llave no entró"
        choque = await insertar(ta, "c13")
        assert choque is not None and choque.startswith("23505") and mig.UNIQUE in choque, (
            f"dos filas con la misma (tenant, llave) entraron o fallaron por otra cosa: {choque}")
        assert await insertar(tb, "c13") is None, "la misma llave en otro tenant no entró"
        assert await insertar(ta, None) is None, "una fila sin llave no entró"
        assert await insertar(ta, None) is None, "dos filas sin llave chocaron"

    mig.en_transaccion(integ, cuerpo)
