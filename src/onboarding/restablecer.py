"""`restablecer`: contraseña temporal nueva para UNA persona — ESPEC_login_piloto §1.7.

Sin SMTP no hay "olvidé mi contraseña": esta es la salida. La corre el
operador, por persona:

    python -m src.onboarding restablecer --slug <slug> --documento <doc> --salida <ruta>

`--documento` es el `documento_id` tal como está en la base (opaco, D1): los
dígitos del documento nacional, o el código ya con su prefijo (`sena_7`).

El documento debe tener una membresía ACTIVA en esa institución y una cuenta;
si no, error y 0 cambios. Así el operador no puede restablecer, por un error
de tipeo en el `slug`, a alguien de otra institución.

Orden, igual que en el alta (H-3): PRIMERO la bandera, commiteada, y DESPUÉS
la contraseña. Si `cambiar_clave` falla, la persona queda obligada a cambiar
una contraseña que sigue siendo la suya: falla cerrado.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.onboarding.alta import Sesiones, marcar_clave_temporal
from src.onboarding.cuentas import CuentasAdmin, ErrorCuenta
from src.onboarding.salida import anotar, clave_temporal
from src.shared.models import Group, Membership, Tenant, TeacherGroup
from src.teachers.service.roster import get_profile_by_documento


@dataclass(frozen=True)
class Destinatario:
    """A quién se le restablece: lo mínimo para la cuenta y para el archivo."""

    perfil_id: UUID
    nombre: str
    rol: str
    grupos: tuple[str, ...]


async def _grupos_del_docente(db: AsyncSession, tenant_id: UUID, perfil_id: UUID,
                              ) -> tuple[str, ...]:
    filas = await db.execute(
        select(Group.group_code)
        .join(TeacherGroup, TeacherGroup.group_id == Group.id)
        .where(TeacherGroup.teacher_id == perfil_id, Group.tenant_id == tenant_id)
        .order_by(Group.group_code)
    )
    return tuple(str(codigo) for codigo in filas.scalars())


async def buscar_destinatario(db: AsyncSession, slug: str,
                              documento_id: str) -> Destinatario | str:
    """El destinatario, o el motivo por el que no se puede restablecer."""
    tenant = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if tenant is None:
        return f"no existe la institución {slug!r}"
    perfil = await get_profile_by_documento(db, documento_id)
    membresia = None
    if perfil is not None:
        membresia = (await db.execute(
            select(Membership).where(Membership.tenant_id == tenant.id,
                                     Membership.profile_id == perfil.id,
                                     Membership.is_active.is_(True))
        )).scalar_one_or_none()
    if perfil is None or membresia is None:
        # El mismo mensaje en los dos casos: no delata si el documento existe en otra.
        return "ese documento no tiene una membresía activa en esta institución"
    if membresia.role == "teacher":
        grupos = await _grupos_del_docente(db, tenant.id, perfil.id)
    else:
        grupos = (membresia.group_code,) if membresia.group_code else ()
    return Destinatario(perfil_id=UUID(str(perfil.id)), nombre=membresia.full_name or "",
                        rol=membresia.role, grupos=grupos)


async def correr_restablecer(*, slug: str, documento_id: str, salida: Path,
                             cuentas: CuentasAdmin, sesiones: Sesiones) -> dict[str, object]:
    """Devuelve el resumen: `{"restablecidas": 1}` o `{"restablecidas": 0, "error": ...}`."""
    def fallo(motivo: str) -> dict[str, object]:
        return {"institucion": slug, "restablecidas": 0, "error": motivo}

    async with sesiones() as db:
        quien = await buscar_destinatario(db, slug, documento_id)
    if isinstance(quien, str):
        return fallo(quien)
    try:
        correo = await cuentas.buscar(quien.perfil_id)
        if correo is None:
            return fallo("esa persona no tiene cuenta: se crea con `alta`")
        clave = clave_temporal()
        await marcar_clave_temporal(sesiones, quien.perfil_id)  # la bandera primero (H-3)
        await cuentas.cambiar_clave(quien.perfil_id, clave)
    except ErrorCuenta as exc:
        return fallo(f"la contraseña no se cambió: {exc}")
    anotar(salida, nombre=quien.nombre, correo=correo, rol=quien.rol, grupos=quien.grupos,
           clave=clave)
    return {"institucion": slug, "restablecidas": 1}
