"""HE1 (humo) y RE1 (réplica) de los eventos del anillo — `docs/ESPEC_eventos_anillo.md` §3.

HE1: una clase sintética (1 profe y 6 estudiantes). Un generador con
`random.Random(37)` arma el lote como lo haría EVA (inicio, 4 ítems, respuestas
con acierto al azar, monedas por acierto con tope 20, cierre) y lo manda DOS
veces; después SET manda el nivel de 2 estudiantes. Escribe
`tests/_salida/humo_eventos_anillo.json` (en `.gitignore`) ANTES de afirmar.

RE1 solo corre con `ENGRAMA_REPLICA_EVENTOS=1`, con entradas que no se usaron
al desarrollar: otra semilla, un lote de exactamente 200, `event_id` de 256
caracteres con símbolos, un estudiante en dos instituciones con el mismo
`event_id` en las dos, y dos lotes que se solapan.
"""
from __future__ import annotations

import json
import os
import random
from collections.abc import Iterator
from typing import Any

import pytest

from tests.integ_db import RAIZ_BACKEND
from tests.seguridad.veredictos import sembrar
from tests.webhooks import _ayuda as ay

pytestmark = pytest.mark.integ

RUTA_HUMO_EVENTOS = RAIZ_BACKEND / "tests" / "_salida" / "humo_eventos_anillo.json"
SEMILLA = 37
REPLICA = os.environ.get("ENGRAMA_REPLICA_EVENTOS") == "1"
ITEMS = 4

# N, M y K salen de la semilla. Se fijaron al medir el humo por primera vez con el
# código bueno (ESPEC §3) y desde ahí no se mueven: si difieren, se reporta.
HUMO_ESPERADO: dict[str, Any] = {
    "alembic_version": "038_catalogo_nodos", "semilla": 37, "eventos": 42,
    "primera": {"accepted": 42, "duplicates": 0, "rejected": 0},
    "segunda": {"accepted": 0, "duplicates": 42, "rejected": 0},
    "filas": 42, "monedas_acreditadas": 24, "filas_en_el_libro": 12, "bolsa": 976,
    "niveles": {"accepted": 2}, "con_nivel": 2, "sin_nivel": 4, "firma_falsa": 401,
}


@pytest.fixture(autouse=True)
def _apagar_los_secretos_al_terminar() -> Iterator[None]:
    yield
    ay.soltar()


def clase_sintetica(c: ay.Clase, rng: random.Random, sesion: str) -> list[dict[str, Any]]:
    """El lote de una clase, como lo arma EVA: 2 monedas por acierto, tope de 20."""
    eventos = [c.de_eva("live.session.started", sesion=sesion)]
    for item in range(ITEMS):
        eventos.append(c.de_eva("item.exposed", sesion=sesion, sufijo=f"-i{item}"))
        for n in range(len(c.estudiantes)):
            acierto = rng.random() < 0.6
            eventos.append(c.de_eva("answer.submitted", sesion=sesion, n=n, sufijo=f"-i{item}",
                                    correct=acierto))
            if acierto:
                eventos.append(c.monedas(2, sesion=sesion, n=n, sufijo=f"-i{item}"))
    eventos.append(c.de_eva("live.session.closed", sesion=sesion))
    return eventos


def _conteo(r: Any) -> dict[str, Any]:
    visto = ay.resumen(r)
    if len(visto) < 5:
        return {"estado": visto}
    return {"accepted": visto[1], "duplicates": visto[2], "rejected": len(visto[3])}


def test_he1_humo_eventos_anillo(integ) -> None:
    rng = random.Random(SEMILLA)
    ay.preparar()
    c = ay.clase(integ, estudiantes=6)
    eventos = clase_sintetica(c, rng, "aula-humo")
    lote = ay.lote(eventos, sesion="aula-humo")
    primera, segunda = ay.enviar("live", lote), ay.enviar("live", lote)
    medidos = rng.sample(c.estudiantes, 2)
    niveles = ay.enviar("set", ay.lote_de_set(
        *[ay.de_set(c.tenant, p, rng.choice(["A2", "B1", "B2"])) for p in medidos]))
    cuerpo = ay.serializar(lote)
    falsa = ay.enviar_bytes(cuerpo, ay.cabeceras("live", cuerpo, secreto="x" * 40))
    saldos = [ay.saldo(integ, p) for p in c.estudiantes]
    con_nivel = sum(1 for p in c.estudiantes if isinstance(ay.nivel(integ, p), dict))
    datos = {
        "alembic_version": integ.valor("select version_num from alembic_version"),
        "semilla": SEMILLA, "eventos": len(eventos),
        "primera": _conteo(primera), "segunda": _conteo(segunda),
        "filas": int(integ.valor("select count(*) from learning_events where origin = 'live'")),
        "monedas_acreditadas": sum(saldos), "filas_en_el_libro": len(ay.libro(integ)),
        "bolsa": integ.saldo("tenant", c.tenant),
        "niveles": {"accepted": _conteo(niveles).get("accepted")},
        "con_nivel": con_nivel, "sin_nivel": len(c.estudiantes) - con_nivel,
        "firma_falsa": falsa.status_code,
    }
    # Primero se escribe (para poder reportarlo), después se afirma.
    RUTA_HUMO_EVENTOS.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO_EVENTOS.write_text(
        json.dumps(datos, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    en_disco = json.loads(RUTA_HUMO_EVENTOS.read_text(encoding="utf-8"))
    assert en_disco == HUMO_ESPERADO, f"humo eventos: {en_disco} != {HUMO_ESPERADO}"


@pytest.mark.skipif(not REPLICA, reason="réplica de eventos: ENGRAMA_REPLICA_EVENTOS=1")
def test_re1_replica_lote_de_200_ids_raros_y_solapes(integ) -> None:
    rng = random.Random(38)
    ay.preparar()
    a, b = ay.clase(integ, estudiantes=3), ay.clase(integ)
    ana = a.estudiantes[0]
    sembrar(integ, "insert into memberships (tenant_id, profile_id, role, group_code, "
                   "is_active, full_name) values (:t, :p, 'student', 'G1', true, 'Ana en B')",
            t=b.tenant, p=ana)
    raro = ("año:2026 @ñandú · sesión/1 " * 20)[:256]
    en_a = {**a.monedas(3), "event_id": raro}
    en_b = {**a.monedas(4), "event_id": raro, "tenant_id": str(b.tenant)}
    dos_instituciones = ay.cortos(ay.enviar("live", ay.lote([en_a, en_b])))
    doscientos = [a.de_eva("answer.submitted", n=rng.randrange(3), sufijo=f"-r{i}",
                           correct=rng.random() < 0.5) for i in range(200)]
    de_200 = ay.cortos(ay.enviar("live", ay.lote(doscientos, batch_id="r-200")))
    solape = ay.cortos(ay.enviar("live", ay.lote(doscientos[100:] + [
        a.de_eva("item.exposed", sufijo=f"-n{i}") for i in range(50)], batch_id="r-solape")))
    observado = {
        "largo_del_id": len(raro), "mismo_id_en_dos_instituciones": dos_instituciones,
        "saldos_de_ana": [integ.valor(
            "select coalesce(sum(coins), 0) from learning_events where subject_id = :p "
            "and tenant_id = :t", p=ana, t=t) for t in (a.tenant, b.tenant)],
        "de_200": de_200, "solapado": solape, "filas": ay.filas(integ),
        "id_guardado_intacto": integ.valor("select count(*) from learning_events "
                                           "where event_id = :e", e=raro),
    }
    assert observado == {
        "largo_del_id": 256, "mismo_id_en_dos_instituciones": (200, 2, 0, [], []),
        "saldos_de_ana": [3, 4], "de_200": (200, 200, 0, [], []),
        "solapado": (200, 50, 100, [], []), "filas": 252, "id_guardado_intacto": 2,
    }, f"RE1: {observado}"
