"""S-7 hasta el final — `docs/ESPEC_confirmar_protegido.md` §2.

  AR30  C50  si `crear` falla con algo que NO es `ErrorCuenta` después de que
             GoTrue creó la cuenta, la cuenta se borra y no queda nada a medias.

T2 ya estaba protegida (AR12, `656b2f0`). Esto protege el paso anterior: la
llamada a GoTrue. Un `ErrorCuenta` ya se compensaba (AR8); cualquier otra
excepción (un 2xx con cuerpo ilegible, un defecto del adaptador) subía como
500 y dejaba la cuenta viva con la solicitud en `creando`: el estudiante
"espera a su profe" y el profe nunca lo ve.

Las piezas se llaman por su módulo para que el tramposo ZR50 las alcance.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest

from tests.cuentas_falsas import CuentasFalsas
from tests.registro import _ayuda as ay

pytestmark = pytest.mark.integ

NO_DISPONIBLE = (502, {"detail": "registro_no_disponible"})


@pytest.fixture(autouse=True)
def _soltar_el_doble_al_terminar() -> Iterator[None]:
    """El doble de GoTrue no puede quedar puesto para el resto de la suite."""
    yield
    ay.soltar()


def crea_y_revienta(cuentas: CuentasFalsas, excepcion: type[Exception] = ValueError) -> Any:
    """Un `crear` que SÍ crea la cuenta y después lanza algo que no es `ErrorCuenta`.

    Es lo que pasa si GoTrue responde 201 con un cuerpo que no se puede leer:
    la cuenta ya nació. El mensaje lleva el correo a propósito: no debe llegar
    a los logs.
    """
    crear_bueno = cuentas.crear

    async def crear(id: UUID | None, correo: str, clave: str) -> str:
        await crear_bueno(id, correo, clave)
        raise excepcion(f"cuerpo ilegible de GoTrue para {correo}")

    return crear


def _tras_el_fallo(integ: Any, cuentas: CuentasFalsas, a: ay.Aula, n: int,
                   r: Any) -> dict[str, Any]:
    pedido = cuentas.creadas[-1][0] if cuentas.creadas else None
    return {
        "respuesta": ay.estado_y_cuerpo(r),
        "borrar_la_cuenta_del_perfil": pedido is not None and cuentas.borradas[-1:] == [pedido],
        "cuenta": pedido in cuentas.cuentas,
        "perfil": ay.perfil_de(integ, a.doc(n)) is not None,
        "solicitudes": [e for _, e in ay.solicitudes(integ, group_id=a.grupo)],
        "usos": ay.usos(integ, a.grupo),
    }


def test_ar30_si_crear_falla_con_cualquier_cosa_no_queda_cuenta(integ, caplog) -> None:
    """AR30 (C50): `crear` crea y revienta -> 502, la cuenta se borra; el reintento entra."""
    cuentas = ay.preparar(integ)
    caplog.set_level(logging.DEBUG)
    a = ay.aula(integ)
    crear_bueno = cuentas.crear
    datos = ay.cuerpo(a.codigo, 1)
    cuentas.crear = crea_y_revienta(cuentas)  # type: ignore[method-assign]
    inesperado = _tras_el_fallo(integ, cuentas, a, 1, ay.registrar(datos))
    inesperado["el_correo_en_los_logs"] = datos["correo"].lower() in caplog.text.lower()
    cuentas.crear = crear_bueno  # type: ignore[method-assign]
    inesperado["reintento"] = ay.registrar(datos).status_code
    inesperado["tras_el_reintento"] = [e for _, e in ay.solicitudes(integ, group_id=a.grupo)]
    inesperado["en_la_lista_del_profe"] = len(ay.lista(integ, a.profe, a.grupo) or [])

    # Si además GoTrue no deja borrar: no se puede afirmar que no haya cuenta,
    # así que las filas se quedan en `creando` (falla cerrado, §1.5).
    b = ay.aula(integ)
    cuentas.crear = crea_y_revienta(cuentas)  # type: ignore[method-assign]
    cuentas.fallar_borrar = True
    sin_borrar = _tras_el_fallo(integ, cuentas, b, 2, ay.registrar(ay.cuerpo(b.codigo, 2)))
    sin_borrar["lista_del_profe"] = ay.lista(integ, b.profe, b.grupo)

    observado = {"inesperado": inesperado, "y_no_se_puede_borrar": sin_borrar}
    assert observado == {
        "inesperado": {"respuesta": NO_DISPONIBLE, "borrar_la_cuenta_del_perfil": True,
                       "cuenta": False, "perfil": False, "solicitudes": [], "usos": 0,
                       "el_correo_en_los_logs": False, "reintento": 201,
                       "tras_el_reintento": ["pendiente"], "en_la_lista_del_profe": 1},
        "y_no_se_puede_borrar": {"respuesta": NO_DISPONIBLE,
                                 "borrar_la_cuenta_del_perfil": True, "cuenta": True,
                                 "perfil": True, "solicitudes": ["creando"], "usos": 1,
                                 "lista_del_profe": []},
    }, f"AR30: {observado}"
