"""El límite compartido entre procesos — `docs/ESPEC_limites_registro.md` §2.

  UL4  C5  la llave guardada, pura: huella HMAC estable, sin la IP adentro.
  LC1  C1  (integ) un /64 que rota direcciones cuenta como una sola llave, en la tabla.
  LC2  C2  (integ) una avalancha de códigos inventados desde 40 orígenes no
           bloquea a los demás grupos; el techo global sigue vivo para lo que sirve.
  LC3  C4  (integ) con el candado de la IP ocupado, 429 con Retry-After: 5 (no 500).
  DP1  C3  (integ) dos procesos del sistema operativo contra la misma base: un solo tope.

Las piezas se llaman por su módulo (`limite.…`) para que los tramposos ZR37 a
ZR42 (`tests/tramposos/test_tramposos_limite_compartido*.py`) las alcancen.
Cada cuerpo afirma un dict entero que va en el mensaje.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from typing import Any

import asyncpg  # type: ignore[import-untyped]
import pytest

from src.registro import limite
from src.shared.config import settings
from tests.integ_db import RAIZ_BACKEND
from tests.registro import _ayuda as ay

MALO = "ZZZZ{:04d}"


def _filas(integ: Any, contador: str, llave: str | None = None) -> int:
    """Filas de ese contador en la tabla (de esa llave, si se da)."""
    if llave is None:
        return ay.contar(integ, "select count(*) from limite_intentos where contador = :c",
                         c=contador)
    return ay.contar(integ, "select count(*) from limite_intentos "
                            "where contador = :c and llave = :l",
                     c=contador, l=limite._llave_guardada(contador, llave))


def _desde(ip: str, datos: dict[str, Any]) -> Any:
    """Un registro que llega por el proxy desde esa IP (`PROXIES_DE_CONFIANZA = 1`)."""
    return ay.registrar(datos, **{"X-Forwarded-For": ip})


def _retry(r: Any) -> int:
    return int(r.headers.get("Retry-After", "0"))


# =============================================================================
# UL4 — C5 (la llave guardada, pura)
# =============================================================================
def test_ul4_la_llave_guardada_no_lleva_la_ip() -> None:
    """UL4 (C5): misma entrada, misma huella; otro contador, otra; nada de la IP adentro."""
    red, ipv4 = "2001:db8:a:b::/64", "203.0.113.9"
    una = limite._llave_guardada("por_ip", red)
    observado = {
        "estable": una == limite._llave_guardada("por_ip", red),
        "otro_contador_otra": una != limite._llave_guardada("malos_por_ip", red),
        "otra_ip_otra": una != limite._llave_guardada("por_ip", "2001:db8:a:c::/64"),
        "hex_de_64": [bool(re.fullmatch(r"[0-9a-f]{64}", h)) for h in
                      (una, limite._llave_guardada("por_ip", ipv4))],
        "sin_la_ip_adentro": [p not in h for p, h in (
            ("2001", una), ("db8", una), ("203.0.113", limite._llave_guardada("por_ip", ipv4)),
            ("113", limite._llave_guardada("por_ip", ipv4)))],
    }
    assert observado == {
        "estable": True, "otro_contador_otra": True, "otra_ip_otra": True,
        "hex_de_64": [True, True], "sin_la_ip_adentro": [True, True, True, True],
    }, f"UL4: {observado}"


# =============================================================================
# LC1 — C1 (a: un /64 que rota direcciones, en la ruta y en la tabla)
# =============================================================================
@pytest.mark.integ
def test_lc1_un_64_que_rota_direcciones_es_un_solo_cubo(integ) -> None:
    """LC1 (C1): 61 direcciones distintas del mismo /64 -> el 61 da 429; otro /64 no."""
    ay.preparar(integ)
    red = "2001:db8:a:b"
    saltos = settings.proxies_de_confianza
    try:
        settings.proxies_de_confianza = 1
        rotando = [_desde(f"{red}:{i + 1:x}::{(i * 7919) % 65536:x}",
                          ay.cuerpo(MALO.format(i), 1)) for i in range(61)]
        otro = _desde("2001:db8:a:c::1", ay.cuerpo(MALO.format(99), 1))
    finally:
        settings.proxies_de_confianza = saltos
    observado = {
        "direcciones_distintas": len({f"{red}:{i + 1:x}::{(i * 7919) % 65536:x}"
                                      for i in range(61)}),
        "sesenta": sorted({r.status_code for r in rotando[:60]}),
        "el_61": (rotando[60].status_code, ay.campo(rotando[60], "detail"),
                  _retry(rotando[60]) > 0),
        "otro_64": otro.status_code,
        "llaves_por_ip": ay.llaves(integ, limite.POR_IP),
        "filas_malos_del_64": _filas(integ, "malos_por_ip", f"{red}::/64"),
    }
    assert observado == {
        "direcciones_distintas": 61, "sesenta": [403],
        "el_61": (429, "demasiados_intentos", True), "otro_64": 403,
        "llaves_por_ip": 2, "filas_malos_del_64": 60,
    }, f"LC1: {observado}"


# =============================================================================
# LC2 — C2 (c: la avalancha anónima no bloquea a los demás grupos)
# =============================================================================
@pytest.mark.integ
def test_lc2_la_avalancha_anonima_no_bloquea_a_los_grupos(integ) -> None:
    """LC2 (C2): 40 códigos inventados de 40 orígenes; B y C siguen entrando; el techo vive."""
    ay.preparar(integ)
    b = ay.aula(integ, grupo="GB")
    c = ay.aula(integ, grupo="GC")
    tope, saltos = limite.GLOBAL.tope, settings.proxies_de_confianza
    try:
        limite.GLOBAL.tope = 5
        settings.proxies_de_confianza = 1
        origenes = ([f"198.51.100.{i + 1}" for i in range(20)]
                    + [f"2001:db8:{i + 1:x}:1::5" for i in range(20)])
        basura = [_desde(ip, ay.cuerpo(MALO.format(i), 1)).status_code
                  for i, ip in enumerate(origenes)]
        tras_la_basura = (_filas(integ, "global"), _filas(integ, "por_codigo"))
        grupo_b = [_desde(f"203.0.113.{n}", ay.cuerpo(b.codigo, n)).status_code for n in (1, 2)]
        grupo_c = [_desde(f"203.0.113.{n}", ay.cuerpo(c.codigo, n)).status_code for n in (3, 4)]
        quinto = _desde("203.0.113.5", ay.cuerpo(b.codigo, 5))
        sexto = _desde("203.0.113.6", ay.cuerpo(c.codigo, 6))
        al_final = (ay.llaves(integ, limite.POR_CODIGO), _filas(integ, "global"))
    finally:
        limite.GLOBAL.tope, settings.proxies_de_confianza = tope, saltos
    observado = {
        "basura": basura, "global_y_por_codigo_tras_la_basura": tras_la_basura,
        "grupo_b": grupo_b, "grupo_c": grupo_c, "quinto": quinto.status_code,
        "sexto": (sexto.status_code, ay.campo(sexto, "detail"), _retry(sexto) > 0),
        "llaves_por_codigo_y_filas_global_al_final": al_final,
    }
    assert observado == {
        "basura": [403] * 40, "global_y_por_codigo_tras_la_basura": (0, 0),
        "grupo_b": [201, 201], "grupo_c": [201, 201], "quinto": 201,
        "sexto": (429, "demasiados_intentos", True),
        "llaves_por_codigo_y_filas_global_al_final": (2, 5),
    }, f"LC2: {observado}"


# =============================================================================
# LC3 — C4 (el candado ocupado da 429, no 500)
# =============================================================================
@pytest.mark.integ
def test_lc3_con_el_candado_ocupado_429_y_no_500(integ, monkeypatch) -> None:
    """LC3 (C4): otra conexión tiene el candado de la IP: 429 con Retry-After 5; luego 403."""
    ay.preparar(integ)
    monkeypatch.setattr(limite, "ESPERA_CANDADO_MS", 200)
    llave = "registro:por_ip:" + limite._llave_guardada("candado", "testclient")
    dsn = integ.url.replace("postgresql+asyncpg://", "postgresql://", 1)

    async def con_el_candado_tomado() -> tuple[Any, float]:
        conn = await asyncpg.connect(dsn, timeout=10)
        try:
            await conn.execute("select pg_advisory_lock(hashtextextended($1, 0))", llave)
            inicio = time.perf_counter()
            r = await asyncio.to_thread(ay.registrar, ay.cuerpo(MALO.format(1), 1))
            return r, time.perf_counter() - inicio
        finally:
            await conn.execute("select pg_advisory_unlock_all()")
            await conn.close()

    tomado, segundos = integ.run(con_el_candado_tomado())
    suelto = ay.registrar(ay.cuerpo(MALO.format(2), 1))
    observado = {
        "con_candado_tomado": (tomado.status_code, ay.campo(tomado, "detail"),
                               tomado.headers.get("Retry-After")),
        "no_espero_de_mas": segundos < 5,
        "suelto": suelto.status_code,
        "filas_por_ip": _filas(integ, "por_ip", "testclient"),
    }
    assert observado == {
        "con_candado_tomado": (429, "demasiados_intentos", "5"), "no_espero_de_mas": True,
        "suelto": 403, "filas_por_ip": 1,
    }, f"LC3: {observado}"


# =============================================================================
# DP1 — C3 (b: dos procesos, un solo tope)
# =============================================================================
def medir_dos_procesos(integ: Any, modo: str = "bueno") -> dict[str, Any]:
    """Lanza dos procesos hijos a la vez (`tests/registro/_dos_procesos.py`) y mide la tabla."""
    ay.vaciar_limite(integ)
    empezar = time.time() + 12  # importar y abrir 30 conexiones por proceso
    hijos = [subprocess.Popen(
        [sys.executable, "-m", "tests.registro._dos_procesos", "--url", integ.url,
         "--modo", modo, "--etiqueta", etiqueta, "--empezar-en", str(empezar)],
        cwd=str(RAIZ_BACKEND), env=dict(os.environ), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True) for etiqueta in ("a", "b")]
    salidas = [h.communicate(timeout=240) for h in hijos]
    vistos: list[dict[str, Any]] = []
    for h, (out, err) in zip(hijos, salidas, strict=True):
        lineas = out.strip().splitlines()
        vistos.append(json.loads(lineas[-1]) if h.returncode == 0 and lineas
                      else {"error": err[-800:]})

    async def global_desde_aqui() -> int:
        tope = limite.GLOBAL.tope
        try:
            limite.GLOBAL.tope = 5
            async with integ.engine.connect() as conn:
                return int(await limite.GLOBAL.espera(conn, "todos"))
        finally:
            limite.GLOBAL.tope = tope

    inicios = [float(v.get("inicio", 0.0)) for v in vistos]
    fines = [float(v.get("fin", 0.0)) for v in vistos]
    return {
        "salidas": [h.returncode for h in hijos],
        "se_solaparon": max(inicios) < min(fines),
        "admitidos": sum(int(v.get("admitidos", -100)) for v in vistos),
        "por_proceso": [(v.get("admitidos"), round(float(v.get("tarde_s", -1)), 2),
                         round(float(v.get("fin", 0)) - float(v.get("inicio", 0)), 2))
                        for v in vistos],
        "una_llave_por_proceso": [v.get("llaves_vistas") for v in vistos],
        "filas_por_ip": _filas(integ, "por_ip"),
        "filas_global": _filas(integ, "global"),
        "global_lleno_visto_desde_aqui": integ.run(global_desde_aqui()) > 0,
        "errores": [v["error"] for v in vistos if "error" in v],
    }


@pytest.mark.integ
def test_dp1_dos_procesos_un_solo_tope(integ) -> None:
    """DP1 (C3): 2 procesos x 30 intentos concurrentes, tope 10 -> 10 admitidos, no 20."""
    observado = medir_dos_procesos(integ)
    por_proceso = observado.pop("por_proceso")
    assert observado == {
        "salidas": [0, 0], "se_solaparon": True, "admitidos": 10,
        "una_llave_por_proceso": [1, 1],
        "filas_por_ip": 10, "filas_global": 6, "global_lleno_visto_desde_aqui": True,
        "errores": [],
    }, f"DP1: {observado} | por proceso: {por_proceso}"
