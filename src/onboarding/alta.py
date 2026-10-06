"""El alta: institución, personas y cuentas — `docs/ESPEC_login_piloto.md` §1.7.

Orden de una corrida (`correr_alta`):
  1. Se valida TODO el CSV (`leer_csv`). Con un solo error no se escribe nada.
  2. En UNA transacción: la institución (tenant + billetera) y las personas
     (perfil, membresía, grupo, y M2/M3 con los servicios de siempre).
     Cualquier error -> ROLLBACK de todo, y se reporta la fila.
  3. Después del commit, una cuenta de GoTrue por persona (`asegurar_cuenta`).

Idempotente: una segunda corrida con el mismo CSV no crea nada, no recarga la
billetera y NO toca ni la contraseña ni la bandera de una cuenta que ya existe.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.onboarding.csv_personas import FilaPersona, Persona, leer_csv, personas
from src.onboarding.cuentas import CORREO_EN_USO, CREADA, CuentasAdmin, ErrorCuenta
from src.onboarding.salida import anotar, clave_temporal
from src.shared.models import CoinWallet, Group, Membership, Profile, Tenant
from src.teachers.schemas import GroupCreateIn
from src.teachers.service import roster

Sesiones = async_sessionmaker[AsyncSession]

CUENTA_EXISTENTE = "cuenta_existente"
CUENTA_CON_OTRO_CORREO = "cuenta_con_otro_correo"


@dataclass
class Resumen:
    """Lo que la CLI imprime al final, en JSON. NUNCA lleva contraseñas ni correos."""

    institucion: str
    institucion_creada: bool = False
    personas: int = 0
    perfiles_nuevos: int = 0
    membresias_nuevas: int = 0
    grupos_nuevos: int = 0
    cuentas_nuevas: int = 0
    cuenta_existente: int = 0
    cuenta_con_otro_correo: int = 0
    errores: list[dict[str, Any]] = field(default_factory=list)

    def error(self, fila: int, motivo: str) -> None:
        self.errores.append({"fila": fila, "motivo": motivo})

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


class ErrorDeAlta(Exception):
    """Una fila chocó con la base: se deshace TODO y se reporta esa fila."""

    def __init__(self, fila: int, motivo: str) -> None:
        super().__init__(f"fila {fila}: {motivo}")
        self.fila = fila
        self.motivo = motivo


# =============================================================================
# 2. La institución y las personas (una transacción; el commit lo hace quien llama)
# =============================================================================
async def asegurar_institucion(db: AsyncSession, nombre: str, slug: str,
                               monedas: int) -> tuple[Tenant, bool]:
    """El tenant de `slug`. Devuelve (tenant, ¿se creó ahora?).

    Si no existe, nace con `coin_pool = monedas` y su billetera con ese saldo:
    es la EMISIÓN de monedas de la institución, y por eso `--monedas` no tiene
    valor por defecto. Si ya existe se reusa y la billetera NUNCA se recarga:
    correr el alta dos veces no puede duplicar el dinero.
    """
    tenant = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if tenant is not None:
        return tenant, False
    tenant = Tenant(id=uuid4(), name=nombre, slug=slug, coin_pool=monedas)
    db.add(tenant)
    await db.flush()
    db.add(CoinWallet(tenant_id=tenant.id, owner_type="tenant", owner_id=tenant.id,
                      currency="COIN", balance=monedas))
    await db.flush()
    return tenant, True


async def _asegurar_grupo(db: AsyncSession, tenant_id: UUID, codigo: str,
                          resumen: Resumen) -> Group:
    grupo = (await db.execute(
        select(Group).where(Group.tenant_id == tenant_id, Group.group_code == codigo)
    )).scalar_one_or_none()
    if grupo is None:
        grupo = await roster.create_group(db, tenant_id, GroupCreateIn(group_code=codigo))  # M1
        resumen.grupos_nuevos += 1
    return grupo


async def _asegurar_perfil(db: AsyncSession, documento_id: str, rol: str,
                           resumen: Resumen) -> Profile:
    """El perfil de ese documento; si falta, nace como en M3 (`uuid4`, sin nombre ni PIN)."""
    perfil = await roster.get_profile_by_documento(db, documento_id)
    if perfil is None:
        perfil = Profile(id=uuid4(), documento_id=documento_id, full_name="", pin_hash="",
                         role=rol)
        db.add(perfil)
        await db.flush()
        resumen.perfiles_nuevos += 1
    return perfil


async def _asegurar_membresia(db: AsyncSession, tenant_id: UUID, perfil: Profile,
                              f: FilaPersona, resumen: Resumen) -> None:
    """Membresía `admin` o `teacher`, con el nombre del CSV. Si ya existe, no se pisa."""
    membresia = (await db.execute(
        select(Membership).where(Membership.tenant_id == tenant_id,
                                 Membership.profile_id == perfil.id)
    )).scalar_one_or_none()
    if membresia is None:
        db.add(Membership(tenant_id=tenant_id, profile_id=perfil.id, role=f.rol,
                          is_active=True, full_name=f.nombre))
        await db.flush()
        resumen.membresias_nuevas += 1
    elif membresia.role != f.rol:
        raise ErrorDeAlta(f.fila, f"ya tiene el rol {membresia.role!r} en esta institución")
    elif not membresia.is_active:
        raise ErrorDeAlta(f.fila, "su membresía está inactiva en esta institución")


async def sembrar_fila(db: AsyncSession, tenant: Tenant, f: FilaPersona,
                       resumen: Resumen) -> UUID:
    """Una fila del CSV en la base. Devuelve el `profiles.id` de la persona."""
    if f.rol == "student":
        grupo = await _asegurar_grupo(db, tenant.id, f.grupo or "", resumen)
        if await roster.get_profile_by_documento(db, f.documento_id) is None:
            resumen.perfiles_nuevos += 1
        perfil, resultado = await roster.enroll_student(  # M3
            db, tenant.id, grupo, f.documento_id, f.nombre)
        if resultado == "inscrito":
            resumen.membresias_nuevas += 1
        return UUID(str(perfil.id))
    perfil = await _asegurar_perfil(db, f.documento_id, f.rol, resumen)
    await _asegurar_membresia(db, tenant.id, perfil, f, resumen)
    if f.rol == "teacher":
        grupo = await _asegurar_grupo(db, tenant.id, f.grupo or "", resumen)
        await roster.assign_teacher(db, tenant.id, grupo, f.documento_id)  # M2
    return UUID(str(perfil.id))


async def escribir_en_base(db: AsyncSession, nombre: str, slug: str, monedas: int,
                           filas: list[FilaPersona], resumen: Resumen) -> dict[str, UUID]:
    """Institución y personas en la transacción de `db`. NO hace commit.

    Devuelve `documento_id -> profiles.id`. Un choque (p. ej. el 409 de M3: el
    estudiante ya está en otro grupo) sale como `ErrorDeAlta` con su fila.
    """
    tenant, resumen.institucion_creada = await asegurar_institucion(db, nombre, slug, monedas)
    perfiles: dict[str, UUID] = {}
    for f in filas:
        try:
            perfiles[f.documento_id] = await sembrar_fila(db, tenant, f, resumen)
        except HTTPException as exc:
            raise ErrorDeAlta(f.fila, str(exc.detail)) from exc
    return perfiles


# =============================================================================
# 3. Las cuentas (después del commit)
# =============================================================================
async def marcar_clave_temporal(sesiones: Sesiones, perfil_id: UUID) -> None:
    """`force_password_reset = true`, COMMITEADO, en su propia sesión."""
    async with sesiones() as db:
        await db.execute(
            update(Profile).where(Profile.id == perfil_id).values(force_password_reset=True))
        await db.commit()


async def asegurar_cuenta(sesiones: Sesiones, cuentas: CuentasAdmin, perfil_id: UUID,
                          correo: str, clave: str) -> str:
    """La cuenta de GoTrue de un perfil, con `id = profiles.id` (el vínculo, §1.1).

    Si la cuenta ya existe NO se toca: ni su contraseña ni su bandera (la
    persona quizá ya la cambió).

    Si no existe, el orden importa (H-3): PRIMERO la bandera, commiteada, y
    DESPUÉS la cuenta. Si el proceso muere en el medio queda un perfil con la
    bandera y sin cuenta: inocuo (nadie puede entrar) y la próxima corrida lo
    completa. Al revés quedaría una cuenta con una contraseña temporal que no
    obliga a cambiarse, y la próxima corrida no la tocaría: fallaría abierto.
    """
    actual = await cuentas.buscar(perfil_id)
    if actual is not None:
        return CUENTA_EXISTENTE if actual.lower() == correo.lower() else CUENTA_CON_OTRO_CORREO
    await marcar_clave_temporal(sesiones, perfil_id)
    return await cuentas.crear(perfil_id, correo, clave)


async def crear_cuentas(sesiones: Sesiones, cuentas: CuentasAdmin, gente: list[Persona],
                        perfiles: dict[str, UUID], salida: Path, resumen: Resumen) -> None:
    """Una cuenta por persona. Un fallo es de ESA fila: las demás siguen."""
    for p in gente:
        clave = clave_temporal()
        try:
            resultado = await asegurar_cuenta(sesiones, cuentas, perfiles[p.documento_id],
                                              p.correo, clave)
        except ErrorCuenta as exc:
            resumen.error(p.fila, f"cuenta no creada: {exc}")
            continue
        if resultado == CREADA:
            # Se anota de inmediato: si la corrida muere después, la clave no se pierde.
            anotar(salida, nombre=p.nombre, correo=p.correo, rol=p.rol, grupos=p.grupos,
                   clave=clave)
            resumen.cuentas_nuevas += 1
        elif resultado == CORREO_EN_USO:
            resumen.error(p.fila, "cuenta no creada: el correo ya es de otra cuenta")
        else:
            resumen.cuenta_existente += 1
            if resultado == CUENTA_CON_OTRO_CORREO:
                resumen.cuenta_con_otro_correo += 1


# =============================================================================
# La corrida completa
# =============================================================================
async def correr_alta(*, nombre: str, slug: str, monedas: int, contenido: bytes, salida: Path,
                      cuentas: CuentasAdmin, sesiones: Sesiones) -> Resumen:
    """`alta` de punta a punta. El resumen trae `errores` si algo no se hizo."""
    resumen = Resumen(institucion=slug)
    filas, errores = leer_csv(contenido, slug)
    if errores:
        for e in errores:
            resumen.error(e.fila, e.motivo)
        return resumen  # todo o nada: ni la institución
    gente = personas(filas)
    resumen.personas = len(gente)
    async with sesiones() as db:
        try:
            perfiles = await escribir_en_base(db, nombre, slug, monedas, filas, resumen)
            await db.commit()
        except ErrorDeAlta as exc:
            await db.rollback()
            fallido = Resumen(institucion=slug, personas=len(gente))
            fallido.error(exc.fila, exc.motivo)
            return fallido
    await crear_cuentas(sesiones, cuentas, gente, perfiles, salida, resumen)
    return resumen
