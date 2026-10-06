"""Las tres rutas de `/grader` — ESPEC_grader_anillo §1.

Todas con `require_teacher` (el Bearer del profe; un admin también pasa) y con
el grupo resuelto por `access.visible_groups`. Sin secretos compartidos.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.grader import listas, service
from src.grader.schemas import ExamenIn, ExamenOut, ListaOut, ResultadosIn, ResultadosOut
from src.shared.db import get_db
from src.shared.deps import require_teacher

router = APIRouter()

CODIGO_NO_COINCIDE = "codigo_no_coincide"


@router.get("/grupos/{group_code}/lista", response_model=ListaOut,
            status_code=status.HTTP_200_OK)
async def leer_lista(
    group_code: str,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> ListaOut:
    """La lista numerada del grupo. Es un GET que ESCRIBE: da número a quien no tenga."""
    grupo = await service.grupo_del_profe(db, auth, group_code)
    estudiantes = await listas.lista_numerada(db, grupo)
    await db.commit()
    return ListaOut(group_code=grupo.group_code, estudiantes=estudiantes)


@router.put("/examenes/{codigo}", response_model=ExamenOut, status_code=status.HTTP_201_CREATED)
async def registrar_examen(
    codigo: str,
    datos: ExamenIn,
    response: Response,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> ExamenOut:
    """201 la primera vez; 200 si llega igual; 409 si el código existe con otra huella."""
    if codigo != datos.codigo:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=CODIGO_NO_COINCIDE)
    salida = await service.registrar_examen(db, auth, datos)
    await db.commit()
    if not salida.creado:
        response.status_code = status.HTTP_200_OK
    return salida


@router.post("/resultados", response_model=ResultadosOut, status_code=status.HTTP_200_OK)
async def recibir_resultados(
    lote: ResultadosIn,
    auth: AuthContext = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> ResultadosOut:
    """Un lote de hojas calificadas: cada hoja entra o se rechaza por separado."""
    return await service.recibir(db, auth, lote)
