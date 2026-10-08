"""La guardia estática del redondeo único — `docs/ESPEC_economia_oleada0.md` §1.8.

No empieza por `test_`: no se recolecta; la usa `test_economia_unit.py` (UE2).
Recorre el AST (no busca texto) y exige dos cosas:

  1. en los módulos que SOLO calculan monedas (`economia.py` y `onboarding/recarga.py`):
     ninguna llamada a `round`, ninguna constante `float` (ni `float(...)`) y ninguna
     división `/` (la `//` entera sí vale);
  2. en todo `src/`: ninguna llamada a `round`.

A `attendance.py` o `attempts.py` NO se les puede pedir lo primero: tienen `float`
y `/` legítimos que no son monedas (la distancia de la geocerca, el porcentaje del
intento). Por eso la regla de la casa es que todo monto sale de una función de
`economia.py`.
"""
from __future__ import annotations

import ast
from pathlib import Path

RAIZ_SRC = Path(__file__).resolve().parents[2] / "src"

# Los módulos que solo calculan monedas. `onboarding/recarga.py` nace con la recarga
# de la bolsa (E7): mientras no exista, la guardia no lo exige; apenas exista, se vigila.
MODULOS_DE_MONEDAS = ("engrama_core/service/economia.py", "onboarding/recarga.py")


def violaciones(texto: str, *, solo_monedas: bool) -> list[str]:
    """Las violaciones del `texto` (vacío = limpio). `solo_monedas` activa la regla 1."""
    encontradas: list[str] = []
    for nodo in ast.walk(ast.parse(texto)):
        linea = getattr(nodo, "lineno", 0)
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name):
            if nodo.func.id == "round":
                encontradas.append(f"línea {linea}: llamada a round()")
            elif solo_monedas and nodo.func.id == "float":
                encontradas.append(f"línea {linea}: llamada a float()")
        if not solo_monedas:
            continue
        if isinstance(nodo, ast.Constant) and isinstance(nodo.value, float):
            encontradas.append(f"línea {linea}: constante float {nodo.value!r}")
        if isinstance(nodo, ast.BinOp | ast.AugAssign) and isinstance(nodo.op, ast.Div):
            encontradas.append(f"línea {linea}: división /")
    return encontradas


def revisar_codigo(raiz: Path = RAIZ_SRC) -> dict[str, list[str]]:
    """Corre la guardia sobre el código real: {archivo: violaciones}, solo los que fallan."""
    resultado: dict[str, list[str]] = {}
    for ruta in sorted(raiz.rglob("*.py")):
        relativa = ruta.relative_to(raiz).as_posix()
        malas = violaciones(ruta.read_text(encoding="utf-8"),
                            solo_monedas=relativa in MODULOS_DE_MONEDAS)
        if malas:
            resultado[relativa] = malas
    return resultado
