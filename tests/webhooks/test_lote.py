"""La puerta y el lote — `docs/ESPEC_eventos_anillo.md` C1 a C8.

  EV1  C1, C2  un lote de 5 entra; reenviarlo no crea filas ni paga otra vez.
  EV3  C3, C4  la firma: sobre los bytes que viajaron, con ventana, y un solo 401.
  EV5  C5      los topes (200 eventos, 262.144 bytes) y la raíz.
  EV6  C6      mismo `event_id` con otro contenido: conflicto, gana el primero.
  EV7  C7      un evento malo no tumba el lote: cada uno con su motivo.
  EV9  C8      dos lotes iguales a la vez: una fila por evento y una sola paga.

Concurrencia de EV9: `efectos.aplicar` (que corre DESPUÉS del INSERT del
evento) se envuelve con una `threading.Barrier(2)`. Con el código bueno, el
segundo lote está bloqueado en el UNIQUE y no llega: el primero espera hasta el
timeout (unos 3 s) y sigue. Mismo patrón que A13-2 y AR4.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.shared.config import settings
from src.webhooks import efectos as efectos_mod
from tests.seguridad.veredictos import PruebaRota
from tests.webhooks import _ayuda as ay

pytestmark = pytest.mark.integ

BARRERA_S = 3
ESPERA_HILO_S = 30


# =============================================================================
# EV1 — C1 y C2
# =============================================================================
def test_ev1_un_lote_entra_y_reenviarlo_no_repite_nada(integ) -> None:
    """EV1 (C1, C2): 5 aceptados y una paga; otra vez, 5 duplicados y todo igual."""
    ay.preparar()
    c = ay.clase(integ)
    cinco = c.cinco(amount=3)

    def foto(r: httpx.Response) -> dict[str, Any]:
        return {"respuesta": ay.resumen(r), "filas": ay.filas(integ),
                "saldo": ay.saldo(integ, c.estudiantes[0]), "libro": ay.libro(integ),
                "bolsa": integ.saldo("tenant", c.tenant), "efectos": ay.efectos(integ)}

    observado = {"primera": foto(ay.enviar("live", ay.lote(cinco))),
                 "segunda": foto(ay.enviar("live", ay.lote(cinco)))}
    estado = {"filas": 5, "saldo": 3, "libro": [("live", "event:aula-1:coins.granted:0", 3)],
              "bolsa": 997,
              "efectos": [("none", 0)] * 3 + [("coins_credited", 3), ("none", 0)]}
    assert observado == {
        "primera": {"respuesta": (200, 5, 0, [], []), **estado},
        "segunda": {"respuesta": (200, 0, 5, [], []), **estado},
    }, f"EV1: {observado}"


# =============================================================================
# EV3 — C3 y C4
# =============================================================================
def test_ev3_la_firma_y_la_ventana(integ, caplog) -> None:
    """EV3 (C3, C4): todo fallo de firma da el MISMO 401; se firma lo que viajó."""
    ay.preparar()
    caplog.set_level(logging.DEBUG)
    c = ay.clase(integ)
    datos = ay.lote(c.cinco())
    cuerpo = ay.serializar(datos)
    otro_orden = json.dumps(datos, sort_keys=True, indent=1).encode()
    buenas = ay.cabeceras("live", cuerpo)
    casos: dict[str, tuple[bytes, dict[str, str]]] = {
        "firma_falsa": (cuerpo, {**buenas, "X-Engrama-Signature": "sha256=" + "0" * 64}),
        "firma_sin_prefijo": (cuerpo, {**buenas, "X-Engrama-Signature":
                                       buenas["X-Engrama-Signature"].removeprefix("sha256=")}),
        "firma_de_otro_cuerpo": (cuerpo, ay.cabeceras("live", cuerpo + b" ")),
        "sin_encabezados": (cuerpo, {"Content-Type": "application/json"}),
        "origen_desconocido": (cuerpo, ay.cabeceras("grader", cuerpo, secreto=ay.SECRETO_LIVE)),
        "con_el_secreto_del_otro_origen": (cuerpo, ay.cabeceras("live", cuerpo,
                                                                secreto=ay.SECRETO_SET)),
        "bearer_valido_sin_firma": (cuerpo, {**integ.headers(c.estudiantes[0]),
                                             "Content-Type": "application/json"}),
        "otro_orden_con_la_firma_del_original": (otro_orden, buenas),
        "de_hace_10_minutos": (cuerpo, ay.cabeceras("live", cuerpo, hace_s=600)),
        "de_dentro_de_10_minutos": (cuerpo, ay.cabeceras("live", cuerpo, hace_s=-600)),
        "timestamp_no_numerico": (cuerpo, {**buenas, "X-Engrama-Timestamp": "ahora"}),
    }
    respuestas = {nombre: ay.enviar_bytes(*caso) for nombre, caso in casos.items()}
    settings.events_secret_set = ""  # el origen `set`, apagado
    respuestas["origen_apagado"] = ay.enviar_bytes(
        cuerpo, ay.cabeceras("set", cuerpo, secreto=ay.SECRETO_SET))
    settings.events_secret_set = "corto"  # un secreto de menos de 32 no vale
    respuestas["secreto_corto"] = ay.enviar_bytes(
        cuerpo, ay.cabeceras("set", cuerpo, secreto="corto"))
    filas_tras_los_401 = ay.filas(integ)
    controles = {
        "otro_orden_firmado_sobre_sus_bytes": ay.enviar_bytes(
            otro_orden, ay.cabeceras("live", otro_orden)).status_code,
        "de_hace_299_s": ay.enviar_bytes(cuerpo, ay.cabeceras("live", cuerpo,
                                                              hace_s=299)).status_code,
    }
    textos = " ".join(r.text for r in respuestas.values()) + caplog.text
    observado = {
        "respuestas": {n: (r.status_code, ay.cuerpo_json(r)) for n, r in respuestas.items()},
        "filas_tras_los_401": filas_tras_los_401, "controles": controles,
        "el_secreto_en_respuestas_o_logs": ay.SECRETO_LIVE in textos or ay.SECRETO_SET in textos,
    }
    assert observado == {
        "respuestas": dict.fromkeys(respuestas, ay.NO_AUTORIZADO), "filas_tras_los_401": 0,
        "controles": {"otro_orden_firmado_sobre_sus_bytes": 200, "de_hace_299_s": 200},
        "el_secreto_en_respuestas_o_logs": False,
    }, f"EV3: {observado}"


# =============================================================================
# EV5 — C5
# =============================================================================
def test_ev5_topes_y_raiz(integ) -> None:
    """EV5 (C5): 201 eventos o más de 262.144 bytes, 413; raíz mal formada, 422."""
    ay.preparar()
    c = ay.clase(integ)
    expuestos = [c.de_eva("item.exposed", n=i) for i in range(201)]
    gordo = c.de_eva("item.exposed", relleno="x" * 270_000)
    bueno = c.de_eva("item.exposed")
    no_json = b"esto no es JSON"
    casos = {
        "de_201": ay.enviar("live", ay.lote(expuestos)).status_code,
        "de_mas_de_262144_bytes": ay.enviar("live", ay.lote([gordo])).status_code,
        "raiz_con_una_clave_de_mas": ay.enviar("live", ay.lote([bueno], de_mas=1)).status_code,
        "sin_events": ay.enviar("live", {"schema_version": 1, "batch_id": "b",
                                         "instance": "i"}).status_code,
        "events_vacio": ay.enviar("live", ay.lote([])).status_code,
        "schema_version_2": ay.enviar("live", ay.lote([bueno], schema_version=2)).status_code,
        "no_es_json": ay.enviar_bytes(no_json, ay.cabeceras("live", no_json)).status_code,
    }
    sin_filas = ay.filas(integ)
    observado = {"casos": casos, "filas": sin_filas,
                 "control_de_200": ay.cortos(ay.enviar("live", ay.lote(expuestos[:200])))}
    assert observado == {
        "casos": {"de_201": 413, "de_mas_de_262144_bytes": 413, "raiz_con_una_clave_de_mas": 422,
                  "sin_events": 422, "events_vacio": 422, "schema_version_2": 422,
                  "no_es_json": 422},
        "filas": 0, "control_de_200": (200, 200, 0, [], []),
    }, f"EV5: {observado}"


# =============================================================================
# EV6 — C6
# =============================================================================
def test_ev6_conflicto_gana_el_primero(integ) -> None:
    """EV6 (C6): el mismo `event_id` con otro `amount` se rechaza; nada se sobrescribe."""
    ay.preparar()
    c = ay.clase(integ)
    primero, distinto = c.monedas(3), c.monedas(5)
    r1 = ay.enviar("live", ay.lote([primero]))
    r2 = ay.enviar("live", ay.lote([distinto]))
    guardado = (integ.valor("select payload->>'amount' from learning_events"),
                ay.saldo(integ, c.estudiantes[0]))
    repetido = c.monedas(4, sufijo="-b")
    r3 = ay.enviar("live", ay.lote([repetido, repetido]))
    observado = {
        "primero": ay.resumen(r1), "otro_contenido": ay.resumen(r2),
        "la_fila_y_el_saldo_son_del_primero": guardado,
        "dos_veces_en_un_lote": ay.resumen(r3), "filas": ay.filas(integ),
        "saldo_final": ay.saldo(integ, c.estudiantes[0]),
    }
    assert observado == {
        "primero": (200, 1, 0, [], []),
        "otro_contenido": (200, 0, 0, [(primero["event_id"], "conflict")], []),
        "la_fila_y_el_saldo_son_del_primero": ("3", 3),
        "dos_veces_en_un_lote": (200, 1, 1, [], []), "filas": 2, "saldo_final": 7,
    }, f"EV6: {observado}"


# =============================================================================
# EV7 — C7
# =============================================================================
def test_ev7_uno_malo_no_tumba_el_lote(integ) -> None:
    """EV7 (C7): ocho rechazados, cada uno con su motivo, y el bueno entra."""
    ay.preparar()
    c, otra = ay.clase(integ), ay.clase(integ)
    respuesta = c.de_eva("answer.submitted")

    def con(sufijo: str, **cambios: Any) -> dict[str, Any]:
        return {**respuesta, "event_id": f"ev7:{sufijo}", **cambios}

    eventos = [
        con("sujeto-de-otra-institucion", subject_id=str(otra.estudiantes[0])),
        con("sujeto-inexistente", subject_id=str(uuid4())),
        con("institucion-inexistente", tenant_id=str(uuid4())),
        con("tipo-fuera-de-la-lista", type="nota.final"),
        {**c.monedas(2), "event_id": "ev7:monedas-con-source-teacher", "source": "teacher"},
        {**c.de_eva("item.exposed"), "event_id": "ev7:expuesto-con-sujeto",
         "subject_id": str(c.estudiantes[0])},
        con("un-campo-de-mas", nota=5),
        {**c.monedas(21), "event_id": "ev7:monedas-de-21"},
        con("el-bueno"),
    ]
    r = ay.enviar("live", ay.lote(eventos))
    observado = {"respuesta": ay.resumen(r), "filas": ay.filas(integ),
                 "saldo": ay.saldo(integ, c.estudiantes[0])}
    motivos = ["unknown_subject", "unknown_subject", "unknown_tenant", "unknown_type",
               "unknown_type", "unknown_type", "invalid_event", "invalid_event"]
    assert observado == {
        "respuesta": (200, 1, 0,
                      [(e["event_id"], m) for e, m in zip(eventos, motivos, strict=False)], []),
        "filas": 1, "saldo": 0,
    }, f"EV7: {observado}"


# =============================================================================
# EV9 — C8
# =============================================================================
def _a_la_vez(monkeypatch: pytest.MonkeyPatch, lote_: dict[str, Any]) -> list[httpx.Response]:
    barrera = threading.Barrier(2, timeout=BARRERA_S)
    original = efectos_mod.aplicar

    async def con_barrera(*args: Any) -> Any:
        try:
            barrera.wait()
        except threading.BrokenBarrierError:
            pass
        return await original(*args)

    monkeypatch.setattr(efectos_mod, "aplicar", con_barrera)
    respuestas: list[httpx.Response | None] = [None, None]
    errores: list[BaseException] = []

    def mandar(i: int) -> None:
        try:
            respuestas[i] = ay.enviar("live", lote_,
                                      TestClient(app, raise_server_exceptions=False))
        except BaseException as exc:  # noqa: BLE001 — se re-lanza en el hilo principal
            errores.append(exc)

    hilos = [threading.Thread(target=mandar, args=(i,)) for i in range(2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=ESPERA_HILO_S)
    monkeypatch.setattr(efectos_mod, "aplicar", original)
    if any(h.is_alive() for h in hilos):
        raise PruebaRota(f"un lote no volvió en {ESPERA_HILO_S} s (¿bloqueo?)")
    if errores:
        raise errores[0]
    return [r for r in respuestas if r is not None]


def test_ev9_dos_lotes_iguales_a_la_vez(integ, monkeypatch) -> None:
    """EV9 (C8): entre los dos, 5 aceptados y 5 duplicados; 5 filas y una sola paga."""
    ay.preparar()
    c = ay.clase(integ)
    respuestas = _a_la_vez(monkeypatch, ay.lote(c.cinco(amount=4)))
    vistos = [ay.resumen(r) for r in respuestas]
    observado = {
        "estados": sorted(v[0] for v in vistos),
        "aceptados": sum(v[1] for v in vistos if len(v) == 5),
        "duplicados": sum(v[2] for v in vistos if len(v) == 5),
        "filas": ay.filas(integ), "saldo": ay.saldo(integ, c.estudiantes[0]),
        "pagas_en_el_libro": len(ay.libro(integ)),
    }
    assert observado == {"estados": [200, 200], "aceptados": 5, "duplicados": 5, "filas": 5,
                         "saldo": 4, "pagas_en_el_libro": 1}, f"EV9: {observado}"
