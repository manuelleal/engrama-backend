"""Tramposos ZE (no-integ) del 422 sin eco en toda la API — `docs/ESPEC_422_sin_eco.md` §3.

Cada uno es una versión ROTA a propósito, puesta con monkeypatch; se corre el
cuerpo del test real y se exige `AssertionError` con el mensaje del mecanismo.
Se automatiza la diagonal; la matriz completa está medida en la espec (§7).

  ZE1  no hay manejador global (el 422 de fábrica de FastAPI)        -> SE2
  ZE2  el manejador limpia solo el registro y el cambio de contraseña
       (lo que había antes de este cambio)                            -> SE2
  ZE3  `sin_valores_enviados` quita solo `input` (la función anterior:
       deja el detalle del analizador en `ctx` y en `msg`)            -> SE1, SE3
  ZE4  `sin_valores_enviados` deja solo `msg` (rompe la forma)        -> SE5

ZE1 y ZE2 cambian el manejador registrado en la app. Starlette copia los
manejadores al armar su pila de middleware (en la primera petición), así que
además se vacía `app.middleware_stack` para que la arme de nuevo; monkeypatch
devuelve la pila buena al terminar.

El humo de los tests reales se desvía a una carpeta temporal: el archivo de
`tests/_salida` solo lo escribe la corrida buena.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi import Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.main import app
from src.shared import validacion
from tests.seguridad import test_422_sin_eco as se

RUTAS_YA_CERRADAS = ("/auth/registro", "/auth/contrasena")


async def _solo_las_dos_rutas(request: Request, exc: Exception) -> JSONResponse:
    """ZE2: limpia el 422 de las dos rutas de antes; el resto sale como de fábrica."""
    assert isinstance(exc, RequestValidationError)
    if request.url.path in RUTAS_YA_CERRADAS:
        return await validacion.responder_sin_eco(request, exc)
    return await request_validation_exception_handler(request, exc)


def _solo_input(errores: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """ZE3: la función de ESPEC_autorregistro §13.1, tal cual (no mira `ctx` ni `msg`)."""
    return [{k: v for k, v in e.items() if k != "input"} for e in errores]


def _solo_msg(errores: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """ZE4: sin `input`, pero también sin `loc` ni `type`."""
    return [{"msg": e.get("msg")} for e in errores]


def _manejador(rota: Callable[..., Any]) -> Callable[[pytest.MonkeyPatch], None]:
    def poner(monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(app.exception_handlers, RequestValidationError, rota)
        monkeypatch.setattr(app, "middleware_stack", None)
    return poner


def _funcion(rota: Callable[..., Any]) -> Callable[[pytest.MonkeyPatch], None]:
    def poner(monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(validacion, "sin_valores_enviados", rota)
    return poner


Registro = dict[str, tuple[Callable[[pytest.MonkeyPatch], None],
                           list[tuple[Callable[[], None], str]]]]

TRAMPOSOS: Registro = {
    "ZE1": (_manejador(request_validation_exception_handler), [
        (se.test_se2_ninguna_ruta_con_cuerpo_devuelve_lo_enviado,
         r"SE2: \d+ problemas en 21 rutas .*devolvió el centinela 'CENTINELA-9f3a7c'"),
    ]),
    "ZE2": (_manejador(_solo_las_dos_rutas), [
        (se.test_se2_ninguna_ruta_con_cuerpo_devuelve_lo_enviado,
         r"SE2: \d+ problemas en 19 rutas .*'POST /auth/consentimiento'.*un error trae `input`"),
    ]),
    "ZE3": (_funcion(_solo_input), [
        (se.test_se1_sin_valores_enviados_quita_input_y_lo_derivado_del_valor,
         r"SE1: quedó el ctx del analizador de UUID"),
        (se.test_se3_ningun_parametro_de_ruta_invalido_devuelve_lo_enviado,
         r"SE3: \d+ problemas en \d+ rutas .*el ctx trae \['error'\].*"
         r"la respuesta depende del valor enviado: .*found `N` at 3.* CONTRA .*found `Z` at 1"),
    ]),
    "ZE4": (_funcion(_solo_msg), [
        (se.test_se5_la_web_sigue_leyendo_loc_msg_y_type_en_las_dos_rutas,
         r"SE5: la web leería .*'loc': None, 'type': None"),
    ]),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                    clave: str) -> None:
    poner, diagonal = TRAMPOSOS[clave]
    monkeypatch.setattr(se, "RUTA_HUMO", tmp_path / "humo_del_tramposo.json")
    poner(monkeypatch)
    for test_real, motivo in diagonal:
        with pytest.raises(AssertionError, match=motivo):
            test_real()
