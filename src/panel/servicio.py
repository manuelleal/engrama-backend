"""Arma las respuestas del panel a partir de las consultas de `metricas.py` (§1.4).

Nada se escribe: ni `add`, ni `flush`, ni `commit`. Lo que ve el admin sale de
`panel_admin(db, tenant_id)` con el tenant activo de SU contexto, y no tiene
ningún campo de nombre (§1.2): la etiqueta privada solo la arman las funciones
del super admin.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.panel import metricas as m
from src.panel import ventanas as v
from src.panel.schemas import (
    ClienteDetalle,
    ClienteResumen,
    DiaRegistros,
    Metricas,
    Monedas,
    PanelAdmin,
    PanelSuper,
    SemanaMonedas,
    Series,
)
from src.shared.config import settings
from src.shared.models import Tenant


def _desfase() -> int:
    return settings.engrama_utc_offset_hours


async def tenants_en_orden(db: AsyncSession) -> list[Tenant]:
    """Todos los tenants por (created_at, id): el puesto en esta lista es su código."""
    stmt = select(Tenant).order_by(Tenant.created_at, Tenant.id)
    return list((await db.execute(stmt)).scalars().all())


async def metricas_por_tenant(
    db: AsyncSession, ids: Sequence[UUID], ahora_utc: datetime
) -> dict[UUID, Metricas]:
    """Las cifras de cada tenant de `ids` (§1.3). Un tenant sin filas sale en ceros."""
    dias = v.dias_de_la_ventana(v.hoy_local(ahora_utc, _desfase()))
    desde_registros = v.inicio_utc(dias[0], _desfase())
    roles = await m.conteo_por_rol(db, ids)
    grupos = await m.grupos_por_tenant(db, ids)
    activos = await m.activos_por_tenant(db, ids, ahora_utc - timedelta(hours=v.HORAS_DE_ACTIVIDAD))
    registros = await m.registros_por_tenant(db, ids, desde_registros, _desfase())
    bolsas = await m.bolsa_por_tenant(db, ids)
    monedas = await m.monedas_por_tenant(db, ids)
    salida: dict[UUID, Metricas] = {}
    for tid in ids:
        r = roles.get(tid, {})
        emitidas, gastadas = monedas.get(tid, (0, 0))
        salida[tid] = Metricas(
            profes=r.get("teacher", 0), admins=r.get("admin", 0), grupos=grupos.get(tid, 0),
            estudiantes=r.get("student", 0), activos_7d=activos.get(tid, 0),
            registros_30d=sum(n for d, n in registros.get(tid, {}).items() if d in dias),
            monedas=Monedas(bolsa=bolsas.get(tid, 0), emitidas=emitidas, gastadas=gastadas),
        )
    return salida


async def series_de(db: AsyncSession, ids: Sequence[UUID], ahora_utc: datetime) -> Series:
    """Registros por día (30) y monedas por semana (8), sumando los tenants de `ids`."""
    hoy = v.hoy_local(ahora_utc, _desfase())
    dias = v.dias_de_la_ventana(hoy)
    semanas = v.semanas_de_la_ventana(hoy)
    por_tenant = await m.registros_por_tenant(db, ids, v.inicio_utc(dias[0], _desfase()), _desfase())
    por_dia: dict[object, int] = {}
    for conteo in por_tenant.values():
        for d, n in conteo.items():
            por_dia[d] = por_dia.get(d, 0) + n
    monedas = await m.monedas_por_semana(db, ids, v.inicio_utc(semanas[0], _desfase()), _desfase())
    return Series(
        registros_por_dia=[DiaRegistros(dia=d, n=por_dia.get(d, 0)) for d in dias],
        monedas_por_semana=[SemanaMonedas(semana=s, emitidas=monedas.get(s, (0, 0))[0],
                                          gastadas=monedas.get(s, (0, 0))[1]) for s in semanas],
    )


def sumar(lista: Sequence[Metricas]) -> Metricas:
    """Campo a campo (los totales del super admin)."""
    def total(campo: str) -> int:
        return sum(int(getattr(x, campo)) for x in lista)

    def total_monedas(campo: str) -> int:
        return sum(int(getattr(x.monedas, campo)) for x in lista)

    return Metricas(
        profes=total("profes"), admins=total("admins"), grupos=total("grupos"),
        estudiantes=total("estudiantes"), activos_7d=total("activos_7d"),
        registros_30d=total("registros_30d"),
        monedas=Monedas(bolsa=total_monedas("bolsa"), emitidas=total_monedas("emitidas"),
                        gastadas=total_monedas("gastadas")),
    )


def _resumen(t: Tenant, puesto: int, cifras: Metricas) -> ClienteResumen:
    return ClienteResumen(id=t.id, codigo=v.codigo_de(puesto), etiqueta=t.name,
                          suspendido=bool(t.is_suspended), creado=t.created_at, metricas=cifras)


async def panel_super(db: AsyncSession) -> PanelSuper:
    """Todos los clientes con sus cifras, los totales y las series globales."""
    ahora_utc = v.ahora()
    tenants = await tenants_en_orden(db)
    ids = [t.id for t in tenants]
    cifras = await metricas_por_tenant(db, ids, ahora_utc)
    series = await series_de(db, ids, ahora_utc)
    return PanelSuper(
        hoy=v.hoy_local(ahora_utc, _desfase()), totales=sumar(list(cifras.values())),
        registros_por_dia=series.registros_por_dia, monedas_por_semana=series.monedas_por_semana,
        clientes=[_resumen(t, i + 1, cifras[t.id]) for i, t in enumerate(tenants)],
    )


async def detalle(db: AsyncSession, tenant_id: UUID) -> ClienteDetalle | None:
    """Un cliente con sus series; None si ese tenant no existe."""
    ahora_utc = v.ahora()
    tenants = await tenants_en_orden(db)
    puesto = next((i + 1 for i, t in enumerate(tenants) if t.id == tenant_id), None)
    if puesto is None:
        return None
    cifras = (await metricas_por_tenant(db, [tenant_id], ahora_utc))[tenant_id]
    series = await series_de(db, [tenant_id], ahora_utc)
    base = _resumen(tenants[puesto - 1], puesto, cifras)
    return ClienteDetalle(**base.model_dump(), registros_por_dia=series.registros_por_dia,
                          monedas_por_semana=series.monedas_por_semana)


async def panel_admin(db: AsyncSession, tenant_id: UUID) -> PanelAdmin:
    """El tablero del admin: SOLO `tenant_id` (el activo de su contexto), sin nombre."""
    ahora_utc = v.ahora()
    cifras = (await metricas_por_tenant(db, [tenant_id], ahora_utc))[tenant_id]
    series = await series_de(db, [tenant_id], ahora_utc)
    return PanelAdmin(hoy=v.hoy_local(ahora_utc, _desfase()), metricas=cifras,
                      registros_por_dia=series.registros_por_dia,
                      monedas_por_semana=series.monedas_por_semana)
