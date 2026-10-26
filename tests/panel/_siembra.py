"""Siembra sintética del panel (ESPEC_panel_super_admin §2): dos clientes A y B con cifras conocidas.

Todo se escribe con fechas EXPLÍCITAS relativas a `ahora` (el reloj del panel se
fija con `fijar_reloj`), para que los bordes de la ventana (hoy, hace 29 y 30
días, hace 8 días) no dependan de la hora a la que corre la suite.

Los nombres de los tenants son "secretos" a propósito: AM4 los busca en la
respuesta del admin y no deben aparecer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.panel import ventanas
from src.shared.config import settings
from src.shared.models import (
    Attendance,
    AttendanceSession,
    ChallengeAttempt,
    CoinLedger,
    CoinWallet,
    Group,
    LearningEvent,
    Membership,
    Profile,
    Tenant,
)

NOMBRE_A = "Colegio Secreto Alfa"
NOMBRE_B = "Instituto Privado Beta"


def fijar_reloj(mp: pytest.MonkeyPatch) -> datetime:
    """Fija `ventanas.ahora` en este instante y lo devuelve."""
    ahora = datetime.now(UTC).replace(microsecond=0)
    mp.setattr(ventanas, "ahora", lambda: ahora)
    return ahora


def hoy_local(ahora: datetime) -> date:
    return ventanas.hoy_local(ahora, settings.engrama_utc_offset_hours)


def en_dia_local(ahora: datetime, dias_atras: int) -> datetime:
    """Un instante (00:01 local) del día local `hoy - dias_atras`."""
    dia = hoy_local(ahora) - timedelta(days=dias_atras)
    return ventanas.inicio_utc(dia, settings.engrama_utc_offset_hours) + timedelta(minutes=1)


@dataclass
class Cliente:
    id: UUID
    nombre: str
    personas: dict[str, UUID] = field(default_factory=dict)
    grupos: list[UUID] = field(default_factory=list)
    billeteras: dict[str, UUID] = field(default_factory=dict)


class Sembrador:
    """Fábricas finas sobre `integ._insertar` (cada llamada, su propia transacción)."""

    def __init__(self, integ: Any, ahora: datetime) -> None:
        self.integ = integ
        self.ahora = ahora

    def tenant(self, nombre: str, *, creado_hace: timedelta, bolsa: int) -> Cliente:
        tid = uuid4()
        wid = uuid4()
        self.integ._insertar(
            Tenant(id=tid, name=nombre, slug=f"t-{tid.hex[:12]}", coin_pool=bolsa,
                   created_at=self.ahora - creado_hace),
            CoinWallet(id=wid, tenant_id=tid, owner_type="tenant", owner_id=tid,
                       currency="COIN", balance=bolsa),
        )
        return Cliente(id=tid, nombre=nombre, billeteras={"bolsa": wid})

    def perfil(self, *, rol_perfil: str = "student") -> UUID:
        pid = uuid4()
        self.integ._insertar(Profile(id=pid, documento_id=f"doc-{pid.hex[:12]}",
                                     full_name=f"Persona {pid.hex[:6]}", pin_hash="sintetico",
                                     role=rol_perfil))
        return pid

    def miembro(self, c: Cliente, alias: str, rol: str, *, creado: datetime,
                activo: bool = True, perfil: UUID | None = None) -> UUID:
        pid = perfil or self.perfil(rol_perfil=rol)
        mid = uuid4()
        self.integ._insertar(Membership(
            id=mid, tenant_id=c.id, profile_id=pid, role=rol, is_active=activo,
            full_name=f"Persona {pid.hex[:6]}" if rol == "student" else None, created_at=creado))
        c.personas[alias] = pid
        c.billeteras[f"m:{alias}"] = mid  # el id de la membresía (dueño del bolsillo)
        return pid

    def grupo(self, c: Cliente, codigo: str) -> UUID:
        gid = uuid4()
        self.integ._insertar(Group(id=gid, tenant_id=c.id, group_code=codigo))
        c.grupos.append(gid)
        return gid

    def intento(self, c: Cliente, alumno: UUID, cuando: datetime) -> None:
        creador = next(iter(c.personas.values()))
        reto, _ = self.integ.crear_challenge(c.id, creador)
        self.integ._insertar(ChallengeAttempt(
            tenant_id=c.id, challenge_id=reto, student_id=alumno, status="in_progress",
            score_percent=0, answers=[], started_at=cuando, created_at=cuando))

    def asistencia(self, c: Cliente, alumno: UUID, cuando: datetime) -> None:
        sid = uuid4()
        creador = next(iter(c.personas.values()))
        self.integ._insertar(
            AttendanceSession(id=sid, tenant_id=c.id, group_id=c.grupos[0],
                              session_code=f"S{sid.hex[:10]}", expires_at=cuando,
                              created_by=creador, starts_at=cuando, created_at=cuando),
            Attendance(tenant_id=c.id, session_id=sid, student_id=alumno, created_at=cuando),
        )

    def evento(self, c: Cliente, alumno: UUID, cuando: datetime) -> None:
        self.integ._insertar(LearningEvent(
            tenant_id=c.id, event_id=f"ev-{uuid4().hex}", origin="eva", source="quiz",
            type="answer.recorded", subject_id=alumno, payload={}, occurred_at=cuando,
            schema_version=1, body_hash="x", batch_id="b", instance="i"))

    def billetera(self, c: Cliente, clave: str, dueno: str, owner_id: UUID) -> UUID:
        wid = uuid4()
        self.integ._insertar(CoinWallet(id=wid, tenant_id=c.id, owner_type=dueno,
                                        owner_id=owner_id, currency="COIN", balance=0))
        c.billeteras[clave] = wid
        return wid

    def asiento(self, c: Cliente, desde: str | None, hacia: str, monto: int, accion: str,
                cuando: datetime) -> None:
        self.integ._insertar(CoinLedger(
            tenant_id=c.id, from_wallet_id=c.billeteras[desde] if desde else None,
            to_wallet_id=c.billeteras[hacia], amount=monto, action=accion, created_at=cuando))


# =============================================================================
# Los dos clientes de desarrollo y lo que el panel debe decir de ellos
# =============================================================================
def sembrar_a(s: Sembrador) -> Cliente:
    """Cliente A: 2 profes activos (+1 inactivo), 1 admin, 3 grupos, 5 estudiantes activos (+1 inactivo)."""
    ah = s.ahora
    a = s.tenant(NOMBRE_A, creado_hace=timedelta(days=90), bolsa=777)
    s.miembro(a, "admin", "admin", creado=en_dia_local(ah, 60))
    s.miembro(a, "p1", "teacher", creado=en_dia_local(ah, 60))
    s.miembro(a, "p2", "teacher", creado=en_dia_local(ah, 1))
    s.miembro(a, "p3", "teacher", creado=en_dia_local(ah, 1), activo=False)
    for codigo in ("A-1", "A-2", "A-3"):
        s.grupo(a, codigo)
    # registros: s1 hoy, s2 hace 29 (entra), s3 hace 30 (no), s4 hace 5, s5 hace 40, s6 inactivo hace 2
    for alias, dias, activo in (("s1", 0, True), ("s2", 29, True), ("s3", 30, True),
                                ("s4", 5, True), ("s5", 40, True), ("s6", 2, False)):
        s.miembro(a, alias, "student", creado=en_dia_local(ah, dias), activo=activo)
    p = a.personas
    s.intento(a, p["s1"], ah - timedelta(hours=1))  # activo
    s.asistencia(a, p["s2"], ah - timedelta(days=6, hours=23))  # activo (dentro de 168 h)
    s.intento(a, p["s4"], ah - timedelta(days=8))  # fuera de los 7 días
    s.evento(a, p["s5"], ah - timedelta(days=2))  # activo por un evento del anillo
    s.intento(a, p["s6"], ah - timedelta(hours=2))  # membresía inactiva: no cuenta
    s.intento(a, p["p1"], ah - timedelta(hours=2))  # un profe no es estudiante activo
    _monedas_a(s, a)
    return a


def _monedas_a(s: Sembrador, a: Cliente) -> None:
    ah, p = s.ahora, a.personas
    s.billetera(a, "s1", "profile", p["s1"])
    s.billetera(a, "s2", "profile", p["s2"])
    s.billetera(a, "bolsillo", "membership", a.billeteras["m:p1"])
    s.billetera(a, "puja", "auction", uuid4())
    hace = ah - timedelta(minutes=1)
    for desde, hacia, monto, accion, cuando in (
        (None, "bolsa", 500, "pool_topup", hace),            # recarga: ni emisión ni gasto
        ("bolsa", "s1", 20, "challenge", hace),              # emite +20
        ("bolsa", "s2", 10, "attendance", ah - timedelta(days=21)),  # emite +10 (hace 3 semanas)
        ("bolsa", "s1", 6, "challenge", ah - timedelta(days=70)),    # emite +6 (fuera de 8 semanas)
        ("bolsa", "bolsillo", 100, "budget_allocation", hace),       # nada
        ("bolsillo", "s1", 15, "teacher_award", hace),       # emite +15
        ("s1", "bolsillo", 5, "teacher_reversal", hace),     # emite −5
        ("bolsillo", "bolsa", 30, "budget_return", hace),    # nada
        ("s1", "bolsa", 12, "shop_purchase", hace),          # gasta +12
        ("bolsa", "s1", 4, "shop_refund", hace),             # gasta −4 (y NO es emisión)
        ("s2", "puja", 7, "auction_hold", hace),             # nada (retenido)
        ("puja", "bolsa", 7, "auction_settle", hace),        # gasta +7
        ("s1", "puja", 3, "auction_hold", hace),             # nada
        ("puja", "s1", 3, "auction_refund", hace),           # nada
        ("bolsa", "s2", 8, "live", hace),                    # emite +8
    ):
        s.asiento(a, desde, hacia, monto, accion, cuando)


def sembrar_b(s: Sembrador, a: Cliente) -> Cliente:
    """Cliente B: 1 profe, 1 admin, 1 grupo, 3 estudiantes (uno es s3 de A, que juega SOLO en B)."""
    ah = s.ahora
    b = s.tenant(NOMBRE_B, creado_hace=timedelta(days=10), bolsa=5000)
    s.miembro(b, "admin", "admin", creado=en_dia_local(ah, 9))
    s.miembro(b, "p1", "teacher", creado=en_dia_local(ah, 9))
    s.grupo(b, "B-1")
    s.miembro(b, "t1", "student", creado=en_dia_local(ah, 0))
    s.miembro(b, "t2", "student", creado=en_dia_local(ah, 10))
    s.miembro(b, "s3", "student", creado=en_dia_local(ah, 1), perfil=a.personas["s3"])
    s.intento(b, b.personas["s3"], ah - timedelta(hours=1))  # activo en B, NO en A
    s.billetera(b, "t1", "profile", b.personas["t1"])
    s.asiento(b, "bolsa", "t1", 100, "challenge", ah - timedelta(minutes=1))
    s.asiento(b, "t1", "bolsa", 40, "shop_purchase", ah - timedelta(minutes=1))
    return b


ESPERADO_A: dict[str, Any] = {
    "profes": 2, "admins": 1, "grupos": 3, "estudiantes": 5, "activos_7d": 3,
    "registros_30d": 4, "monedas": {"bolsa": 777, "emitidas": 54, "gastadas": 15},
}
ESPERADO_B: dict[str, Any] = {
    "profes": 1, "admins": 1, "grupos": 1, "estudiantes": 3, "activos_7d": 1,
    "registros_30d": 3, "monedas": {"bolsa": 5000, "emitidas": 100, "gastadas": 40},
}


def sembrar(integ: Any, mp: pytest.MonkeyPatch) -> tuple[Sembrador, Cliente, Cliente]:
    s = Sembrador(integ, fijar_reloj(mp))
    a = sembrar_a(s)
    b = sembrar_b(s, a)
    return s, a, b


def super_admin(s: Sembrador, *, activo: bool = True, temporal: bool = False) -> UUID:
    """Un perfil `super_admin` SIN membresía (no pertenece a ningún cliente)."""
    pid = uuid4()
    s.integ._insertar(Profile(id=pid, documento_id=f"doc-{pid.hex[:12]}", full_name="Super",
                              pin_hash="sintetico", role="super_admin", is_active=activo,
                              force_password_reset=temporal))
    return pid
