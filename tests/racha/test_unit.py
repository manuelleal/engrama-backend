"""UW1 a UW3: las reglas PURAS de la racha semanal — `docs/ESPEC_racha_semanal.md` §2.

Sin base ni reloj. Lo observado va en un dict que se compara ENTERO y sale en
el mensaje. Tramposos: `tests/tramposos/test_tramposos_racha_unit.py`.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

import pytest

from src.racha import reglas
from src.racha.reglas import Dia, Racha, Umbrales
from src.shared.config import Settings

LUNES = date(2026, 10, 12)  # un lunes
U = Umbrales(dias_por_semana=3, dias_protector=5, respuestas_dia=6, correctas_dia=4,
             protector_inicial=1, protector_tope=2, bono_semana=5)


def _dia(respuestas: int = 0, correctas: int = 0, asistio: bool = False) -> Dia:
    return Dia(asistio, respuestas, correctas, 0, {}, {})


def _racha(semanas: int = 0, mejor: int = 0, total: int = 0, protectores: int = 1,
           cerrada: date = LUNES - timedelta(days=7)) -> Racha:
    return Racha(semanas, mejor, total, protectores, cerrada)


def _corta(r: Racha) -> tuple[int, int, int, int]:
    return (r.racha_semanas, r.mejor_racha, r.semanas_cumplidas, r.protectores)


def _tras_dias(desde: Racha, dias: range) -> list[tuple[tuple[int, int, int, int], bool]]:
    """La racha tras cada día activo de una semana (1.º, 2.º, …)."""
    visto, racha = [], desde
    for n in dias:
        racha, cumplida = reglas.al_activarse_un_dia(racha, n, U)
        visto.append((_corta(racha), cumplida))
    return visto


def test_uw1_dia_activo_semana_y_protector(monkeypatch: pytest.MonkeyPatch) -> None:
    """UW1 (C1): el día activo, el lunes, el 3.er y el 5.º día, y los valores por defecto."""
    for nombre in ("RACHA_DIAS_POR_SEMANA", "RACHA_DIAS_PROTECTOR", "RACHA_RESPUESTAS_DIA",
                   "RACHA_CORRECTAS_DIA", "RACHA_PROTECTOR_INICIAL", "RACHA_PROTECTOR_TOPE",
                   "RACHA_BONO_SEMANA"):
        monkeypatch.delenv(nombre, raising=False)
    config = Settings(_env_file=None)  # type: ignore[call-arg]
    observado: dict[str, Any] = {
        "por_defecto": (config.racha_dias_por_semana, config.racha_dias_protector,
                        config.racha_respuestas_dia, config.racha_correctas_dia,
                        config.racha_protector_inicial, config.racha_protector_tope,
                        config.racha_bono_semana),
        "dia_activo": {
            "nada (abrir la app)": reglas.dia_activo(_dia(), U),
            "una respuesta correcta": reglas.dia_activo(_dia(1, 1), U),
            "5 de 5": reglas.dia_activo(_dia(5, 5), U),
            "6 con 3 correctas": reglas.dia_activo(_dia(6, 3), U),
            "6 con 4 correctas": reglas.dia_activo(_dia(6, 4), U),
            "20 con 3 correctas (clic al azar)": reglas.dia_activo(_dia(20, 3), U),
            "solo asistencia": reglas.dia_activo(_dia(asistio=True), U),
        },
        "lunes_de": [reglas.lunes_de(LUNES + timedelta(days=i)).isoformat() for i in (0, 3, 6, 7)],
        "semana_dia_a_dia": _tras_dias(_racha(protectores=0), range(1, 8)),
        "protector_con_tope": [_corta(reglas.al_activarse_un_dia(_racha(protectores=p), 5, U)[0])[3]
                               for p in (0, 1, 2)],
        "inicial": _corta(reglas.inicial(LUNES, U)),
        "llave_del_bono": reglas.llave_bono(UUID(int=1), UUID(int=2), LUNES)[-8:],
    }
    assert observado == {
        "por_defecto": (3, 5, 6, 4, 1, 2, 5),
        "dia_activo": {
            "nada (abrir la app)": False, "una respuesta correcta": False, "5 de 5": False,
            "6 con 3 correctas": False, "6 con 4 correctas": True,
            "20 con 3 correctas (clic al azar)": False, "solo asistencia": True,
        },
        "lunes_de": ["2026-10-12", "2026-10-12", "2026-10-12", "2026-10-19"],
        "semana_dia_a_dia": [((0, 0, 0, 0), False), ((0, 0, 0, 0), False), ((1, 1, 1, 0), True),
                             ((1, 1, 1, 0), False), ((1, 1, 1, 1), False),
                             ((1, 1, 1, 1), False), ((1, 1, 1, 1), False)],
        "protector_con_tope": [1, 2, 2],
        "inicial": (0, 0, 0, 1),
        "llave_del_bono": "2026-W42",
    }, f"UW1: {observado}"


def test_uw2_el_cierre_perezoso() -> None:
    """UW2 (C2): no cumplir gasta el protector o rompe; el récord y el total no bajan."""
    hace = lambda n: LUNES - timedelta(days=7 * n)  # noqa: E731
    con_racha = _racha(4, 6, 14, protectores=1, cerrada=hace(2))  # falta cerrar la semana pasada
    sin_protector = _racha(4, 6, 14, protectores=0, cerrada=hace(2))
    ausente = _racha(4, 6, 14, protectores=2, cerrada=hace(5))  # 4 semanas sin cerrar
    una_vez = reglas.cerrar(sin_protector, LUNES, {}, None, U)
    observado: dict[str, Any] = {
        "cumplida_no_toca_nada": _corta(reglas.cerrar(con_racha, LUNES, {hace(1): 3}, None, U)),
        "no_cumplida_gasta_el_protector": _corta(
            reglas.cerrar(con_racha, LUNES, {hace(1): 2}, None, U)),
        "sin_protector_vuelve_a_cero": _corta(una_vez),
        "la_semana_de_la_membresia_no_cuenta": _corta(
            reglas.cerrar(sin_protector, LUNES, {}, hace(1), U)),
        "cuatro_semanas_ausente_con_dos_protectores": _corta(
            reglas.cerrar(ausente, LUNES, {}, None, U)),
        "dos_ausencias_con_dos_protectores": _corta(
            reglas.cerrar(_racha(4, 6, 14, 2, hace(3)), LUNES, {}, None, U)),
        "la_semana_en_curso_no_se_cierra": _corta(
            reglas.cerrar(_racha(4, 6, 14, 0, hace(1)), LUNES, {}, None, U)),
        "queda_cerrada_hasta_la_pasada": una_vez.ultima_semana_cerrada.isoformat(),
        "cerrar_dos_veces_da_lo_mismo": reglas.cerrar(una_vez, LUNES, {}, None, U) == una_vez,
    }
    assert observado == {
        "cumplida_no_toca_nada": (4, 6, 14, 1),
        "no_cumplida_gasta_el_protector": (4, 6, 14, 0),
        "sin_protector_vuelve_a_cero": (0, 6, 14, 0),
        "la_semana_de_la_membresia_no_cuenta": (4, 6, 14, 0),
        "cuatro_semanas_ausente_con_dos_protectores": (0, 6, 14, 0),
        "dos_ausencias_con_dos_protectores": (4, 6, 14, 0),
        "la_semana_en_curso_no_se_cierra": (4, 6, 14, 0),
        "queda_cerrada_hasta_la_pasada": "2026-10-05",
        "cerrar_dos_veces_da_lo_mismo": True,
    }, f"UW2: {observado}"


def test_uw3_cada_pregunta_cuenta_una_vez_al_dia() -> None:
    """UW3 (C3): una vez por día con su mejor resultado; el primer intento, aparte."""
    def tras(*respuestas: tuple[str, bool, str]) -> tuple[Any, ...]:
        dia = reglas.DIA_VACIO
        for clave, acerto, origen in respuestas:
            dia = reglas.anotar_respuesta(dia, clave, acerto, origen)
        return (dia.respuestas, dia.correctas, dia.primeras_correctas,
                dict(dia.preguntas), dict(dia.por_origen))

    observado = {
        "la_misma_tres_veces": tras(("a", True, "reto"), ("a", True, "reto"), ("a", True, "eva")),
        "falla_y_luego_acierta": tras(("a", False, "reto"), ("a", True, "repaso")),
        "acierta_y_luego_falla": tras(("a", True, "reto"), ("a", False, "reto")),
        "tres_distintas": tras(("a", True, "reto"), ("b", False, "eva"), ("c", True, "repaso")),
    }
    assert observado == {
        "la_misma_tres_veces": (1, 1, 1, {"a": 1}, {"reto": 1}),
        "falla_y_luego_acierta": (1, 1, 0, {"a": 1}, {"reto": 1}),
        "acierta_y_luego_falla": (1, 1, 1, {"a": 1}, {"reto": 1}),
        "tres_distintas": (3, 2, 2, {"a": 1, "b": 0, "c": 1}, {"reto": 1, "eva": 1, "repaso": 1}),
    }, f"UW3: {observado}"
