"""La asistencia paga 5 + 5 por puntualidad — `docs/ESPEC_economia_oleada0.md` §1.1 a §1.3.

  EA1  C2  check-in puntual: 200, 10 monedas; el asiento lleva base, puntualidad y puntual
  EA2  C3  a los 5:00 paga 10; a los 5:01 paga 5 (`puntualidad: 0`)
  EA3  C4  los números son configuración: con 4 + 3 y 10 minutos paga 7 y 4
  ER1  C7  la segunda sesión del mismo día NO cambia la racha
  ER2  C8  el día es el de la institución (Bogotá), no el UTC
  ED1  C9  una segunda sesión del día se registra con 0 monedas (un pago por día)
  ED2  C10 el día de la paga es el local
  ED3  C11 dos check-ins a la vez a dos sesiones del día: una sola paga

El reloj se fija con la costura `attendance._ahora`; la sesión se abre con
`crear_sesion_asistencia(inicio=...)`. Los tramposos:
`tests/tramposos/test_tramposos_economia.py`.
"""
from __future__ import annotations

import threading
from datetime import UTC, date, datetime, timedelta
from typing import Any, NamedTuple
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.engrama_core.service import attendance as attendance_mod
from src.main import app
from src.shared.config import settings
from tests.seguridad.veredictos import PruebaRota

pytestmark = pytest.mark.integ
client = TestClient(app)

POOL = 1000
INICIO = datetime(2026, 10, 6, 23, 0, tzinfo=UTC)  # las 18:00 de Bogotá


def fijar_ahora(mp: pytest.MonkeyPatch, instante: datetime) -> None:
    """El reloj de la asistencia (`attendance._ahora`) marca `instante`."""
    mp.setattr(attendance_mod, "_ahora", lambda: instante)


class Escena(NamedTuple):
    tenant: UUID
    grupo: UUID
    docente: UUID
    alumnos: list[UUID]


def armar(integ: Any, *, estudiantes: int = 1, racha: int = 0,
          ultima: date | None = None) -> Escena:
    """Colegio (pool 1000), grupo G1, su docente y `estudiantes` alumnos de G1."""
    tenant = integ.crear_tenant(pool=POOL)
    grupo = integ.crear_grupo(tenant, "G1")
    docente = integ.crear_perfil(tenant, rol="teacher", group_code="G1")
    alumnos = [integ.crear_perfil(tenant, group_code="G1", racha=racha, ultima_asistencia=ultima)
               for _ in range(estudiantes)]
    return Escena(tenant, grupo, docente, alumnos)


def abrir(integ: Any, esc: Escena, inicio: datetime = INICIO,
          expira_en: timedelta = timedelta(minutes=15)) -> str:
    """Abre una sesión de G1 a las `inicio`; devuelve su código."""
    return integ.crear_sesion_asistencia(esc.tenant, esc.grupo, esc.docente,
                                         inicio=inicio, expira_en=expira_en)


def marcar_con(cliente: TestClient, integ: Any, alumno: UUID, codigo: str) -> Any:
    return cliente.post("/core/attendance/check-in", json={"session_code": codigo},
                        headers=integ.headers(alumno))


def marcar(integ: Any, alumno: UUID, codigo: str) -> Any:
    return marcar_con(client, integ, alumno, codigo)


def asientos(integ: Any, alumno: UUID) -> list[dict[str, Any]]:
    """Los asientos 'attendance' del libro cuyo destino es la billetera del estudiante."""
    async def _q() -> list[dict[str, Any]]:
        from sqlalchemy import text
        async with integ.Session() as db:
            filas = (await db.execute(text(
                "select l.amount, l.metadata, l.from_wallet_id, l.idempotency_key "
                "from coin_ledger l join coin_wallets w on w.id = l.to_wallet_id "
                "where l.action = 'attendance' and w.owner_id = :p order by l.created_at"),
                {"p": alumno})).mappings().all()
            return [dict(f) for f in filas]
    return integ.run(_q())  # type: ignore[no-any-return]


def estado_racha(integ: Any, alumno: UUID) -> dict[str, Any]:
    fila = integ.fila("select current_streak, longest_streak, last_attendance_date "
                      "from profiles where id = :p", p=alumno)
    assert fila is not None
    return fila


# =============================================================================
# EA1 — C2: check-in puntual
# =============================================================================
def test_ea1_checkin_puntual_paga_10(integ, monkeypatch) -> None:
    esc = armar(integ)
    (alumno,), codigo = esc.alumnos, abrir(integ, esc)
    fijar_ahora(monkeypatch, INICIO + timedelta(minutes=2))

    r = marcar(integ, alumno, codigo)
    assert r.status_code == 200, f"EA1: {r.status_code} {r.text}"
    body = r.json()
    assert body["coins_awarded"] == 10, f"EA1: la respuesta dice {body['coins_awarded']}, no 10"
    assert body["message"] == "Check-in exitoso! +10 coins", f"EA1: {body['message']!r}"

    filas = asientos(integ, alumno)
    assert len(filas) == 1, f"EA1: {len(filas)} asientos de asistencia"
    asiento = filas[0]
    assert asiento["amount"] == 10, f"EA1: el asiento es de {asiento['amount']}, no 10"
    meta = asiento["metadata"]
    assert (meta["base"], meta["puntualidad"], meta["puntual"]) == (5, 5, True), f"EA1: {meta}"
    assert "multiplier" not in meta, f"EA1: el asiento aún lleva el multiplicador: {meta}"
    assert integ.saldo("profile", alumno) == 10, "EA1: el saldo del estudiante no es 10"
    assert integ.saldo("tenant", esc.tenant) == POOL - 10, "EA1: la bolsa no bajó 10"


# =============================================================================
# EA2 — C3: el límite es inclusivo
# =============================================================================
def test_ea2_el_limite_de_cinco_minutos_es_inclusivo(integ, monkeypatch) -> None:
    esc = armar(integ, estudiantes=2)
    (en_el_limite, pasado), codigo = esc.alumnos, abrir(integ, esc)

    fijar_ahora(monkeypatch, INICIO + timedelta(minutes=5))
    a = marcar(integ, en_el_limite, codigo)
    fijar_ahora(monkeypatch, INICIO + timedelta(minutes=5, seconds=1))
    b = marcar(integ, pasado, codigo)

    assert (a.status_code, b.status_code) == (200, 200), f"EA2: {a.text} | {b.text}"
    assert a.json()["coins_awarded"] == 10, f"EA2: a los 5:00 pagó {a.json()['coins_awarded']}"
    assert b.json()["coins_awarded"] == 5, f"EA2: a los 5:01 pagó {b.json()['coins_awarded']}"
    meta = asientos(integ, pasado)[0]["metadata"]
    assert (meta["base"], meta["puntualidad"], meta["puntual"]) == (5, 0, False), f"EA2: {meta}"


# =============================================================================
# EA3 — C4: son configuración, sin tocar código
# =============================================================================
def test_ea3_los_numeros_son_configuracion(integ, monkeypatch) -> None:
    monkeypatch.setattr(settings, "asistencia_monedas_base", 4)
    monkeypatch.setattr(settings, "asistencia_monedas_puntualidad", 3)
    monkeypatch.setattr(settings, "asistencia_minutos_puntualidad", 10)
    esc = armar(integ, estudiantes=2)
    (a, b), codigo = esc.alumnos, abrir(integ, esc)

    fijar_ahora(monkeypatch, INICIO + timedelta(minutes=8))
    en_8 = marcar(integ, a, codigo)
    fijar_ahora(monkeypatch, INICIO + timedelta(minutes=11))
    en_11 = marcar(integ, b, codigo)

    assert (en_8.status_code, en_11.status_code) == (200, 200), f"EA3: {en_8.text} | {en_11.text}"
    pagos = (en_8.json()["coins_awarded"], en_11.json()["coins_awarded"])
    assert pagos == (7, 4), f"EA3: pagó {pagos}, esperado (7, 4)"
    assert integ.saldo("profile", a) == 7 and integ.saldo("profile", b) == 4, "EA3: saldos"


# =============================================================================
# ER1 — C7: la segunda sesión del mismo día no toca la racha
# =============================================================================
def test_er1_la_segunda_sesion_del_dia_no_cambia_la_racha(integ, monkeypatch) -> None:
    """Racha 5, última asistencia ayer. La 1.ª sesión de hoy -> 6; la 2.ª -> sigue en 6."""
    ayer, hoy = date(2026, 10, 5), date(2026, 10, 6)
    esc = armar(integ, racha=5, ultima=ayer)
    (alumno,) = esc.alumnos
    # 13:00 y 15:00 de Bogotá: el mismo día local Y el mismo día UTC.
    primera = abrir(integ, esc, datetime(2026, 10, 6, 18, 0, tzinfo=UTC))
    segunda = abrir(integ, esc, datetime(2026, 10, 6, 20, 0, tzinfo=UTC))

    fijar_ahora(monkeypatch, datetime(2026, 10, 6, 18, 1, tzinfo=UTC))
    r1 = marcar(integ, alumno, primera)
    assert r1.status_code == 200, f"ER1: {r1.text}"
    assert r1.json()["streak"] == 6, f"ER1: la 1.ª sesión dio racha {r1.json()['streak']}, no 6"

    fijar_ahora(monkeypatch, datetime(2026, 10, 6, 20, 1, tzinfo=UTC))
    r2 = marcar(integ, alumno, segunda)
    assert r2.status_code == 200, f"ER1: {r2.text}"
    assert r2.json()["streak"] == 6, f"ER1: la 2.ª sesión dio racha {r2.json()['streak']}, no 6"
    estado = estado_racha(integ, alumno)
    assert estado == {"current_streak": 6, "longest_streak": 6,
                      "last_attendance_date": hoy}, f"ER1: {estado}"


# =============================================================================
# ER2 — C8: el día es el local
# =============================================================================
def test_er2_el_dia_es_el_de_la_institucion(integ, monkeypatch) -> None:
    """A las 19:30 de Bogotá ya es otro día en UTC; la racha cuenta por el día de Bogotá."""
    esc = armar(integ, estudiantes=0)
    seguido = integ.crear_perfil(esc.tenant, group_code="G1", racha=3,
                                 ultima_asistencia=date(2026, 10, 6))  # ayer, en Bogotá
    con_hueco = integ.crear_perfil(esc.tenant, group_code="G1", racha=3,
                                   ultima_asistencia=date(2026, 10, 5))  # dos días atrás
    # 19:30 del 7 de octubre en Bogotá = 00:30 del 8 en UTC.
    codigo = abrir(integ, esc, datetime(2026, 10, 8, 0, 28, tzinfo=UTC))
    fijar_ahora(monkeypatch, datetime(2026, 10, 8, 0, 30, tzinfo=UTC))

    a, b = marcar(integ, seguido, codigo), marcar(integ, con_hueco, codigo)
    assert (a.status_code, b.status_code) == (200, 200), f"ER2: {a.text} | {b.text}"
    assert a.json()["streak"] == 4, f"ER2: ayer local + hoy local dio racha {a.json()['streak']}"
    assert b.json()["streak"] == 1, f"ER2: con dos días de hueco dio racha {b.json()['streak']}"
    dia_local = date(2026, 10, 7)
    assert estado_racha(integ, seguido)["last_attendance_date"] == dia_local, "ER2: la fecha"
    assert integ.valor("select attendance_date from attendance where student_id = :p",
                       p=seguido) == dia_local, "ER2: attendance_date no es el día local"


# =============================================================================
# ED1 — C9: dos sesiones del mismo grupo el mismo día: se paga UNA vez
# =============================================================================
def _filas(integ: Any, alumno: UUID) -> tuple[int, int]:
    """(filas en `attendance`, asientos 'attendance' en el libro) de ese estudiante."""
    return (int(integ.valor("select count(*) from attendance where student_id = :p", p=alumno)),
            len(asientos(integ, alumno)))


def test_ed1_una_segunda_sesion_del_dia_se_registra_pero_no_paga(integ, monkeypatch) -> None:
    """La 1.ª sesión llega tarde (5); la 2.ª, puntual, no paga. Otro estudiante cobra lo suyo."""
    esc = armar(integ, estudiantes=2)
    e, control = esc.alumnos
    # 13:00 y 15:00 de Bogotá, el mismo día.
    primera = abrir(integ, esc, datetime(2026, 10, 6, 18, 0, tzinfo=UTC))
    segunda = abrir(integ, esc, datetime(2026, 10, 6, 20, 0, tzinfo=UTC))

    fijar_ahora(monkeypatch, datetime(2026, 10, 6, 18, 10, tzinfo=UTC))  # 10 min: tarde
    r1 = marcar(integ, e, primera)
    assert r1.status_code == 200 and r1.json()["coins_awarded"] == 5, f"ED1: {r1.text}"
    racha = r1.json()["streak"]

    fijar_ahora(monkeypatch, datetime(2026, 10, 6, 20, 1, tzinfo=UTC))  # 1 min: puntual
    r2 = marcar(integ, e, segunda)
    # Primero la base de datos (qué quedó), después lo que respondió.
    filas, pagos = _filas(integ, e)
    assert filas == 2, f"ED1: {filas} filas en attendance, esperadas 2 (se registra la asistencia)"
    assert pagos == 1, f"ED1: {pagos} asientos de asistencia, esperado 1 (un pago por día)"
    assert asientos(integ, e)[0]["metadata"]["dia"] == "2026-10-06", "ED1: el asiento sin su día"
    assert r2.status_code == 200, f"ED1: la 2.ª sesión respondió {r2.status_code} {r2.text}"
    assert r2.json()["coins_awarded"] == 0, f"ED1: la 2.ª pagó {r2.json()['coins_awarded']}"
    assert r2.json()["streak"] == racha, f"ED1: la racha cambió a {r2.json()['streak']}"
    assert integ.valor("select coins_awarded from attendance where session_id = "
                       "(select id from attendance_sessions where session_code = :c)",
                       c=segunda) == 0, "ED1: la fila de la 2.ª sesión no dice 0 monedas"
    assert integ.saldo("profile", e) == 5, "ED1: el saldo de E se movió con la 2.ª sesión"
    assert integ.saldo("tenant", esc.tenant) == POOL - 5, "ED1: la bolsa se movió con la 2.ª"

    # Control: otro estudiante del grupo, su primera asistencia del día, SÍ cobra.
    r3 = marcar(integ, control, segunda)
    assert r3.status_code == 200 and r3.json()["coins_awarded"] == 10, \
        f"ED1: el control cobró {r3.json().get('coins_awarded')}, no 10 ({r3.text})"
    assert integ.saldo("tenant", esc.tenant) == POOL - 15, "ED1: la bolsa tras el control"


# =============================================================================
# ED2 — C10: el día de la paga es el local
# =============================================================================
def test_ed2_el_dia_de_la_paga_es_el_local(integ, monkeypatch) -> None:
    """18:00 y 19:30 de Bogotá (otro día en UTC): una paga. A las 00:10 del día siguiente, otra."""
    esc = armar(integ)
    (e,) = esc.alumnos
    a = abrir(integ, esc, datetime(2026, 10, 6, 23, 0, tzinfo=UTC))  # 18:00 Bogotá
    b = abrir(integ, esc, datetime(2026, 10, 7, 0, 28, tzinfo=UTC))  # 19:28 Bogotá, ya 7 en UTC
    c = abrir(integ, esc, datetime(2026, 10, 7, 5, 8, tzinfo=UTC))   # 00:08 Bogotá del día 7

    pagos = []
    for codigo, ahora in ((a, datetime(2026, 10, 6, 23, 1, tzinfo=UTC)),
                          (b, datetime(2026, 10, 7, 0, 30, tzinfo=UTC)),
                          (c, datetime(2026, 10, 7, 5, 10, tzinfo=UTC))):
        fijar_ahora(monkeypatch, ahora)
        r = marcar(integ, e, codigo)
        assert r.status_code == 200, f"ED2: {r.text}"
        pagos.append(r.json()["coins_awarded"])
    # 18:00 -> 10 · 19:30 (mismo día local) -> 0 · 00:10 del día siguiente -> 10 otra vez
    assert pagos == [10, 0, 10], f"ED2: las pagas fueron {pagos}, esperadas [10, 0, 10]"
    dias = [x["metadata"]["dia"] for x in asientos(integ, e)]
    assert dias == ["2026-10-06", "2026-10-07"], f"ED2: los días de los asientos: {dias}"


# =============================================================================
# ED3 — C11: dos check-ins a la vez a dos sesiones del mismo día: una paga
# =============================================================================
ESPERA_HILO_S = 60  # si un hilo no vuelve en este tiempo, el arnés está roto


def test_ed3_dos_checkins_a_la_vez_pagan_una_vez(integ, monkeypatch) -> None:
    esc = armar(integ)
    (e,) = esc.alumnos
    codigos = [abrir(integ, esc, datetime(2026, 10, 6, 18, 0, tzinfo=UTC)),
               abrir(integ, esc, datetime(2026, 10, 6, 18, 0, tzinfo=UTC))]
    fijar_ahora(monkeypatch, datetime(2026, 10, 6, 18, 1, tzinfo=UTC))  # ambas puntuales

    respuestas: list[Any] = [None, None]
    errores: list[BaseException] = []
    barrera = threading.Barrier(2)

    def marcar_a_la_vez(i: int) -> None:
        try:
            barrera.wait(timeout=ESPERA_HILO_S)
            respuestas[i] = marcar_con(TestClient(app), integ, e, codigos[i])
        except BaseException as exc:  # noqa: BLE001 — se re-lanza en el hilo principal
            errores.append(exc)

    hilos = [threading.Thread(target=marcar_a_la_vez, args=(i,)) for i in (0, 1)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=ESPERA_HILO_S)
    if any(h.is_alive() for h in hilos):
        raise PruebaRota("ED3: un check-in no volvió a tiempo (¿bloqueo?)")
    if errores:
        raise errores[0]

    estados = sorted(r.status_code for r in respuestas)
    pagos = sorted(r.json()["coins_awarded"] for r in respuestas if r.status_code == 200)
    filas, asientos_n = _filas(integ, e)
    medido = {"estados": estados, "pagos": pagos, "filas": filas, "asientos": asientos_n,
              "saldo": integ.saldo("profile", e)}
    assert medido == {"estados": [200, 200], "pagos": [0, 10], "filas": 2, "asientos": 1,
                      "saldo": 10}, f"ED3: dos check-ins a la vez: {medido}"
