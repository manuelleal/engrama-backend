"""UE1: la firma y el catálogo, puros — `docs/ESPEC_eventos_anillo.md` C16 y C17.

No-integ. Las funciones se llaman por el módulo (`events.…`) para que los
tramposos ZE18 y ZE19 las alcancen.
"""
from __future__ import annotations

from src.shared import events
from tests.webhooks import _ayuda as ay

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
