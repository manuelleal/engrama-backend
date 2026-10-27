"""Alta, lista y reenvío de invitaciones — `docs/ESPEC_invitar_profe.md` §3.1-§3.3.

NADA de aquí habla con GoTrue (IP12): las tres funciones solo tocan la base y
devuelven, cuando hay que mandar un correo, el `PedidoDeEnvio` que la ruta deja
en segundo plano (`envio.enviar`). Así la respuesta es la misma, y tarda lo
mismo, para un correo nuevo y para uno que ya tenía cuenta en otra institución.

Toda consulta filtra por `auth.tenant_id`: la institución sale del token, nunca
del cuerpo. La tabla tiene RLS sin políticas; el aislamiento lo hace este filtro
(IP4, tramposo XP1).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.invitar.envio import PedidoDeEnvio
from src.invitar.schemas import ACEPTADA, ENVIADA, InvitacionIn, InvitacionOut
from src.shared.config import settings
from src.shared.models import Group, InvitacionDocente, Membership, Profile, TeacherGroup
from src.teachers.service import access

YA_INVITADO = "ya_invitado"
YA_ACEPTADA = "ya_aceptada"
NO_ENCONTRADA = "invitacion_no_encontrada"
DEMASIADAS = "demasiadas_invitaciones"
ESPERA = "espera_para_reenviar"
ACCION_AUDITORIA = "invitacion_profe"
VENTANA_S = 3600
_UNIQUE_VIOLADO = "23505"


@dataclass(frozen=True)
class Resultado:
    """Lo que ve el admin y lo que se manda después de responder."""

    salida: InvitacionOut
    pedido: PedidoDeEnvio


def _429(detalle: str, espera_s: int) -> HTTPException:
    return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detalle,
                         headers={"Retry-After": str(max(1, espera_s))})


# =============================================================================
# El tope por admin (§3.1 paso 4)
# =============================================================================
async def _exigir_tope(db: AsyncSession, auth: AuthContext) -> None:
    """429 si ESTE admin ya hizo `invitaciones_por_hora` envíos en la última hora.

    Se cuenta en `audit_logs` (cada invitar y cada reenviar deja una fila), así
    que vale con dos procesos y tras reiniciar. El candado de transacción por
    admin hace que dos peticiones simultáneas pasen de una en una: la segunda ya
    cuenta la primera.
    """
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:llave, 0))"),
                     {"llave": f"invitar:{auth.profile_id}"})
    fila = (await db.execute(text("""
        SELECT count(*) AS n,
               extract(epoch FROM (min(created_at) + make_interval(secs => :ventana) - now()))
                 AS espera
        FROM audit_logs
        WHERE user_id = :admin AND action_type = :accion
          AND created_at > now() - make_interval(secs => :ventana)
    """), {"admin": auth.profile_id, "accion": ACCION_AUDITORIA, "ventana": VENTANA_S})).one()
    if int(fila.n) >= settings.invitaciones_por_hora:
        raise _429(DEMASIADAS, math.ceil(float(fila.espera or VENTANA_S)))
    await _exigir_tope_global(db)


async def _exigir_tope_global(db: AsyncSession) -> None:
    """429 si TODOS los admins juntos ya hicieron `invitaciones_globales_por_hora` envíos (H-3).

    Invitar y recuperar comparten el cupo de correos de GoTrue: este tope deja
    reserva para recuperar. El mismo `detail` que el tope por admin: el admin no
    aprende si otras instituciones están invitando. Candado global DESPUÉS del
    del admin (siempre en ese orden: sin abrazo mortal).
    """
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:llave, 0))"),
                     {"llave": "invitar:global"})
    fila = (await db.execute(text("""
        SELECT count(*) AS n,
               extract(epoch FROM (min(created_at) + make_interval(secs => :ventana) - now()))
                 AS espera
        FROM audit_logs
        WHERE action_type = :accion AND created_at > now() - make_interval(secs => :ventana)
    """), {"accion": ACCION_AUDITORIA, "ventana": VENTANA_S})).one()
    if int(fila.n) >= settings.invitaciones_globales_por_hora:
        raise _429(DEMASIADAS, math.ceil(float(fila.espera or VENTANA_S)))


async def _auditar(db: AsyncSession, auth: AuthContext, invitacion_id: int, tipo: str) -> None:
    """Una fila por envío pedido: es el registro y es lo que cuenta el tope. Sin correo."""
    await db.execute(text("""
        INSERT INTO audit_logs (tenant_id, user_id, action_type, result, metadata)
        VALUES (:tenant, :admin, :accion, 'success',
                jsonb_build_object('invitacion_id', CAST(:inv AS bigint), 'tipo', CAST(:tipo AS text)))
    """), {"tenant": auth.tenant_id, "admin": auth.profile_id, "accion": ACCION_AUDITORIA,
           "inv": invitacion_id, "tipo": tipo})


# =============================================================================
# Lectura común
# =============================================================================
def _consulta(auth: AuthContext):  # type: ignore[no-untyped-def]
    """Invitaciones de la institución ACTIVA con su perfil, su membresía y su grupo."""
    return (
        select(InvitacionDocente, Profile.force_password_reset, Membership.full_name,
               Group.group_code)
        .join(Profile, Profile.id == InvitacionDocente.profile_id)
        .join(Group, Group.id == InvitacionDocente.group_id)
        .outerjoin(Membership, (Membership.profile_id == InvitacionDocente.profile_id)
                   & (Membership.tenant_id == InvitacionDocente.tenant_id))
        .where(InvitacionDocente.tenant_id == auth.tenant_id)
        # Lo recién escrito con UPDATE (el reenvío) se lee de la base, no del mapa de identidad.
        .execution_options(populate_existing=True)
    )


def estado_de(force_password_reset: bool) -> str:
    """Aceptada = el profe ya puso su contraseña (la bandera bajó). Pura."""
    return ENVIADA if force_password_reset else ACEPTADA


def _salida(inv: InvitacionDocente, bandera: bool, nombre: str | None,
            group_code: str) -> InvitacionOut:
    return InvitacionOut(id=inv.id, nombre=nombre or "", correo=inv.correo,
                         group_id=inv.group_id, group_code=group_code,
                         estado=estado_de(bandera),  # type: ignore[arg-type]
                         enviada_en=inv.ultimo_envio_en, envios=inv.envios)


async def listar(db: AsyncSession, auth: AuthContext) -> list[InvitacionOut]:
    filas = (await db.execute(_consulta(auth).order_by(InvitacionDocente.created_at.desc(),
                                                       InvitacionDocente.id.desc()))).all()
    return [_salida(*fila) for fila in filas]


async def una(db: AsyncSession, auth: AuthContext, invitacion_id: int,
               *, para_actualizar: bool = False) -> InvitacionOut:
    stmt = _consulta(auth).where(InvitacionDocente.id == invitacion_id)
    if para_actualizar:
        stmt = stmt.with_for_update(of=InvitacionDocente)
    fila = (await db.execute(stmt)).first()
    if fila is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_ENCONTRADA)
    return _salida(*fila)


# =============================================================================
# §3.1 — invitar
# =============================================================================
async def _crear_filas(db: AsyncSession, auth: AuthContext, group: Group,
                       datos: InvitacionIn) -> InvitacionDocente:
    """Perfil `teacher` con bandera, membresía con el nombre, grupo e invitación.

    LAS MISMAS filas para un correo nuevo y para uno con cuenta en otra parte
    (§1.3): con el ajeno, el perfil se queda sin cuenta de GoTrue y nadie entra
    con él. `documento_id` opaco y único (`DOC_ID_PATRON`: 28 caracteres).
    """
    perfil = Profile(id=uuid4(), documento_id=f"inv_{uuid4().hex[:24]}", full_name="",
                     pin_hash="", role="teacher", force_password_reset=True)
    db.add(perfil)
    await db.flush()
    db.add(Membership(tenant_id=auth.tenant_id, profile_id=perfil.id, role="teacher",
                      is_active=True, full_name=datos.nombre))
    db.add(TeacherGroup(tenant_id=auth.tenant_id, teacher_id=perfil.id, group_id=group.id))
    invitacion = InvitacionDocente(tenant_id=auth.tenant_id, profile_id=perfil.id,
                                   group_id=group.id, correo=datos.correo_normalizado(),
                                   invitada_por=auth.profile_id)
    db.add(invitacion)
    await db.flush()
    await db.refresh(invitacion)
    return invitacion


async def _exigir_correo_nuevo(db: AsyncSession, auth: AuthContext, correo: str) -> None:
    """409 si ESTA institución ya invitó ese correo. Otra institución no cuenta."""
    ya = (await db.execute(select(InvitacionDocente.id).where(
        InvitacionDocente.tenant_id == auth.tenant_id,
        InvitacionDocente.correo == correo))).scalar_one_or_none()
    if ya is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=YA_INVITADO)


async def invitar(db: AsyncSession, auth: AuthContext, datos: InvitacionIn) -> Resultado:
    """§3.1 pasos 3 a 6. No hace commit (lo hace la ruta) ni llama a GoTrue."""
    group = await access.authorize_group(db, auth, datos.group_id)
    await _exigir_tope(db, auth)
    correo = datos.correo_normalizado()
    await _exigir_correo_nuevo(db, auth, correo)
    try:
        invitacion = await _crear_filas(db, auth, group, datos)
    except IntegrityError as exc:
        # Otro admin de la misma institución invitó ese correo en el mismo instante.
        await db.rollback()
        if getattr(exc.orig, "pgcode", None) == _UNIQUE_VIOLADO:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail=YA_INVITADO) from exc
        raise
    await _auditar(db, auth, invitacion.id, "invitar")
    salida = _salida(invitacion, True, datos.nombre, group.group_code)
    return Resultado(salida, PedidoDeEnvio(invitacion.id, invitacion.profile_id, correo))


# =============================================================================
# §3.3 — reenviar
# =============================================================================
async def _exigir_espera(db: AsyncSession, invitacion_id: int) -> None:
    """429 si el último envío de ESTA invitación fue hace menos de la espera (GoTrue no limita, P3)."""
    espera = (await db.execute(text("""
        SELECT extract(epoch FROM (ultimo_envio_en + make_interval(secs => :espera) - now()))
        FROM invitaciones_docente WHERE id = :id
    """), {"id": invitacion_id, "espera": settings.invitacion_espera_reenvio_s})).scalar_one()
    if float(espera) > 0:
        raise _429(ESPERA, math.ceil(float(espera)))


async def reenviar(db: AsyncSession, auth: AuthContext, invitacion_id: int) -> Resultado:
    """§3.3: 404, 409, espera, tope y 202. No hace commit ni llama a GoTrue."""
    actual = await una(db, auth, invitacion_id, para_actualizar=True)
    if actual.estado == ACEPTADA:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=YA_ACEPTADA)
    await _exigir_espera(db, invitacion_id)
    await _exigir_tope(db, auth)
    await db.execute(update(InvitacionDocente)
                     .where(InvitacionDocente.id == invitacion_id,
                            InvitacionDocente.tenant_id == auth.tenant_id)
                     .values(ultimo_envio_en=func.now(), envios=InvitacionDocente.envios + 1))
    await _auditar(db, auth, invitacion_id, "reenviar")
    nueva = await una(db, auth, invitacion_id)
    perfil = (await db.execute(select(InvitacionDocente.profile_id).where(
        InvitacionDocente.id == invitacion_id))).scalar_one()
    return Resultado(nueva, PedidoDeEnvio(invitacion_id, perfil, nueva.correo))
