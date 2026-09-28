"""El único punto de autorización de `/teachers` y `/admin` — ESPEC §1.

Toda ruta de los dos routers pasa por aquí para decidir qué grupos puede ver
o tocar `auth`:
  - `visible_groups(db, auth)`: todos los grupos del `auth.tenant_id` si
    `auth.is_admin`; si no, solo los que `teacher_groups` le asigna.
  - `authorize_group(db, auth, group_id)`: el mismo filtro más `id = group_id`;
    sin resultado, 404 (nunca 403 — no delata si el grupo existe en OTRO
    colegio, mismo patrón que `challenges_service.get_challenge`).

BUG-10 (ESPEC §0, §6 "para después"): esto NO toca `/challenges/all` ni
`/core/attendance/sessions/active`, que hoy siguen mostrando todo el colegio
a cualquier docente. Ese hueco queda fuera de esta espec.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.shared.models import Group, TeacherGroup


def _base_stmt(auth: AuthContext):  # type: ignore[no-untyped-def]
    """SELECT de grupos del tenant de `auth`, sin resolver todavía el filtro
    de docente asignado (eso lo agrega el caller con `.where` /  `.join`)."""
    return select(Group).where(Group.tenant_id == auth.tenant_id)


def _requiere_asignacion(auth: AuthContext, *, only_assigned: bool) -> bool:
    """True si hay que exigir `teacher_groups` aunque `auth` sea admin.

    Por defecto (`only_assigned=False`) el admin ve todo su colegio. Las
    rutas de aprendizaje (T5/T7, ERR-16 §1) piden `only_assigned=True`:
    ahí el filtro de asignación se aplica TAMBIÉN al admin.
    """
    if only_assigned:
        return True
    return not auth.is_admin


async def visible_groups(
    db: AsyncSession, auth: AuthContext, *, only_assigned: bool = False
) -> list[Group]:
    """Grupos que `auth` puede ver: todos los del tenant si es admin.

    Si no es admin (es teacher), o si `only_assigned=True` (ERR-16 §1: T5 y
    T7, "solo los ve el docente del grupo"), solo los que tiene en
    `teacher_groups`. Nunca se filtra por otra cosa que `tenant_id` — el
    BUG-10 §0 (un docente del mismo colegio SIN asignación opera un grupo
    ajeno) queda cerrado exactamente por esta línea: sin `tenant_id`, X1 lo
    reabre (ERR-15).
    """
    stmt = _base_stmt(auth)
    if _requiere_asignacion(auth, only_assigned=only_assigned):
        stmt = stmt.join(TeacherGroup, TeacherGroup.group_id == Group.id).where(
            TeacherGroup.teacher_id == auth.profile_id
        )
    result = await db.execute(stmt.order_by(Group.group_code))
    return list(result.scalars().all())


async def authorize_group(
    db: AsyncSession, auth: AuthContext, group_id: UUID, *, only_assigned: bool = False
) -> Group:
    """`visible_groups` + `id = group_id`. 404 si no hay resultado.

    Un grupo de OTRO colegio, o del mismo colegio pero sin asignar a este
    docente (o sin asignar y `only_assigned=True`), dan el mismo 404 — no se
    distingue "no existe" de "no es tuyo".
    """
    stmt = _base_stmt(auth).where(Group.id == group_id)
    if _requiere_asignacion(auth, only_assigned=only_assigned):
        stmt = stmt.join(TeacherGroup, TeacherGroup.group_id == Group.id).where(
            TeacherGroup.teacher_id == auth.profile_id
        )
    group = (await db.execute(stmt)).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return group


__all__ = ["visible_groups", "authorize_group"]
