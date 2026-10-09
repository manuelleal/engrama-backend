"""SE0 — regresión = identidad de los 422 de las dos rutas ya cerradas.

`docs/ESPEC_422_sin_eco.md`, C1. Antes de pasar la limpieza del 422 a un
manejador global, se congela lo que la web ya consume: el cuerpo EXACTO (byte a
byte) de cada 422 de `POST /auth/registro` y de `POST /auth/contrasena`, medido
sobre `59fe08a` y guardado en `snapshot_422_dos_rutas.json`. El cambio no puede
mover ni una coma de esas respuestas.

Los casos del registro son los mismos de VE2 (se importan, no se copian); los
del cambio de contraseña son los de VE3.

Para volver a congelar (solo si una espec lo pide, nunca para "arreglar" un rojo):
`observar()` devuelve lo que hay que escribir en el JSON.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.auth.cuentas import get_cambio_de_clave
from src.auth.schemas import AuthContext
from src.registro.cuentas import get_cuentas_de_registro
from src.shared.deps import get_current_user
from tests.registro import test_validacion_sin_eco as ve

RUTA_SNAPSHOT = Path(__file__).resolve().parent / "snapshot_422_dos_rutas.json"
_JSON = {"content-type": "application/json"}
_BEARER = {"Authorization": "Bearer sintetico"}

CASOS_DE_CONTRASENA: list[tuple[str, Any]] = [
    ("nueva corta", {"nueva": "corta-ma1"}),
    ("nueva larga", {"nueva": "clave-larga-MARCA" + "x" * 60}),
    ("falta nueva y campo de mas", {"viejo": "MARCA-VIEJA"}),
    ("nueva numerica", {"nueva": 1357924680123}),
    ("nueva en lista", {"nueva": ["MARCA-NUEVA-LISTA"]}),
    ("cuerpo lista", ["MARCA-ARR-CLAVE"]),
    ("cuerpo vacio", {}),
]


def observar() -> dict[str, dict[str, Any]]:
    """El código y el cuerpo exacto de cada 422 de las dos rutas, por nombre de caso."""
    visto: dict[str, dict[str, Any]] = {}
    with ve.dependencias({get_cuentas_de_registro: None}):
        for nombre, cuerpo, crudo, _ in ve._casos_del_registro():
            if crudo is not None:
                r = ve.client.post("/auth/registro", content=crudo, headers=_JSON)
            else:
                r = ve.client.post("/auth/registro", json=cuerpo)
            visto[f"registro: {nombre}"] = {"status": r.status_code, "texto": r.text}
    sesion = AuthContext(profile_id=uuid4(), role="student", tenant_id=uuid4())
    with ve.dependencias({get_current_user: sesion, get_cambio_de_clave: None}):
        for nombre, cuerpo in CASOS_DE_CONTRASENA:
            r = ve.client.post("/auth/contrasena", json=cuerpo, headers=_BEARER)
            visto[f"contrasena: {nombre}"] = {"status": r.status_code, "texto": r.text}
        r = ve.client.post("/auth/contrasena", content=b'{"nueva": "marca-rota-88',
                           headers={**_JSON, **_BEARER})
        visto["contrasena: json roto"] = {"status": r.status_code, "texto": r.text}
    return visto


def test_se0_los_422_de_las_dos_rutas_cerradas_son_identicos_al_congelado() -> None:
    congelado: dict[str, dict[str, Any]] = json.loads(RUTA_SNAPSHOT.read_text(encoding="utf-8"))
    visto = observar()

    assert len(congelado) >= 30, f"SE0: el congelado trae {len(congelado)} casos, no 30 o más"
    assert sorted(visto) == sorted(congelado), (
        f"SE0: los casos no son los congelados: sobran {sorted(set(visto) - set(congelado))}, "
        f"faltan {sorted(set(congelado) - set(visto))}")
    distintos = {nombre: {"congelado": congelado[nombre], "visto": visto[nombre]}
                 for nombre in congelado if visto[nombre] != congelado[nombre]}
    assert distintos == {}, (
        f"SE0: {len(distintos)} de {len(congelado)} respuestas cambiaron: "
        f"{json.dumps(distintos, ensure_ascii=False)[:1500]}")
    no_422 = sorted(n for n, r in visto.items() if r["status"] != 422)
    assert no_422 == [], f"SE0: casos que no dieron 422: {no_422}"
