"""Un lote, una transacción — `docs/ESPEC_lote_una_transaccion.md` §2.

  LT1  un lote de 38 eventos válidos hace UN commit (antes, 38).
  LT2  un rechazado en medio no deshace a los aceptados de antes ni de después.
  LT3  réplica: el reenvío solapado de un satélite que cortó por timeout.
  HL1  humo: un lote de 200 (el tope) con un commit; escribe su archivo.

Los commits se cuentan con el evento `commit` de `Engine` (SQLAlchemy): cada uno
es un COMMIT real en la base, y en un disco mecánico cada uno espera el disco.
Lo observado va en un dict que se compara ENTERO (reglas de `_ayuda.py`).
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from tests.integ_db import RAIZ_BACKEND
from tests.webhooks import _ayuda as ay

pytestmark = pytest.mark.integ

RUTA_HUMO = RAIZ_BACKEND / "tests" / "_salida" / "humo_lote_una_transaccion.json"
HUMO_ESPERADO = {"eventos": 200, "aceptados": 200, "commits": 1, "instantes_de_recepcion": 1}


@contextmanager
def commits() -> Iterator[list[int]]:
    """Cuántos COMMIT llegan a la base mientras dura el bloque (todas las conexiones)."""
    cuenta = [0]

    def al_commit(_conexion: Any) -> None:
        cuenta[0] += 1

    event.listen(Engine, "commit", al_commit)
    try:
        yield cuenta
    finally:
        event.remove(Engine, "commit", al_commit)


def enviar_contando(lote_: dict[str, Any]) -> tuple[httpx.Response, int]:
    with commits() as cuenta:
        r = ay.enviar("live", lote_)
    return r, cuenta[0]


def instantes(integ: Any, batch_id: str) -> int:
    """`received_at` distintos del lote: `now()` es el inicio de SU transacción."""
    return int(integ.valor("select count(distinct received_at) from learning_events "
                           "where batch_id = :b", b=batch_id))


def saldos(integ: Any, c: ay.Clase) -> list[int]:
    return [ay.saldo(integ, e) for e in c.estudiantes]


def una_clase(c: ay.Clase, items: int, *, sesion: str, monedas: Callable[[int, int], int]
              ) -> list[dict[str, Any]]:
    """Por pregunta `k`: la exposición, la respuesta de cada estudiante y sus monedas.

    `monedas(k, n)` = cuántas gana el estudiante `n` en la pregunta `k` (0 = ninguna).
    """
    eventos: list[dict[str, Any]] = []
    for k in range(items):
        eventos.append(c.de_eva("item.exposed", sesion=sesion, sufijo=f"-i{k}"))
        eventos += [c.de_eva("answer.submitted", sesion=sesion, n=n, sufijo=f"-i{k}")
                    for n in range(len(c.estudiantes))]
        eventos += [c.monedas(m, n=n, sesion=sesion, sufijo=f"-i{k}")
                    for n in range(len(c.estudiantes)) if (m := monedas(k, n))]
    return eventos


# =============================================================================
# LT1 — un lote, un commit
# =============================================================================
def test_lt1_un_lote_hace_un_solo_commit(integ) -> None:
    """LT1: 38 eventos (5 tipos, 4 estudiantes) entran con 1 COMMIT y un solo `received_at`."""
    ay.preparar()
    c = ay.clase(integ, estudiantes=4)
    eventos = ([c.de_eva("live.session.started")]
               + una_clase(c, 4, sesion="aula-1", monedas=lambda k, n: 2)
               + [c.de_eva("live.session.closed")])
    r, n_commits = enviar_contando(ay.lote(eventos, batch_id="lt1"))
    observado = {"eventos": len(eventos), "respuesta": ay.resumen(r), "commits": n_commits,
                 "instantes": instantes(integ, "lt1"), "filas": ay.filas(integ),
                 "saldos": saldos(integ, c)}
    assert observado == {"eventos": 38, "respuesta": (200, 38, 0, [], []), "commits": 1,
                         "instantes": 1, "filas": 38, "saldos": [8, 8, 8, 8]}, f"LT1: {observado}"


# =============================================================================
# LT2 — un rechazado en medio no se lleva a sus vecinos
# =============================================================================
def test_lt2_un_rechazado_en_medio_no_deshace_a_los_vecinos(integ) -> None:
    """LT2: [monedas est0, respuesta, sujeto ajeno, monedas est1, respuesta] → 4 filas, saldos [2, 3]."""
    ay.preparar()
    c, otra = ay.clase(integ, estudiantes=2), ay.clase(integ)
    ajeno = {**c.de_eva("answer.submitted", sufijo="-ajeno"),
             "subject_id": str(otra.estudiantes[0])}
    eventos = [c.monedas(2, n=0), c.de_eva("answer.submitted", n=0), ajeno,
               c.monedas(3, n=1), c.de_eva("answer.submitted", n=1)]
    r = ay.enviar("live", ay.lote(eventos, batch_id="lt2"))
    observado = {"respuesta": ay.resumen(r), "filas": ay.filas(integ), "saldos": saldos(integ, c)}
    assert observado == {
        "respuesta": (200, 4, 0, [(ajeno["event_id"], "unknown_subject")], []),
        "filas": 4, "saldos": [2, 3],
    }, f"LT2: {observado}"


# =============================================================================
# LT3 — réplica: el reenvío solapado (lo que deja un timeout del satélite)
# =============================================================================
def test_lt3_replica_reenvio_solapado(integ) -> None:
    """LT3: 30 eventos y luego los 60 que los contienen → 30 nuevos, 30 duplicados, una paga por evento."""
    ay.preparar()
    c = ay.clase(integ, estudiantes=6)
    sesenta = una_clase(c, 6, sesion="aula-r", monedas=lambda k, n: 1 if (k + n) % 2 == 0 else 0)
    primero = ay.resumen(ay.enviar("live", ay.lote(sesenta[:30], batch_id="aula-r:0-29")))
    r, n_commits = enviar_contando(ay.lote(sesenta, batch_id="aula-r:0-59"))
    observado = {"eventos": len(sesenta), "primero": primero, "segundo": ay.resumen(r),
                 "commits_del_segundo": n_commits, "filas": ay.filas(integ),
                 "pagas_en_el_libro": len(ay.libro(integ)), "saldos": saldos(integ, c)}
    assert observado == {"eventos": 60, "primero": (200, 30, 0, [], []),
                         "segundo": (200, 30, 30, [], []), "commits_del_segundo": 1,
                         "filas": 60, "pagas_en_el_libro": 18,
                         "saldos": [3, 3, 3, 3, 3, 3]}, f"LT3: {observado}"


# =============================================================================
# HL1 — humo: el tope de 200, escrito a disco
# =============================================================================
def test_hl1_humo_lote_de_200(integ) -> None:
    """HL1: 200 respuestas en un lote; el archivo se escribe ANTES de afirmar y se relee."""
    ay.preparar()
    c = ay.clase(integ, estudiantes=6)
    doscientos = [c.de_eva("answer.submitted", sesion="aula-h", n=i % 6, sufijo=f"-h{i}")
                  for i in range(200)]
    inicio = time.perf_counter()
    r, n_commits = enviar_contando(ay.lote(doscientos, batch_id="hl1"))
    segundos = round(time.perf_counter() - inicio, 3)
    datos = {"eventos": len(doscientos), "aceptados": (ay.cuerpo_json(r) or {}).get("accepted"),
             "commits": n_commits, "instantes_de_recepcion": instantes(integ, "hl1")}
    RUTA_HUMO.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO.write_text(json.dumps({**datos, "segundos_informativo": segundos},
                                    ensure_ascii=False, separators=(",", ":")) + "\n",
                         encoding="utf-8")
    en_disco = json.loads(RUTA_HUMO.read_text(encoding="utf-8"))
    en_disco.pop("segundos_informativo")  # el tiempo depende de la máquina: se anota, no se afirma
    assert en_disco == HUMO_ESPERADO, f"HL1: {en_disco} != {HUMO_ESPERADO}"
