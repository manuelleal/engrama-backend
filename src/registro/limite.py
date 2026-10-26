"""Límite de intentos del registro — `docs/ESPEC_autorregistro.md` §1.6 y
`docs/ESPEC_limites_registro.md`.

Ventana deslizante de 600 s. Los eventos viven en la tabla `limite_intentos`
(migración 046), que ven TODOS los procesos de uvicorn: con `--workers 2` cada
tope vale lo que dice, no el doble, y reiniciar el backend no lo pone en cero.
Antes vivían en la memoria de cada proceso (auditoría 03, S-3).

La IP del visitante la da `ip_del_visitante`, una función pura. Nunca se usa
un valor de `X-Forwarded-For` que el visitante haya podido escribir.
Una dirección IPv6 se cuenta por su red /64 (`_agrupar`).

En la tabla no se guarda ni la IP ni el código: se guarda una huella HMAC de
la llave (`_llave_guardada`), para que ni la base ni su respaldo diario tengan
direcciones de nadie.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import math
import time
from collections import deque
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from src.shared.config import settings

VENTANA_S = 600
MAX_LLAVES = 20_000
IP_DESCONOCIDA = "desconocida"
# Los bits de red con los que se agrupa una dirección IPv6 (ver `_agrupar`).
PREFIJO_IPV6 = 64
# Cuánto espera una petición por el candado de su IP antes de rendirse, y qué
# `Retry-After` recibe si se rinde (ESPEC_limites_registro §1.3).
ESPERA_CANDADO_MS = 2000
ESPERA_SI_OCUPADO_S = 5
# Cada contador borra sus filas vencidas como mucho una vez por minuto y proceso.
PURGA_CADA_S = 60
# La etiqueta con la que se deriva la llave del HMAC: la huella de una IP en
# esta tabla no sirve para nada más (ni coincide con la huella de un código).
_ETIQUETA = b"engrama-limite-registro-v1"
# El código SQLSTATE de Postgres cuando vence `lock_timeout` (lock_not_available).
_CANDADO_OCUPADO = "55P03"

# Con qué se habla con la base: la sesión de la ruta, o una conexión suelta
# (las pruebas y los procesos hijos de DP1). Las dos tienen `execute`,
# `commit`, `rollback` e `in_transaction`.
Conexion = AsyncSession | AsyncConnection


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
        return _agrupar(client_host or IP_DESCONOCIDA)
    valores = [v.strip() for v in (x_forwarded_for or "").split(",") if v.strip()]
    if len(valores) < saltos:
        return IP_DESCONOCIDA
    return _agrupar(valores[-saltos])


def _agrupar(valor: str) -> str:
    """La llave del límite para esa dirección (auditoría 03, S-3; ESPEC §11.2).

    IPv6 se cuenta por su red /64: es lo que un proveedor le entrega a UNA
    casa o a un servidor, y quien la tiene dispone de 2^64 direcciones. Si la
    llave fuera la dirección completa, rotarlas saltaría el límite sin esfuerzo.
    IPv4 sigue por dirección completa. Una IPv6 que envuelve una IPv4
    (`::ffff:203.0.113.9`) cuenta como esa IPv4. Lo que no es una dirección
    (el `testclient` de las pruebas, `desconocida`) queda igual.
    """
    try:
        ip = ipaddress.ip_address(valor)
    except ValueError:
        return valor
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        # Por el entero: una dirección con zona (`fe80::1%eth0`) no rompe.
        return str(ipaddress.IPv6Network((int(ip), PREFIJO_IPV6), strict=False))
    return str(ip)


def _segundos_de_espera(vigentes: int, mas_antigua: float | None, tope: int,
                        ventana_s: float, ahora: float) -> int:
    """La cuenta de la ventana deslizante, la misma en memoria y en la tabla.

    Con menos eventos vigentes que el tope, 0. Si no, los segundos que faltan
    para que venza el más antiguo (al menos 1).
    """
    if vigentes < tope or mas_antigua is None:
        return 0
    return max(1, math.ceil(mas_antigua + ventana_s - ahora))


class Limitador:
    """A lo sumo `tope` eventos por llave en `ventana_s` segundos, EN MEMORIA.

    Ya no lo usa la ruta (usa `Contador`, compartido). Queda como la versión
    pura del algoritmo: UL1 la prueba con el reloj inyectado y comparte con
    `Contador` la cuenta (`_segundos_de_espera`).
    """

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
        return _segundos_de_espera(len(marcas), marcas[0], self.tope, self.ventana_s, ahora)

    def anotar(self, llave: str) -> None:
        self._eventos.setdefault(llave, deque()).append(self.reloj())

    def llaves(self) -> int:
        return len(self._eventos)

    def reiniciar(self) -> None:
        self._eventos.clear()


def _llave_guardada(contador: str, llave: str) -> str:
    """La huella con la que la llave se guarda en la tabla (HMAC-SHA256, hex).

    La llave del HMAC se deriva del secreto JWT con una etiqueta propia, como
    la huella del código de grupo (`codigos._llave`). Los dos procesos tienen
    el mismo secreto: la misma IP da la misma huella en los dos.
    """
    clave = hmac.new(settings.supabase_jwt_secret.encode(), _ETIQUETA, hashlib.sha256).digest()
    return hmac.new(clave, f"{contador}|{llave}".encode(), hashlib.sha256).hexdigest()


class Contador:
    """A lo sumo `tope` eventos por llave en `ventana_s` segundos, en la tabla compartida.

    `espera` y `anotar` no confirman nada: quien llama decide qué va junto y
    cuándo se confirma (ver `tomar`). `reloj` da segundos de
    pared (`time.time`): los procesos del backend corren en el mismo anfitrión.
    """

    def __init__(self, nombre: str, tope: int, *, ventana_s: float = VENTANA_S,
                 reloj: Callable[[], float] = time.time) -> None:
        self.nombre = nombre
        self.tope = tope
        self.ventana_s = ventana_s
        self.reloj = reloj
        self._ultima_purga = -math.inf

    async def espera(self, conn: Conexion, llave: str) -> int:
        """Segundos que faltan para poder anotar otro evento; 0 si ya se puede. No anota."""
        ahora = self.reloj()
        fila = (await conn.execute(
            text("SELECT count(*), min(momento) FROM limite_intentos "
                 "WHERE contador = :c AND llave = :l AND momento > :desde"),
            {"c": self.nombre, "l": _llave_guardada(self.nombre, llave),
             "desde": ahora - self.ventana_s},
        )).one()
        return _segundos_de_espera(int(fila[0]), fila[1], self.tope, self.ventana_s, ahora)

    async def anotar(self, conn: Conexion, llave: str) -> None:
        """Anota un evento y, si toca, borra los vencidos de este contador."""
        ahora = self.reloj()
        await conn.execute(
            text("INSERT INTO limite_intentos (contador, llave, momento) VALUES (:c, :l, :m)"),
            {"c": self.nombre, "l": _llave_guardada(self.nombre, llave), "m": ahora},
        )
        # Una vez por minuto y proceso; también si el reloj fue hacia atrás.
        if ahora - self._ultima_purga >= PURGA_CADA_S or ahora < self._ultima_purga:
            self._ultima_purga = ahora
            await conn.execute(
                text("DELETE FROM limite_intentos WHERE contador = :c AND momento <= :hasta"),
                {"c": self.nombre, "hasta": ahora - self.ventana_s},
            )

    async def llaves(self, conn: Conexion) -> int:
        """Cuántas llaves distintas tienen eventos vigentes."""
        ahora = self.reloj()
        return int((await conn.execute(
            text("SELECT count(DISTINCT llave) FROM limite_intentos "
                 "WHERE contador = :c AND momento > :desde"),
            {"c": self.nombre, "desde": ahora - self.ventana_s},
        )).scalar_one())

    def reiniciar(self) -> None:
        """Pone en cero lo que el proceso recuerda (el calendario de la purga). No toca la tabla."""
        self._ultima_purga = -math.inf


# Los cuatro contadores de la ruta (ESPEC §1.6). Un salón de 40 sale por una
# sola IP y se equivoca al teclear: por eso 150 y 60, y no menos.
# Los dos primeros cuentan por IP; los otros dos, solo intentos con un código
# de grupo VÁLIDO (`anotar_codigo`). Compartidos por todos los procesos.
POR_IP = Contador("por_ip", 150)
MALOS_POR_IP = Contador("malos_por_ip", 60)
POR_CODIGO = Contador("por_codigo", 200)
GLOBAL = Contador("global", 1000)
_TODOS = (POR_IP, MALOS_POR_IP, POR_CODIGO, GLOBAL)
_LLAVE_GLOBAL = "todos"


async def _candado(conn: Conexion, ip: str) -> None:
    """El candado de la IP hasta el final de la transacción, esperando a lo sumo 2 s.

    Pone en fila a las peticiones simultáneas de una misma IP, vengan del
    proceso que vengan. Sin él, entre revisar y anotar hay un `await`, y una
    ráfaga entera pasaría la revisión antes de que nadie anote.
    """
    await conn.execute(text("SELECT set_config('lock_timeout', :espera, true)"),
                       {"espera": f"{int(ESPERA_CANDADO_MS)}ms"})
    await conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:llave, 0))"),
                       {"llave": "registro:por_ip:" + _llave_guardada("candado", ip)})


def _es_candado_ocupado(exc: DBAPIError) -> bool:
    """Si el error es que venció `lock_timeout` (y no otra cosa)."""
    original = exc.orig
    estado = getattr(original, "sqlstate", None) or getattr(
        getattr(original, "__cause__", None), "sqlstate", None)
    return estado == _CANDADO_OCUPADO


async def revisar(conn: Conexion, ip: str, huella_del_codigo: str) -> int:
    """Segundos de espera si algún tope ya se alcanzó; 0 si se puede seguir."""
    return max(await POR_IP.espera(conn, ip), await MALOS_POR_IP.espera(conn, ip),
               await POR_CODIGO.espera(conn, huella_del_codigo),
               await GLOBAL.espera(conn, _LLAVE_GLOBAL))


async def anotar(conn: Conexion, ip: str) -> None:
    """Cuenta un intento de esa IP (antes de saber cómo termina)."""
    await POR_IP.anotar(conn, ip)


async def _limpia(conn: Conexion) -> None:
    """Deja la sesión sin transacción abierta antes de que el límite escriba.

    El registro (`service.registrar`) confirma o deshace lo suyo antes de
    volver; lo que quedara abierto (un error a medias) se perdería igual, porque
    la ruta no hace `commit` después. Así el `commit` del límite nunca confirma
    algo ajeno.
    """
    if conn.in_transaction():
        await conn.rollback()


async def tomar(conn: Conexion, ip: str, huella_del_codigo: str) -> int:
    """Revisa los cuatro topes y, si se puede, anota el intento de la IP. Todo junto.

    Una sola transacción con el candado de la IP: dos peticiones de la misma IP
    no pasan la revisión a la vez, vengan del proceso que vengan. Se confirma
    enseguida (los otros procesos la ven y el candado se suelta). Devuelve los
    segundos de espera (0 = adelante). Si el candado no llega en
    `ESPERA_CANDADO_MS`, devuelve `ESPERA_SI_OCUPADO_S` (falla cerrado: 429, no 500).

    En la ruta, `conn` es la MISMA sesión del registro, en transacciones
    propias y cortas: así la petición nunca tiene dos conexiones del pool a la
    vez. (Con una conexión aparte durante toda la petición, 15 registros
    simultáneos en un proceso agotan su pool de 15 y se quedan esperándose.)
    """
    await _limpia(conn)
    try:
        await _candado(conn, ip)
        espera = await revisar(conn, ip, huella_del_codigo)
        if espera == 0:
            await anotar(conn, ip)
        await conn.commit()
        return espera
    except DBAPIError as exc:
        await conn.rollback()
        if _es_candado_ocupado(exc):
            return ESPERA_SI_OCUPADO_S
        raise


async def anotar_codigo(conn: Conexion, huella_del_codigo: str, *,
                        valido: bool) -> None:
    """Cuenta el intento en el tope por código y en el global, SOLO si el código servía.

    Auditoría 03, S-3 (ESPEC_autorregistro §11.3). Antes se contaba todo
    intento, sin saber si servía: 1.000 peticiones con códigos inventados
    llenaban el contador global y dejaban a TODOS en 429 por diez minutos.
    Ahora quien no tiene un código válido solo gasta los cupos de su propia IP
    (`POR_IP` y `MALOS_POR_IP`).

    Se llama DESPUÉS de consultar la base. "Válido" es el código de GRUPO
    (existe, activo, vigente y con cupo), aunque el registro termine en 403
    por un código estudiantil que no cabe.
    """
    if not valido:
        return
    await _limpia(conn)
    await POR_CODIGO.anotar(conn, huella_del_codigo)
    await GLOBAL.anotar(conn, _LLAVE_GLOBAL)
    await conn.commit()


async def anotar_malo(conn: Conexion, ip: str) -> None:
    """Cuenta un intento con un código que no sirvió (cada 403)."""
    await _limpia(conn)
    await MALOS_POR_IP.anotar(conn, ip)
    await conn.commit()


async def vaciar(motor: AsyncEngine) -> None:
    """Borra todos los eventos de la tabla y pone en cero lo del proceso (pruebas, operación)."""
    async with motor.begin() as conn:
        await conn.execute(text("DELETE FROM limite_intentos"))
    reiniciar()


def reiniciar() -> None:
    """Pone en cero lo que este proceso recuerda. La tabla no: eso es `vaciar`."""
    for contador in _TODOS:
        contador.reiniciar()
