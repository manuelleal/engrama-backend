"""Un piso de tiempo común para `POST /auth/registro` — ESPEC_autorregistro §12.2 (S-5).

El problema (medido en el despliegue, ESPEC del anillo §15.22): el registro
responde el MISMO 201 cuando la cuenta se creó, cuando el correo ya era de otra
cuenta y cuando el código estudiantil ya estaba inscrito, pero no tarda lo
mismo: 131 ms, 90 ms y 10 ms de mediana. Quien tenga un código de grupo válido
podía, con un cronómetro, saber qué códigos estudiantiles ya están inscritos.

La solución es simple y no inventa trabajo: que TODA respuesta tarde al menos
lo mismo. Se mide cuánto tardó el manejador y se espera lo que falte hasta un
piso (más un pequeño componente aleatorio). La espera es `asyncio.sleep`: no
bloquea el bucle de eventos, así que otras peticiones siguen atendiéndose. No
se calcula ninguna huella "de mentira": solo se espera.

Se envuelve la RUTA entera (`RutaConPiso`) y no cada rama, para que ninguna
respuesta se escape: el 201 en sus tres variantes, el 403 uniforme, el 429, el
502, el 503 y hasta el 422 del cuerpo.

Si un camino tarda MÁS que el piso, no se alarga ni se acorta: ahí el piso ya
no esconde nada, y por eso su valor (`REGISTRO_PISO_MS`) debe quedar por encima
del camino más lento REAL. Eso no se ha medido contra un GoTrue real: lo mide
el despliegue.
"""
from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from fastapi import Request, Response

from src.shared.config import settings
from src.shared.validacion import RutaSinEco

# El componente aleatorio llega hasta esta fracción del piso (0,2 = 20 %): con
# 250 ms, de 0 a 50 ms más. Es para que la respuesta no caiga siempre en el
# mismo milisegundo; no es un secreto.
FRACCION_ALEATORIA = 0.2

# Las tres piezas del tiempo, como atributos del módulo y no como valores por
# defecto de la función: así los tests (y el tramposo que bloquea el bucle)
# las reemplazan aquí y la ruta real las usa.
# Reloj de alta resolución: en Windows `time.monotonic` avanza a saltos de
# ~15 ms y mediría mal una espera de 250 ms.
_ahora: Callable[[], float] = time.perf_counter
_azar: Callable[[], float] = random.random
_dormir: Callable[[float], Awaitable[None]] = asyncio.sleep
# Un `sleep` puede despertar antes de tiempo (la resolución del temporizador);
# como el piso es un "al menos", se vuelve a mirar el reloj y, si falta, se
# duerme el resto. El tope evita girar para siempre si el reloj no avanza.
_MAX_DORMIDAS = 4


def espera_total_s(piso_ms: int, azar: float) -> float:
    """El tiempo mínimo que debe durar la respuesta, en segundos.

    `azar` es un número en `[0, 1)`: 0 da el piso exacto y casi 1 da el piso
    más el 20 %.
    """
    return (piso_ms / 1000.0) * (1.0 + FRACCION_ALEATORIA * azar)


async def esperar(inicio: float, *, piso_ms: int | None = None,
                  ahora: Callable[[], float] | None = None,
                  azar: Callable[[], float] | None = None,
                  dormir: Callable[[float], Awaitable[None]] | None = None) -> float:
    """Espera lo que falte para llegar al piso desde `inicio`. Devuelve lo esperado (s).

    Con piso 0 no espera ni sortea nada. Con un manejador que ya tardó más que
    el piso, no espera. Los cuatro parámetros opcionales son para los tests;
    la ruta real no pasa ninguno.
    """
    piso = settings.registro_piso_ms if piso_ms is None else piso_ms
    if piso <= 0:
        return 0.0
    reloj = ahora or _ahora
    sorteo = azar or _azar
    dormir_ = dormir or _dormir
    objetivo = espera_total_s(piso, sorteo())
    esperado = 0.0
    for _ in range(_MAX_DORMIDAS):
        falta = objetivo - (reloj() - inicio)
        if falta <= 0:
            break
        await dormir_(falta)
        esperado += falta
    return esperado


class RutaConPiso(RutaSinEco):
    """Una ruta cuya respuesta, sea la que sea, tarda al menos el piso común.

    Hereda de `RutaSinEco`: el 422 del registro tampoco devuelve lo que se
    envió (ESPEC §13.1). El piso envuelve POR FUERA, así que ese 422 también
    espera.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        manejador = super().get_route_handler()

        async def con_piso(request: Request) -> Response:
            inicio = _ahora()
            try:
                respuesta = await manejador(request)
            except Exception:
                # También los errores (403, 429, 502, 503, el 422 del cuerpo):
                # salen como `HTTPException` o `RequestValidationError`, y su
                # tiempo no debe distinguirlos del 201.
                await esperar(inicio)
                raise
            await esperar(inicio)
            return respuesta

        return con_piso
