"""U1 y U2 — ESPEC §4: el parseo/validación sintáctica del CSV de M4, sin DB.

`parse_csv` y `validate_syntax` son funciones puras (`src/teachers/service/
roster.py`): no hablan con la base, así que estos tests no llevan
`pytestmark = pytest.mark.integ` y corren con `-m "not integ"`.
"""
from __future__ import annotations

from src.teachers.service.roster import MAX_FILAS_CSV, parse_csv, validate_syntax


# =============================================================================
# U1 — CSV válido (`,`, `;`, BOM)
# =============================================================================
def test_u1_csv_valido() -> None:
    con_coma = parse_csv(b"documento_id,nombre_completo\ndoc-1,Ana Perez\ndoc-2,Beto Ruiz\n")
    assert con_coma == [
        {"documento_id": "doc-1", "nombre_completo": "Ana Perez"},
        {"documento_id": "doc-2", "nombre_completo": "Beto Ruiz"},
    ]

    con_pyc = parse_csv("documento_id;nombre_completo\ndoc-1;Ana Pérez\n".encode())
    assert con_pyc == [{"documento_id": "doc-1", "nombre_completo": "Ana Pérez"}]

    con_bom = parse_csv("documento_id,nombre_completo\ndoc-1,Ana\n".encode("utf-8-sig"))
    assert con_bom == [{"documento_id": "doc-1", "nombre_completo": "Ana"}]
    assert "documento_id" in con_bom[0]  # el BOM no queda pegado a la 1a clave

    # Columnas de más se leen pero `validate_syntax` solo usa las 2 que importan;
    # `pin` nunca llega a `enroll_student` (ESPEC M4: "pin nunca se guarda").
    con_pin = parse_csv(b"documento_id,nombre_completo,pin\ndoc-1,Ana,1234\n")
    validas, errores = validate_syntax(con_pin)
    assert errores == []
    assert validas == [(1, "doc-1", "Ana")]


# =============================================================================
# U2 — CSV con errores
# =============================================================================
def test_u2_csv_con_errores() -> None:
    doc_invalido, err_doc = validate_syntax([{"documento_id": "a!", "nombre_completo": "Ana"}])
    assert doc_invalido == []
    assert err_doc[0].fila == 1 and "inválido" in err_doc[0].motivo

    nombre_vacio, err_nombre = validate_syntax([{"documento_id": "doc-1",
                                                  "nombre_completo": "   "}])
    assert nombre_vacio == []
    assert err_nombre[0].fila == 1 and "vac" in err_nombre[0].motivo

    repetida, err_rep = validate_syntax([
        {"documento_id": "doc-1", "nombre_completo": "Ana"},
        {"documento_id": "doc-1", "nombre_completo": "Ana Otra Vez"},
    ])
    assert repetida == [(1, "doc-1", "Ana")]
    assert err_rep[0].fila == 2 and "repetido" in err_rep[0].motivo

    exceso = [{"documento_id": f"doc-{i}", "nombre_completo": "Ana"}
              for i in range(MAX_FILAS_CSV + 1)]
    validas_exceso, err_exceso = validate_syntax(exceso)
    assert validas_exceso == []
    assert len(err_exceso) == 1 and str(MAX_FILAS_CSV + 1) in err_exceso[0].motivo

    exactas = [{"documento_id": f"doc-{i}", "nombre_completo": "Ana"}
               for i in range(MAX_FILAS_CSV)]
    validas_exactas, err_exactas = validate_syntax(exactas)
    assert err_exactas == []
    assert len(validas_exactas) == MAX_FILAS_CSV
