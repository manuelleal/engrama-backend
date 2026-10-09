"""Que un 422 de validación no devuelva lo que el cliente envió — ESPEC_autorregistro §13.1.

El problema (medido contra el backend real): el 422 de `POST /auth/registro`
incluía el valor rechazado en `input`; por ejemplo, la contraseña. Es el formato
de Pydantic v2: cada error trae `type`, `loc`, `msg`, `input` (y a veces `ctx` y
`url`). Y es peor que un campo suelto: cuando FALTA un campo, el `input` de ese
error es el CUERPO ENTERO (contraseña, código de grupo y correo incluidos).

La solución es quitar `input` de TODOS los errores de la ruta, sin tocar
`loc`, `msg` ni `type` (la web ya lee `msg`). Se hace en una clase de ruta
(`RutaSinEco`) que envuelve el manejador: así cubre todo lo que FastAPI valida
antes de llamarlo, sin importar cuál campo ni cuál validador falló.

No se hizo un manejador global de la aplicación a propósito: quitaría `input` de
todas las rutas (retos, grupos, EVA...) y eso es decisión de Christiam. Se usa
solo donde viaja un secreto: el registro y el cambio de contraseña.
"""
from __future__ import annotations

from collections.abc import Callable, Coroutine, Mapping, Sequence
from typing import Any

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

# El único campo que se quita. `ctx` trae el límite o el patrón (o el mensaje
# fijo de un validador nuestro) y `url` un enlace a la documentación de
# Pydantic: ninguno lleva lo que el cliente envió.
CAMPO_CON_EL_VALOR_ENVIADO = "input"


def sin_valores_enviados(errores: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Copia de los errores de validación sin `input` (no toca la lista que recibe)."""
    return [{clave: valor for clave, valor in error.items()
             if clave != CAMPO_CON_EL_VALOR_ENVIADO} for error in errores]


class RutaSinEco(APIRoute):
    """Una ruta cuyos 422 de validación no traen de vuelta los valores enviados."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        manejador = super().get_route_handler()

        async def sin_eco(request: Request) -> Response:
            try:
                return await manejador(request)
            except RequestValidationError as exc:
                # Se vuelve a lanzar con los mismos errores menos `input`. No se
                # pasa `body=`: el cuerpo crudo tampoco debe viajar. `from None`
                # para que el error original (con los valores) no quede encadenado.
                raise RequestValidationError(sin_valores_enviados(exc.errors())) from None

        return sin_eco
