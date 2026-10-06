"""Tramposos ZM1-ZM6 del catálogo de nodos — `docs/ESPEC_catalogo_nodos.md` §3.

Una versión ROTA a propósito, inyectada con monkeypatch en el módulo donde se
USA; se corre el cuerpo del test real y se exige `AssertionError` con el
mensaje del mecanismo. Aquí se automatiza la DIAGONAL; la matriz completa se
mide aparte (ERR-15, 19 y 23). ZM6 es no-integ.
"""
from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.curriculo import __main__ as orden_mod
from src.curriculo import carga as carga_mod
from src.curriculo import mapa as mapa_mod
from src.curriculo import service as service_mod
from src.shared.models import CurriculumNode
from tests.curriculo import test_catalogo as tc

Aplicar = Callable[[pytest.MonkeyPatch], None]

_CARGAR = carga_mod.cargar
_DESTINOS = service_mod._destinos
_VIGENTES = service_mod.vigentes


def _parche(modulo: Any, nombre: str, valor: Any) -> Aplicar:
    return lambda mp: mp.setattr(modulo, nombre, valor)


async def _cargar_borrando(db: AsyncSession, mapa: Any) -> dict[str, Any]:
    """ZM1: lo que el archivo no trae, se borra (y así "nada desaparece")."""
    declarados = [n.id for n in mapa.nodos] + list(mapa.reemplazos)
    await db.execute(delete(CurriculumNode).where(CurriculumNode.id.not_in(declarados)))
    return await _CARGAR(db, mapa)


async def _cargar_a_medias(db: AsyncSession, mapa: Any) -> dict[str, Any]:
    """ZM2: escribe y confirma los vigentes ANTES de comprobar lo que desaparece."""
    for valores in carga_mod._filas(mapa, {})[:len(mapa.nodos)]:
        await carga_mod._guardar(db, valores)
    await db.commit()
    return await _CARGAR(db, mapa)


async def _sin_seguir_reemplazos(db: AsyncSession, ids: list[str]) -> dict[str, str]:
    """ZM3: un reemplazado "resuelve" a sí mismo."""
    return {ident: ident for ident in await _DESTINOS(db, ids)}


async def _todo_existe(db: AsyncSession, ids: list[str]) -> dict[str, str]:
    """ZM4: lo que no está en el catálogo pasa tal cual."""
    return {**{ident: ident for ident in ids}, **await _DESTINOS(db, ids)}


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[..., None], str]] = {
    "ZM1": (_parche(orden_mod, "cargar", _cargar_borrando), tc.test_mn2_un_nodo_no_se_borra,
            r"MN2: \{'rechazada': \{'version': 'v2'"),
    "ZM2": (_parche(orden_mod, "cargar", _cargar_a_medias), tc.test_mn2_un_nodo_no_se_borra,
            r"'la_tabla_quedo_identica': False, "
            r"'nuevos_que_se_colaron': \['gr.b1.nuevo-a', 'gr.b1.nuevo-b'\]"),
    "ZM3": (_parche(service_mod, "_destinos", _sin_seguir_reemplazos),
            tc.test_mn3_canonicos_resuelve_y_rechaza, r"'reemplazado': \['gr.a1.viejo'\]"),
    "ZM4": (_parche(service_mod, "_destinos", _todo_existe),
            tc.test_mn3_canonicos_resuelve_y_rechaza,
            r"MN3: \{'con_el_catalogo_vacio': \['gr.a1.dos'\]"),
    "ZM5": (_parche(service_mod, "vigentes",
                    functools.partial(_VIGENTES, incluir_reemplazados=True)),
            tc.test_mn1_la_carga_su_repeticion_y_el_get,
            r"'profe': \(200, 'v1', \['ds.b2.cinco', 'fn.a2.tres', 'gr.a1.dos', "
            r"'gr.a1.mas-viejo'"),
    "ZM6": (_parche(mapa_mod, "exigir_id_nuevo", lambda *_: None),
            tc.test_um1_lectura_pura_del_mapa,
            r"'id_repetido': \{'version': 'v1', 'nodos': \['gr.a1.uno', 'gr.a1.dos', "
            r"'gr.a1.uno'\]"),
}
SIN_BASE = ("ZM6",)


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
