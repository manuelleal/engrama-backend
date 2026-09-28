"""Lógica de `/admin/*` (M1-M4) — ESPEC §2.

`access.py` decide qué grupo puede tocar el admin (`authorize_group`); este
módulo arma M1 (crear grupo), M2 (asignar docente), M3 (matricular un
estudiante) y M4 (importar CSV), en el orden de los commits de la espec (§7).
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.models import Group, Membership, Profile, TeacherGroup
from src.teachers.schemas import GroupCreateIn


# =============================================================================
# M1 — POST /admin/groups
# =============================================================================
async def create_group(db: AsyncSession, tenant_id: UUID, data: GroupCreateIn) -> Group:
    """Crea un grupo. `group_code` repetido en el mismo tenant -> 409."""
    exists = await db.execute(
        select(Group.id).where(Group.tenant_id == tenant_id, Group.group_code == data.group_code)
    )
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"group_code {data.group_code!r} already exists in this tenant",
        )
    group = Group(tenant_id=tenant_id, group_code=data.group_code, max_capacity=data.max_capacity)
    db.add(group)
    await db.flush()
    return group


# =============================================================================
# M2 — POST /admin/groups/{gid}/teachers
# =============================================================================
async def assign_teacher(
    db: AsyncSession, tenant_id: UUID, group: Group, documento_id: str
) -> tuple[Profile, str]:
    """Asigna un docente al grupo. Devuelve (perfil, 'asignado' | 'ya_estaba').

    Exige una `Membership` `teacher` ACTIVA en el tenant (ESPEC M2); si no,
    404 — no delata si el `documento_id` existe en otro colegio o con otro rol.
    """
    profile = (
        await db.execute(select(Profile).where(Profile.documento_id == documento_id))
    ).scalar_one_or_none()
    membership = None
    if profile is not None:
        membership = (
            await db.execute(
                select(Membership).where(
                    Membership.tenant_id == tenant_id, Membership.profile_id == profile.id
                )
            )
        ).scalar_one_or_none()
    if (
        profile is None
        or membership is None
        or membership.role != "teacher"
        or not membership.is_active
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active teacher membership for that documento_id in this tenant",
        )

    existing = (
        await db.execute(
            select(TeacherGroup).where(
                TeacherGroup.teacher_id == profile.id, TeacherGroup.group_id == group.id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return profile, "ya_estaba"

    db.add(TeacherGroup(tenant_id=tenant_id, teacher_id=profile.id, group_id=group.id))
    await db.flush()
    return profile, "asignado"


__all__ = [
    "create_group", "assign_teacher", "enroll_student", "get_profile_by_documento",
    "ErrorFila", "CSVImportError", "parse_csv", "validate_syntax",
    "validate_against_db", "import_csv", "DOC_ID_RE", "MAX_FILAS_CSV",
]


# =============================================================================
# M3 — POST /admin/groups/{gid}/students
# =============================================================================
async def get_profile_by_documento(db: AsyncSession, documento_id: str) -> Profile | None:
    """Busca un `Profile` por `documento_id` (único, `002:101`)."""
    return (
        await db.execute(select(Profile).where(Profile.documento_id == documento_id))
    ).scalar_one_or_none()


async def enroll_student(
    db: AsyncSession, tenant_id: UUID, group: Group, documento_id: str, nombre_completo: str
) -> tuple[Profile, str]:
    """Matricula un estudiante en `group`. Devuelve (perfil, 'inscrito' | 'ya_estaba').

    Crea el `Profile` si falta (`uuid4`, `pin_hash=''`, `full_name=''`,
    ESPEC M3); si ya existe (quizá lo creó OTRO colegio), lo REUSA: la
    identidad es global por `documento_id`.

    El nombre que escribe el colegio va en SU membresía, nunca en el perfil
    (BUG-11, `docs/ESPEC_bug11.md`): así dos colegios que matriculan el mismo
    documento ven cada uno el nombre que escribieron. Si la membresía ya
    existía (`ya_estaba`), NO se pisa su nombre.

    409 si la membresía existente en este tenant tiene otro rol, está
    inactiva o es de otro grupo.
    """
    profile = await get_profile_by_documento(db, documento_id)
    if profile is None:
        # `full_name=''`: el perfil no guarda datos de un colegio (BUG-11).
        # Mismo precedente que `pin_hash=''`.
        profile = Profile(
            id=uuid4(), documento_id=documento_id, full_name="",
            pin_hash="", role="student",
        )
        db.add(profile)
        await db.flush()

    membership = (
        await db.execute(
            select(Membership).where(
                Membership.tenant_id == tenant_id, Membership.profile_id == profile.id
            )
        )
    ).scalar_one_or_none()

    if membership is None:
        db.add(
            Membership(
                tenant_id=tenant_id, profile_id=profile.id, role="student",
                group_code=group.group_code, is_active=True,
                full_name=nombre_completo,  # el nombre de ESTE colegio
            )
        )
        await db.flush()
        return profile, "inscrito"

    if membership.role != "student":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{documento_id} already has role {membership.role!r} in this tenant",
        )
    if not membership.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{documento_id} membership is inactive in this tenant",
        )
    if membership.group_code != group.group_code:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{documento_id} is already enrolled in group {membership.group_code!r}",
        )
    return profile, "ya_estaba"


# =============================================================================
# M4 — POST /admin/groups/{gid}/students/import
# =============================================================================
DOC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
MAX_FILAS_CSV = 500


@dataclass(frozen=True)
class ErrorFila:
    """Una fila de CSV rechazada — ESPEC M4: `[{fila, motivo}]`."""

    fila: int
    motivo: str


class CSVImportError(Exception):
    """Se lanza con 1+ `ErrorFila`: "todo o nada", el caller no debe escribir nada."""

    def __init__(self, errores: list[ErrorFila]) -> None:
        super().__init__(f"{len(errores)} fila(s) rechazada(s)")
        self.errores = errores


def parse_csv(contenido: bytes) -> list[dict[str, str]]:
    """Bytes crudos -> lista de dicts (1 por fila de datos, en orden).

    BOM opcional (`utf-8-sig` lo quita si está; si no, no hace nada) y
    separador `,` o `;`, detectado por la cabecera (ESPEC M4). Columnas
    que no sean `documento_id`/`nombre_completo` se ignoran al leerlas
    (nunca se guarda `pin`, que ni siquiera se busca aquí).
    """
    texto = contenido.decode("utf-8-sig")
    lineas = [linea for linea in texto.splitlines() if linea.strip() != ""]
    if not lineas:
        return []
    separador = ";" if ";" in lineas[0] else ","
    lector = csv.DictReader(io.StringIO("\n".join(lineas)), delimiter=separador)
    return [dict(fila) for fila in lector]


def validate_syntax(
    filas_crudas: list[dict[str, str]],
) -> tuple[list[tuple[int, str, str]], list[ErrorFila]]:
    """Sin DB: regex de `documento_id`, nombre no vacío, sin repetidos, ≤500 filas.

    Devuelve (filas válidas como `(fila, documento_id, nombre_completo)`,
    errores). Una fila con error NO entra en las válidas — no se revisa contra
    la base (eso lo hace `validate_against_db`, solo con las que pasaron aquí).
    """
    if len(filas_crudas) > MAX_FILAS_CSV:
        return [], [ErrorFila(fila=0, motivo=f"más de {MAX_FILAS_CSV} filas: {len(filas_crudas)}")]

    errores: list[ErrorFila] = []
    vistas: dict[str, int] = {}
    validas: list[tuple[int, str, str]] = []
    for i, cruda in enumerate(filas_crudas, start=1):
        doc = (cruda.get("documento_id") or "").strip()
        nombre = (cruda.get("nombre_completo") or "").strip()
        if not DOC_ID_RE.match(doc):
            errores.append(ErrorFila(fila=i, motivo=f"documento_id inválido: {doc!r}"))
        elif not nombre:
            errores.append(ErrorFila(fila=i, motivo="nombre_completo vacío"))
        elif doc in vistas:
            errores.append(
                ErrorFila(fila=i, motivo=f"documento_id repetido (ya en la fila {vistas[doc]})")
            )
        else:
            vistas[doc] = i
            validas.append((i, doc, nombre))
    return validas, errores


async def validate_against_db(
    db: AsyncSession, tenant_id: UUID, group: Group, validas: list[tuple[int, str, str]]
) -> list[ErrorFila]:
    """De las filas sintácticamente válidas, cuáles chocan con una membresía existente."""
    errores: list[ErrorFila] = []
    for fila, doc, _nombre in validas:
        profile = await get_profile_by_documento(db, doc)
        if profile is None:
            continue
        membership = (
            await db.execute(
                select(Membership).where(
                    Membership.tenant_id == tenant_id, Membership.profile_id == profile.id
                )
            )
        ).scalar_one_or_none()
        if membership is None:
            continue
        if membership.role != "student":
            errores.append(ErrorFila(fila=fila, motivo=f"{doc}: tiene rol {membership.role!r}"))
        elif not membership.is_active:
            errores.append(ErrorFila(fila=fila, motivo=f"{doc}: membresía inactiva"))
        elif membership.group_code != group.group_code:
            errores.append(
                ErrorFila(fila=fila, motivo=f"{doc}: ya está en el grupo {membership.group_code!r}")
            )
    return errores


async def import_csv(
    db: AsyncSession, tenant_id: UUID, group: Group, contenido: bytes
) -> dict[str, int]:
    """Importa el CSV completo. "Todo o nada": si hay CUALQUIER error, 0 escrituras.

    Orden (ESPEC M4, X8): se VALIDA TODO antes de escribir una sola fila —
    ni siquiera la primera fila válida se inserta si otra fila del mismo
    archivo falla.
    """
    crudas = parse_csv(contenido)
    validas, errores_sintaxis = validate_syntax(crudas)
    errores_db = await validate_against_db(db, tenant_id, group, validas)
    errores = sorted(errores_sintaxis + errores_db, key=lambda e: e.fila)
    if errores:
        raise CSVImportError(errores)

    creados = 0
    ya_estaban = 0
    for _fila, doc, nombre in validas:
        _profile, resultado = await enroll_student(db, tenant_id, group, doc, nombre)
        if resultado == "inscrito":
            creados += 1
        else:
            ya_estaban += 1
    return {"creados": creados, "ya_estaban": ya_estaban, "total": len(validas)}
