"""US1 y US2: las reglas PURAS de la segunda vuelta y del cierre sin contenido.

`docs/ESPEC_solo_refuerzo.md` §2 (C1 y C2). Sin base ni reloj. Tramposos:
`tests/tramposos/test_tramposos_solo_refuerzo.py`.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from src.engrama_core.service import economia
from src.practica import reglas
from src.practica.reglas import FormaDeReto
from src.racha import reglas as racha_reglas
from src.racha.reglas import Racha, Umbrales
from src.shared.config import Settings

AHORA = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
LUNES = date(2026, 10, 12)
U = Umbrales(dias_por_semana=3, dias_protector=5, respuestas_dia=6, correctas_dia=4,
             protector_inicial=1, protector_tope=2, bono_semana=5)


def _hace(dias: int) -> datetime:
    return AHORA - timedelta(days=dias)


def _g(clave: str, familia: str | None = "f1", rol: str | None = "gemela") -> FormaDeReto:
    return FormaDeReto(clave, familia, rol)


def _entra(formas: list[FormaDeReto], *, vistas: tuple[str, ...] = (),
           jugado: dict[str, datetime] | None = None, dias: int = 21) -> bool:
    originales = {"f1": _hace(21), "f2": _hace(30)} if jugado is None else jugado
    return reglas.elegible_segunda_vuelta(formas, set(vistas), originales, AHORA, dias)


def test_us1_la_segunda_vuelta_los_prestados_y_la_paga(monkeypatch: pytest.MonkeyPatch) -> None:
    """US1 (C1): gemelas no vistas con su original a 21 días; de dónde se presta; paga 5."""
    for nombre in ("SEGUNDA_VUELTA_DIAS", "SEGUNDA_VUELTA_PAGA"):
        monkeypatch.delenv(nombre, raising=False)
    c = Settings(_env_file=None)  # type: ignore[call-arg]
    observado: dict[str, Any] = {
        "por_defecto": (c.segunda_vuelta_dias, c.segunda_vuelta_paga),
        "entra": {
            "a 21 dias": _entra([_g("a")]),
            "a 20 dias": _entra([_g("a")], jugado={"f1": _hace(20)}),
            "sin haber jugado el original": _entra([_g("a")], jugado={}),
            "ya vista": _entra([_g("a")], vistas=("a",)),
            "una ya vista de dos": _entra([_g("a"), _g("b")], vistas=("b",)),
            "una de rol repaso": _entra([_g("a"), _g("b", rol="repaso")]),
            "una original": _entra([_g("a", rol="original")]),
            "sin rol": _entra([_g("a", rol=None)]),
            "sin familia": _entra([_g("a", familia=None)]),
            "dos familias a tiempo": _entra([_g("a"), _g("b", "f2")]),
            "dos familias, una reciente": _entra([_g("a"), _g("b", "f2")],
                                                jugado={"f1": _hace(21), "f2": _hace(3)}),
            "reto sin preguntas": _entra([]),
            "con 7 dias configurados": _entra([_g("a")], jugado={"f1": _hace(7)}, dias=7),
        },
        "prestar_de": {n: reglas.otros_niveles(n) for n in reglas.NIVELES},
        "paga_de_refuerzo": [economia.paga_de_refuerzo(valor, paga)
                             for valor, paga in ((10, 5), (3, 5), (20, 5), (10, 0), (10, 10))],
    }
    assert observado == {
        "por_defecto": (21, 5),
        "entra": {
            "a 21 dias": True, "a 20 dias": False, "sin haber jugado el original": False,
            "ya vista": False, "una ya vista de dos": False, "una de rol repaso": False,
            "una original": False, "sin rol": False, "sin familia": False,
            "dos familias a tiempo": True, "dos familias, una reciente": False,
            "reto sin preguntas": False, "con 7 dias configurados": True,
        },
        "prestar_de": {"A1": ["A2", "B1", "B2", "C1"], "A2": ["A1", "B1", "B2", "C1"],
                       "B1": ["A2", "A1", "B2", "C1"], "B2": ["B1", "A2", "A1", "C1"],
                       "C1": ["B2", "B1", "A2", "A1"]},
        "paga_de_refuerzo": [5, 3, 5, 0, 10],
    }, f"US1: {observado}"


def _racha(protectores: int, cerrada_hace: int) -> Racha:
    return Racha(4, 6, 14, protectores, LUNES - timedelta(days=7 * cerrada_hace))


def _corta(r: Racha) -> tuple[int, int, int, int]:
    return (r.racha_semanas, r.mejor_racha, r.semanas_cumplidas, r.protectores)


def test_us2_la_semana_sin_contenido_no_rompe_la_racha() -> None:
    """US2 (C2): al cerrar, una semana marcada sin contenido no gasta protector ni baja."""
    hace = lambda n: LUNES - timedelta(days=7 * n)  # noqa: E731
    cerrar = lambda racha, exentas: _corta(  # noqa: E731
        racha_reglas.cerrar(racha, LUNES, {}, exentas, U))
    observado = {
        "sin_contenido_no_gasta_el_protector": cerrar(_racha(1, 2), {hace(1)}),
        "sin_contenido_y_sin_protector_no_baja": cerrar(_racha(0, 2), [hace(1)]),
        "sin_marca_si_gasta": cerrar(_racha(1, 2), set()),
        "la_semana_siguiente_sin_marca_si_cuenta": cerrar(_racha(1, 3), {hace(2)}),
        "dos_sin_marca_y_una_marcada_en_medio": cerrar(_racha(1, 4), {hace(2)}),
        "la_de_la_membresia_y_una_sin_contenido": cerrar(_racha(0, 3), {hace(2), hace(1)}),
        "una_fecha_sola_sigue_valiendo": cerrar(_racha(0, 2), hace(1)),
        "exentas_de": [sorted(d.isoformat() for d in racha_reglas.exentas_de(x))
                       for x in (None, hace(1), [hace(1), hace(2)])],
    }
    assert observado == {
        "sin_contenido_no_gasta_el_protector": (4, 6, 14, 1),
        "sin_contenido_y_sin_protector_no_baja": (4, 6, 14, 0),
        "sin_marca_si_gasta": (4, 6, 14, 0),
        "la_semana_siguiente_sin_marca_si_cuenta": (4, 6, 14, 0),
        "dos_sin_marca_y_una_marcada_en_medio": (0, 6, 14, 0),
        "la_de_la_membresia_y_una_sin_contenido": (4, 6, 14, 0),
        "una_fecha_sola_sigue_valiendo": (4, 6, 14, 0),
        "exentas_de": [[], ["2026-10-05"], ["2026-09-28", "2026-10-05"]],
    }, f"US2: {observado}"
