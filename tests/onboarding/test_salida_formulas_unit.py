"""UH12 y su tramposo ZH12 — `docs/ESPEC_endurecimiento_piloto.md`, H-12.

No-integ. Un nombre o un correo que empieza por `=`, `+`, `-`, `@`, tabulador
o retorno de carro se escribe con un `'` delante: al abrir el CSV de
credenciales en Excel, ya no se ejecuta como fórmula.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.onboarding import salida

PELIGROSOS = ("=HYPERLINK(\"http://x\")", "+1+1", "-2+3", "@SUM(A1)", "\tcmd", "\rcmd")
CLAVE = "abcd-efgh-jkmn"


def _escrito(tmp_path: Path) -> list[list[str]]:
    ruta = tmp_path / "credenciales.csv"
    for texto in (*PELIGROSOS, "Ana Sintética"):
        salida.anotar(ruta, nombre=texto, correo=texto, rol="student", grupos=(texto,),
                      clave=CLAVE)
    with ruta.open(encoding="utf-8", newline="") as archivo:
        return list(csv.reader(archivo))[1:]


def test_uh12_las_formulas_se_neutralizan(tmp_path) -> None:
    """UH12 (H-12): los seis comienzos peligrosos llevan `'`; lo normal queda igual."""
    filas = _escrito(tmp_path)
    observado = {
        "nombres": [f[0] for f in filas],
        "correos_y_grupos_iguales_al_nombre": all(f[1] == f[0] == f[3] for f in filas),
        "claves": sorted({f[4] for f in filas}),
        "pura": [salida.neutralizar(t) for t in ("=1", "a=1", "", "'ya")],
    }
    assert observado == {
        "nombres": ["'" + p for p in PELIGROSOS] + ["Ana Sintética"],
        "correos_y_grupos_iguales_al_nombre": True, "claves": [CLAVE],
        "pura": ["'=1", "a=1", "", "'ya"],
    }, f"UH12: {observado}"


def test_zh12_tramposo_sin_neutralizar(tmp_path, monkeypatch) -> None:
    """ZH12: si la fórmula llega intacta al CSV, UH12 se pone rojo."""
    monkeypatch.setattr(salida, "neutralizar", lambda celda: celda)
    with pytest.raises(AssertionError, match=r"UH12: \{'nombres': \['=HYPERLINK"):
        test_uh12_las_formulas_se_neutralizan(tmp_path)
