"""Que ningún 422 de validación devuelva lo que el cliente envió — `docs/ESPEC_422_sin_eco.md`.

El problema (medido contra el backend real): el 422 de fábrica de FastAPI
incluye el valor rechazado en `input`. En el registro llegó a devolver la
contraseña. Es el formato de Pydantic v2: cada error trae `type`, `loc`, `msg`,
`input` y, a veces, `ctx` y `url`. Y es peor que un campo suelto: cuando FALTA
un campo, el `input` de ese error es el CUERPO ENTERO.

Primero se cerró solo en el registro y en el cambio de contraseña, con una clase
de ruta (ESPEC_autorregistro §13.1). Ahora se cierra para TODA la API en un solo
lugar: un manejador global de `RequestValidationError` (`instalar`, que llama
`src/main.py`). Una ruta nueva queda cubierta sin que nadie se acuerde de nada.

Qué se quita de cada error:
  - `input`, siempre.
  - de `ctx`, todo lo que no sea un límite o un "se esperaba" que pone el
    servidor. Ahí viajan datos derivados de lo enviado: el detalle del
    analizador de un UUID (`found `N` at 3`: un carácter del valor y su
    posición), la etiqueta de una unión, el largo real...
  - del `msg`, ese mismo detalle cuando Pydantic lo copió ahí.
Qué NO se toca: `loc`, `type`, `url` y el `msg` de todo lo demás. La web lee
`loc`, `msg` (con el prefijo `Value error, ` de nuestros validadores) y `type`.

No pasan por aquí los 422 del dominio (`HTTPException(422, detail="...")`): su
`detail` no es una lista de errores de validación.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

CAMPO_CON_EL_VALOR_ENVIADO = "input"

# Las claves de `ctx` que pone el SERVIDOR (el límite, el patrón, lo esperado).
# Es una lista de lo permitido y no de lo prohibido a propósito: una clave que
# Pydantic agregue mañana queda fuera hasta que alguien la mire.
CLAVES_DE_CTX_DEL_SERVIDOR = frozenset({
    "min_length", "max_length", "pattern", "gt", "ge", "lt", "le", "multiple_of",
    "expected", "max_digits", "max_decimal_places", "max_whole_digits", "field_type",
    "discriminator", "expected_tags", "expected_schemes", "tz_expected", "class_name",
})

# `ctx.error` es el detalle de quien rechazó el valor. Solo se conserva donde no
# puede traer nada de lo enviado: en los errores de NUESTROS validadores (un
# `ValueError` de texto fijo; al serializarse sale `{}`) y en el JSON roto (la
# frase fija del decodificador de Python: "Unterminated string starting at").
# En los demás tipos lo escribe el analizador de Pydantic a partir del valor.
CLAVE_DE_ERROR = "error"
TIPOS_QUE_CONSERVAN_SU_ERROR = frozenset({"value_error", "assertion_error", "json_invalid"})

# Lo que queda en `msg` cuando traía un dato de `ctx` que se quitó y no estaba
# al final (donde basta cortarlo). En inglés, como los demás `msg` de Pydantic.
MENSAJE_NEUTRO = "Invalid value"


def _se_conserva(tipo: Any, clave: str) -> bool:
    if clave in CLAVES_DE_CTX_DEL_SERVIDOR:
        return True
    return clave == CLAVE_DE_ERROR and tipo in TIPOS_QUE_CONSERVAN_SU_ERROR


def _msg_sin(msg: str, quitados: list[str]) -> str:
    """El `msg` sin los textos de `ctx` que se quitaron.

    Las plantillas de Pydantic ponen el detalle del analizador al final
    (`Input should be a valid UUID, {error}`): ahí se corta y queda la frase
    general. Si el dato está en otra parte de la frase no hay corte limpio, y se
    cambia la frase entera por una neutra (`loc` y `type` siguen diciendo qué pasó).
    """
    for texto in quitados:
        if msg.endswith(texto):
            msg = msg[:-len(texto)].rstrip(" ,:;")
        if texto in msg:
            return MENSAJE_NEUTRO
    return msg or MENSAJE_NEUTRO


def _error_sin_valores(error: Mapping[str, Any]) -> dict[str, Any]:
    limpio = {clave: valor for clave, valor in error.items()
              if clave != CAMPO_CON_EL_VALOR_ENVIADO}
    ctx = error.get("ctx")
    if not isinstance(ctx, Mapping):
        return limpio
    tipo = error.get("type")
    quitados = [valor for clave, valor in ctx.items()
                if not _se_conserva(tipo, clave) and isinstance(valor, str) and valor]
    ctx_limpio = {clave: valor for clave, valor in ctx.items() if _se_conserva(tipo, clave)}
    if ctx_limpio or not ctx:
        limpio["ctx"] = ctx_limpio
    else:
        del limpio["ctx"]  # no quedó nada: la clave sobra
    if quitados and isinstance(error.get("msg"), str):
        limpio["msg"] = _msg_sin(error["msg"], quitados)
    return limpio


def sin_valores_enviados(errores: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Copia de los errores de validación sin nada de lo enviado (no toca lo que recibe)."""
    return [_error_sin_valores(error) for error in errores]


async def responder_sin_eco(request: Request, exc: Exception) -> JSONResponse:
    """El 422 de fábrica de FastAPI (`{"detail": [...]}`), con la lista limpia.

    `sin_valores_enviados` se busca en el módulo en cada llamada: así sus
    tramposos la reemplazan con `monkeypatch` y la ruta real usa la rota.
    """
    errores = exc.errors() if isinstance(exc, RequestValidationError) else []
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        content={"detail": jsonable_encoder(sin_valores_enviados(errores))})


def instalar(app: FastAPI) -> None:
    """Registra el manejador en la aplicación: cubre todas las rutas, las de hoy y las que vengan."""
    app.add_exception_handler(RequestValidationError, responder_sin_eco)
