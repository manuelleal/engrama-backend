"""Lo que el profe mira antes de Dar o Corregir — ESPEC_ola1_economia, ADENDA 1 §A.3.

`GET /economia/grupo/{gid}/saldos` es una ruta APARTE del roster: el roster
(`/teachers/groups/{gid}/students`) sigue sin saldo por decisión del pedagogo
(X9); esta es la vista de economía, la que necesita el botón Dar.
"""
from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.bolsillo import consultas, reglas
from src.bolsillo.schemas import EntregaRecienteOut, SaldoAlumnoOut
from src.shared.config import settings
from src.shared.models import CoinLedger, CoinWallet, Membership
from src.teachers.service import access as access_service


async def saldos_grupo(db: AsyncSession, auth: AuthContext, gid: UUID) -> list[SaldoAlumnoOut]:
    """Estudiantes activos del grupo con saldo y cupo semanal de entregas que les queda."""
    grupo = await access_service.authorize_group(db, auth, gid)
    filas = (await db.execute(
        select(Membership.profile_id, Membership.full_name, CoinWallet.id, CoinWallet.balance)
        .outerjoin(CoinWallet, (CoinWallet.owner_id == Membership.profile_id)
                   & (CoinWallet.owner_type == "profile") & (CoinWallet.currency == "COIN"))
        .where(Membership.tenant_id == grupo.tenant_id,
               Membership.group_code == grupo.group_code,
               Membership.role == "student", Membership.is_active.is_(True))
        .order_by(Membership.full_name, Membership.profile_id))).all()
    tope = settings.profe_semana_por_estudiante_tope
    lunes = consultas.lunes_actual()
    salida: list[SaldoAlumnoOut] = []
    for profile_id, nombre, wallet_id, saldo in filas:
        recibido = (await consultas.recibido_semana(db, auth.tenant_id, wallet_id, lunes)
                    if wallet_id is not None else 0)
        salida.append(SaldoAlumnoOut(
            estudiante_id=profile_id, nombre=nombre or "", saldo=int(saldo or 0),
            recibido_semana=recibido, cupo_semana=max(tope - recibido, 0)))
    return salida


async def mis_entregas(db: AsyncSession, auth: AuthContext) -> list[EntregaRecienteOut]:
    """Mis entregas dentro del plazo de corrección, la más nueva primero."""
    plazo = timedelta(days=settings.corregir_plazo_dias)
    filas = (await db.execute(
        select(CoinLedger, CoinWallet.owner_id)
        .join(CoinWallet, CoinWallet.id == CoinLedger.to_wallet_id)
        .where(CoinLedger.tenant_id == auth.tenant_id,
               CoinLedger.action == consultas.ENTREGA,
               CoinLedger.created_by_profile_id == auth.profile_id,
               CoinLedger.created_at >= consultas.ahora() - plazo)
        .order_by(CoinLedger.created_at.desc()))).all()
    salida: list[EntregaRecienteOut] = []
    for entrada, alumno in filas:
        ya = await consultas.ya_corregido(db, auth.tenant_id, entrada.id)
        salida.append(EntregaRecienteOut(
            entrega_id=entrada.id, estudiante_id=alumno, monto=int(entrada.amount),
            motivo=str((entrada.ledger_metadata or {}).get("reason", "")),
            creada_en=entrada.created_at,
            corregible=reglas.corregible(int(entrada.amount), ya),
            corregible_hasta=entrada.created_at + plazo))
    return salida
