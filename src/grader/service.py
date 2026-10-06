"""Registrar el examen y recibir las hojas — ESPEC_grader_anillo §1.2, §1.3 y §9.

Todo se resuelve dentro de la institución activa del profe (`auth.tenant_id`)
y por la barrera de grupos de siempre (`access.visible_groups`): un grupo o un
examen de otra institución responden 404, igual que uno que no existe.

Este módulo NO llama a `record_confirmed_level` ni a `award_coins`: guardar
hojas no mueve el nivel ni las monedas.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, literal_column, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.curriculo import service as curriculo_service
from src.grader import listas, reglas
from src.grader.schemas import (
    ExamenIn,
    ExamenOut,
    HojaIn,
    ItemExamenIn,
    RechazadaOut,
    ResultadosIn,
    ResultadosOut,
)
from src.shared.models import GraderExam, GraderExamItem, GraderSheet, GraderSheetItem, Group
from src.teachers.service import access as access_service

OTRA_HUELLA = "examen_con_otra_huella"
NO_ENCONTRADO = "Group not found"
EXAMEN_NO_ENCONTRADO = "Exam not found"


async def grupo_del_profe(db: AsyncSession, auth: AuthContext, group_code: str) -> Group:
    """El grupo con ese código, SOLO si `auth` puede verlo. 404 si no (nunca 403)."""
    for grupo in await access_service.visible_groups(db, auth):
        if grupo.group_code == group_code:
            return grupo
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_ENCONTRADO)


async def _examen(db: AsyncSession, tenant_id: UUID, codigo: str) -> GraderExam | None:
    """El examen con ese código EN esa institución (el mismo código en otra no se ve)."""
    return (await db.execute(select(GraderExam).where(
        GraderExam.tenant_id == tenant_id, GraderExam.codigo == codigo))).scalar_one_or_none()


def misma_huella(examen: GraderExam, huella: str) -> bool:
    return examen.huella == huella


def _exigir_la_misma_huella(examen: GraderExam, huella: str) -> None:
    if not misma_huella(examen, huella):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=OTRA_HUELLA)


async def _nodos_de(db: AsyncSession, items: list[ItemExamenIn]) -> list[list[str]]:
    """Los nodos VIGENTES de cada ítem. 422 `nodo_desconocido` si alguno no está en el catálogo."""
    return [await curriculo_service.canonicos(db, item.nodos) for item in items]


def _salida(examen: GraderExam, group_code: str, *, creado: bool) -> ExamenOut:
    return ExamenOut(codigo=examen.codigo, huella=examen.huella, group_code=group_code,
                     n_items=examen.n_items, creado=creado)


async def registrar_examen(db: AsyncSession, auth: AuthContext, datos: ExamenIn) -> ExamenOut:
    """Guarda el examen una vez. Igual otra vez: no cambia nada. Otra huella: 409."""
    grupo = await grupo_del_profe(db, auth, datos.group_code)
    previo = await _examen(db, auth.tenant_id, datos.codigo)
    if previo is not None:
        _exigir_la_misma_huella(previo, datos.huella)
        return _salida(previo, datos.group_code, creado=False)
    nodos = await _nodos_de(db, datos.items)  # antes de escribir: un desconocido deja 0 filas
    nuevo_id = (await db.execute(
        pg_insert(GraderExam).values(
            tenant_id=auth.tenant_id, group_id=grupo.id, codigo=datos.codigo,
            huella=datos.huella, titulo=datos.titulo, nivel=datos.nivel,
            n_items=datos.n_items, created_by=auth.profile_id)
        .on_conflict_do_nothing(constraint="grader_exams_tenant_codigo_key")
        .returning(GraderExam.id))).scalar_one_or_none()
    if nuevo_id is None:  # otro envío lo registró en este instante
        return await registrar_examen(db, auth, datos)
    for posicion, (item, sus_nodos) in enumerate(zip(datos.items, nodos, strict=True), start=1):
        db.add(GraderExamItem(
            exam_id=nuevo_id, posicion=posicion, item_id=item.item_id, origen=item.origen,
            nivel=item.nivel, destreza=item.destreza, tema=item.tema, enunciado=item.enunciado,
            correcta_texto=item.correcta_texto, explicacion=item.explicacion, nodos=sus_nodos))
    await db.flush()
    creado = await _examen(db, auth.tenant_id, datos.codigo)
    assert creado is not None  # recién insertado en esta transacción
    return _salida(creado, datos.group_code, creado=True)


async def _items_del_examen(db: AsyncSession, exam_id: UUID) -> list[str]:
    filas = (await db.execute(select(GraderExamItem.item_id)
                              .where(GraderExamItem.exam_id == exam_id)
                              .order_by(GraderExamItem.posicion))).scalars().all()
    return list(filas)


async def _guardar_hoja(db: AsyncSession, examen: GraderExam, hoja: HojaIn, *,
                        profile_id: UUID, profe_id: UUID) -> bool:
    """Guarda la hoja y sus ítems. True si es NUEVA; False si REEMPLAZÓ a la que había.

    Una sentencia (`ON CONFLICT ... DO UPDATE`): dos envíos a la vez no dejan dos hojas.
    """
    valores = {"tenant_id": examen.tenant_id, "profile_id": profile_id, "forma": hoja.forma,
               "calificado_en": hoja.calificado_en, "aciertos": reglas.aciertos_de(hoja),
               "total": hoja.total, "enviada_por": profe_id}
    fila = (await db.execute(
        pg_insert(GraderSheet).values(exam_id=examen.id, numero=hoja.numero, **valores)
        .on_conflict_do_update(constraint="grader_sheets_exam_numero_key",
                               set_={**valores, "recibida_en": text("now()")})
        .returning(GraderSheet.id, literal_column("(xmax = 0)")))).one()
    hoja_id, nueva = fila[0], bool(fila[1])
    await db.execute(delete(GraderSheetItem).where(GraderSheetItem.sheet_id == hoja_id))
    for item in hoja.items:
        db.add(GraderSheetItem(sheet_id=hoja_id, item_id=item.item_id, estado=item.estado,
                               correcta=reglas.es_acierto(item),
                               elegida_texto=item.elegida_texto,
                               resuelta_por=item.resuelta_por))
    await db.flush()
    return nueva


async def recibir(db: AsyncSession, auth: AuthContext, lote: ResultadosIn) -> ResultadosOut:
    """Hoja por hoja, cada una en SU transacción: una mala no tumba a las demás."""
    examen = await _examen(db, auth.tenant_id, lote.codigo)
    if examen is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=EXAMEN_NO_ENCONTRADO)
    _exigir_la_misma_huella(examen, lote.huella)
    grupo = await grupo_del_profe(db, auth, lote.group_code)
    if grupo.id != examen.group_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_ENCONTRADO)
    items = await _items_del_examen(db, examen.id)
    numeros = await listas.numeros_asignados(db, grupo.id)
    recibidas = reemplazadas = 0
    rechazadas: list[RechazadaOut] = []
    for hoja in lote.hojas:
        motivo = reglas.motivo_de_rechazo(hoja, codigo=examen.codigo, items_del_examen=items,
                                          numeros=numeros, profe_id=auth.profile_id)
        if motivo is not None:
            rechazadas.append(RechazadaOut(numero=hoja.numero, motivo=motivo))
            continue
        nueva = await _guardar_hoja(db, examen, hoja, profile_id=numeros[hoja.numero],
                                    profe_id=auth.profile_id)
        await db.commit()
        recibidas += 1
        reemplazadas += int(not nueva)
    return ResultadosOut(recibidas=recibidas, reemplazadas=reemplazadas, rechazadas=rechazadas)
