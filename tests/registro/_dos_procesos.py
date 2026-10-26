"""Proceso hijo de DP1 — `docs/ESPEC_limites_registro.md` C3.

No empieza por `test_`: pytest no lo recolecta. Lo lanza
`tests/registro/test_limite_compartido.py` dos veces a la vez, como dos
procesos de uvicorn: cada uno con su propio motor contra la MISMA base.

Cada proceso:
  1. abre sus `--n` conexiones (abrir una cuesta ~100 ms en Docker de Windows:
     si se abrieran sobre la marcha, las llamadas quedarían escalonadas y una
     carrera no se vería);
  2. espera hasta `--empezar-en` (para que los dos arranquen juntos) y hace,
     a la vez, `--n` llamadas a `limite.tomar`, cada una desde una dirección
     DISTINTA del mismo /64 (`--red`), con `POR_IP.tope = --tope` y una pausa
     de 20 ms entre revisar y anotar (en el bueno y en los tramposos por igual);
  3. anota 3 códigos válidos (`anotar_codigo`), que suben el contador global;
  4. imprime en la última línea un JSON con lo que vio.

`--modo` elige qué código corre:
  - `bueno`: el de `src/registro/limite.py`.
  - `memoria` (tramposo ZR41): los contadores guardan en la memoria del proceso,
    con el `Limitador` de antes (el código de `f7f7aeb`).
  - `sin_candado` (tramposo ZR42): `_candado` no hace nada.

Guarda: solo acepta la URL del contenedor de pruebas (127.0.0.1 y el puerto del
arnés: 55432 o el de ENGRAMA_TEST_PG_PUERTO).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from typing import Any

PAUSA_S = 0.02


def _en_memoria(limite: Any) -> None:
    """ZR41: cada `Contador` guarda en un `Limitador` de este proceso, como antes."""
    memoria: dict[str, Any] = {}

    def _de(contador: Any) -> Any:
        lim = memoria.setdefault(contador.nombre, limite.Limitador(
            contador.tope, ventana_s=contador.ventana_s, reloj=contador.reloj))
        lim.tope = contador.tope
        return lim

    async def espera(self: Any, conn: Any, llave: str) -> int:
        return int(_de(self).espera(llave))

    async def anotar(self: Any, conn: Any, llave: str) -> None:
        _de(self).anotar(llave)

    setattr(limite.Contador, "espera", espera)
    setattr(limite.Contador, "anotar", anotar)


def _sin_candado(limite: Any) -> None:
    """ZR42: revisar y anotar sin poner en fila a las peticiones de la misma IP."""
    async def nada(conn: Any, ip: str) -> None:
        return None

    setattr(limite, "_candado", nada)


async def _correr(url: str, red: str, n: int, etiqueta: str,
                  empezar_en: float) -> dict[str, Any]:
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from src.registro import limite

    revisar_de_verdad = limite.revisar

    async def revisar_con_pausa(conn: Any, ip: str, huella: str) -> int:
        espera = int(await revisar_de_verdad(conn, ip, huella))
        await asyncio.sleep(PAUSA_S)
        return espera

    setattr(limite, "revisar", revisar_con_pausa)
    motor = create_async_engine(url, poolclass=NullPool)

    async def uno(i: int, conn: Any) -> int:
        direccion = f"{red}:{i + 1:x}:{os.getpid() % 65536:x}::{etiqueta}"
        ip = limite.ip_del_visitante(None, direccion, 1)
        return int(await limite.tomar(conn, ip, "huella-dp1"))

    conexiones = list(await asyncio.gather(*(motor.connect() for _ in range(n))))
    try:
        await asyncio.sleep(max(0.0, empezar_en - time.time()))
        inicio = time.time()
        esperas = await asyncio.gather(*(uno(i, c) for i, c in enumerate(conexiones)))
        fin = time.time()
        async with motor.connect() as conn:
            for _ in range(3):
                await limite.anotar_codigo(conn, "huella-dp1", valido=True)
    finally:
        for c in conexiones:
            await c.close()
        await motor.dispose()
    return {"etiqueta": etiqueta, "inicio": inicio, "fin": fin, "tarde_s": inicio - empezar_en,
            "admitidos": sum(1 for e in esperas if e == 0),
            "rechazados_con_espera": sum(1 for e in esperas if e > 0),
            "llaves_vistas": len({limite.ip_del_visitante(
                None, f"{red}:{i + 1:x}:1::1", 1) for i in range(n)})}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--modo", choices=("bueno", "memoria", "sin_candado"), default="bueno")
    p.add_argument("--red", default="2001:db8:77:1")
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--tope", type=int, default=10)
    p.add_argument("--etiqueta", default="a")
    p.add_argument("--empezar-en", type=float, default=0.0)
    a = p.parse_args()
    # El host y el puerto del contenedor de pruebas salen del arnés
    # (`tests/integ_db.py`), que los lee de ENGRAMA_TEST_PG_PUERTO y solo acepta
    # 127.0.0.1 y 55432-55499 (ERR-44): el subproceso hereda el entorno del test.
    from tests.integ_db import HOST, PUERTO

    if f"@{HOST}:{PUERTO}/" not in a.url:
        raise SystemExit(f"GUARDA: DP1 solo corre contra el contenedor de pruebas {HOST}:{PUERTO}")

    from src.registro import limite

    limite.POR_IP.tope = a.tope
    if a.modo == "memoria":
        _en_memoria(limite)
    elif a.modo == "sin_candado":
        _sin_candado(limite)
    resultado = asyncio.run(_correr(a.url, a.red, a.n, a.etiqueta, a.empezar_en))
    resultado["modo"] = a.modo
    print(json.dumps(resultado, sort_keys=True))


if __name__ == "__main__":
    main()
