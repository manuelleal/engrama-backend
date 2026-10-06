"""`suspender` y `reactivar`: cortar el acceso de UNA persona — ESPEC_endurecimiento_piloto, H-8.

    python -m src.onboarding suspender --slug <slug> --documento <doc> [--solo-institucion]
    python -m src.onboarding reactivar --slug <slug> --documento <doc>

`suspender` pone `profiles.is_active = false` (el backend responde 403
`account_suspended` en TODA ruta, al instante: se lee de la base en cada
petición) y desactiva la membresía en esa institución.

OJO: el perfil es GLOBAL. Suspender a una persona le corta el acceso en todas
sus instituciones. Con `--solo-institucion` se desactiva solo la membresía y
el perfil queda como está.

No toca GoTrue (la cuenta sigue existiendo, pero no sirve para nada) y no
necesita `--salida`: solo `DATABASE_URL`. `--documento` es el `documento_id`
tal como está en la base, igual que en `restablecer`.
"""
from __future__ import annotations

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.onboarding.alta import Sesiones
from src.shared.models import Membership, Profile, Tenant
from src.teachers.service.roster import get_profile_by_documento

SIN_MEMBRESIA = "ese documento no tiene una membresía en esta institución"


async def _membresia(db: AsyncSession, slug: str, documento_id: str) -> Membership | str:
    """La membresía (activa o no) de ese documento en esa institución, o el motivo."""
    tenant = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if tenant is None:
        return f"no existe la institución {slug!r}"
    perfil = await get_profile_by_documento(db, documento_id)
    membresia = None
    if perfil is not None:
        membresia = (await db.execute(
            select(Membership).where(Membership.tenant_id == tenant.id,
                                     Membership.profile_id == perfil.id)
        )).scalar_one_or_none()
    # El mismo mensaje si el documento no existe o si es de otra institución.
    return membresia if membresia is not None else SIN_MEMBRESIA


async def _aplicar(db: AsyncSession, membresia: Membership, *, activo: bool,
                   tocar_perfil: bool) -> None:
    """La membresía y (salvo `--solo-institucion`) el perfil, más la auditoría."""
    await db.execute(update(Membership).where(Membership.id == membresia.id)
                     .values(is_active=activo))
    if tocar_perfil:
        await db.execute(update(Profile).where(Profile.id == membresia.profile_id)
                         .values(is_active=activo))
    await db.execute(
        text("""
            INSERT INTO audit_logs (tenant_id, user_id, action_type, result, metadata)
            VALUES (:tenant, :quien, :accion, 'success',
                    jsonb_build_object('por', 'operador', 'solo_institucion', CAST(:solo AS boolean)))
        """),
        {"tenant": membresia.tenant_id, "quien": membresia.profile_id,
         "accion": "cuenta_reactivada" if activo else "cuenta_suspendida",
         "solo": not tocar_perfil})


async def correr_suspension(*, slug: str, documento_id: str, activo: bool,
                            solo_institucion: bool, sesiones: Sesiones) -> dict[str, object]:
    """Suspende (`activo=False`) o reactiva. Devuelve el resumen; con `error` no cambió nada."""
    clave = "reactivadas" if activo else "suspendidas"
    async with sesiones() as db:
        membresia = await _membresia(db, slug, documento_id)
        if isinstance(membresia, str):
            return {"institucion": slug, clave: 0, "error": membresia}
        await _aplicar(db, membresia, activo=activo, tocar_perfil=not solo_institucion)
        await db.commit()
    return {"institucion": slug, clave: 1}
