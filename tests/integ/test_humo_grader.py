"""HG1 (humo) y RG1 (réplica) de la puerta del Grader — `docs/ESPEC_grader_anillo.md` §9.8.

HG1: un grupo sintético de 28, un examen de 15 ítems (5 con nodos del catálogo
sintético), 28 hojas con respuestas al azar (`random.Random(39)`) y 2
reenviadas con una corrección. Escribe `tests/_salida/humo_grader.json` (en
`.gitignore`) ANTES de afirmar.

RG1 solo corre con `ENGRAMA_REPLICA_GRADER=1`, con entradas que no se usaron al
desarrollar: tres instituciones con el MISMO código de grupo y el MISMO código
de examen; formas A y B; una hoja con todo `vacia`; un examen de 1 ítem; y un
examen de 200 ítems.
"""
from __future__ import annotations

import json
import os
import random
from typing import Any

import pytest

from tests.curriculo import _ayuda as cat
from tests.grader import _ayuda as ay
from tests.integ_db import RAIZ_BACKEND

pytestmark = pytest.mark.integ

RUTA_HUMO_GRADER = RAIZ_BACKEND / "tests" / "_salida" / "humo_grader.json"
SEMILLA = 39
REPLICA = os.environ.get("ENGRAMA_REPLICA_GRADER") == "1"

# Contenido exacto (ESPEC §9.8). `aciertos_totales` salió de la primera medición
# con el código bueno y no se mueve. Si difiere se reporta; no se ajusta.
HUMO_ESPERADO: dict[str, Any] = {
    "alembic_version": "039_grader", "semilla": 39, "lista": 28, "examen": 201,
    "examen_otra_vez": 200,
    "primer_envio": {"recibidas": 28, "reemplazadas": 0, "rechazadas": 0},
    "reenvio": {"recibidas": 2, "reemplazadas": 2, "rechazadas": 0},
    "hojas": 28, "items": 420, "aciertos_totales": 301, "con_nodos": 5, "nivel_escrito": 0,
    "monedas_movidas": 0,
}


def _corto(respuesta: tuple[int, Any]) -> Any:
    if respuesta[0] != 200:
        return respuesta
    recibidas, reemplazadas, rechazadas = respuesta[1]
    return {"recibidas": recibidas, "reemplazadas": reemplazadas, "rechazadas": len(rechazadas)}


def _hoja_al_azar(rng: random.Random, numero: int, n: int) -> dict[str, Any]:
    """Cada ítem: 70 % acierta, 20 % falla, 5 % vacía y 5 % doble."""
    malas, vacias, dobles = [], [], []
    for i in range(n):
        tiro = rng.random()
        if tiro >= 0.95:
            dobles.append(i)
        elif tiro >= 0.90:
            vacias.append(i)
        elif tiro >= 0.70:
            malas.append(i)
    return ay.hoja(numero, n, malas=tuple(malas), vacias=tuple(vacias), dobles=tuple(dobles),
                   forma=rng.choice("AB"))


def test_hg1_humo_grader(integ) -> None:
    rng = random.Random(SEMILLA)
    cat.cargar(integ, cat.mapa_v1())
    c = ay.colegio(integ, n=28)
    lista = ay.lista(integ, c.profe, c.codigo_grupo)
    ids = ay.ids_de_items(15)
    items = [ay.item(i, nodos=[rng.choice(cat.VIGENTES_V1)] if pos < 5 else [])
             for pos, i in enumerate(ids)]
    cuerpo = ay.examen(c.codigo_grupo, items=items)
    registro = ay.registrar(integ, c.profe, cuerpo)
    otra_vez = ay.registrar(integ, c.profe, cuerpo)
    hojas = [_hoja_al_azar(rng, numero, 15) for numero, _ in lista[1]]
    primer_envio = ay.enviar(integ, c.profe, c.codigo_grupo, hojas)
    corregidas = [ay.hoja(n, malas=(0,)) for n in rng.sample(range(1, 29), 2)]
    reenvio = ay.enviar(integ, c.profe, c.codigo_grupo, corregidas)
    datos = {
        "alembic_version": integ.valor("select version_num from alembic_version"),
        "semilla": SEMILLA, "lista": len(lista[1]), "examen": registro[0],
        "examen_otra_vez": otra_vez[0], "primer_envio": _corto(primer_envio),
        "reenvio": _corto(reenvio), "hojas": ay.cuenta(integ, "grader_sheets"),
        "items": ay.cuenta(integ, "grader_sheet_items"),
        "aciertos_totales": int(integ.valor("select coalesce(sum(aciertos), 0) "
                                            "from grader_sheets")),
        "con_nodos": int(integ.valor("select count(*) from grader_exam_items "
                                     "where cardinality(nodos) > 0")),
        "nivel_escrito": int(integ.valor("select count(*) from confirmed_levels")),
        "monedas_movidas": int(integ.valor("select count(*) from coin_ledger")),
    }
    RUTA_HUMO_GRADER.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO_GRADER.write_text(
        json.dumps(datos, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    assert datos == HUMO_ESPERADO, f"HG1: {datos}"


@pytest.mark.skipif(not REPLICA, reason="réplica del Grader: ENGRAMA_REPLICA_GRADER=1")
def test_rg1_replica_mismo_codigo_en_tres_instituciones(integ) -> None:
    """RG1: tres instituciones con el mismo grupo y el mismo código no se mezclan."""
    colegios = [ay.colegio(integ, "9-01", n=4) for _ in range(3)]
    huellas = ["1" * 64, "2" * 64, "3" * 64]
    tamanos = [1, 200, 7]
    por_colegio = []
    for c, huella, n in zip(colegios, huellas, tamanos, strict=True):
        lista = ay.lista(integ, c.profe, "9-01")
        registro = ay.registrar(integ, c.profe, ay.examen("9-01", n, huella=huella))
        hojas = [ay.hoja(1, n, forma="A"), ay.hoja(2, n, forma="B", vacias=tuple(range(n))),
                 ay.hoja(3, n, forma="B", malas=(0,))]
        envio = ay.enviar(integ, c.profe, "9-01", hojas, huella=huella)
        ajena = ay.enviar(integ, c.profe, "9-01", [ay.hoja(4, n)],
                          huella=huellas[(huellas.index(huella) + 1) % 3])
        guardadas = [fila for fila in (ay_hoja(integ, c, k) for k in (1, 2, 3))]
        por_colegio.append((len(lista[1]), registro, envio, ajena, guardadas))
    esperado: list[Any] = [(4, (201, True), (200, (3, 0, [])), (409, "examen_con_otra_huella"),
                 [(n, n), (0, n), (n - 1, n)]) for n in tamanos]
    observado = {"por_colegio": por_colegio, "filas": ay.filas(integ)}
    assert observado == {"por_colegio": esperado, "filas": (3, 208, 9, 624)}, f"RG1: {observado}"


def ay_hoja(integ: Any, c: ay.Colegio, numero: int) -> Any:
    """(aciertos, total) de la hoja de ese número en el examen de ESE colegio."""
    fila = integ.fila(
        "select s.aciertos, s.total from grader_sheets s join grader_exams e "
        "on e.id = s.exam_id where e.tenant_id = :t and s.numero = :n", t=c.tenant, n=numero)
    return None if fila is None else (fila["aciertos"], fila["total"])
