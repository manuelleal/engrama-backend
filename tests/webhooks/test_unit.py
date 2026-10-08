"""UE1: la firma y el catálogo, puros — `docs/ESPEC_eventos_anillo.md` C16 y C17.
UE3: los secretos de eventos se validan al arrancar — §12, C20 (auditoría 03, S-11).

No-integ. Las funciones se llaman por el módulo (`events.…`, `config_mod.…`)
para que los tramposos ZE18, ZE19 y ZE20 las alcancen.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from src.shared import config as config_mod
from src.shared import events
from tests.webhooks import _ayuda as ay

RAIZ_BACKEND = Path(__file__).resolve().parents[2]

SECRETO = ay.SECRETO_LIVE
CUERPO = b'{"schema_version":1}'


def _vale(secreto: str = SECRETO, ts: str = "1000", cuerpo: bytes = CUERPO,
          firma: str | None = None, ahora: float = 1000.0) -> bool:
    """¿El backend acepta una firma hecha AQUÍ (con `ay.firma`, no con su código)?"""
    hecha = ay.firma(SECRETO, "1000", CUERPO) if firma is None else firma
    return events.verificar(secreto, ts, cuerpo, hecha, ahora=ahora)


def test_ue1_la_firma_y_el_catalogo() -> None:
    """UE1 (C16, C17): la firma ata secreto, timestamp y bytes; cada origen, sus tipos."""
    evento = {"event_id": "e1", "payload": {"a": 1, "b": [1, 2]}, "type": "x"}
    al_reves = {"type": "x", "payload": {"b": [1, 2], "a": 1}, "event_id": "e1"}
    observado = {
        "firmar_coincide_con_el_satelite": events.firmar(SECRETO, "1000", CUERPO)
        == ay.firma(SECRETO, "1000", CUERPO),
        "firma": {
            "buena": _vale(),
            "otro_cuerpo": _vale(cuerpo=CUERPO + b" "),
            "otro_timestamp": _vale(ts="1001"),
            "otro_secreto": _vale(secreto=ay.SECRETO_SET),
            "sin_prefijo": _vale(firma=ay.firma(SECRETO, "1000", CUERPO)[7:]),
            "a_300_s": _vale(ahora=1300.0),
            "a_301_s": _vale(ahora=1301.0),
            "del_futuro_a_301_s": _vale(ahora=699.0),
            "timestamp_no_numerico": events.verificar(SECRETO, "mil", CUERPO,
                                                      ay.firma(SECRETO, "mil", CUERPO), ahora=0),
            "secreto_de_31": events.verificar("s" * 31, "1000", CUERPO,
                                              ay.firma("s" * 31, "1000", CUERPO), ahora=1000),
            "secreto_vacio": events.verificar("", "1000", CUERPO,
                                              ay.firma("", "1000", CUERPO), ahora=1000),
        },
        "tipos_de_live": sorted(events.PERMITIDOS["live"]),
        "tipos_de_set": sorted(events.PERMITIDOS["set"]),
        "origenes": sorted(events.PERMITIDOS),
        "set_no_acredita": events.regla_de("set", "coins.granted"),
        "live_no_mide": events.regla_de("live", "level.assessed"),
        "huella_sin_importar_el_orden": events.huella_del_evento(evento)
        == events.huella_del_evento(al_reves),
        "huella_cambia_con_un_valor": events.huella_del_evento(evento)
        != events.huella_del_evento({**evento, "payload": {"a": 2, "b": [1, 2]}}),
    }
    assert observado == {
        "firmar_coincide_con_el_satelite": True,
        "firma": {"buena": True, "otro_cuerpo": False, "otro_timestamp": False,
                  "otro_secreto": False, "sin_prefijo": False, "a_300_s": True,
                  "a_301_s": False, "del_futuro_a_301_s": False,
                  "timestamp_no_numerico": False, "secreto_de_31": False,
                  "secreto_vacio": False},
        "tipos_de_live": ["answer.submitted", "coins.granted", "item.exposed",
                          "live.session.closed", "live.session.started"],
        "tipos_de_set": ["level.assessed"], "origenes": ["live", "set"],
        "set_no_acredita": None, "live_no_mide": None,
        "huella_sin_importar_el_orden": True, "huella_cambia_con_un_valor": True,
    }, f"UE1: {observado}"


# =============================================================================
# UE3 — C20 de la adenda §12 (S-11)
# =============================================================================
# Todo sintético: ninguno de estos textos es un secreto de ningún sistema.
BUENO_1, BUENO_2 = ay.SECRETO_LIVE, ay.SECRETO_SET
JWT_SINTETICO = "secreto-jwt-sintetico-solo-para-pytest-0003"
CORTO = "c" * 31
_SECRETOS_DE_LA_PRUEBA = (BUENO_1, BUENO_2, JWT_SINTETICO, CORTO)


def _arranca(live: str, set_: str) -> dict[str, object]:
    """Importa la aplicación en OTRO proceso, con esos secretos en el entorno.

    Es lo que hace uvicorn al arrancar: si el import falla, el servicio no
    llega a escuchar. No abre ninguna conexión (la base no se toca al importar).
    """
    entorno = {**os.environ, "EVENTS_SECRET_LIVE": live, "EVENTS_SECRET_SET": set_,
               "SUPABASE_JWT_SECRET": JWT_SINTETICO,
               "DATABASE_URL": "postgresql+asyncpg://nadie:nada@127.0.0.1:1/ninguna"}
    r = subprocess.run([sys.executable, "-c", "import src.main"], cwd=RAIZ_BACKEND,
                       env=entorno, capture_output=True, text=True, timeout=120)
    salida = r.stdout + r.stderr
    return {"arranca": r.returncode == 0,
            "nombra_las_variables": "EVENTS_SECRET_LIVE y EVENTS_SECRET_SET son iguales" in salida,
            "imprime_un_secreto": any(v in salida for v in _SECRETOS_DE_LA_PRUEBA)}


def _al_cargar(monkeypatch, live: str) -> tuple[bool, bool]:
    """(¿`get_settings` se niega?, ¿el mensaje trae el valor?). Sin tocar el caché."""
    monkeypatch.setenv("EVENTS_SECRET_LIVE", live)
    try:
        config_mod.get_settings.__wrapped__()
    except config_mod.ConfiguracionInvalida as exc:
        return True, live in str(exc)
    finally:
        monkeypatch.delenv("EVENTS_SECRET_LIVE")
    return False, False


def test_ue3_los_secretos_de_eventos_se_validan_al_arrancar(monkeypatch) -> None:
    """UE3 (C20): corto, repetido o igual al JWT -> no arranca, y no se imprime ninguno."""
    def problemas(live: str, set_: str, jwt: str = JWT_SINTETICO) -> list[str]:
        return config_mod.problemas_de_secretos(live, set_, jwt)

    todo_mal = problemas(CORTO, CORTO, CORTO)
    mensajes = [*todo_mal, *problemas(BUENO_1, BUENO_1), *problemas(BUENO_1, JWT_SINTETICO)]
    observado = {
        "los_dos_vacios": problemas("", ""),
        "solo_live": problemas(BUENO_1, ""),
        "solo_set": problemas("", BUENO_2),
        "los_dos_buenos": problemas(BUENO_1, BUENO_2),
        "live_de_31": problemas(CORTO, BUENO_2),
        "iguales": problemas(BUENO_1, BUENO_1),
        "set_igual_al_jwt": problemas(BUENO_1, JWT_SINTETICO),
        "todo_mal": len(todo_mal),
        "algun_mensaje_trae_un_valor": any(v in m for m in mensajes
                                           for v in _SECRETOS_DE_LA_PRUEBA),
        "el_mismo_minimo_que_la_firma": config_mod.EVENTS_SECRET_MINIMO
        == events.SECRETO_MINIMO,
        "al_cargar_con_uno_corto": _al_cargar(monkeypatch, CORTO),
        "al_cargar_con_uno_bueno": _al_cargar(monkeypatch, BUENO_1),
        "proceso_con_dos_iguales": _arranca(BUENO_1, BUENO_1),
        "proceso_con_dos_buenos": _arranca(BUENO_1, BUENO_2),
        "proceso_sin_secretos": _arranca("", ""),
    }
    assert observado == {
        "los_dos_vacios": [], "solo_live": [], "solo_set": [], "los_dos_buenos": [],
        "live_de_31": ["EVENTS_SECRET_LIVE mide menos de 32 caracteres"],
        "iguales": ["EVENTS_SECRET_LIVE y EVENTS_SECRET_SET son iguales"],
        "set_igual_al_jwt": ["EVENTS_SECRET_SET es igual a SUPABASE_JWT_SECRET"],
        "todo_mal": 5, "algun_mensaje_trae_un_valor": False,
        "el_mismo_minimo_que_la_firma": True,
        "al_cargar_con_uno_corto": (True, False), "al_cargar_con_uno_bueno": (False, False),
        "proceso_con_dos_iguales": {"arranca": False, "nombra_las_variables": True,
                                    "imprime_un_secreto": False},
        "proceso_con_dos_buenos": {"arranca": True, "nombra_las_variables": False,
                                   "imprime_un_secreto": False},
        "proceso_sin_secretos": {"arranca": True, "nombra_las_variables": False,
                                 "imprime_un_secreto": False},
    }, f"UE3: {observado}"
