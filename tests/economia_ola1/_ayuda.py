"""Ayudas de los tests de la ola 1 (no empieza por `test_`: no se recolecta).

Una "escuela" sintética: institución con bolsa, un admin, dos profes (P1 con el
grupo 10A, P2 con el 10B) y N estudiantes por grupo con la matrícula de fecha
EXPLÍCITA. Los saldos de los estudiantes se siembran con `award_coins` (el
camino real de un reto), así la bolsa baja lo mismo que sube el estudiante y la
conservación del dinero se puede medir.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from src.main import app
from src.shared.models import TeacherGroup

client = TestClient(app, raise_server_exceptions=False)


@dataclass(frozen=True)
class Escuela:
    tenant: UUID
    admin: UUID
    p1: UUID
    p2: UUID
    g1: UUID
    g2: UUID
    a1: list[UUID]  # estudiantes del 10A (de P1)
    a2: list[UUID]  # estudiantes del 10B (de P2)


def escuela(integ: Any, *, pool: int = 10_000, n: int = 3, saldo: int = 0) -> Escuela:
    tenant = integ.crear_tenant(pool=pool)
    admin = integ.crear_perfil(tenant, rol="admin", creada_hace=timedelta(days=2000))
    p1 = integ.crear_perfil(tenant, rol="teacher", creada_hace=timedelta(days=1999))
    p2 = integ.crear_perfil(tenant, rol="teacher", creada_hace=timedelta(days=1998))
    g1, g2 = integ.crear_grupo(tenant, "10A"), integ.crear_grupo(tenant, "10B")
    integ._insertar(TeacherGroup(tenant_id=tenant, teacher_id=p1, group_id=g1),
                    TeacherGroup(tenant_id=tenant, teacher_id=p2, group_id=g2))
    a1 = [integ.crear_perfil(tenant, group_code="10A", creada_hace=timedelta(days=1000 - i))
          for i in range(n)]
    a2 = [integ.crear_perfil(tenant, group_code="10B", creada_hace=timedelta(days=900 - i))
          for i in range(n)]
    if saldo:
        for alumno in a1 + a2:
            sembrar(integ, tenant, alumno, saldo)
    return Escuela(tenant, admin, p1, p2, g1, g2, a1, a2)


def sembrar(integ: Any, tenant: UUID, alumno: UUID, monto: int) -> None:
    """Le paga `monto` al estudiante desde la bolsa con `award_coins`, como un reto."""
    from src.engrama_core.service import coins

    async def _pagar() -> None:
        async with integ.Session() as db:
            await coins.award_coins(db, student_id=alumno, tenant_id=tenant, amount=monto,
                                    action="challenge_reward")
            await db.commit()

    asyncio.run(_pagar())


def _llave() -> str:
    return uuid4().hex


def _post(integ: Any, quien: UUID, ruta: str, cuerpo: dict[str, Any]) -> Any:
    return client.post(ruta, json=cuerpo, headers=integ.headers(quien))


def recargar(integ: Any, admin: UUID, profe: UUID, monto: int, *, llave: str | None = None,
             devolver: bool = False) -> Any:
    ruta = f"/admin/presupuestos/{profe}/" + ("devolver" if devolver else "recargar")
    return _post(integ, admin, ruta, {"monto": monto, "llave": llave or _llave()})


def dar(integ: Any, profe: UUID, alumno: UUID, monto: int, *, motivo: str = "participacion",
        nota: str | None = None, llave: str | None = None) -> Any:
    return _post(integ, profe, "/economia/dar",
                 {"student_id": str(alumno), "monto": monto, "motivo": motivo, "nota": nota,
                  "llave": llave or _llave()})


def corregir(integ: Any, profe: UUID, entrega: str, monto: int | None = None, *,
             llave: str | None = None) -> Any:
    cuerpo: dict[str, Any] = {"entrega_id": entrega, "nota": "error de dedo",
                              "llave": llave or _llave()}
    if monto is not None:
        cuerpo["monto"] = monto
    return _post(integ, profe, "/economia/corregir", cuerpo)


def crear_objeto(integ: Any, quien: UUID, nombre: str = "Elegir la canción", *,
                 precio: int = 40, existencias: int = 10, tipo: str = "privilegio",
                 descripcion: str | None = None) -> Any:
    return _post(integ, quien, "/economia/tienda",
                 {"nombre": nombre, "descripcion": descripcion, "tipo": tipo,
                  "precio": precio, "existencias": existencias})


def comprar(integ: Any, alumno: UUID, objeto: str, *, llave: str | None = None) -> Any:
    return _post(integ, alumno, f"/economia/tienda/{objeto}/comprar",
                 {"llave": llave or _llave()})


def entregar(integ: Any, quien: UUID, compra: str) -> Any:
    return client.post(f"/economia/mochila/{compra}/entregar", headers=integ.headers(quien))


def crear_subasta(integ: Any, profe: UUID, grupo: UUID, *, titulo: str | None = "Elegir la "
                  "canción", objeto: str | None = None, minima: int = 10,
                  segundos: int = 90) -> Any:
    cuerpo: dict[str, Any] = {"grupo_id": str(grupo), "puja_minima": minima,
                              "duracion_segundos": segundos}
    if objeto is not None:
        cuerpo["objeto_id"] = objeto
    else:
        cuerpo["titulo"] = titulo
    return _post(integ, profe, "/subastas", cuerpo)


def pujar(integ: Any, alumno: UUID, subasta: str, monto: int, *, llave: str | None = None) -> Any:
    return _post(integ, alumno, f"/subastas/{subasta}/pujar",
                 {"monto": monto, "llave": llave or _llave()})


def leer(integ: Any, quien: UUID, ruta: str) -> Any:
    return client.get(ruta, headers=integ.headers(quien))


def detalle(r: Any) -> str:
    """El `detail` en español del error ('' si no hay)."""
    try:
        d = r.json().get("detail")
    except (ValueError, AttributeError):
        return ""
    return d if isinstance(d, str) else str(d)


# ------------------------------------------------------------------ la base
def _escribir(integ: Any, sql: str, **params: Any) -> None:
    """Escritura de preparación, confirmada (mover fechas para simular el tiempo)."""
    from sqlalchemy import text

    async def _e() -> None:
        async with integ.engine.begin() as conn:
            await conn.execute(text(sql), params)

    integ.run(_e())


def envejecer_entrega(integ: Any, entrada: str, dias: float) -> None:
    _escribir(integ, "update coin_ledger set created_at = now() - make_interval(secs => :s) "
                     "where id = :i", s=dias * 86400, i=UUID(entrada))


def mover_entrega_a(integ: Any, entrada: str, instante: Any) -> None:
    _escribir(integ, "update coin_ledger set created_at = :t where id = :i",
              t=instante, i=UUID(entrada))


def envejecer_compra(integ: Any, compra: str, dias: float) -> None:
    _escribir(integ, "update inventory set purchased_at = now() - make_interval(secs => :s) "
                     "where id = :i", s=dias * 86400, i=UUID(compra))


def saldo(integ: Any, alumno: UUID) -> int:
    return integ.saldo("profile", alumno) or 0


def bolsa(integ: Any, tenant: UUID) -> int:
    return integ.saldo("tenant", tenant) or 0


def bolsillo(integ: Any, tenant: UUID, profe: UUID) -> int:
    v = integ.valor("select w.balance from coin_wallets w join memberships m on m.id = w.owner_id "
                    "where w.owner_type = 'membership' and m.tenant_id = :t "
                    "and m.profile_id = :p", t=tenant, p=profe)
    return 0 if v is None else int(v)


def total(integ: Any, tenant: UUID) -> int:
    """Bolsa + bolsillos + saldos de la institución: no cambia con la ola 1."""
    return int(integ.valor("select coalesce(sum(balance), 0) from coin_wallets "
                           "where tenant_id = :t", t=tenant))


def filas(integ: Any, accion: str, tenant: UUID) -> int:
    return int(integ.valor("select count(*) from coin_ledger where action = :a "
                           "and tenant_id = :t", a=accion, t=tenant))


def stock(integ: Any, objeto: str) -> int | None:
    v = integ.valor("select stock from shop_items where id = :i", i=UUID(objeto))
    return None if v is None else int(v)


def vencer_subasta(integ: Any, subasta: str, *, en_segundos: float = -1) -> None:
    """Mueve el cierre de la subasta a `en_segundos` desde ahora (negativo = ya pasó)."""
    _escribir(integ, "update auctions set ends_at = now() + make_interval(secs => :s) "
                     "where id = :i", s=en_segundos, i=UUID(subasta))
