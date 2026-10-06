"""CN6 y su tramposo ZH13 — `docs/ESPEC_endurecimiento_piloto.md`, H-13.

Con `AVISO_VERSIONES_VALIDAS` puesta, el consentimiento y el registro aceptan
SOLO una versión de la lista: cualquier otra da 422 y no escribe. Con la lista
vacía no hay restricción (lo de antes). Sin la lista, cualquier usuario podía
crear filas de consentimiento sin tope (auditoría 02).
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from src.auth import consentimiento as consentimiento_mod
from src.shared.config import settings
from tests.auth import test_consentimiento as cn
from tests.registro import _ayuda as ay

pytestmark = pytest.mark.integ


@pytest.fixture(autouse=True)
def _dejar_todo_como_estaba() -> Iterator[None]:
    antes = settings.aviso_versiones_validas
    yield
    settings.aviso_versiones_validas = antes
    ay.soltar()


def _aceptar(integ: Any, perfil: Any, version: str) -> tuple[int, Any]:
    r = cn.aceptar(integ, perfil, {"version": version})
    return r.status_code, cn._json(r).get("detail")


def test_cn6_solo_las_versiones_de_la_lista(integ) -> None:
    """CN6 (H-13): con la lista `v-a, v-b`, `v-c` da 422 sin escribir; vacía, todo pasa."""
    ay.preparar(integ)
    ana = integ.crear_perfil(integ.crear_tenant())
    aula = ay.aula(integ)
    settings.aviso_versiones_validas = " v-a , v-b,"
    con_lista = {
        "consentimiento_v_a": _aceptar(integ, ana, "v-a"),
        "consentimiento_v_c": _aceptar(integ, ana, "v-c"),
        "filas": cn.filas(integ, ana),
        "registro_v_c": ay.estado_y_cuerpo(ay.registrar(ay.cuerpo(aula.codigo, 1,
                                                                  aviso_version="v-c"))),
        "perfiles_del_registro": ay.perfil_de(integ, aula.doc(1)),
        "registro_v_b": ay.registrar(ay.cuerpo(aula.codigo, 1, aviso_version="v-b")).status_code,
    }
    settings.aviso_versiones_validas = ""
    observado = {"con_lista": con_lista, "lista_vacia_v_c": _aceptar(integ, ana, "v-c")}
    no_permitida = "aviso_version_no_permitida"
    assert observado == {
        "con_lista": {
            "consentimiento_v_a": (200, None), "consentimiento_v_c": (422, no_permitida),
            "filas": ["v-a"], "registro_v_c": (422, {"detail": no_permitida}),
            "perfiles_del_registro": None, "registro_v_b": 201},
        "lista_vacia_v_c": (200, None),
    }, f"CN6: {observado}"


def test_zh13_tramposo_toda_version_es_permitida(integ, monkeypatch) -> None:
    """ZH13: si la validación siempre dice que sí, `v-c` entra con la lista puesta."""
    monkeypatch.setattr(consentimiento_mod, "version_permitida", lambda version: True)
    with pytest.raises(AssertionError, match=r"'consentimiento_v_c': \(200, None\)"):
        test_cn6_solo_las_versiones_de_la_lista(integ)
