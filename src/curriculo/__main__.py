"""Orden del operador: `python -m src.curriculo cargar --archivo <nodos.json>`.

ESPEC_catalogo_nodos §1.2. Corre contra `DATABASE_URL`. Sale con 0 si cargó;
con 2 si el archivo no cumple o falta algo, y entonces NO escribió nada.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from src.curriculo.carga import cargar
from src.curriculo.mapa import MapaInvalido, leer_mapa
from src.onboarding.__main__ import sesiones_del_entorno
from src.onboarding.cuentas import ErrorDeConfiguracion

SALIDA_OK = 0
SALIDA_NO_CORRIO = 2


async def correr_carga(datos: Any, sesiones: Any) -> dict[str, Any]:
    """Lee, carga y confirma. Lanza `MapaInvalido` sin haber escrito nada."""
    mapa = leer_mapa(datos)
    async with sesiones() as db:
        resumen = await cargar(db, mapa)
        await db.commit()
    return resumen


def _argumentos(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m src.curriculo")
    sub = p.add_subparsers(dest="orden", required=True)
    orden = sub.add_parser("cargar", help="carga el mapa generado en el catálogo")
    orden.add_argument("--archivo", required=True, type=Path, help="curriculo/nodos.json")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, sesiones: Any = None) -> int:
    """Punto de entrada. `sesiones` se inyecta en los tests."""
    a = _argumentos(sys.argv[1:] if argv is None else argv)
    try:
        datos = json.loads(a.archivo.read_text(encoding="utf-8"))
        sesiones = sesiones if sesiones is not None else sesiones_del_entorno()
        resumen = asyncio.run(correr_carga(datos, sesiones))
    except (OSError, ValueError) as exc:
        print(f"no se pudo leer {a.archivo}: {exc}", file=sys.stderr)
        return SALIDA_NO_CORRIO
    except ErrorDeConfiguracion as exc:
        print(str(exc), file=sys.stderr)
        return SALIDA_NO_CORRIO
    except MapaInvalido as exc:
        print(json.dumps({"error": exc.motivo, "nodos": exc.ids}, ensure_ascii=False),
              file=sys.stderr)
        return SALIDA_NO_CORRIO
    print(json.dumps(resumen, ensure_ascii=False))
    return SALIDA_OK


if __name__ == "__main__":
    raise SystemExit(main())
