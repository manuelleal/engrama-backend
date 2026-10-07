"""HC1 (humo) y RC1 (réplica) del catálogo de nodos — `docs/ESPEC_catalogo_nodos.md` §3.

HC1: un mapa sintético de 40 nodos (5 tipos x 8 niveles); se carga; una segunda
versión fusiona 4 al azar (`random.Random(38)`) y agrega 3; se carga; se
resuelven los 4 fusionados. Escribe `tests/_salida/humo_catalogo_nodos.json`
(en `.gitignore`) ANTES de afirmar.

RC1 solo corre con `ENGRAMA_REPLICA_CATALOGO=1`: carga EL MAPA REAL
(`ENGRAMA_CATALOGO_NODOS` o, por defecto, `INGLES/curriculo/nodos.json`, que
está fuera de este repo y solo se lee). Si el archivo no está, se salta.
"""
from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Any

import pytest

from tests.curriculo import _ayuda as ay
from tests.integ_db import RAIZ_BACKEND

pytestmark = pytest.mark.integ

RUTA_HUMO_CATALOGO = RAIZ_BACKEND / "tests" / "_salida" / "humo_catalogo_nodos.json"
SEMILLA = 38
REPLICA = os.environ.get("ENGRAMA_REPLICA_CATALOGO") == "1"
MAPA_REAL = Path(os.environ.get("ENGRAMA_CATALOGO_NODOS")
                 or RAIZ_BACKEND.parent.parent / "curriculo" / "nodos.json")
NIVELES = ("a1", "a2", "a2p", "b1", "b1p", "b2", "b2p", "c1")

# Contenido exacto (ESPEC §3). Si difiere se reporta; no se ajusta para que pase.
HUMO_ESPERADO: dict[str, Any] = {
    "alembic_version": "040_foco_grupo", "semilla": 38,
    "primera": {"vigentes": 40, "reemplazados": 0, "nuevos": 40},
    "segunda": {"vigentes": 39, "reemplazados": 4, "nuevos": 3},
    "filas": 43, "api_nodos": 39, "fusionados_resuelven": True, "desconocido": 422,
}


def _corto(resumen: Any) -> Any:
    if not isinstance(resumen, dict):
        return resumen
    return {k: resumen[k] for k in ("vigentes", "reemplazados", "nuevos")}


def test_hc1_humo_catalogo_nodos(integ) -> None:
    rng = random.Random(SEMILLA)
    profe = integ.crear_perfil(integ.crear_tenant(), rol="teacher")
    ids = [f"{t}.{n}.tema-{i}" for i, t in enumerate(ay.TIPOS) for n in NIVELES]
    primera = ay.cargar(integ, ay.mapa("humo-1", ids))
    fusionados = rng.sample(ids, 4)
    quedan = [i for i in ids if i not in fusionados]
    reemplazos = {viejo: rng.choice(quedan) for viejo in fusionados}
    nuevos = [f"gr.b1.nuevo-{i}" for i in range(3)]
    segunda = ay.cargar(integ, ay.mapa("humo-2", quedan + nuevos, reemplazos))
    resueltos = {v: ay.resolver(integ, [v]) for v in fusionados}
    desconocido = ay.resolver(integ, ["no.esta.en-el-mapa"])
    datos = {
        "alembic_version": integ.valor("select version_num from alembic_version"),
        "semilla": SEMILLA, "primera": _corto(primera), "segunda": _corto(segunda),
        "filas": len(ay.tabla(integ)), "api_nodos": len(ay.leer(integ, profe)[2]),
        "fusionados_resuelven": resueltos == {v: [d] for v, d in reemplazos.items()},
        "desconocido": desconocido[0] if isinstance(desconocido, tuple) else 200,
    }
    RUTA_HUMO_CATALOGO.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO_CATALOGO.write_text(
        json.dumps(datos, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    assert datos == HUMO_ESPERADO, f"HC1: {datos}"


@pytest.mark.skipif(not REPLICA, reason="réplica del catálogo: ENGRAMA_REPLICA_CATALOGO=1")
def test_rc1_replica_con_el_mapa_real(integ) -> None:
    """RC1: el mapa real carga entero, repetirlo no cambia nada y sus reemplazos resuelven."""
    if not MAPA_REAL.is_file():
        pytest.skip(f"no está el mapa real en {MAPA_REAL}")
    real = json.loads(MAPA_REAL.read_text(encoding="utf-8"))
    vigentes = {n["id"] for n in real["nodos"]}
    reemplazos = real.get("reemplazos") or []
    primera = ay.cargar(integ, real)
    segunda = ay.cargar(integ, real)
    resueltos = [ay.resolver(integ, [r["id"]]) for r in reemplazos]
    observado = {
        "primera": _corto(primera), "segunda_nuevos_y_cambiados": (
            segunda.get("nuevos"), segunda.get("cambiados")) if isinstance(segunda, dict)
        else segunda,
        "todos_resuelven_a_un_vigente": all(
            isinstance(r, list) and len(r) == 1 and r[0] in vigentes for r in resueltos),
        "todos_los_vigentes_valen": ay.resolver(integ, sorted(vigentes)) == sorted(vigentes),
    }
    assert observado == {
        "primera": {"vigentes": len(vigentes), "reemplazados": len(reemplazos),
                    "nuevos": len(vigentes) + len(reemplazos)},
        "segunda_nuevos_y_cambiados": (0, 0),
        "todos_resuelven_a_un_vigente": True, "todos_los_vigentes_valen": True,
    }, f"RC1 ({real.get('version')}, {len(vigentes)} vigentes): {observado}"
