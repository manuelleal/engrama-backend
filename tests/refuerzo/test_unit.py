"""UR1: las reglas puras de la cola de refuerzo — `docs/ESPEC_refuerzo.md` §2, C1. No-integ."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from src.refuerzo import reglas
from src.refuerzo.reglas import Estado, Forma, Regla
from src.shared.config import Settings

AHORA = datetime(2026, 10, 6, 15, 0, tzinfo=UTC)
PROPUESTA = Regla(aciertos_para_repaso=1, dias_repaso=7)


def _q(n: int) -> UUID:
    return UUID(int=n)


def _paso(status: str, acerto: bool, regla: Regla = PROPUESTA, hits: int = 0) -> tuple[str, int, int | None, bool]:
    """(estado, aciertos, días hasta el repaso, ¿quedó con fecha de superado?)."""
    vence = AHORA if status == reglas.POR_REPASAR else None
    e = reglas.transicion(Estado(status, hits, vence, None), acerto, AHORA, regla)
    dias = (e.next_due_at - AHORA).days if e.next_due_at else None
    return e.status, e.hits, dias, e.mastered_at is not None


def _por_defecto(monkeypatch: pytest.MonkeyPatch) -> tuple[int, int, int]:
    """Los tres valores con las variables AUSENTES del entorno y sin leer ningún `.env`."""
    for nombre in ("REFUERZO_ACIERTOS_PARA_REPASO", "REFUERZO_DIAS_REPASO",
                   "REFUERZO_MAX_POR_VEZ"):
        monkeypatch.delenv(nombre, raising=False)
    limpio = Settings(_env_file=None, supabase_jwt_secret="x" * 32,  # type: ignore[call-arg]
                      database_url="postgresql://u:p@127.0.0.1:1/x")
    return (limpio.refuerzo_aciertos_para_repaso, limpio.refuerzo_dias_repaso,
            limpio.refuerzo_max_por_vez)


def _elegida(candidatas: list[Forma], vistas: set[str], etapa: str, *,
             familia: str | None = "F", usadas: set[str] | None = None) -> str | None:
    forma = reglas.elegir(candidatas, vistas, familia=familia, etapa=etapa,
                          usadas=usadas or set())
    return forma.clave if forma else None


def test_ur1_reglas_puras_del_refuerzo(monkeypatch) -> None:
    """UR1 (C1): transiciones, cuándo toca, la identidad y cuál forma se sirve."""
    banco = [Forma(_q(1), "it-1", "F", "original"), Forma(_q(2), "it-2", "F", "gemela"),
             Forma(_q(3), "it-3", "F", "repaso"), Forma(_q(4), "it-0", "G", "gemela"),
             Forma(_q(5), "q:5", None, None), Forma(_q(6), "it-2", "F", "gemela")]
    dos = Regla(aciertos_para_repaso=2, dias_repaso=3)
    observado = {
        "por_defecto": _por_defecto(monkeypatch),
        "transiciones": {
            "refuerzo_acierta": _paso(reglas.EN_REFUERZO, True),
            "refuerzo_falla": _paso(reglas.EN_REFUERZO, False),
            "repaso_acierta": _paso(reglas.POR_REPASAR, True),
            "repaso_falla": _paso(reglas.POR_REPASAR, False),
            "con_dos_el_primero": _paso(reglas.EN_REFUERZO, True, dos),
            "con_dos_el_segundo": _paso(reglas.EN_REFUERZO, True, dos, hits=1),
            "con_dos_falla_y_vuelve_a_cero": _paso(reglas.EN_REFUERZO, False, dos, hits=1),
        },
        "toca": {
            "en_refuerzo": reglas.toca(reglas.EN_REFUERZO, None, AHORA),
            "repaso_un_segundo_antes": reglas.toca(reglas.POR_REPASAR,
                                                 AHORA + timedelta(seconds=1), AHORA),
            "repaso_en_punto": reglas.toca(reglas.POR_REPASAR, AHORA, AHORA),
            "superado": reglas.toca(reglas.SUPERADO, None, AHORA),
        },
        "identidad": (reglas.clave_de_forma("b1-u01-f01-2", _q(9)),
                      reglas.clave_de_forma(None, _q(9)), reglas.clave_de_forma("", _q(9))),
        "elegir": {
            "refuerzo": _elegida(banco, {"it-1"}, reglas.ETAPA_REFUERZO),
            "repaso": _elegida(banco, {"it-1"}, reglas.ETAPA_REPASO),
            "sin_la_gemela": _elegida(banco, {"it-1", "it-2"}, reglas.ETAPA_REFUERZO),
            "sin_la_familia": _elegida(banco, {"it-1", "it-2", "it-3"}, reglas.ETAPA_REFUERZO),
            "sin_familia_de_origen": _elegida(banco, set(), reglas.ETAPA_REFUERZO, familia=None),
            "ya_dada_a_otra_entrada": _elegida(banco, {"it-1"}, reglas.ETAPA_REFUERZO,
                                               usadas={"it-2"}),
            "todas_vistas": _elegida(banco, {f.clave for f in banco}, reglas.ETAPA_REFUERZO),
            "sin_candidatas": _elegida([], set(), reglas.ETAPA_REFUERZO),
        },
    }
    assert observado == {
        "por_defecto": (1, 7, 5),
        "transiciones": {
            "refuerzo_acierta": ("por_repasar", 0, 7, False),
            "refuerzo_falla": ("en_refuerzo", 0, None, False),
            "repaso_acierta": ("superado", 0, None, True),
            "repaso_falla": ("en_refuerzo", 0, None, False),
            "con_dos_el_primero": ("en_refuerzo", 1, None, False),
            "con_dos_el_segundo": ("por_repasar", 0, 3, False),
            "con_dos_falla_y_vuelve_a_cero": ("en_refuerzo", 0, None, False),
        },
        "toca": {"en_refuerzo": True, "repaso_un_segundo_antes": False,
                 "repaso_en_punto": True, "superado": False},
        "identidad": ("b1-u01-f01-2", f"q:{_q(9)}", f"q:{_q(9)}"),
        "elegir": {"refuerzo": "it-2", "repaso": "it-3", "sin_la_gemela": "it-3",
                   "sin_la_familia": "it-0", "sin_familia_de_origen": "it-0",
                   "ya_dada_a_otra_entrada": "it-3", "todas_vistas": None,
                   "sin_candidatas": None},
    }, f"UR1: {observado}"
