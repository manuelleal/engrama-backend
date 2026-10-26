"""HRD1 (humo) y RRD1 (réplica) del "reto del día sin profe".

`docs/ESPEC_humo_reto_del_dia.md` §2 y §3. Cuatro estudiantes sintéticos (dos
clases por semana; estudia solo; clic al azar; copia la clave) viven 4 semanas
con un reloj simulado, por las rutas que usará la web: la tanda, la respuesta
pregunta por pregunta, el repaso y el check-in. Escribe
`tests/_salida/humo_reto_del_dia.json` (en `.gitignore`) ANTES de afirmar, con
los datos de vigilancia del dictamen pedagógico 04 §2.

RRD1 solo corre con `ENGRAMA_REPLICA_RETO_DEL_DIA=1`, con entradas que no se
usaron al desarrollar: otra semilla, el segundo intento pagando 5, un banco sin
gemelas y sin retos del nivel de arranque, y un estudiante con nivel de SET.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from src.shared.config import settings
from tests.curriculo import _ayuda as cat
from tests.grader import _ayuda as gr
from tests.integ import _reto_del_dia as sim
from tests.integ_db import RAIZ_BACKEND
from tests.practica import _ayuda as ay

pytestmark = pytest.mark.integ

SALIDA = RAIZ_BACKEND / "tests" / "_salida"
RUTA_HUMO = SALIDA / "humo_reto_del_dia.json"
RUTA_REPLICA = SALIDA / "replica_reto_del_dia.json"
REPLICA = os.environ.get("ENGRAMA_REPLICA_RETO_DEL_DIA") == "1"
SEMANAS = 4

# Los seis CRITERIOS (ESPEC §2.2, H1 a H6): fijados antes de medir.
CEROS: dict[str, int] = {
    "errores_5xx": 0, "claves_antes_de_responder": 0, "retos_de_refuerzo_fuera_de_lugar": 0,
    "pagas_dobles": 0, "nivel_escrito": 0, "rachas_rotas_sin_contenido": 0,
}

# H8: el archivo entero. Los criterios son los de arriba; los demás números
# salieron de la PRIMERA medición con el código bueno (la semilla manda) y no se mueven.
HUMO_ESPERADO: dict[str, Any] = {'alembic_version': '050_invitaciones_docente',
 'criterios': {'claves_antes_de_responder': 0,
               'errores_5xx': 0,
               'nivel_escrito': 0,
               'pagas_dobles': 0,
               'rachas_rotas_sin_contenido': 0,
               'retos_de_refuerzo_fuera_de_lugar': 0},
 'estudiantes': {'azar': {'acierto_primer_intento_pct': 24.4,
                          'de_donde': {'streak_week': 5},
                          'dias_activos': 8,
                          'dias_activos_solo_por_asistencia': 0,
                          'dias_en_el_tope': [14, 15],
                          'dias_sin_contenido': 3,
                          'monedas': 5,
                          'nivel_de_practica': 'B1',
                          'racha': [1, 1, 1, 0],
                          'reintentos_con_gemela': 26,
                          'respuestas_por_answers': 156,
                          'semanas_cumplidas': [2],
                          'tandas_por_modo': {'nuevo': 26, 'repetir': 3},
                          'vigilancia': {'bono_sobre_monedas_pct': 100.0,
                                         'dias_activos_dudosos_pct': 100.0,
                                         'dias_activos_por_respuestas': 8,
                                         'dias_activos_solo_repetidos_pct': 0.0,
                                         'pagas_en_intento_2_pct': 0.0,
                                         'pagas_por_intento': {},
                                         'repaso_respondido_pct': 100.0,
                                         'repasos': 78,
                                         'repasos_con_preguntas_del_feed': 0,
                                         'semanas_cumplidas_sin_respuestas_pct': 0.0}},
                 'clases': {'acierto_primer_intento_pct': 64.5,
                            'de_donde': {'attendance': 80,
                                         'challenge': 20,
                                         'streak_week': 15},
                            'dias_activos': 11,
                            'dias_activos_solo_por_asistencia': 8,
                            'dias_en_el_tope': [0, 4],
                            'dias_sin_contenido': 0,
                            'monedas': 115,
                            'nivel_de_practica': 'B1',
                            'racha': [3, 3, 3, 0],
                            'reintentos_con_gemela': 3,
                            'respuestas_por_answers': 24,
                            'semanas_cumplidas': [1, 2, 3],
                            'tandas_por_modo': {'nuevo': 4},
                            'vigilancia': {'bono_sobre_monedas_pct': 13.0,
                                           'dias_activos_dudosos_pct': 0.0,
                                           'dias_activos_por_respuestas': 3,
                                           'dias_activos_solo_repetidos_pct': 0.0,
                                           'pagas_en_intento_2_pct': 50.0,
                                           'pagas_por_intento': {'1': 1, '2': 1},
                                           'repaso_respondido_pct': 100.0,
                                           'repasos': 7,
                                           'repasos_con_preguntas_del_feed': 0,
                                           'semanas_cumplidas_sin_respuestas_pct': 0.0}},
                 'copia': {'acierto_primer_intento_pct': 29.3,
                           'de_donde': {'challenge': 10, 'streak_week': 5},
                           'dias_activos': 7,
                           'dias_activos_solo_por_asistencia': 0,
                           'dias_en_el_tope': [0, 12],
                           'dias_sin_contenido': 0,
                           'monedas': 15,
                           'nivel_de_practica': 'B1',
                           'racha': [0, 1, 1, 0],
                           'reintentos_con_gemela': 23,
                           'respuestas_por_answers': 141,
                           'semanas_cumplidas': [0],
                           'tandas_por_modo': {'nuevo': 12},
                           'vigilancia': {'bono_sobre_monedas_pct': 33.3,
                                          'dias_activos_dudosos_pct': 100.0,
                                          'dias_activos_por_respuestas': 7,
                                          'dias_activos_solo_repetidos_pct': 0.0,
                                          'pagas_en_intento_2_pct': 0.0,
                                          'pagas_por_intento': {'1': 1},
                                          'repaso_respondido_pct': 100.0,
                                          'repasos': 33,
                                          'repasos_con_preguntas_del_feed': 0,
                                          'semanas_cumplidas_sin_respuestas_pct': 0.0}},
                 'solo': {'acierto_primer_intento_pct': 73.1,
                          'de_donde': {'challenge': 130, 'streak_week': 20},
                          'dias_activos': 12,
                          'dias_activos_solo_por_asistencia': 0,
                          'dias_en_el_tope': [12, 12],
                          'dias_sin_contenido': 0,
                          'monedas': 150,
                          'nivel_de_practica': 'B2',
                          'racha': [4, 4, 4, 1],
                          'reintentos_con_gemela': 19,
                          'respuestas_por_answers': 135,
                          'semanas_cumplidas': [0, 1, 2, 3],
                          'tandas_por_modo': {'nuevo': 23, 'repetir': 1},
                          'vigilancia': {'bono_sobre_monedas_pct': 13.3,
                                         'dias_activos_dudosos_pct': 0.0,
                                         'dias_activos_por_respuestas': 12,
                                         'dias_activos_solo_repetidos_pct': 0.0,
                                         'pagas_en_intento_2_pct': 30.8,
                                         'pagas_por_intento': {'1': 9, '2': 4},
                                         'repaso_respondido_pct': 100.0,
                                         'repasos': 36,
                                         'repasos_con_preguntas_del_feed': 0,
                                         'semanas_cumplidas_sin_respuestas_pct': 0.0}}},
 'explicaciones_por_idioma': {'en': 123, 'es': 333},
 'huecos': {'A1': 8, 'A2': 5, 'B1': 3, 'B2': 22},
 'retos_sembrados': 78,
 'semanas': 4,
 'semilla': 45,
 'tandas_vacias': {'azar': 1}}


def _escribir(ruta: Path, datos: dict[str, Any]) -> dict[str, Any]:
    """Escribe y devuelve lo escrito tal como queda en disco (JSON: tuplas → listas)."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(datos, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ruta.write_text(texto, encoding="utf-8")
    return dict(json.loads(texto))


def _vivir(integ: Any, monkeypatch: pytest.MonkeyPatch, *, semilla: int, semanas: int,
           unidades: dict[str, int], gemelas: bool,
           con_set: dict[str, str] | None = None) -> dict[str, Any]:
    """Siembra el banco, corre la simulación y devuelve lo medido."""
    reloj = sim.Reloj()
    sim.instalar(monkeypatch, reloj)
    cat.cargar(integ, cat.mapa_v1())
    politicas: tuple[sim.Politica, ...] = sim.CUATRO
    if con_set:
        politicas = (*politicas, *(sim.Politica(
            nombre, asiste=(), practica=(1, 3, 5), tandas=1, modo="sabe", acierta=0.75,
            segundos=(8, 20)) for nombre in con_set))
    c = gr.colegio(integ, "9A", n=len(politicas))
    quienes = dict(zip((p.nombre for p in politicas), c.estudiantes, strict=True))
    for nombre, nivel in (con_set or {}).items():
        ay.confirmar_con_set(integ, c.tenant, quienes[nombre], nivel)
    antes = int(integ.valor("select count(*) from confirmed_levels"))
    banco = sim.sembrar_banco(integ, c, unidades, gemelas=gemelas)
    corrida = sim.Simulacion(integ, c, banco, reloj, semilla, quienes)
    corrida.correr(politicas, semanas)
    datos = sim.medir(integ, corrida, semanas)
    datos["criterios"]["nivel_escrito"] -= antes  # lo que sembró el test no cuenta
    if corrida.primer_error:
        datos["primer_error"] = corrida.primer_error
    return datos


def test_hrd1_humo_del_reto_del_dia(integ, monkeypatch) -> None:
    """HRD1: cuatro estudiantes, cuatro semanas; los seis ceros y el archivo idéntico."""
    datos = _escribir(RUTA_HUMO, _vivir(
        integ, monkeypatch, semilla=45, semanas=SEMANAS,
        unidades={"A1": 3, "A2": 6, "B1": 4}, gemelas=True))
    assert datos["criterios"] == CEROS, f"HRD1, criterios: {datos['criterios']} ({datos})"
    assert datos == HUMO_ESPERADO, f"HRD1: {json.dumps(datos, sort_keys=True)}"


@pytest.mark.skipif(not REPLICA, reason="réplica: solo con ENGRAMA_REPLICA_RETO_DEL_DIA=1")
def test_rrd1_replica_con_entradas_nuevas(integ, monkeypatch) -> None:
    """RRD1: otra semilla, el segundo intento a 5, sin gemelas, sin A2 y uno con SET."""
    monkeypatch.setattr(settings, "segundo_intento_paga", 5)
    datos = _escribir(RUTA_REPLICA, _vivir(
        integ, monkeypatch, semilla=46, semanas=3, unidades={"A1": 2, "B1": 5},
        gemelas=False, con_set={"con_set": "B1"}))
    assert datos["criterios"] == CEROS, f"RRD1, criterios: {datos['criterios']} ({datos})"
    for nombre, e in datos["estudiantes"].items():
        assert e["reintentos_con_gemela"] == 0, f"RRD1: {nombre} recibió gemelas sin haberlas"
        assert e["monedas"] == sum(e["de_donde"].values()), f"RRD1: {nombre}: {e}"
