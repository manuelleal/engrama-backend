"""HC1 (humo) y RC1 (réplica) del consentimiento — `docs/ESPEC_consentimiento.md` §3.

HC1: tres personas sintéticas (una está en dos instituciones). Ninguna tiene
consentimiento; las tres aceptan `2026-10-v1` por la API; una, elegida con
`random.Random(34)`, lo repite; se intenta una versión vacía; y la que está en
dos instituciones se mira desde la otra. Escribe
`tests/_salida/humo_consentimiento.json` (en `.gitignore`) ANTES de afirmar.

RC1 solo corre con `ENGRAMA_REPLICA_CONSENTIMIENTO=1` (sin ella se salta), con
entradas que no se usaron al desarrollar: una versión con ñ y tilde, una de
exactamente 32 caracteres y 6 versiones seguidas de la misma persona.
"""
from __future__ import annotations

import json
import os
import random
from typing import Any

import pytest

from tests.auth import test_consentimiento as cn
from tests.integ_db import RAIZ_BACKEND

pytestmark = pytest.mark.integ

RUTA_HUMO_CONSENTIMIENTO = RAIZ_BACKEND / "tests" / "_salida" / "humo_consentimiento.json"
SEMILLA = 34
REPLICA = os.environ.get("ENGRAMA_REPLICA_CONSENTIMIENTO") == "1"

# Contenido exacto (ESPEC §3). Si difiere se reporta; no se ajusta para que pase.
HUMO_ESPERADO: dict[str, Any] = {
    "alembic_version": "035_autorregistro", "semilla": 34, "antes": [None, None, None],
    "aceptan": [200, 200, 200], "despues": ["2026-10-v1", "2026-10-v1", "2026-10-v1"],
    "repite": {"status": 200, "misma_fecha": True}, "vacia": 422, "filas": 3, "auditorias": 3,
    "en_su_otra_institucion": "2026-10-v1", "sin_bloqueo": 200,
}


def test_hc1_humo_consentimiento(integ) -> None:
    rng = random.Random(SEMILLA)
    a, b = integ.crear_tenant(), integ.crear_tenant()
    personas = [integ.crear_perfil(a), integ.crear_perfil(a, rol="teacher"),
                integ.crear_perfil(b)]
    integ.afiliar(personas[1], b, rol="teacher")  # la docente está en A y en B
    quien_repite = rng.choice(personas)

    sin_bloqueo = cn.client.get("/challenges/", headers=integ.headers(personas[0])).status_code
    antes = [cn.version_en_me(integ, p) for p in personas]
    respuestas = {p: cn.aceptar(integ, p, {"version": cn.V1}) for p in personas}
    repetida = cn.aceptar(integ, quien_repite, {"version": cn.V1})
    datos = {
        "alembic_version": integ.valor("select version_num from alembic_version"),
        "semilla": SEMILLA,
        "antes": antes,
        "aceptan": [respuestas[p].status_code for p in personas],
        "despues": [cn.version_en_me(integ, p) for p in personas],
        "repite": {"status": repetida.status_code,
                   "misma_fecha": cn._json(repetida).get("accepted_at") is not None
                   and cn._json(repetida).get("accepted_at")
                   == cn._json(respuestas[quien_repite]).get("accepted_at")},
        "vacia": cn.aceptar(integ, personas[0], {"version": ""}).status_code,
        "filas": int(integ.valor("select count(*) from consentimientos")),
        "auditorias": sum(cn.auditorias(integ, p) for p in personas),
        "en_su_otra_institucion": cn.version_en_me(integ, personas[1],
                                                   **{"X-Tenant-ID": str(b)}),
        "sin_bloqueo": sin_bloqueo,
    }
    # Primero se escribe (para poder reportarlo), después se afirma.
    RUTA_HUMO_CONSENTIMIENTO.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO_CONSENTIMIENTO.write_text(
        json.dumps(datos, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    en_disco = json.loads(RUTA_HUMO_CONSENTIMIENTO.read_text(encoding="utf-8"))
    assert en_disco == HUMO_ESPERADO, f"humo consentimiento: {en_disco} != {HUMO_ESPERADO}"


@pytest.mark.skipif(not REPLICA,
                    reason="réplica del consentimiento: ENGRAMA_REPLICA_CONSENTIMIENTO=1")
def test_rc1_replica_versiones_raras_y_seis_seguidas(integ) -> None:
    ana = integ.crear_perfil(integ.crear_tenant())
    con_enie, de_32 = "aviso-señal-2027-versión-1", "v" * 32
    seguidas = [f"r{n}-2027" for n in range(6)]
    estados = [cn.aceptar(integ, ana, {"version": v}).status_code
               for v in (con_enie, de_32, *seguidas)]
    observado = {
        "estados": estados,
        "filas": cn.filas(integ, ana),
        "ultima": cn.version_en_me(integ, ana),
        "auditorias": cn.auditorias(integ, ana),
        "repetir_la_primera": cn.aceptar(integ, ana, {"version": con_enie}).status_code,
        "ultima_despues": cn.version_en_me(integ, ana),
    }
    assert observado == {
        "estados": [200] * 8, "filas": [con_enie, de_32, *seguidas], "ultima": seguidas[-1],
        "auditorias": 8, "repetir_la_primera": 200, "ultima_despues": seguidas[-1],
    }, f"RC1: {observado}"
