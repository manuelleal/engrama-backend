"""El piso de tiempo del registro (S-5) — `docs/ESPEC_autorregistro.md` §12.2.

  UP1  C27  el piso, puro: reloj, azar y sueño inyectados.
  UP2  C28  la espera no bloquea el bucle de eventos.
  AR18 C29  en la ruta, los cuatro caminos (`creado`, `correo_en_uso`, `ocupado`
            y el 403) quedan pegados en el tiempo con el piso, y sin él no.

Las piezas se llaman por su módulo (`piso._dormir`, `piso._azar`,
`piso.esperar`) para que los tramposos ZR32 a ZR35 las alcancen.

OJO con AR18: mide TIEMPO REAL contra el GoTrue de mentira de los tests. El
umbral (25 ms de diferencia entre medianas), las 10 repeticiones y los 60 ms de
espera de `crear` se fijaron en la espec ANTES de medir y no se movieron. El
piso del test se subió de 150 a 400 ms después de la primera corrida, porque
en esta máquina `creado` tarda ~200 ms y el piso quedaba por debajo (errata,
§12.6). Con mucha carga en la máquina el test puede salir rojo por ruido: se
repite una vez y se dice. Nada de esto se ha medido contra un GoTrue real: lo
mide el despliegue.
"""
from __future__ import annotations

import asyncio
import json
import statistics
import time
from typing import Any

import pytest
from pydantic import ValidationError

from src.main import app
from src.registro import piso
from src.registro.cuentas import get_cuentas_de_registro
from src.shared.config import Settings, settings
from tests.registro import _ayuda as ay


# =============================================================================
# UP1 — C27 (el piso, puro)
# =============================================================================
class RelojFalso:
    """Un reloj que solo avanza cuando alguien duerme: nada de tiempo real."""

    def __init__(self, ya_gastado: float = 0.0) -> None:
        self.t = ya_gastado
        self.dormidos: list[float] = []

    def ahora(self) -> float:
        return self.t

    async def dormir(self, segundos: float) -> None:
        self.dormidos.append(segundos)
        self.t += segundos


def _esperado(piso_ms: int, azar: float | None, gastado: float = 0.0) -> tuple[float, int]:
    """(lo que esperó, cuántas veces pidió dormir) con el reloj falso."""
    reloj = RelojFalso(gastado)
    kwargs: dict[str, Any] = {"azar": (lambda: azar)} if azar is not None else {}
    esperado = asyncio.run(piso.esperar(0.0, piso_ms=piso_ms, ahora=reloj.ahora,
                                        dormir=reloj.dormir, **kwargs))
    return round(esperado, 6), len(reloj.dormidos)


def test_up1_el_piso_puro() -> None:
    """UP1 (C27): el piso exacto, el azar hasta el 20 %, lo que falta, 0 si ya pasó."""
    sorteadas: list[float] = []

    def azar_que_se_anota() -> float:
        sorteadas.append(0.5)
        return 0.5

    reloj = RelojFalso()
    cero = asyncio.run(piso.esperar(0.0, piso_ms=0, ahora=reloj.ahora, dormir=reloj.dormir,
                                    azar=azar_que_se_anota))
    cero_sin_dormir_ni_sortear = reloj.dormidos == [] and sorteadas == []
    # 50 llamadas con el azar REAL del módulo (el que rompe el tramposo ZR35).
    reales: list[float] = []
    for _ in range(50):
        reloj = RelojFalso()
        reales.append(asyncio.run(piso.esperar(0.0, piso_ms=250, ahora=reloj.ahora,
                                               dormir=reloj.dormir)))
    por_defecto = Settings.model_fields["registro_piso_ms"].default
    try:
        Settings(registro_piso_ms=5001)  # type: ignore[call-arg]
        quinientos_uno = "aceptado"
    except ValidationError:
        quinientos_uno = "rechazado"
    observado = {
        "piso_exacto": _esperado(250, 0.0),
        "con_azar_casi_uno": _esperado(250, 0.9999)[0] < 0.3,
        "con_azar_casi_uno_sube": _esperado(250, 0.9999)[0] > 0.2999,
        "con_100ms_gastados": _esperado(250, 0.0, gastado=0.1),
        "gastado_mas_que_el_piso": _esperado(250, 0.0, gastado=0.4),
        "piso_cero": (cero, cero_sin_dormir_ni_sortear),
        "esperas_distintas": len(set(reales)) > 1,
        "todas_en_rango": all(0.25 <= e < 0.3 for e in reales),
        "por_defecto_y_maximo": (por_defecto, quinientos_uno),
    }
    assert observado == {
        "piso_exacto": (0.25, 1),
        "con_azar_casi_uno": True,
        "con_azar_casi_uno_sube": True,
        "con_100ms_gastados": (0.15, 1),
        "gastado_mas_que_el_piso": (0.0, 0),
        "piso_cero": (0.0, True),
        "esperas_distintas": True,
        "todas_en_rango": True,
        "por_defecto_y_maximo": (250, "rechazado"),
    }, f"UP1: {observado}"


# =============================================================================
# UP2 — C28 (no bloquea el bucle)
# =============================================================================
def test_up2_la_espera_no_bloquea_el_bucle() -> None:
    """UP2 (C28): mientras se espera 200 ms, otra corrutina sigue avanzando.

    (Errata de §12.2: la espec decía "se despierta cada 10 ms, al menos 10
    despertares". En Windows un `sleep(0.01)` despierta cada ~15 ms y el
    número depende de la carga. Se cuenta cuántas veces cede el turno una
    corrutina que solo hace `sleep(0)`: miles si el bucle está libre, 0 o 1 si
    la espera lo bloquea.)
    """
    async def correr() -> tuple[float, int]:
        turnos = 0

        async def otra() -> None:
            nonlocal turnos
            while True:
                await asyncio.sleep(0)
                turnos += 1

        tarea = asyncio.create_task(otra())
        esperado = await piso.esperar(piso._ahora(), piso_ms=200, azar=lambda: 0.0)
        tarea.cancel()
        return esperado, turnos

    esperado, turnos = asyncio.run(correr())
    observado = {"espero_lo_pedido": esperado >= 0.19, "otro_corrio_mientras": turnos >= 50}
    assert observado == {
        "espero_lo_pedido": True, "otro_corrio_mientras": True,
    }, f"UP2: {observado} (turnos={turnos}, esperado={esperado:.3f}s)"


# =============================================================================
# AR18 — C29 (en la ruta, los cuatro caminos pegados)
# =============================================================================
CAMINOS = ("creado", "correo_en_uso", "ocupado", "403")
REPETICIONES = 10
PISO_DEL_TEST_MS = 400
UMBRAL_MS = 25.0
ESPERA_DE_GOTRUE_S = 0.06


def _bloque(a: ay.Aula, desde: int) -> tuple[dict[str, list[float]], dict[str, list[str]]]:
    """Las 4 peticiones, intercaladas, `REPETICIONES` veces: (tiempos en ms, respuestas)."""
    tiempos: dict[str, list[float]] = {c: [] for c in CAMINOS}
    respuestas: dict[str, set[str]] = {c: set() for c in CAMINOS}
    for i in range(REPETICIONES):
        n = desde + i
        pasos = {
            "creado": ay.cuerpo(a.codigo, n),
            # Un código estudiantil NUEVO con el correo de la cuenta de arriba.
            "correo_en_uso": ay.cuerpo(a.codigo, n + 500, correo=f"persona{n}@sintetico.test"),
            # El mismo código estudiantil que `creado`: ya está inscrito.
            "ocupado": ay.cuerpo(a.codigo, n, correo=f"otra{n}@sintetico.test"),
            "403": ay.cuerpo("ZZZZ-ZZZZ", n + 900),
        }
        for camino, datos in pasos.items():
            inicio = time.perf_counter()
            r = ay.registrar(datos)
            tiempos[camino].append((time.perf_counter() - inicio) * 1000)
            respuestas[camino].add(f"{r.status_code} {json.dumps(ay.cuerpo_json(r), sort_keys=True)}")
    return tiempos, {c: sorted(v) for c, v in respuestas.items()}


def _medianas(tiempos: dict[str, list[float]]) -> dict[str, float]:
    return {c: round(statistics.median(v), 1) for c, v in tiempos.items()}


def _dispersion(medianas: dict[str, float]) -> float:
    return max(medianas.values()) - min(medianas.values())


@pytest.mark.integ
def test_ar18_el_201_y_el_403_del_registro_no_delatan_por_tiempo(integ, monkeypatch) -> None:
    """AR18 (C29): con el piso, las medianas de los 4 caminos quedan a menos de 25 ms."""
    cuentas = ay.preparar(integ)
    cuentas.espera_crear = ESPERA_DE_GOTRUE_S
    a = ay.aula(integ, cupo=100)
    ay.registrar(ay.cuerpo(a.codigo, 990))                 # calentamiento: la primera es lenta
    ay.registrar(ay.cuerpo("ZZZZ-ZZZZ", 991))

    monkeypatch.setattr(settings, "registro_piso_ms", 0)
    tiempos_sin, respuestas_sin = _bloque(a, 1)
    monkeypatch.setattr(settings, "registro_piso_ms", PISO_DEL_TEST_MS)
    # El componente aleatorio se prueba en UP1; aquí se fija en 0 para que 10 muestras
    # no sean más ruidosas que el umbral (con 400 ms llegaría a 80 ms de dispersión).
    monkeypatch.setattr(piso, "_azar", lambda: 0.0)
    tiempos_con, respuestas_con = _bloque(a, 101)

    sin, con = _medianas(tiempos_sin), _medianas(tiempos_con)
    # "Toda respuesta": también el 422 del cuerpo y el 503 del registro apagado.
    otras = {}
    app.dependency_overrides[get_cuentas_de_registro] = lambda: None
    for nombre, datos in {"422": ay.cuerpo(a.codigo, 5, mayor_de_edad=False),
                          "503": ay.cuerpo(a.codigo, 6)}.items():
        inicio = time.perf_counter()
        otras[nombre] = (ay.registrar(datos).status_code,
                         (time.perf_counter() - inicio) * 1000 >= PISO_DEL_TEST_MS)
    uniforme = '201 {"estado": "pendiente"}'
    observado = {
        "respuestas": respuestas_con,
        "igual_sin_piso": respuestas_sin == respuestas_con,
        "sin_piso_se_distinguen": _dispersion(sin) >= UMBRAL_MS,
        "creado_sin_piso_bajo_el_piso": sin["creado"] < PISO_DEL_TEST_MS,
        "con_piso_pegados": _dispersion(con) < UMBRAL_MS,
        "nadie_bajo_el_piso": min(min(v) for v in tiempos_con.values()) >= PISO_DEL_TEST_MS,
        "el_422_y_el_503_tambien_esperan": otras,
    }
    assert observado == {
        "respuestas": {"creado": [uniforme], "correo_en_uso": [uniforme],
                       "ocupado": [uniforme],
                       "403": ['403 {"detail": "codigo_no_valido"}']},
        "igual_sin_piso": True,
        "sin_piso_se_distinguen": True,
        "creado_sin_piso_bajo_el_piso": True,
        "con_piso_pegados": True,
        "nadie_bajo_el_piso": True,
        "el_422_y_el_503_tambien_esperan": {"422": (422, True), "503": (503, True)},
    }, (f"AR18: {observado} | medianas en ms: sin piso={sin} (dispersión "
        f"{_dispersion(sin):.1f}), con piso={con} (dispersión {_dispersion(con):.1f})")

