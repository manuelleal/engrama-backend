"""H1 — Humo de BUG-11 de punta a punta — `docs/ESPEC_bug11.md` §5.

Datos sintéticos con semilla fija (`random.Random(11)`): 5 documentos
`SINT-H11-0001..0005`. El colegio A los inscribe por M4 (CSV con `,`) y el
colegio B por M3, uno a uno, con nombres distintos: se cubren los dos
caminos de escritura. Después, T2 de D en GA y T2 de DT en GB.

Cada nombre lleva el sufijo de su colegio (`… A3`, `… B3`): los de un colegio
nunca son subcadena de los del otro.

Escribe `tests/_salida/humo_bug11.json` (en `.gitignore`) ANTES de afirmar,
y afirma que su contenido, leído del disco, es exactamente el esperado.
"""
from __future__ import annotations

import json
import random
from typing import Any

import pytest

from tests.integ_db import RAIZ_BACKEND
from tests.teachers import test_bug11_nombre_por_colegio as b11

pytestmark = pytest.mark.integ

RUTA_HUMO_BUG11 = RAIZ_BACKEND / "tests" / "_salida" / "humo_bug11.json"
SEMILLA = 11

NOMBRES = ("Ana", "Beto", "Caro", "Dani", "Eva", "Fede", "Gabi", "Hugo")
APELLIDOS = ("Rojas", "Pardo", "Mejía", "Ortiz", "Lozano", "Castro", "Vargas", "Silva")

# Contenido exacto (ESPEC §5). Si difiere se reporta; no se ajusta para que pase.
HUMO_ESPERADO: dict[str, Any] = {
    "alembic_version": "041_refuerzo", "semilla": 11, "documentos": 5,
    "perfiles": 5, "inscritos": [5, 5], "nombres_propios": [5, 5],
    "nombres_ajenos": [0, 0], "nombre_en_profiles": 0,
}


def _nombres(rng: random.Random, letra: str, n: int) -> list[str]:
    """`n` nombres sintéticos con el sufijo del colegio y la posición (`… A3`)."""
    return [f"{rng.choice(NOMBRES)} {rng.choice(APELLIDOS)} {letra}{i}" for i in range(1, n + 1)]


def _propios_y_ajenos(texto: str, filas: list[dict[str, Any]], propios: list[str],
                      ajenos: list[str]) -> tuple[int, int]:
    """(cuántos nombres propios salen tal cual, cuántos ajenos aparecen en el cuerpo)."""
    vistos = {f["full_name"] for f in filas}
    return sum(n in vistos for n in propios), sum(n in texto for n in ajenos)


def test_h1_humo_bug11(integ) -> None:
    rng = random.Random(SEMILLA)
    docs = [f"SINT-H11-{i:04d}" for i in range(1, 6)]
    nombres_a, nombres_b = _nombres(rng, "A", len(docs)), _nombres(rng, "B", len(docs))

    esc = b11._sembrar(integ)
    # A: M4, un solo CSV con `,`.
    inscritos_a = b11._m4(integ, esc, esc.aa, esc.grupo_a,
                          list(zip(docs, nombres_a, strict=True)))["creados"]
    # B: M3, uno a uno (`_m3` exige 201 `inscrito`).
    inscritos_b = sum(bool(b11._m3(integ, esc, esc.ab, esc.grupo_b, d, n))
                      for d, n in zip(docs, nombres_b, strict=True))

    filas_a, texto_a = b11._t2(integ, esc, esc.d, esc.grupo_a)
    filas_b, texto_b = b11._t2(integ, esc, esc.dt, esc.grupo_b)
    propios_a, ajenos_a = _propios_y_ajenos(texto_a, filas_a, nombres_a, nombres_b)
    propios_b, ajenos_b = _propios_y_ajenos(texto_b, filas_b, nombres_b, nombres_a)

    datos = {
        "alembic_version": integ.valor("select version_num from alembic_version"),
        "semilla": SEMILLA,
        "documentos": len(docs),
        "perfiles": integ.valor(
            "select count(*) from profiles where documento_id like 'SINT-H11-%'"),
        "inscritos": [inscritos_a, inscritos_b],
        "nombres_propios": [propios_a, propios_b],
        "nombres_ajenos": [ajenos_a, ajenos_b],
        "nombre_en_profiles": integ.valor(
            "select count(*) from profiles "
            "where documento_id like 'SINT-H11-%' and full_name <> ''"),
    }
    # Primero se escribe (para poder reportarlo), después se afirma.
    RUTA_HUMO_BUG11.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO_BUG11.write_text(
        json.dumps(datos, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    en_disco = json.loads(RUTA_HUMO_BUG11.read_text(encoding="utf-8"))
    assert en_disco == HUMO_ESPERADO, f"humo BUG-11: {en_disco} != {HUMO_ESPERADO}"
