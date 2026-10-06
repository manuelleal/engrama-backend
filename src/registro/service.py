"""Registrar a quien llega con un código de grupo — `docs/ESPEC_autorregistro.md` §1.3 y §1.5.

Perfil primero, cuenta después (el orden del login piloto), en dos
transacciones cortas con la llamada a GoTrue EN MEDIO:

  T1  candado del código, perfil + membresía inactiva + solicitud `creando`,
      un uso del código. COMMIT.
  --  GoTrue: crear la cuenta con `id = profiles.id`.
  T2  solicitud a `pendiente`, consentimiento y auditoría. COMMIT.

No se llama a GoTrue con una transacción abierta: la ruta es pública, y un
GoTrue lento dejaría conexiones y el candado del código tomados.

Si la cuenta no se crea, se COMPENSA: se borra el perfil (todo lo suyo cae en
cascada) y se devuelve el uso. Si ni siquiera se puede confirmar que no hay
cuenta, las filas se quedan en `creando`: nadie entra con ellas y el profe no
las ve (falla cerrado). Las recoge el siguiente intento con ese documento.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.onboarding.csv_personas import con_prefijo
from src.onboarding.cuentas import CREADA, ErrorCuenta
from src.registro.codigos import huella
from src.registro.cuentas import CuentasDeRegistro
from src.registro.schemas import RegistroIn
from src.shared.models import (
    CodigoInscripcion,
    Consentimiento,
    Group,
    Membership,
    Profile,
    SolicitudInscripcion,
    Tenant,
)
from src.teachers.service import roster

logger = logging.getLogger("engrama.registro")

CODIGO_NO_VALIDO = "codigo_no_valido"
# Lo que `registrar` devuelve. La ruta responde LO MISMO en los tres casos.
CREADO, OCUPADO, CORREO_EN_USO = "creado", "ocupado", "correo_en_uso"
# Opción (a) de la espec §1.1: nadie entra sin que su profe lo apruebe.
NACE_ACTIVA = False
# Una solicitud `creando` más vieja que esto es un registro que no terminó.
HUERFANO_S = 60
_UNIQUE_VIOLADO = "23505"


class CodigoNoValido(Exception):
    """El código no sirve. `motivo` es SOLO para el log: la respuesta no lo dice."""

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


class RegistroNoDisponible(Exception):
    """GoTrue no respondió o falló: 502."""


@dataclass(frozen=True)
class Reserva:
    """Lo que dejó T1: el perfil recién creado, su solicitud y el código usado."""

    profile_id: UUID
    solicitud_id: int
    codigo_id: int
    tenant_id: UUID


def detalle_de_rechazo(motivo: str) -> str:
    """El `detail` del 403: el mismo para todo motivo (el código no se puede enumerar)."""
    return CODIGO_NO_VALIDO


# =============================================================================
# T1 — la reserva
# =============================================================================
async def _codigo_con_candado(db: AsyncSession, huella_del_codigo: str,
                              ) -> tuple[CodigoInscripcion, bool] | None:
    """La fila del código, BLOQUEADA, y si sigue vigente según el reloj de la base.

    El `FOR UPDATE` hace que dos registros con el mismo código pasen de uno en
    uno: el segundo lee `usos` ya actualizado.
    """
    fila = (await db.execute(
        select(CodigoInscripcion, CodigoInscripcion.expires_at > func.now())
        .where(CodigoInscripcion.codigo_hash == huella_del_codigo)
        .with_for_update(of=CodigoInscripcion)
    )).first()
    return None if fila is None else (fila[0], bool(fila[1]))


def _rechazo(codigo: CodigoInscripcion, vigente: bool) -> str | None:
    """Por qué no sirve el código, o `None` si sirve."""
    if not codigo.activo:
        return "apagado"
    if not vigente:
        return "vencido"
    if codigo.usos >= codigo.cupo:
        return "sin_cupo"
    return None


async def _grupo_del_codigo(db: AsyncSession, codigo: CodigoInscripcion) -> tuple[Group, Tenant]:
    """El grupo y la institución salen de la fila del código, nunca del cuerpo."""
    group = (await db.execute(select(Group).where(
        Group.id == codigo.group_id, Group.tenant_id == codigo.tenant_id))).scalar_one()
    tenant = (await db.execute(select(Tenant).where(Tenant.id == codigo.tenant_id))).scalar_one()
    return group, tenant


async def _borrar_perfil_y_devolver_uso(db: AsyncSession, profile_id: UUID,
                                        codigo_id: int) -> None:
    """Deshace T1. La membresía, la solicitud y el consentimiento caen en cascada."""
    await db.execute(delete(Profile).where(Profile.id == profile_id))
    await db.execute(
        update(CodigoInscripcion).where(CodigoInscripcion.id == codigo_id)
        .values(usos=func.greatest(CodigoInscripcion.usos - 1, 0))
    )


async def _recoger_huerfano(db: AsyncSession, cuentas: CuentasDeRegistro,
                            perfil: Profile) -> bool:
    """Si el perfil es un registro que no terminó (`creando` y viejo), lo deshace.

    Devuelve True si lo recogió. La cuenta se borra PRIMERO: si GoTrue no
    confirma, el perfil no se toca.
    """
    solicitud = (await db.execute(
        select(SolicitudInscripcion).where(
            SolicitudInscripcion.profile_id == perfil.id,
            SolicitudInscripcion.estado == "creando",
            SolicitudInscripcion.created_at < func.now() - func.make_interval(0, 0, 0, 0, 0, 0,
                                                                             HUERFANO_S))
    )).scalar_one_or_none()
    if solicitud is None:
        return False
    try:
        await _borrar_cuenta(cuentas, perfil.id)
    except ErrorCuenta as exc:
        await db.rollback()
        logger.error("registro: no se pudo recoger un registro a medias: %s", exc)
        raise RegistroNoDisponible() from exc
    await _borrar_perfil_y_devolver_uso(db, perfil.id, solicitud.codigo_id)
    await db.flush()
    return True


async def _ocupado(db: AsyncSession, cuentas: CuentasDeRegistro, documento: str) -> bool:
    """¿Ese código estudiantil ya tiene perfil? (ya se registró, o entró por lista).

    Un perfil que ya existe NUNCA se toca desde el registro: ni se le crea
    cuenta ni se le cambia el correo. La única excepción es el huérfano.
    """
    perfil = await roster.get_profile_by_documento(db, documento)
    if perfil is None:
        return False
    return not await _recoger_huerfano(db, cuentas, perfil)


async def _escribir_reserva(db: AsyncSession, codigo: CodigoInscripcion, group: Group,
                            documento: str, datos: RegistroIn) -> Reserva:
    """Perfil y membresía (por la matrícula de siempre), solicitud `creando` y un uso.

    La membresía nace con `is_active = NACE_ACTIVA` (falso): no entra hasta
    que su profe la apruebe. No hace commit.
    """
    perfil, _ = await roster.enroll_student(db, codigo.tenant_id, group, documento,
                                            datos.nombre)
    await db.execute(update(Membership).where(
        Membership.tenant_id == codigo.tenant_id, Membership.profile_id == perfil.id
    ).values(is_active=NACE_ACTIVA))
    solicitud = SolicitudInscripcion(
        tenant_id=codigo.tenant_id, group_id=group.id, codigo_id=codigo.id,
        profile_id=perfil.id, estado="creando", declaro_mayor_de_edad=datos.mayor_de_edad)
    db.add(solicitud)
    codigo.usos = codigo.usos + 1
    await db.flush()
    return Reserva(perfil.id, solicitud.id, codigo.id, codigo.tenant_id)


async def _reservar(db: AsyncSession, cuentas: CuentasDeRegistro,
                    datos: RegistroIn) -> Reserva | None:
    """T1. `None` si el código estudiantil ya estaba ocupado. Hace COMMIT o ROLLBACK."""
    encontrado = await _codigo_con_candado(db, huella(datos.codigo))
    motivo = "inexistente" if encontrado is None else _rechazo(*encontrado)
    if encontrado is None or motivo is not None:
        await db.rollback()
        raise CodigoNoValido(motivo or "inexistente")
    codigo = encontrado[0]
    group, tenant = await _grupo_del_codigo(db, codigo)
    documento = con_prefijo(tenant.slug, datos.codigo_estudiantil)
    if not roster.DOC_ID_RE.fullmatch(documento):
        await db.rollback()
        raise CodigoNoValido("documento")
    if await _ocupado(db, cuentas, documento):
        await db.rollback()
        return None
    # Si se recogió un huérfano, el UPDATE le devolvió un uso a su código (que
    # puede ser este): se relee la fila, que sigue bloqueada.
    await db.refresh(codigo)
    try:
        reserva = await _escribir_reserva(db, codigo, group, documento, datos)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        # Solo un UNIQUE (23505): otro registro creó ese documento en el mismo
        # instante, con el código de otro grupo. Es un "ocupado" más. Cualquier
        # otra violación (p. ej. el CHECK del cupo) NO se calla: es un defecto.
        if getattr(exc.orig, "pgcode", None) != _UNIQUE_VIOLADO:
            raise
        return None
    return reserva


# =============================================================================
# GoTrue y la compensación
# =============================================================================
async def _crear_cuenta(cuentas: CuentasDeRegistro, profile_id: UUID, correo: str,
                        clave: str) -> str:
    """La cuenta nace con el id del perfil: el `sub` del JWT ES `profiles.id`."""
    return await cuentas.crear(profile_id, correo, clave)


async def _borrar_cuenta(cuentas: CuentasDeRegistro, profile_id: UUID) -> None:
    await cuentas.borrar(profile_id)


async def _deshacer(db: AsyncSession, cuentas: CuentasDeRegistro, reserva: Reserva, *,
                    puede_haber_cuenta: bool) -> None:
    """Compensa T1. Si no se puede confirmar que no hay cuenta, deja `creando`."""
    if puede_haber_cuenta:
        try:
            await _borrar_cuenta(cuentas, reserva.profile_id)
        except ErrorCuenta as exc:
            logger.error("registro: solicitud %s queda en 'creando' (no se pudo confirmar "
                         "que no hay cuenta): %s", reserva.solicitud_id, exc)
            return
    await _borrar_perfil_y_devolver_uso(db, reserva.profile_id, reserva.codigo_id)
    await db.commit()


# =============================================================================
# T2 — la confirmación
# =============================================================================
async def _confirmar(db: AsyncSession, reserva: Reserva, datos: RegistroIn) -> None:
    """La cuenta ya existe: la solicitud pasa a `pendiente`, con su consentimiento."""
    await db.execute(update(SolicitudInscripcion)
                     .where(SolicitudInscripcion.id == reserva.solicitud_id)
                     .values(estado="pendiente"))
    await db.execute(
        pg_insert(Consentimiento)
        .values(profile_id=reserva.profile_id, version=datos.aviso_version)
        .on_conflict_do_nothing(constraint="consentimientos_perfil_version"))
    # `user_id` nulo a propósito: `audit_logs.user_id` no tiene ON DELETE, y
    # un perfil rechazado se tiene que poder borrar entero.
    await db.execute(
        text("""
            INSERT INTO audit_logs (tenant_id, user_id, action_type, result, metadata)
            VALUES (:tenant, NULL, 'registro_solicitado', 'success',
                    jsonb_build_object('solicitud_id', CAST(:solicitud AS bigint),
                                       'aviso_version', CAST(:version AS text),
                                       'declara_mayor_de_edad', true))
        """),
        {"tenant": reserva.tenant_id, "solicitud": reserva.solicitud_id,
         "version": datos.aviso_version})
    await db.commit()


async def registrar(db: AsyncSession, cuentas: CuentasDeRegistro, datos: RegistroIn) -> str:
    """Registra y devuelve `creado`, `ocupado` o `correo_en_uso`.

    Lanza `CodigoNoValido` (403) o `RegistroNoDisponible` (502). Los logs no
    llevan el correo, el nombre ni la contraseña: solo el id de la solicitud.
    """
    reserva = await _reservar(db, cuentas, datos)
    if reserva is None:
        return OCUPADO
    try:
        resultado = await _crear_cuenta(cuentas, reserva.profile_id,
                                        datos.correo_normalizado(), datos.contrasena)
    except ErrorCuenta as exc:
        logger.error("registro: GoTrue falló al crear la cuenta de la solicitud %s: %s",
                     reserva.solicitud_id, exc)
        await _deshacer(db, cuentas, reserva, puede_haber_cuenta=True)
        raise RegistroNoDisponible() from exc
    if resultado != CREADA:
        await _deshacer(db, cuentas, reserva, puede_haber_cuenta=False)
        return CORREO_EN_USO
    await _confirmar(db, reserva, datos)
    logger.info("registro: solicitud %s pendiente", reserva.solicitud_id)
    return CREADO
