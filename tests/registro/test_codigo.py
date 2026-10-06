"""El código de inscripción — `docs/ESPEC_autorregistro.md` C1, C3 y C4.

  AR1  C1  el profe lo crea, lo reemplaza y lo apaga; en la base solo la huella.
  AR3  C3  inexistente, vencido, apagado, sin cupo o documento que no cabe: UNA respuesta.
  AR4  C4  el cupo no se pasa, ni con dos registros a la vez por el último puesto.

Concurrencia de AR4: `service._ocupado` (que se llama DESPUÉS de leer el
código) se envuelve con una `threading.Barrier(2)`. Con el código bueno, el
segundo registro está bloqueado en el `FOR UPDATE` y nunca llega a la barrera:
el primero espera hasta el timeout (unos 3 s) y sigue. Mismo patrón que A13-2.
"""
from __future__ import annotations

import re
import threading
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.registro import service as service_mod
from tests.registro import _ayuda as ay
from tests.seguridad.veredictos import PruebaRota, sembrar

pytestmark = pytest.mark.integ

FORMA = re.compile(r"[ABCDEFGHJKMNPQRSTUVWXYZ2-9]{4}-[ABCDEFGHJKMNPQRSTUVWXYZ2-9]{4}")
BARRERA_S = 3
ESPERA_HILO_S = 30


def _estado_del_codigo(integ: Any, a: ay.Aula) -> Any:
    return ay.cuerpo_json(ay.client.get(f"/teachers/groups/{a.grupo}/codigo-inscripcion",
                                        headers=integ.headers(a.profe)))


def _resumen(estado: Any) -> Any:
    """(claves, activo, cupo, usos): el `vence` cambia en cada corrida."""
    if not isinstance(estado, dict):
        return estado
    return (sorted(estado), estado.get("activo"), estado.get("cupo"), estado.get("usos"))


# =============================================================================
# AR1 — C1
# =============================================================================
def test_ar1_el_profe_crea_reemplaza_y_apaga_el_codigo(integ) -> None:
    """AR1 (C1): 201 con el código; en la base, solo la huella; uno activo; se apaga."""
    ay.preparar(integ)
    a = ay.aula(integ, con_codigo=False)
    r1 = ay.crear_codigo(integ, a.profe, a.grupo)
    c1 = str(ay.campo(r1, "codigo") or "")
    fila = integ.fila("select codigo_hash, cupo, usos, activo from codigos_inscripcion") or {}
    en_la_base = str(fila.get("codigo_hash") or "")
    tras_crear = {
        "respuesta": (r1.status_code, bool(FORMA.fullmatch(c1)), ay.campo(r1, "cupo"),
                      ay.campo(r1, "usos"), sorted(ay.cuerpo_json(r1) or {})),
        "huella_de_64_hex": bool(re.fullmatch(r"[0-9a-f]{64}", en_la_base)),
        "codigo_en_claro_en_la_base": c1 != "" and c1.replace("-", "") in en_la_base.upper(),
        "estado": _resumen(_estado_del_codigo(integ, a)),
    }
    c2 = str(ay.campo(ay.crear_codigo(integ, a.profe, a.grupo, cupo=5, horas=1), "codigo") or "")
    tras_reemplazar = {
        "distinto": c2 not in ("", c1),
        "activos": ay.contar(integ, "select count(*) from codigos_inscripcion where activo"),
        "filas": ay.contar(integ, "select count(*) from codigos_inscripcion"),
        "con_el_viejo": ay.registrar(ay.cuerpo(c1, 1)).status_code,
        "con_el_nuevo": ay.registrar(ay.cuerpo(c2, 1)).status_code,
        "estado": _resumen(_estado_del_codigo(integ, a)),
    }
    ruta = f"/teachers/groups/{a.grupo}/codigo-inscripcion"
    apagar = [ay.client.delete(ruta, headers=integ.headers(a.profe)).status_code
              for _ in range(2)]
    tras_apagar = {
        "delete": apagar, "estado": _estado_del_codigo(integ, a),
        "con_el_apagado": ay.registrar(ay.cuerpo(c2, 2)).status_code,
    }
    observado = {"crear": tras_crear, "reemplazar": tras_reemplazar, "apagar": tras_apagar}
    claves = ["activo", "cupo", "usos", "vence"]
    assert observado == {
        "crear": {"respuesta": (201, True, 40, 0, ["codigo", "cupo", "usos", "vence"]),
                  "huella_de_64_hex": True, "codigo_en_claro_en_la_base": False,
                  "estado": (claves, True, 40, 0)},
        "reemplazar": {"distinto": True, "activos": 1, "filas": 2, "con_el_viejo": 403,
                       "con_el_nuevo": 201, "estado": (claves, True, 5, 1)},
        "apagar": {"delete": [204, 204],
                   "estado": {"activo": False, "vence": None, "cupo": None, "usos": None},
                   "con_el_apagado": 403},
    }, f"AR1: {observado}"


# =============================================================================
# AR3 — C3
# =============================================================================
def test_ar3_codigo_no_valido_una_sola_respuesta(integ) -> None:
    """AR3 (C3): cinco causas, el mismo estado y el mismo cuerpo; nada escrito."""
    cuentas = ay.preparar(integ)
    vencida, apagada, llena, larga = (ay.aula(integ), ay.aula(integ), ay.aula(integ, cupo=1),
                                      ay.aula(integ))
    sembrar(integ, "update codigos_inscripcion set expires_at = now() - interval '1 hour' "
                   "where group_id = :g", g=vencida.grupo)
    sembrar(integ, "update codigos_inscripcion set activo = false where group_id = :g",
            g=apagada.grupo)
    quien_lleno = ay.registrar(ay.cuerpo(llena.codigo, 1)).status_code
    antes = (ay.estudiantes(integ), len(cuentas.creadas))
    casos = {
        "inexistente": ay.cuerpo("ZZZZ-ZZZZ", 2),
        "vencido": ay.cuerpo(vencida.codigo, 2),
        "apagado": ay.cuerpo(apagada.codigo, 2),
        "sin_cupo": ay.cuerpo(llena.codigo, 2),
        "documento_no_cabe": ay.cuerpo(larga.codigo, 2, codigo_estudiantil="9" * 24),
    }
    respuestas = {nombre: ay.estado_y_cuerpo(ay.registrar(c)) for nombre, c in casos.items()}
    observado = {
        "quien_lleno": quien_lleno, "respuestas": respuestas,
        "nada_escrito": (ay.estudiantes(integ), len(cuentas.creadas)) == antes,
        "solicitudes": len(ay.solicitudes(integ)),
        "control": ay.registrar(ay.cuerpo(larga.codigo, 2)).status_code,
    }
    assert observado == {
        "quien_lleno": 201, "respuestas": dict.fromkeys(casos, ay.NO_VALIDO),
        "nada_escrito": True, "solicitudes": 1, "control": 201,
    }, f"AR3: {observado}"


# =============================================================================
# AR4 — C4
# =============================================================================
def _a_la_vez(monkeypatch: pytest.MonkeyPatch, cuerpos: list[dict[str, Any]]) -> list[int]:
    """Los registros en hilos separados, con la barrera después de leer el código."""
    barrera = threading.Barrier(len(cuerpos), timeout=BARRERA_S)
    original = service_mod._ocupado

    async def con_barrera(*args: Any) -> bool:
        try:
            barrera.wait()
        except threading.BrokenBarrierError:
            pass
        return await original(*args)

    monkeypatch.setattr(service_mod, "_ocupado", con_barrera)
    respuestas: list[httpx.Response | None] = [None] * len(cuerpos)
    errores: list[BaseException] = []

    def enviar(i: int) -> None:
        try:
            cliente = TestClient(app, raise_server_exceptions=False)
            respuestas[i] = cliente.post(ay.RUTA, json=cuerpos[i])
        except BaseException as exc:  # noqa: BLE001 — se re-lanza en el hilo principal
            errores.append(exc)

    hilos = [threading.Thread(target=enviar, args=(i,)) for i in range(len(cuerpos))]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=ESPERA_HILO_S)
    monkeypatch.setattr(service_mod, "_ocupado", original)
    if any(h.is_alive() for h in hilos):
        raise PruebaRota(f"un registro no volvió en {ESPERA_HILO_S} s (¿bloqueo?)")
    if errores:
        raise errores[0]
    return sorted(r.status_code for r in respuestas if r is not None)


def test_ar4_el_cupo_no_se_pasa(integ, monkeypatch) -> None:
    """AR4 (C4): con cupo 2 el tercero no entra; dos a la vez por el último, entra uno."""
    cuentas = ay.preparar(integ)
    a = ay.aula(integ, cupo=2)
    seguidos = [ay.registrar(ay.cuerpo(a.codigo, n)).status_code for n in (1, 2, 3)]
    tras_seguidos = (ay.usos(integ, a.grupo), len(ay.solicitudes(integ, group_id=a.grupo)))

    b = ay.aula(integ, cupo=1)
    antes = len(cuentas.cuentas)
    carrera = _a_la_vez(monkeypatch, [ay.cuerpo(b.codigo, 11), ay.cuerpo(b.codigo, 12)])
    observado = {
        "seguidos": seguidos, "usos_y_solicitudes": tras_seguidos,
        "carrera": {"estados": carrera, "usos": ay.usos(integ, b.grupo),
                    "solicitudes": len(ay.solicitudes(integ, group_id=b.grupo)),
                    "cuentas": len(cuentas.cuentas) - antes},
    }
    assert observado == {
        "seguidos": [201, 201, 403], "usos_y_solicitudes": (2, 2),
        "carrera": {"estados": [201, 403], "usos": 1, "solicitudes": 1, "cuentas": 1},
    }, f"AR4: {observado}"
