"""H16 — Humo de BUG-16 — `docs/ESPEC_bug16.md` §3.

Un docente real, por la API: un reto con `challenge_type: "practice"`, otro con
`cefr_level: "B3"`, `POST /challenges/generate` con `B3` (sin clave de
Anthropic: si el 422 no llegara, sería un 503 local, nunca una llamada a la
IA), y después los 4 tipos y los 11 niveles válidos.

Escribe `tests/_salida/humo_bug16.json` (en `.gitignore`) ANTES de afirmar, y
afirma que su contenido, leído del disco, es exactamente el esperado.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from tests.challenge_engine import test_bug16_enum as b16
from tests.integ_db import RAIZ_BACKEND

pytestmark = pytest.mark.integ

RUTA_HUMO_BUG16 = RAIZ_BACKEND / "tests" / "_salida" / "humo_bug16.json"

# Contenido exacto (ESPEC §3). Si difiere se reporta; no se ajusta para que pase.
HUMO_ESPERADO: dict[str, Any] = {
    "practice": 422, "B3": 422, "generate_B3": 422,
    "tipos_validos": [201, 201, 201, 201], "niveles_validos": 11,
    "filas_con_valor_invalido": 0,
}


def test_h16_humo_bug16(integ, monkeypatch) -> None:
    docente = b16._docente(integ)
    datos = {
        "practice": b16.crear(integ, docente, challenge_type="practice").status_code,
        "B3": b16.crear(integ, docente, cefr_level="B3").status_code,
        "generate_B3": b16.generar_b3(monkeypatch, headers=integ.headers(docente)),
        "tipos_validos": [b16.crear(integ, docente, challenge_type=t).status_code
                          for t in b16.TIPOS],
        "niveles_validos": [b16.crear(integ, docente, cefr_level=n).status_code
                            for n in b16.NIVELES].count(201),
        "filas_con_valor_invalido": int(integ.valor(
            "select count(*) from challenges where challenge_type <> all(:tipos) "
            "or (cefr_level is not null and cefr_level <> all(:niveles))",
            tipos=list(b16.TIPOS), niveles=list(b16.NIVELES))),
    }
    # Primero se escribe (para poder reportarlo), después se afirma.
    RUTA_HUMO_BUG16.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO_BUG16.write_text(
        json.dumps(datos, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    en_disco = json.loads(RUTA_HUMO_BUG16.read_text(encoding="utf-8"))
    assert en_disco == HUMO_ESPERADO, f"humo BUG-16: {en_disco} != {HUMO_ESPERADO}"
