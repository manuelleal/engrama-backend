"""U1 (C10): ningún `.py` de `src/teachers/` lee el nombre global — `docs/ESPEC_bug11.md` §2, §3.

Desde la 032, el nombre que ve un colegio sale de SU membresía
(`Membership.full_name`). `profiles.full_name` es el "nombre propio de la
cuenta" y puede ser `''` o el del primer colegio (filas viejas): si alguna
ruta de `/teachers` o `/admin` volviera a leerlo, el hueco de BUG-11 se
reabriría. U1 lo vigila sin base de datos (no-integ).

Cómo: se recorre el AST de cada archivo y se busca el atributo `full_name`
leído sobre el nombre `Profile` (la clase, p. ej. en un `select`) o
`profile` (una instancia). Por ser AST, los comentarios y docstrings no
cuentan. Escribir `Profile(full_name="")` es un argumento con nombre, no
una lectura: tampoco cuenta.

Control (ESPEC C10): se escanearon 8 archivos o más; si no, el lector está
roto y U1 no probaría nada (`PruebaRota`, no AssertionError).

Tramposo: Y8 (`tests/tramposos/test_tramposos_bug11_estatico.py`) parchea
`_fuentes()` y agrega un `falso.py` que sí lee `Profile.full_name`.
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests.seguridad.veredictos import PruebaRota

RAIZ_TEACHERS = Path(__file__).resolve().parents[2] / "src" / "teachers"
DUENOS_DEL_NOMBRE_GLOBAL = frozenset({"Profile", "profile"})
MINIMO_ARCHIVOS = 8


def _fuentes() -> dict[str, str]:
    """{ruta relativa a `src/teachers`: texto} de cada `.py` (recursivo)."""
    return {
        ruta.relative_to(RAIZ_TEACHERS).as_posix(): ruta.read_text(encoding="utf-8")
        for ruta in sorted(RAIZ_TEACHERS.rglob("*.py"))
    }


def lecturas_nombre_global(fuentes: dict[str, str]) -> list[str]:
    """`["archivo:línea", ...]` donde se lee `Profile.full_name` o `profile.full_name`."""
    hallazgos: list[str] = []
    for nombre, texto in sorted(fuentes.items()):
        for nodo in ast.walk(ast.parse(texto, filename=nombre)):
            if (isinstance(nodo, ast.Attribute) and nodo.attr == "full_name"
                    and isinstance(nodo.value, ast.Name)
                    and nodo.value.id in DUENOS_DEL_NOMBRE_GLOBAL):
                hallazgos.append(f"{nombre}:{nodo.lineno}")
    return hallazgos


def test_u1_teachers_no_lee_el_nombre_global() -> None:
    fuentes = _fuentes()
    if len(fuentes) < MINIMO_ARCHIVOS:
        raise PruebaRota(
            f"control U1: se escanearon {len(fuentes)} archivos de {RAIZ_TEACHERS}; "
            f"se esperaban {MINIMO_ARCHIVOS} o más"
        )
    lecturas = lecturas_nombre_global(fuentes)
    assert lecturas == [], (
        f"src/teachers lee el nombre global (BUG-11): {lecturas}"
    )
