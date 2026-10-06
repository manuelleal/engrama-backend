"""D1: M3 valida `documento_id` con la regex de M4 — `docs/ESPEC_login_piloto.md` §1.6.

  AP11  C11  (integ) el admin real matricula por M3: "12.345.678", "sena:001" y
             "ab" -> 422 con `loc == ["body", "documento_id"]` y 0 perfiles
             nuevos; "1098765432", "sena_001" y "uis-A-7" -> 201.

  UP1   C13  (no-integ) una sola fuente de la regex: `DOC_ID_RE.pattern ==
             DOC_ID_PATRON`, el `pattern` de `StudentEnrollIn.documento_id` es
             `DOC_ID_PATRON`, y `DOC_ID_RE.match("sena:001") is None`.

Por UP1 la marca `integ` va en cada test y no en `pytestmark`.

AP11 corrió en el paso 1 (`b81d373`) con `xfail(strict=True, raises=AssertionError)`:
`StudentEnrollIn.documento_id` era `str` a secas y M3 aceptaba cualquier formato.
En el paso 5 (D1) deja el xfail. Observa todo en un dict y lo compara entero,
así el rojo muestra cada documento.

UP1 lee el `pattern` de `model_fields` (no de `model_json_schema()`), para que
un tramposo que reemplace el campo (ZP10) lo alcance.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.teachers.schemas import DOC_ID_PATRON, StudentEnrollIn
from src.teachers.service.roster import DOC_ID_RE
from tests.teachers._actores import armar

client = TestClient(app, raise_server_exceptions=False)

MALOS = ("12.345.678", "sena:001", "ab")
BUENOS = ("1098765432", "sena_001", "uis-A-7")


def _locs(cuerpo: Any) -> list[Any] | None:
    """Los `loc` de un 422 de FastAPI; `None` si el cuerpo no es un error de validación."""
    if not isinstance(cuerpo, dict) or not isinstance(cuerpo.get("detail"), list):
        return None
    return [e.get("loc") for e in cuerpo["detail"] if isinstance(e, dict)]


@pytest.mark.integ
def test_ap11_m3_valida_documento(integ) -> None:
    """AP11 (C11): los tres malos -> 422 sin crear perfiles; los tres buenos -> 201."""
    esc = armar(integ)
    ruta = f"/admin/groups/{esc.grupo_a}/students"
    h = esc.h(integ, esc.aa)

    antes = integ.valor("select count(*) from profiles")
    malos = {}
    for doc in MALOS:
        r = client.post(ruta, headers=h, json={"documento_id": doc,
                                                "nombre_completo": "Estudiante Sintético"})
        cuerpo = r.json() if r.headers.get("content-type") == "application/json" else None
        malos[doc] = (r.status_code, _locs(cuerpo))
    nuevos_malos = integ.valor("select count(*) from profiles") - antes

    buenos = {doc: client.post(ruta, headers=h, json={
        "documento_id": doc, "nombre_completo": "Estudiante Sintético"}).status_code
        for doc in BUENOS}

    assert {"malos": malos, "perfiles_nuevos_por_malos": nuevos_malos, "buenos": buenos} == {
        "malos": {doc: (422, [["body", "documento_id"]]) for doc in MALOS},
        "perfiles_nuevos_por_malos": 0,
        "buenos": {doc: 201 for doc in BUENOS},
    }


def _patron_del_campo(modelo: Any, campo: str) -> str | None:
    """El `pattern` declarado en `Field(pattern=...)` del campo, o `None`."""
    for meta in modelo.model_fields[campo].metadata:
        patron = getattr(meta, "pattern", None)
        if patron is not None:
            return str(patron)
    return None


def test_up1_una_sola_fuente_de_la_regex() -> None:
    """UP1 (C13): M3 y M4 validan con el mismo patrón, y `:` no entra."""
    assert {
        "m4": DOC_ID_RE.pattern,
        "m3": _patron_del_campo(StudentEnrollIn, "documento_id"),
        "sena:001": DOC_ID_RE.match("sena:001"),
    } == {"m4": DOC_ID_PATRON, "m3": DOC_ID_PATRON, "sena:001": None}
