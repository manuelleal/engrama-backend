"""UP2 (C14): el CSV del alta, sin base — `docs/ESPEC_login_piloto.md` §1.7.

No-integ: `leer_csv` es pura (bytes y slug -> filas válidas y errores).

Junta todo lo observado en un dict y lo compara ENTERO: así el rojo muestra de
una vez cada diferencia. `leer_csv` se llama por el módulo (`csv_mod.…`), para
que un tramposo que reemplace `con_prefijo` en `src.onboarding.csv_personas`
(ZP16) la alcance.

Datos sintéticos: ningún documento, nombre o correo es de una persona real.
"""
from __future__ import annotations

from typing import Any

from src.onboarding import csv_personas as csv_mod

CABECERA = "nombre,correo,documento,tipo_documento,grupo,rol"


def _csv(*filas: str, sep: str = ",", cabecera: str = CABECERA) -> str:
    return "\n".join([cabecera.replace(",", sep), *(f.replace(",", sep) for f in filas)]) + "\n"


def _leer(texto: str, slug: str = "sena", *, encoding: str = "utf-8") -> dict[str, Any]:
    """Lo que devuelve `leer_csv`, en una forma fácil de comparar."""
    filas, errores = csv_mod.leer_csv(texto.encode(encoding), slug)
    return {
        "filas": [(f.fila, f.nombre, f.documento_id, f.rol, f.grupo) for f in filas],
        "errores": [e.fila for e in errores],
    }


def test_up2_csv_del_alta() -> None:
    """UP2 (C14): normaliza, pone el prefijo, y junta TODOS los errores con su fila."""
    varios = _csv(
        "Ana Sintética,ana@engrama.test,12.345.678,CC,G1,estudiante",   # 1 buena
        "Beto Sintético,beto@engrama.test,12a,TI,G1,estudiante",        # 2 TI con letras
        "Caro Sintética,caro@engrama.test,9001,CC,,estudiante",         # 3 sin grupo
        "Dani Sintético,dani@engrama.test,9002,CC,G1,",                 # 4 buena (rol vacío)
        "Dani Sintético,dani@engrama.test,9002,CC,G2,profe",            # 5 dos roles
        "Eli Sintética,eli@engrama.test," + "x" * 28 + ",CODIGO,G1,estudiante",  # 6 pasa de 32
    )
    un_estudiante = "Íñigo Peña;inigo@engrama.test;1.234.567;CE;G1;estudiante"
    observado = {
        "cc_con_puntos": _leer(_csv("Ana Sintética,ana@engrama.test,12.345.678,CC,G1,estudiante")),
        "codigo_con_prefijo": _leer(_csv("Ana Sintética,ana@engrama.test,7,CODIGO,G1,estudiante")),
        "codigo_largo": _leer(_csv("Ana Sintética,ana@engrama.test," + "x" * 28
                                   + ",CODIGO,G1,estudiante")),
        "ti_con_letras": _leer(_csv("Ana Sintética,ana@engrama.test,12a,TI,G1,estudiante")),
        "estudiante_sin_grupo": _leer(_csv("Ana Sintética,ana@engrama.test,9001,CC,,estudiante")),
        "dos_roles": _leer(_csv("Ana Sintética,ana@engrama.test,9001,CC,G1,estudiante",
                                "Ana Sintética,ana@engrama.test,9001,CC,G1,profe")),
        "profe_en_dos_grupos": _leer(_csv("Pepa Sintética,pepa@engrama.test,9003,CC,G1,profe",
                                          "Pepa Sintética,pepa@engrama.test,9003,CC,G2,profe")),
        "punto_y_coma": _leer(_csv(un_estudiante, sep=";")),
        "bom": _leer("﻿" + _csv(un_estudiante, sep=";")),
        "cp1252": _leer(_csv(un_estudiante, sep=";"), encoding="cp1252"),
        "varios_errores": _leer(varios),
    }
    inigo = {"filas": [(1, "Íñigo Peña", "1234567", "student", "G1")], "errores": []}
    assert observado == {
        "cc_con_puntos": {"filas": [(1, "Ana Sintética", "12345678", "student", "G1")],
                          "errores": []},
        "codigo_con_prefijo": {"filas": [(1, "Ana Sintética", "sena_7", "student", "G1")],
                               "errores": []},
        "codigo_largo": {"filas": [], "errores": [1]},   # "sena_" + 28 = 33 caracteres
        "ti_con_letras": {"filas": [], "errores": [1]},
        "estudiante_sin_grupo": {"filas": [], "errores": [1]},
        "dos_roles": {"filas": [(1, "Ana Sintética", "9001", "student", "G1")], "errores": [2]},
        "profe_en_dos_grupos": {"filas": [(1, "Pepa Sintética", "9003", "teacher", "G1"),
                                          (2, "Pepa Sintética", "9003", "teacher", "G2")],
                                "errores": []},
        "punto_y_coma": inigo,
        "bom": inigo,
        "cp1252": inigo,
        "varios_errores": {"filas": [(1, "Ana Sintética", "12345678", "student", "G1"),
                                     (4, "Dani Sintético", "9002", "student", "G1")],
                           "errores": [2, 3, 5, 6]},
    }, f"UP2: {observado}"
