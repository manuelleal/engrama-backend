"""HS1 (humo) y RS1 (réplica) de las solicitudes sobre datos — `docs/ESPEC_solicitud_datos.md` §3.

HS1: dos instituciones; 4 personas crean 6 solicitudes (el tipo de cada una lo
elige `random.Random(36)`); el admin de la primera responde 2 (también al
azar); el de la segunda intenta responder una ajena. Escribe
`tests/_salida/humo_solicitudes_datos.json` (en `.gitignore`) ANTES de afirmar.

RS1 solo corre con `ENGRAMA_REPLICA_SOLICITUD_DATOS=1`, con entradas que no se
usaron al desarrollar: un mensaje de exactamente 1000 caracteres con tildes,
ñ, emoji y saltos de línea; una persona en dos instituciones; y el tope de 5
repartido entre las dos.
"""
from __future__ import annotations

import json
import os
import random
from typing import Any

import pytest

from tests.datos import test_solicitudes_datos as sd
from tests.integ_db import RAIZ_BACKEND

pytestmark = pytest.mark.integ

RUTA_HUMO_SOLICITUDES_DATOS = RAIZ_BACKEND / "tests" / "_salida" / "humo_solicitudes_datos.json"
SEMILLA = 36
REPLICA = os.environ.get("ENGRAMA_REPLICA_SOLICITUD_DATOS") == "1"
TIPOS = ("conocer", "actualizar", "rectificar", "suprimir")

# Contenido exacto (ESPEC §3). Si difiere se reporta; no se ajusta para que pase.
HUMO_ESPERADO: dict[str, Any] = {
    "alembic_version": "039_grader", "semilla": 36, "creadas_201": 6, "de_1001": 422,
    "tipo_invalido": 422, "del_usuario": [2, 2, 1, 1], "del_admin": [4, 2],
    "cruce_de_institucion": 404, "respondidas": 2, "con_traza": 2,
    "auditorias": {"creada": 6, "respondida": 2}, "perfiles_borrados": 0,
}


def test_hs1_humo_solicitudes_datos(integ) -> None:
    rng = random.Random(SEMILLA)
    a, b = integ.crear_tenant(), integ.crear_tenant()
    personas = [integ.crear_perfil(a), integ.crear_perfil(a), integ.crear_perfil(b),
                integ.crear_perfil(b)]
    admin_a, admin_b = integ.crear_perfil(a, rol="admin"), integ.crear_perfil(b, rol="admin")
    perfiles_antes = int(integ.valor("select count(*) from profiles"))
    cuantas = (2, 2, 1, 1)
    creadas = [sd.crear(integ, p, sd.pedir(rng.choice(TIPOS), f"Solicitud sintética {i}."))
               for p, n in zip(personas, cuantas, strict=True) for i in range(n)]
    de_a = [f["id"] for f in sd.filas(integ, tenant_id=a)]
    elegidas = rng.sample(de_a, 2) if len(de_a) >= 2 else de_a
    respuestas = [sd.responder(integ, admin_a, sid,
                               {"estado": "resuelta", "respuesta": "Atendida a mano."})
                  for sid in elegidas]
    datos = {
        "alembic_version": integ.valor("select version_num from alembic_version"),
        "semilla": SEMILLA,
        "creadas_201": sum(1 for r in creadas if r.status_code == 201),
        "de_1001": sd.crear(integ, personas[0], sd.pedir(mensaje="m" * 1001)).status_code,
        "tipo_invalido": sd.crear(integ, personas[0], sd.pedir("borrar")).status_code,
        "del_usuario": [len(sd.mias(integ, p) or []) for p in personas],
        "del_admin": [len(sd._json(sd.del_admin(integ, quien)) or [])
                      for quien in (admin_a, admin_b)],
        "cruce_de_institucion": sd.responder(
            integ, admin_b, de_a[0] if de_a else 0,
            {"estado": "rechazada", "respuesta": "No es mía."}).status_code,
        "respondidas": sum(1 for r in respuestas if r.status_code == 200),
        "con_traza": sum(1 for f in sd.filas(integ)
                         if f["respondida_por"] == admin_a and f["respondida_en"] is not None),
        "auditorias": {"creada": sd.auditorias(integ, "datos_solicitud_creada"),
                       "respondida": sd.auditorias(integ, "datos_solicitud_respondida")},
        "perfiles_borrados": perfiles_antes - int(integ.valor("select count(*) from profiles")),
    }
    # Primero se escribe (para poder reportarlo), después se afirma.
    RUTA_HUMO_SOLICITUDES_DATOS.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO_SOLICITUDES_DATOS.write_text(
        json.dumps(datos, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    en_disco = json.loads(RUTA_HUMO_SOLICITUDES_DATOS.read_text(encoding="utf-8"))
    assert en_disco == HUMO_ESPERADO, f"humo solicitudes de datos: {en_disco} != {HUMO_ESPERADO}"


@pytest.mark.skipif(not REPLICA,
                    reason="réplica de solicitudes de datos: ENGRAMA_REPLICA_SOLICITUD_DATOS=1")
def test_rs1_replica_mensaje_raro_y_persona_en_dos_instituciones(integ) -> None:
    a, b = integ.crear_tenant(), integ.crear_tenant()
    ines = integ.crear_perfil(a, rol="teacher")
    integ.afiliar(ines, b, rol="teacher")
    admin_a, admin_b = integ.crear_perfil(a, rol="admin"), integ.crear_perfil(b, rol="admin")
    base = "Señores: actualicen mi teléfono, ¡por favor! 🙂\nGracias.\n"
    de_mil = (base * 40)[:1000]
    en_b = {"X-Tenant-ID": str(b)}
    estados = [sd.crear(integ, ines, sd.pedir("actualizar", de_mil)).status_code,
               sd.crear(integ, ines, sd.pedir("conocer"), **en_b).status_code]
    visto = {"ines": len(sd.mias(integ, ines) or []),
             "ines_desde_b": len(sd.mias(integ, ines, **en_b) or []),
             "admins": [len(sd._json(sd.del_admin(integ, q)) or []) for q in (admin_a, admin_b)]}
    guardado = str(integ.valor("select mensaje from solicitudes_datos order by id limit 1"))
    repartidas = [sd.crear(integ, ines, sd.pedir(), **(en_b if i % 2 else {})).status_code
                  for i in range(4)]
    observado = {
        "largo": len(de_mil), "estados": estados, "visto": visto,
        "mensaje_intacto": guardado == de_mil, "repartidas": repartidas,
        "filas": len(sd.filas(integ)),
        "por_institucion": [len(sd.filas(integ, tenant_id=t)) for t in (a, b)],
    }
    assert observado == {
        "largo": 1000, "estados": [201, 201], "visto": {"ines": 2, "ines_desde_b": 2,
                                                       "admins": [1, 1]},
        "mensaje_intacto": True, "repartidas": [201, 201, 201, 409], "filas": 5,
        "por_institucion": [3, 2],
    }, f"RS1: {observado}"
