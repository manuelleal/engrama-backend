"""El número de lista de un grupo — ESPEC_grader_anillo §1.1.

El número NACE aquí: la primera vez que se pide la lista, cada estudiante
activo recibe el siguiente libre, en orden de matrícula. Desde ahí es estable,
y el de quien sale del grupo NO se reutiliza (su fila se queda).
"""
from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.grader.schemas import EstudianteNumeradoOut
from src.shared.models import GraderListNumber, Group, Membership

NUMERO_MAXIMO = 9999
LISTA_LLENA = "lista_llena"


def siguiente_numero(todos: Collection[int], de_activos: Collection[int]) -> int:
    """El siguiente al MAYOR que se haya dado alguna vez en el grupo.

    `de_activos` no se usa a propósito: mirar solo a los que siguen en el
    grupo devolvería el número de quien salió.
    """
    return max(todos, default=0) + 1


async def numeros_asignados(db: AsyncSession, group_id: UUID) -> dict[int, UUID]:
    """`{numero: profile_id}` de TODOS los números dados en el grupo (también de quien salió)."""
    filas = (await db.execute(
        select(GraderListNumber.numero, GraderListNumber.profile_id)
        .where(GraderListNumber.group_id == group_id))).all()
    return {numero: perfil for numero, perfil in filas}


async def _activos(db: AsyncSession, grupo: Group) -> list[tuple[UUID, str]]:
    """Los estudiantes activos del grupo, en orden de matrícula. El nombre, el de la membresía."""
    filas = (await db.execute(
        select(Membership.profile_id, Membership.full_name)
        .where(Membership.tenant_id == grupo.tenant_id,
               Membership.group_code == grupo.group_code,
               Membership.role == "student", Membership.is_active.is_(True))
        .order_by(Membership.created_at, Membership.id))).all()
    return [(perfil, nombre or "") for perfil, nombre in filas]


async def lista_numerada(db: AsyncSession, grupo: Group) -> list[EstudianteNumeradoOut]:
    """La lista de los activos, dando número a quien no tenga. No hace `commit`."""
    # Candado sobre el grupo: dos peticiones a la vez no reparten el mismo número.
    await db.execute(select(Group.id).where(Group.id == grupo.id).with_for_update())
    activos = await _activos(db, grupo)
    dados = await numeros_asignados(db, grupo.id)
    por_perfil = {perfil: numero for numero, perfil in dados.items()}
    for perfil, _nombre in activos:
        if perfil in por_perfil:
            continue
        de_activos = [por_perfil[p] for p, _ in activos if p in por_perfil]
        numero = siguiente_numero(list(por_perfil.values()), de_activos)
        if numero > NUMERO_MAXIMO:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=LISTA_LLENA)
        db.add(GraderListNumber(tenant_id=grupo.tenant_id, group_id=grupo.id,
                                profile_id=perfil, numero=numero))
        por_perfil[perfil] = numero
    await db.flush()
    lista = [EstudianteNumeradoOut(numero=por_perfil[perfil], student_id=perfil,
                                   full_name=nombre) for perfil, nombre in activos]
    return sorted(lista, key=lambda e: e.numero)
