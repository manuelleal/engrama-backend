"""Tramposos ZG1-ZG13 de la puerta del Grader — `docs/ESPEC_grader_anillo.md` §9.6.

Una versión ROTA a propósito, inyectada con monkeypatch en el módulo donde se
USA; se corre el cuerpo del test real y se exige `AssertionError` con el
mensaje del mecanismo. Aquí se automatiza la DIAGONAL; la matriz completa se
mide aparte (ERR-15, 19 y 23). ZG12 es no-integ.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable, Collection
from typing import Any
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import ProfileOut
from src.curriculo import reapuntar as reapuntar_mod
from src.engrama_core.service import level as level_mod
from src.grader import listas as listas_mod
from src.grader import reglas as reglas_mod
from src.grader import service as service_mod
from src.shared.models import GraderExam, GraderSheet
from src.teachers.service import access as access_mod
from tests.grader import test_lista_y_examen as tl
from tests.grader import test_resultados as tr

Aplicar = Callable[[pytest.MonkeyPatch], None]

_GUARDAR_HOJA = service_mod._guardar_hoja
_RECIBIR = service_mod.recibir


def _parche(modulo: Any, nombre: str, valor: Any) -> Aplicar:
    return lambda mp: mp.setattr(modulo, nombre, valor)


async def _insertar_siempre(db: AsyncSession, examen: Any, hoja: Any, *, profile_id: UUID,
                            profe_id: UUID) -> bool:
    """ZG2: INSERT llano, sin `ON CONFLICT`: reenviar intenta una segunda fila."""
    db.add(GraderSheet(exam_id=examen.id, tenant_id=examen.tenant_id, profile_id=profile_id,
                       numero=hoja.numero, forma=hoja.forma, calificado_en=hoja.calificado_en,
                       aciertos=reglas_mod.aciertos_de(hoja), total=hoja.total,
                       enviada_por=profe_id))
    await db.flush()
    return True


async def _guardar_y_subir_el_nivel(db: AsyncSession, examen: Any, hoja: Any, *,
                                    profile_id: UUID, profe_id: UUID) -> bool:
    """ZG5: una hoja calificada "confirma" C2."""
    await level_mod.record_confirmed_level(
        db, tenant_id=examen.tenant_id, profile_id=profile_id, cefr="C2", source="grader",
        provisional=False, score=None, assessed_at=hoja.calificado_en, event_row_id=None)
    return await _GUARDAR_HOJA(db, examen, hoja, profile_id=profile_id, profe_id=profe_id)


def _el_menor_libre(todos: Collection[int], de_activos: Collection[int]) -> int:
    """ZG7: mira solo a los activos, así que devuelve el número de quien salió."""
    numero = 1
    while numero in de_activos:
        numero += 1
    return numero


async def _examen_sin_institucion(db: AsyncSession, tenant_id: UUID,
                                  codigo: str) -> GraderExam | None:
    """ZG8: el examen se busca solo por su código."""
    return (await db.execute(select(GraderExam).where(GraderExam.codigo == codigo)
                             .order_by(GraderExam.created_at).limit(1))).scalar_one_or_none()


async def _todo_o_nada(db: AsyncSession, auth: Any, lote: Any) -> Any:
    """ZG10: una sola hoja mala tumba el lote entero."""
    examen = await service_mod._examen(db, auth.tenant_id, lote.codigo)
    assert examen is not None
    items = await service_mod._items_del_examen(db, examen.id)
    numeros = await listas_mod.numeros_asignados(db, examen.group_id)
    for hoja in lote.hojas:
        if reglas_mod.motivo_de_rechazo(hoja, codigo=examen.codigo, items_del_examen=items,
                                        numeros=numeros, profe_id=auth.profile_id):
            raise HTTPException(status_code=422, detail="lote_rechazado")
    return await _RECIBIR(db, auth, lote)


async def _nodos_sin_resolver(db: AsyncSession, items: list[Any]) -> list[list[str]]:
    """ZG11: lo que mandó el cliente, tal cual."""
    return [list(item.nodos) for item in items]


class _PerfilSinElCampo:
    """ZG12: `/auth/me` ya no trae `must_change_password`."""

    model_fields = {k: v for k, v in ProfileOut.model_fields.items()
                    if k != "must_change_password"}


async def _no_reapunta(db: AsyncSession, viejo: str, nuevo: str) -> int:
    return 0


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[..., None], str]] = {
    "ZG1": (_parche(access_mod, "_requiere_asignacion", lambda auth, *, only_assigned: False),
            tr.test_gr6_aislamiento_entre_instituciones_y_grupos,
            r"'docente_sin_el_grupo': \(200, 201, 200\)"),
    "ZG2": (_parche(service_mod, "_guardar_hoja", _insertar_siempre),
            tr.test_gr5_reenviar_reemplaza,
            r"GR5: \{'primera': \(200, \(1, 0, \[\]\)\), 'otra_vez': \(500, None\)"),
    "ZG3": (_parche(reglas_mod, "aciertos_de", lambda hoja: hoja.aciertos),
            tr.test_gr7_no_se_confia_en_el_cliente,
            r"GR7: \{'respuesta': \(200, \(3, 0, \[\(3, 'estado_invalido'\)"),
    "ZG4": (_parche(reglas_mod, "ESTADOS", ("marcada", "vacia", "doble", "dudosa")),
            tr.test_gr7_no_se_confia_en_el_cliente, r"GR7: \{'respuesta': \(500, None\)"),
    "ZG5": (_parche(service_mod, "_guardar_hoja", _guardar_y_subir_el_nivel),
            tr.test_gr9_el_nivel_y_las_monedas_no_se_mueven,
            r"'nivel_identico': False, 'tenia': 'A2', 'el_que_no_tenia': \{'cefr': 'C2'"),
    "ZG6": (_parche(service_mod, "misma_huella", lambda examen, huella: True),
            tl.test_gr3_el_examen_se_registra_una_vez, r"'otra_huella': \(200, False\)"),
    "ZG7": (_parche(listas_mod, "siguiente_numero", _el_menor_libre),
            tl.test_gr2_la_lista_numerada_es_estable_y_no_reutiliza,
            # El UNIQUE (group_id, numero) es una segunda barrera: el número de
            # quien salió sigue ocupado, la lista da 500 y el quinto queda sin número.
            r"'sin_el_dos': \[1, 3, 4\], 'el_quinto': None, 'al_final': \[\], 'filas': 4"),
    "ZG8": (_parche(service_mod, "_examen", _examen_sin_institucion),
            tr.test_gr6_aislamiento_entre_instituciones_y_grupos,
            r"'y_registra_el_mismo_codigo': \(409, 'examen_con_otra_huella'\)"),
    "ZG9": (_parche(reglas_mod, "es_acierto", lambda item: item.correcta),
            tr.test_gr7_no_se_confia_en_el_cliente, r"\(9, 'aciertos_no_coinciden'\)"),
    "ZG10": (_parche(service_mod, "recibir", _todo_o_nada),
             tr.test_gr7_no_se_confia_en_el_cliente,
             r"GR7: \{'respuesta': \(422, 'lote_rechazado'\), 'filas': \(1, 15, 0, 0\)"),
    "ZG11": (_parche(service_mod, "_nodos_de", _nodos_sin_resolver),
             tl.test_gr10_cada_item_lleva_sus_nodos,
             r"GR10: \{'con_el_catalogo_vacio': \(201, True\)"),
    "ZG12": (_parche(tl, "ProfileOut", _PerfilSinElCampo), tl.test_gr1_contrato_de_auth_me,
             r"'must_change_password': 'FALTA'"),
    "ZG13": (_parche(reapuntar_mod, "TABLAS", [("grader_exam_items", _no_reapunta)]),
             tl.test_gr10_cada_item_lleva_sus_nodos,
             r"'reapuntadas': 0, 'tras_la_fusion': \['gr.a1.dos'\]"),
}
SIN_BASE = ("ZG12",)


def correr(test_real: Callable[..., None], disponibles: dict[str, Any]) -> None:
    pedidas = inspect.signature(test_real).parameters
    test_real(**{nombre: disponibles[nombre] for nombre in pedidas})


@pytest.mark.integ
@pytest.mark.parametrize("clave", [c for c in TRAMPOSOS if c not in SIN_BASE])
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        correr(test_real, {"integ": integ, "monkeypatch": monkeypatch})


@pytest.mark.parametrize("clave", SIN_BASE)
def test_tramposo_puro_pone_rojo_su_test(monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        test_real()
