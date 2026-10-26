"""HLC1 (humo) y RLC1 (réplica) del límite compartido — `docs/ESPEC_limites_registro.md` C7 y C8.

Por la ruta real (`POST /auth/registro`, detrás de un proxy: `PROXIES_DE_CONFIANZA
= 1`), unos pocos registros desde direcciones IPv6 de un mismo /64 y desde una
IPv4. Después se lee la tabla `limite_intentos` y se escribe el archivo ANTES
de afirmar:

  - HLC1 -> `tests/_salida/humo_limite_compartido.json`
  - RLC1 -> `tests/_salida/replica_limite_compartido.json`, con entradas que
    no se usaron al desarrollar: otro /64, una IPv4 envuelta en IPv6
    (`::ffff:…`), otra institución y otro grupo, y dos registros válidos.

Los archivos no traen IPs ni códigos: solo conteos por contador y si alguna
llave guardada contiene una dirección (debe ser que no).
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from src.registro import limite
from src.shared.config import settings
from tests.integ_db import RAIZ_BACKEND
from tests.registro import _ayuda as ay

pytestmark = pytest.mark.integ

SALIDA = RAIZ_BACKEND / "tests" / "_salida"


@pytest.fixture(autouse=True)
def _soltar_el_doble_al_terminar() -> Iterator[None]:
    yield
    ay.soltar()


def _tabla(integ: Any) -> dict[str, list[int]]:
    """Por contador: [llaves distintas, filas]."""
    filas = integ.run(_leer(integ))
    return {c: [int(llaves), int(n)] for c, llaves, n in filas}


async def _leer(integ: Any) -> list[tuple[str, int, int]]:
    from sqlalchemy import text

    async with integ.engine.connect() as conn:
        r = await conn.execute(text("select contador, count(distinct llave), count(*) "
                                    "from limite_intentos group by contador order by contador"))
        return [(str(c), int(k), int(n)) for c, k, n in r.all()]


def _llaves(integ: Any) -> list[str]:
    async def _q() -> list[str]:
        from sqlalchemy import text

        async with integ.engine.connect() as conn:
            r = await conn.execute(text("select distinct llave from limite_intentos"))
            return [str(x) for (x,) in r.all()]

    return list(integ.run(_q()))


def correr(integ: Any, *, red: str, ipv4: str, ipv4_como_se_ve: str,
           validos: int, grupo: str) -> dict[str, Any]:
    """`validos` registros con código bueno desde el /64, uno malo desde el /64 y uno malo desde la IPv4."""
    ay.preparar(integ)
    a = ay.aula(integ, grupo=grupo)
    saltos = settings.proxies_de_confianza
    try:
        settings.proxies_de_confianza = 1
        buenos = [ay.registrar(ay.cuerpo(a.codigo, n), **{"X-Forwarded-For": f"{red}::{n:x}"})
                  .status_code for n in range(1, validos + 1)]
        malo_64 = ay.registrar(ay.cuerpo("ZZZZ0001", 50),
                               **{"X-Forwarded-For": f"{red}:9:8:7:6"}).status_code
        malo_v4 = ay.registrar(ay.cuerpo("ZZZZ0002", 51),
                               **{"X-Forwarded-For": ipv4}).status_code
    finally:
        settings.proxies_de_confianza = saltos
    llaves = _llaves(integ)
    red_64 = f"{red}::/64"
    return {
        "alembic_version": integ.valor("select version_num from alembic_version"),
        "respuestas": {"buenos": buenos, "malo_desde_el_64": malo_64, "malo_desde_la_ipv4": malo_v4},
        "por_contador_llaves_y_filas": _tabla(integ),
        "filas_por_ip_del_64": ay.contar(
            integ, "select count(*) from limite_intentos where contador = 'por_ip' and llave = :l",
            l=limite._llave_guardada("por_ip", red_64)),
        "filas_por_ip_de_la_ipv4": ay.contar(
            integ, "select count(*) from limite_intentos where contador = 'por_ip' and llave = :l",
            l=limite._llave_guardada("por_ip", ipv4_como_se_ve)),
        "todas_las_llaves_son_huellas": all(re.fullmatch(r"[0-9a-f]{64}", x) for x in llaves),
        "alguna_llave_contiene_una_ip": any(
            p in x for x in llaves for p in (red.split(":")[0], red, ipv4_como_se_ve)),
    }


def _escribir(ruta: Path, datos: dict[str, Any]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def test_hlc1_humo_limite_compartido(integ) -> None:
    """HLC1 (C7): un válido y un malo desde un /64, un malo desde una IPv4; la tabla lo dice."""
    ruta = SALIDA / "humo_limite_compartido.json"
    datos = correr(integ, red="2001:db8:5:6", ipv4="192.0.2.10", ipv4_como_se_ve="192.0.2.10",
                   validos=1, grupo="G1")
    _escribir(ruta, datos)
    assert json.loads(ruta.read_text(encoding="utf-8")) == {
        "alembic_version": "050_invitaciones_docente",
        "respuestas": {"buenos": [201], "malo_desde_el_64": 403, "malo_desde_la_ipv4": 403},
        "por_contador_llaves_y_filas": {"global": [1, 1], "malos_por_ip": [2, 2],
                                        "por_codigo": [1, 1], "por_ip": [2, 3]},
        "filas_por_ip_del_64": 2, "filas_por_ip_de_la_ipv4": 1,
        "todas_las_llaves_son_huellas": True, "alguna_llave_contiene_una_ip": False,
    }, f"HLC1: {datos}"


def test_rlc1_replica_limite_compartido(integ) -> None:
    """RLC1 (C8): otro /64, una IPv4 envuelta, otra institución, dos válidos: el mismo veredicto."""
    ruta = SALIDA / "replica_limite_compartido.json"
    datos = correr(integ, red="2001:db8:ff:ee", ipv4="::ffff:198.51.100.77",
                   ipv4_como_se_ve="198.51.100.77", validos=2, grupo="GR")
    _escribir(ruta, datos)
    assert json.loads(ruta.read_text(encoding="utf-8")) == {
        "alembic_version": "050_invitaciones_docente",
        "respuestas": {"buenos": [201, 201], "malo_desde_el_64": 403, "malo_desde_la_ipv4": 403},
        "por_contador_llaves_y_filas": {"global": [1, 2], "malos_por_ip": [2, 2],
                                        "por_codigo": [1, 2], "por_ip": [2, 4]},
        "filas_por_ip_del_64": 3, "filas_por_ip_de_la_ipv4": 1,
        "todas_las_llaves_son_huellas": True, "alguna_llave_contiene_una_ip": False,
    }, f"RLC1: {datos}"
