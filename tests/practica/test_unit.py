"""UP1 a UP3: las reglas PURAS del nivel de práctica y de la tanda.

`docs/ESPEC_practica_y_tanda.md` §2. Sin base ni reloj. Tramposos:
`tests/tramposos/test_tramposos_practica.py`.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.practica import reglas
from src.practica.reglas import Candidato, Escalera, Tamano
from src.shared.config import Settings

E = Escalera(ventana=12, sube=10, baja=5, ventana_rapida=6, sube_rapida=5, baja_rapida=2,
             decisiones_rapidas=3)
T = Tamano(preguntas_min=6, retos_max=4)
VARIABLES = ("PRACTICA_NIVEL_INICIAL", "PRACTICA_VENTANA", "PRACTICA_SUBE", "PRACTICA_BAJA",
             "PRACTICA_VENTANA_RAPIDA", "PRACTICA_SUBE_RAPIDA", "PRACTICA_BAJA_RAPIDA",
             "PRACTICA_DECISIONES_RAPIDAS", "TANDA_REPASOS_MAX", "TANDA_PREGUNTAS_MIN",
             "TANDA_RETOS_MAX", "TANDA_MAX_AL_DIA")


def _r(correctas: int, total: int) -> list[bool]:
    """`total` respuestas, con las `correctas` al final (lo más nuevo)."""
    return [False] * (total - correctas) + [True] * correctas


def test_up1_el_arranque_y_los_limites(monkeypatch: pytest.MonkeyPatch) -> None:
    """UP1 (C1): con SET, ese nivel y ±1; sin SET, A2; siempre de A1 a C1."""
    for nombre in VARIABLES:
        monkeypatch.delenv(nombre, raising=False)
    c = Settings(_env_file=None)  # type: ignore[call-arg]
    observado: dict[str, Any] = {
        "por_defecto": (c.practica_nivel_inicial, c.practica_ventana, c.practica_sube,
                        c.practica_baja, c.practica_ventana_rapida, c.practica_sube_rapida,
                        c.practica_baja_rapida, c.practica_decisiones_rapidas,
                        c.tanda_repasos_max, c.tanda_preguntas_min, c.tanda_retos_max,
                        c.tanda_max_al_dia),
        "arranque": {s or "sin SET": reglas.inicial(s, c.practica_nivel_inicial)
                     for s in (None, "A1", "B1", "C1", "C2")},
        "base": [reglas.base(x) for x in ("B1+", "B1-", "A1", "C1+", "C2", None, "", "Z9")],
        "limites": {a or "sin SET": [reglas.NIVELES[i] for i in reglas.limites(a)]
                    for a in (None, "A1", "B1", "C1")},
        "mover": {
            "B1 sube con ancla B1": reglas.mover("B1", +1, "B1"),
            "B2 sube con ancla B1": reglas.mover("B2", +1, "B1"),
            "A2 baja con ancla B1": reglas.mover("A2", -1, "B1"),
            "C1 sube sin ancla": reglas.mover("C1", +1, None),
            "A1 baja sin ancla": reglas.mover("A1", -1, None),
        },
    }
    assert observado == {
        "por_defecto": ("A2", 12, 10, 5, 6, 5, 2, 3, 3, 6, 4, 2),
        "arranque": {"sin SET": ("A2", None), "A1": ("A1", "A1"), "B1": ("B1", "B1"),
                     "C1": ("C1", "C1"), "C2": ("C1", "C1")},
        "base": ["B1", "B1", "A1", "C1", "C1", None, None, None],
        "limites": {"sin SET": ["A1", "C1"], "A1": ["A1", "A2"], "B1": ["A2", "B2"],
                    "C1": ["B2", "C1"]},
        "mover": {"B1 sube con ancla B1": "B2", "B2 sube con ancla B1": "B2",
                  "A2 baja con ancla B1": "A2", "C1 sube sin ancla": "C1",
                  "A1 baja sin ancla": "A1"},
    }, f"UP1: {observado}"


def test_up2_la_escalera() -> None:
    """UP2 (C2): 10 de 12 sube y 5 baja; sin SET, las 3 primeras decisiones con ventana de 6."""
    lenta = lambda r, nivel="B1", ancla=None: reglas.decidir(nivel, r, ancla, 3, E)  # noqa: E731
    rapida = lambda r, d=0: reglas.decidir("A2", r, None, d, E)  # noqa: E731
    observado = {
        "ventana_de_12": {
            "10 de 12": lenta(_r(10, 12)), "9 de 12": lenta(_r(9, 12)),
            "6 de 12": lenta(_r(6, 12)), "5 de 12": lenta(_r(5, 12)),
            "11 de 11 (sin llenar)": lenta(_r(11, 11)),
            "viejas buenas, las 12 ultimas malas": lenta([True] * 30 + [False] * 12),
            "viejas malas, las 12 ultimas buenas": lenta([False] * 30 + [True] * 12),
        },
        "con_ancla_b1": {
            "B1 sube a B2": lenta(_r(12, 12), "B1", "B1"),
            "B2 no pasa de B2": lenta(_r(12, 12), "B2", "B1"),
            "B1 baja a A2": lenta(_r(0, 12), "B1", "B1"),
            "A2 no baja de A2": lenta(_r(0, 12), "A2", "B1"),
            "con ancla no hay ventana rapida": reglas.decidir("B1", _r(6, 6), "B1", 0, E),
        },
        "rapida_sin_set": {
            "5 de 6": rapida(_r(5, 6)), "4 de 6": rapida(_r(4, 6)), "2 de 6": rapida(_r(2, 6)),
            "5 de 5 (sin llenar)": rapida(_r(5, 5)),
            "tercera decision todavia rapida": rapida(_r(6, 6), 2),
            "cuarta ya no (6 no llenan 12)": rapida(_r(6, 6), 3),
        },
        "ventana_vigente": [reglas.ventana_vigente(a, d, E)
                            for a, d in ((None, 0), (None, 2), (None, 3), ("B1", 0))],
    }
    assert observado == {
        "ventana_de_12": {
            "10 de 12": "B2", "9 de 12": "B1", "6 de 12": "B1", "5 de 12": "A2",
            "11 de 11 (sin llenar)": "B1", "viejas buenas, las 12 ultimas malas": "A2",
            "viejas malas, las 12 ultimas buenas": "B2"},
        "con_ancla_b1": {
            "B1 sube a B2": "B2", "B2 no pasa de B2": "B2", "B1 baja a A2": "A2",
            "A2 no baja de A2": "A2", "con ancla no hay ventana rapida": "B1"},
        "rapida_sin_set": {
            "5 de 6": "B1", "4 de 6": "A2", "2 de 6": "A1", "5 de 5 (sin llenar)": "A2",
            "tercera decision todavia rapida": "B1", "cuarta ya no (6 no llenan 12)": "A2"},
        "ventana_vigente": [(6, 5, 2), (6, 5, 2), (12, 10, 5), (12, 10, 5)],
    }, f"UP2: {observado}"


def _c(ident: str, topic: str, skill: str | None, preguntas: int) -> Candidato:
    return Candidato(ident, topic, skill, f"titulo {ident}", preguntas)


def test_up3_armar_la_tanda() -> None:
    """UP3 (C3): orden fijo, hasta 6 preguntas o más, máximo 4 retos."""
    banco = [_c("lec-u2", "a2-u02", None, 3), _c("voc-u1", "a2-u01", "vocabulary", 3),
             _c("lec-u1", "a2-u01", None, 3), _c("gra-u2", "a2-u02", "grammar", 2),
             _c("gra-u1", "a2-u01", "grammar", 2)]
    ids = lambda cs: [c.id for c in cs]  # noqa: E731
    observado = {
        "orden_fijo": ids(sorted(banco, key=reglas.orden_fijo)),
        "dos_y_tres_y_tres": ids(reglas.armar(banco, T)),
        "de_tres_en_tres": ids(reglas.armar([b for b in banco if b.preguntas == 3], T)),
        "de_una_pregunta_tope_4_retos": ids(reglas.armar(
            [_c(f"r{i}", "a2-u01", "grammar", 1) for i in range(9)], T)),
        "solo_queda_uno": ids(reglas.armar(banco[:1], T)),
        "nada": ids(reglas.armar([], T)),
        "primeros_tres_repasos": reglas.primeros([1, 2, 3, 4, 5], 3),
    }
    assert observado == {
        "orden_fijo": ["gra-u1", "voc-u1", "lec-u1", "gra-u2", "lec-u2"],
        "dos_y_tres_y_tres": ["gra-u1", "voc-u1", "lec-u1"],
        "de_tres_en_tres": ["voc-u1", "lec-u1"],
        "de_una_pregunta_tope_4_retos": ["r0", "r1", "r2", "r3"],
        "solo_queda_uno": ["lec-u2"], "nada": [], "primeros_tres_repasos": [1, 2, 3],
    }, f"UP3: {observado}"
