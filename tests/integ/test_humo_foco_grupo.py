"""HF1 (humo) y RF1 (réplica) del foco del grupo — `docs/ESPEC_foco_grupo.md` §3.

HF1: un grupo de 12 estudiantes y 8 retos de 3 preguntas, cada pregunta con un
nodo al azar del catálogo sintético (`random.Random(40)`); el profe fija el
foco de la semana con 2 nodos; cada estudiante responde 5 retos al azar.
Escribe `tests/_salida/humo_foco_grupo.json` (en `.gitignore`) ANTES de afirmar.

RF1 solo corre con `ENGRAMA_REPLICA_FOCO=1`, con entradas que no se usaron al
desarrollar: dos grupos de la misma institución con focos distintos la misma
semana; un periodo de un solo día; un foco de 12 nodos; un reto global con
nodos del foco; y "hoy" en el cambio de día de Bogotá.
"""
from __future__ import annotations

import json
import os
import random
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from src.shared.models import TeacherGroup
from tests.curriculo import _ayuda as cat
from tests.foco import _ayuda as ay
from tests.grader._ayuda import colegio
from tests.integ_db import RAIZ_BACKEND

pytestmark = pytest.mark.integ

RUTA_HUMO_FOCO = RAIZ_BACKEND / "tests" / "_salida" / "humo_foco_grupo.json"
SEMILLA = 40
REPLICA = os.environ.get("ENGRAMA_REPLICA_FOCO") == "1"

# Contenido exacto (ESPEC §3). `retos_en_foco` y los tres números del logro
# salieron de la primera medición con el código bueno y no se mueven.
HUMO_ESPERADO: dict[str, Any] = {
    "alembic_version": "041_refuerzo", "semilla": 40, "retos": 8, "preguntas_con_nodo": 24,
    "foco": 200, "feed_sin_foco_igual_al_de_antes": True, "retos_en_foco": 5,
    "primeros_del_feed_en_foco": True, "mismos_retos": True,
    "logro": {"nodos": 2, "items": 35, "correct": 25}, "estudiante_ve_nodos": False,
}


def test_hf1_humo_foco_grupo(integ) -> None:
    rng = random.Random(SEMILLA)
    cat.cargar(integ, cat.mapa_v1())
    c = colegio(integ, "10B", n=12)
    retos = [ay.crear_reto(integ, c.profe, f"reto {i}",
                           [[rng.choice(cat.VIGENTES_V1)] for _ in range(3)],
                           grupo=c.grupo, minuto=i) for i in range(8)]
    alumno = c.estudiantes[0]
    antes = ay.feed(integ, alumno)
    hoy = datetime.now(UTC).date()
    en_foco = rng.sample(cat.VIGENTES_V1, 2)
    foco = ay.fijar_foco(integ, c.profe, c.grupo, str(hoy - timedelta(days=1)), en_foco)[0]
    for estudiante in c.estudiantes:
        for _estado, reto, preguntas in rng.sample(retos, 5):
            integ.crear_intento(
                c.tenant, UUID(reto), estudiante,
                answers=ay.respuestas({q: rng.random() < 0.7 for q in preguntas}),
                completed_at=datetime.now(UTC) - timedelta(hours=3))
    # Los intentos sembrados gastan cupo de intentos pero no sacan retos del
    # feed (3 por reto): el feed del alumno sigue trayendo los mismos 8.
    despues = ay.feed(integ, alumno)
    api = ay.foco_del_estudiante(integ, alumno)[1]
    logro = ay.logro(integ, c.profe, c.grupo)[1]
    crudo = ay.client.get("/challenges/", headers=integ.headers(alumno)).text
    datos = {
        "alembic_version": integ.valor("select version_num from alembic_version"),
        "semilla": SEMILLA, "retos": sum(1 for r in retos if r[0] == 201),
        "preguntas_con_nodo": int(integ.valor(
            "select count(*) from challenge_questions where cardinality(nodes) > 0")),
        "foco": foco,
        "feed_sin_foco_igual_al_de_antes": antes == [r[1] for r in reversed(retos)],
        "retos_en_foco": len(api[2]),
        "primeros_del_feed_en_foco": despues[:len(api[2])] == api[2],
        "mismos_retos": sorted(despues) == sorted(antes),
        "logro": {"nodos": len(logro["nodos"]),
                  "items": sum(n["items"] for n in logro["nodos"]),
                  "correct": sum(n["correct"] for n in logro["nodos"])},
        "estudiante_ve_nodos": any(nodo in crudo for nodo in cat.VIGENTES_V1),
    }
    RUTA_HUMO_FOCO.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO_FOCO.write_text(
        json.dumps(datos, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    assert datos == HUMO_ESPERADO, f"HF1: {datos}"


@pytest.mark.skipif(not REPLICA, reason="réplica del foco: ENGRAMA_REPLICA_FOCO=1")
def test_rf1_replica_dos_grupos_un_dia_y_doce_nodos(integ, monkeypatch) -> None:
    """RF1: dos grupos con focos distintos no se cruzan; un día; 12 nodos; el cambio de día."""
    doce = [f"gr.b1.tema-{i}" for i in range(12)]
    cat.cargar(integ, cat.mapa("replica", list(cat.VIGENTES_V1) + doce))
    c = colegio(integ, "A", n=2)
    grupo_b = integ.crear_grupo(c.tenant, "B")
    integ._insertar(TeacherGroup(tenant_id=c.tenant, teacher_id=c.profe, group_id=grupo_b))
    de_b = integ.crear_perfil(c.tenant, group_code="B")
    de_a = c.estudiantes[0]
    ra = ay.crear_reto(integ, c.profe, "ra", [[doce[0]]], grupo=c.grupo, minuto=1)[1]
    rb = ay.crear_reto(integ, c.profe, "rb", [[doce[11]]], grupo=grupo_b, minuto=2)[1]
    rg = ay.crear_reto(integ, c.profe, "rg", [[doce[11]], [doce[0]]], minuto=3)[1]
    rz = ay.crear_reto(integ, c.profe, "rz", [[]], minuto=4)[1]
    # 23:30 del 6 en Bogotá = 04:30 UTC del 7.
    ay.fijar_hoy(monkeypatch, "2026-10-07", hora_utc=4)
    un_dia = ay.fijar_foco(integ, c.profe, c.grupo, "2026-10-06", [doce[0]], "2026-10-06")
    los_doce = ay.fijar_foco(integ, c.profe, grupo_b, "2026-10-06", doce, "2026-10-12")
    de_noche = (ay.feed(integ, de_a), ay.feed(integ, de_b))
    ay.fijar_hoy(monkeypatch, "2026-10-07", hora_utc=6)  # 01:00 del 7 en Bogotá
    de_madrugada = (ay.feed(integ, de_a), ay.feed(integ, de_b))
    logro_a = ay.logro(integ, c.profe, c.grupo)[1]
    observado = {
        "un_dia": un_dia[1][:3] if un_dia[0] == 200 else un_dia,
        "los_doce": (los_doce[0], len(los_doce[1][3]) if los_doce[0] == 200 else None),
        "de_noche": de_noche, "de_madrugada": de_madrugada,
        "logro_de_a_sin_foco_vigente": (logro_a["foco"], logro_a["nodos"]),
    }
    assert observado == {
        "un_dia": ("2026-10-06", "2026-10-06", True), "los_doce": (200, 12),
        # A: su foco es `doce[0]`: ra y rg delante. B: los doce: rg y rb delante.
        "de_noche": ([rg, ra, rz], [rg, rb, rz]),
        # Pasada la medianoche de Bogotá el foco de un día venció para A; el de B sigue.
        "de_madrugada": ([rz, rg, ra], [rg, rb, rz]),
        "logro_de_a_sin_foco_vigente": (None, []),
    }, f"RF1: {observado}"
