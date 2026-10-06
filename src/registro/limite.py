"""Límite de intentos del registro, en memoria — `docs/ESPEC_autorregistro.md` §1.6.

Ventana deslizante, sin dependencias. Es POR PROCESO: con dos procesos de
uvicorn el tope efectivo es hasta el doble, y reiniciar lo pone en cero.

La IP del visitante la da `ip_del_visitante`, una función pura. Nunca se usa
un valor de `X-Forwarded-For` que el visitante haya podido escribir.
"""
from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable

VENTANA_S = 600
MAX_LLAVES = 20_000
IP_DESCONOCIDA = "desconocida"


def ip_del_visitante(client_host: str | None, x_forwarded_for: str | None, saltos: int) -> str:
    """La IP con la que se cuenta el límite.

    `saltos` es cuántos proxies PROPIOS hay delante del backend
    (`PROXIES_DE_CONFIANZA`). Cada uno agrega AL FINAL de `X-Forwarded-For` la
    IP que vio, así que la del visitante es el valor `saltos`-ésimo contando
    desde el final. Todo lo que quede a su izquierda lo pudo escribir el
    visitante: se ignora.

    Con `saltos == 0` no se lee el encabezado: vale la IP de la conexión.
    Si el encabezado trae menos valores que `saltos`, la petición no vino por
    la cadena esperada: todas esas comparten la llave `desconocida`.
    """
    if saltos <= 0:
        return client_host or IP_DESCONOCIDA
    valores = [v.strip() for v in (x_forwarded_for or "").split(",") if v.strip()]
    if len(valores) < saltos:
        return IP_DESCONOCIDA
    return valores[-saltos]


class Limitador:
    """A lo sumo `tope` eventos por llave en `ventana_s` segundos."""

    def __init__(self, tope: int, *, ventana_s: float = VENTANA_S, max_llaves: int = MAX_LLAVES,
                 reloj: Callable[[], float] = time.monotonic) -> None:
        self.tope = tope
        self.ventana_s = ventana_s
        self.max_llaves = max_llaves
        self.reloj = reloj
        self._eventos: dict[str, deque[float]] = {}

    def _vigentes(self, llave: str, ahora: float) -> deque[float] | None:
        """Los eventos de la llave que siguen dentro de la ventana, o `None`."""
        marcas = self._eventos.get(llave)
        if marcas is None:
            return None
        while marcas and marcas[0] <= ahora - self.ventana_s:
            marcas.popleft()
        if not marcas:
            del self._eventos[llave]
            return None
        return marcas

    def purgar(self) -> None:
        """Quita las llaves cuyos eventos ya vencieron."""
        ahora = self.reloj()
        for llave in list(self._eventos):
            self._vigentes(llave, ahora)

    def espera(self, llave: str) -> int:
        """Segundos que faltan para poder anotar otro evento; 0 si ya se puede.

        No anota nada. Si la tabla está llena de llaves vigentes y esta llave
        es nueva, responde la ventana entera: falla cerrado.
        """
        ahora = self.reloj()
        marcas = self._vigentes(llave, ahora)
        if marcas is None:
            if len(self._eventos) >= self.max_llaves:
                self.purgar()
                if len(self._eventos) >= self.max_llaves:
                    return math.ceil(self.ventana_s)
            return 0
        if len(marcas) < self.tope:
            return 0
        return max(1, math.ceil(marcas[0] + self.ventana_s - ahora))

    def anotar(self, llave: str) -> None:
        self._eventos.setdefault(llave, deque()).append(self.reloj())

    def llaves(self) -> int:
        return len(self._eventos)

    def reiniciar(self) -> None:
        self._eventos.clear()


# Los cuatro contadores de la ruta (ESPEC §1.6). Un salón de 40 sale por una
# sola IP y se equivoca al teclear: por eso 150 y 60, y no menos.
POR_IP = Limitador(150)
MALOS_POR_IP = Limitador(60)
POR_CODIGO = Limitador(200)
GLOBAL = Limitador(1000)
_TODOS = (POR_IP, MALOS_POR_IP, POR_CODIGO, GLOBAL)
_LLAVE_GLOBAL = "todos"


def revisar(ip: str, huella_del_codigo: str) -> int:
    """Segundos de espera si algún tope ya se alcanzó; 0 si se puede seguir."""
    return max(POR_IP.espera(ip), MALOS_POR_IP.espera(ip),
               POR_CODIGO.espera(huella_del_codigo), GLOBAL.espera(_LLAVE_GLOBAL))


def anotar(ip: str, huella_del_codigo: str) -> None:
    """Cuenta un intento (antes de saber cómo termina)."""
    POR_IP.anotar(ip)
    POR_CODIGO.anotar(huella_del_codigo)
    GLOBAL.anotar(_LLAVE_GLOBAL)


def anotar_malo(ip: str) -> None:
    """Cuenta un intento con un código que no sirvió (cada 403)."""
    MALOS_POR_IP.anotar(ip)


def reiniciar() -> None:
    for limitador in _TODOS:
        limitador.reiniciar()
