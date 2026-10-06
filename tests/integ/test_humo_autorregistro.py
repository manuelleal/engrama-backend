"""HA1 (humo) y RA1 (réplica) del autorregistro — `docs/ESPEC_autorregistro.md` §4.

HA1: un grupo sintético de 40 se registra con su código; una persona 41 ya no
cabe; un menor no pasa; los 40 esperan (403); el profe aprueba 38 y rechaza 2
(elegidos con `random.Random(35)`); los 38 entran. Escribe
`tests/_salida/humo_autorregistro.json` (en `.gitignore`) ANTES de afirmar.

RA1 solo corre con `ENGRAMA_REPLICA_AUTORREGISTRO=1`, con entradas que no se
usaron al desarrollar: otra semilla, nombres con tildes y ñ, dos instituciones
con dos grupos cada una, códigos escritos en minúsculas, y un código que vence
a mitad de la corrida.
"""
from __future__ import annotations

import json
import os
import random
from collections.abc import Iterator
from typing import Any

import pytest

from tests.integ_db import RAIZ_BACKEND
from tests.registro import _ayuda as ay
from tests.seguridad.veredictos import sembrar

pytestmark = pytest.mark.integ

RUTA_HUMO_AUTORREGISTRO = RAIZ_BACKEND / "tests" / "_salida" / "humo_autorregistro.json"
SEMILLA = 35
REPLICA = os.environ.get("ENGRAMA_REPLICA_AUTORREGISTRO") == "1"

# Contenido exacto (ESPEC §4). Si difiere se reporta; no se ajusta para que pase.
HUMO_ESPERADO: dict[str, Any] = {
    "alembic_version": "039_grader", "semilla": 35, "registros_201": 40, "sin_cupo": 403,
    "menor": 422, "usos": 40, "cuenta_igual_perfil": 40, "pendientes_bloqueados": 40,
    "aprobadas": 38, "rechazadas": 2, "entran_200": 38, "perfiles": 38,
    "membresias_activas": 38, "cuentas": 38, "consentimientos": 38,
    "solicitudes": {"aprobada": 38}, "codigo_en_claro_en_la_base": False,
}


@pytest.fixture(autouse=True)
def _soltar_el_doble_al_terminar() -> Iterator[None]:
    """El doble de GoTrue no puede quedar puesto para el resto de la suite."""
    yield
    ay.soltar()


def _me(integ: Any, perfil: Any) -> tuple[int, Any]:
    r = ay.client.get("/auth/me", headers=integ.headers(perfil))
    return r.status_code, ay.campo(r, "detail")


def _por_estado(integ: Any) -> dict[str, int]:
    estados = [e for _, e in ay.solicitudes(integ)]
    return {e: estados.count(e) for e in sorted(set(estados))}


def test_ha1_humo_autorregistro(integ) -> None:
    rng = random.Random(SEMILLA)
    cuentas = ay.preparar(integ)
    a = ay.aula(integ, cupo=40)
    numeros = rng.sample(range(1, 90_000), 40)
    registros = [ay.registrar(ay.cuerpo(a.codigo, n)).status_code for n in numeros]
    sin_cupo = ay.registrar(ay.cuerpo(a.codigo, 90_001)).status_code
    menor = ay.registrar(ay.cuerpo(a.codigo, 90_002, mayor_de_edad=False)).status_code
    perfiles = [ay.perfil_de(integ, a.doc(n)) for n in numeros]
    igual = sum(1 for p in perfiles if p is not None and p in cuentas.cuentas)
    bloqueados = sum(1 for p in perfiles if _me(integ, p) == (403, "pending_approval"))
    pendientes = {s["codigo_estudiantil"]: s["id"] for s in ay.lista(integ, a.profe, a.grupo)}
    rechazados = set(rng.sample(numeros, 2))
    decisiones = {n: ay.decidir(integ, a.profe, a.grupo, pendientes.get(a.doc(n), 0),
                                "rechazar" if n in rechazados else "aprobar").status_code
                  for n in numeros}
    en_la_base = str(integ.valor("select string_agg(codigo_hash, ' ') from "
                                 "codigos_inscripcion") or "")
    datos = {
        "alembic_version": integ.valor("select version_num from alembic_version"),
        "semilla": SEMILLA,
        "registros_201": registros.count(201),
        "sin_cupo": sin_cupo,
        "menor": menor,
        "usos": ay.usos(integ, a.grupo),
        "cuenta_igual_perfil": igual,
        "pendientes_bloqueados": bloqueados,
        "aprobadas": sum(1 for n in numeros if n not in rechazados and decisiones[n] == 200),
        "rechazadas": sum(1 for n in rechazados if decisiones[n] == 200),
        "entran_200": sum(1 for p in perfiles if _me(integ, p)[0] == 200),
        "perfiles": ay.estudiantes(integ),
        "membresias_activas": ay.contar(integ, "select count(*) from memberships "
                                               "where role = 'student' and is_active"),
        "cuentas": len(cuentas.cuentas),
        "consentimientos": ay.contar(integ, "select count(*) from consentimientos"),
        "solicitudes": _por_estado(integ),
        "codigo_en_claro_en_la_base": a.codigo.replace("-", "") in en_la_base.upper(),
    }
    # Primero se escribe (para poder reportarlo), después se afirma.
    RUTA_HUMO_AUTORREGISTRO.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO_AUTORREGISTRO.write_text(
        json.dumps(datos, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    en_disco = json.loads(RUTA_HUMO_AUTORREGISTRO.read_text(encoding="utf-8"))
    assert en_disco == HUMO_ESPERADO, f"humo autorregistro: {en_disco} != {HUMO_ESPERADO}"


NOMBRES = ("Íñigo Peña Muñoz", "María José Núñez", "Ángela Güiza Ñáñez", "Óscar Ibáñez",
           "Lucía Cárdenas Ávila", "Sebastián Úsuga", "Begoña Yáñez", "Raúl Quiñones")


@pytest.mark.skipif(not REPLICA,
                    reason="réplica del autorregistro: ENGRAMA_REPLICA_AUTORREGISTRO=1")
def test_ra1_replica_dos_instituciones_y_un_codigo_que_vence(integ) -> None:
    rng = random.Random(36)
    cuentas = ay.preparar(integ)
    aulas = []
    for _ in range(2):
        primera = ay.aula(integ, grupo="B2-mañana")
        aulas += [primera, ay.aula(integ, grupo="A1-noche", tenant=primera.tenant)]
    estados: dict[int, list[int]] = {}
    numero = 0
    for i, a in enumerate(aulas):
        escrito = a.codigo.lower() if i % 2 else a.codigo.replace("-", " ")
        estados[i] = []
        for k in range(8):
            if i == 0 and k == 5:  # el código del primer grupo vence a mitad de la corrida
                sembrar(integ, "update codigos_inscripcion set expires_at = now() - interval "
                               "'1 second' where group_id = :g", g=a.grupo)
            numero += 1
            estados[i].append(ay.registrar(ay.cuerpo(
                escrito, rng.randrange(10_000, 99_999) * 10 + k, nombre=NOMBRES[k],
                correo=f"replica{numero}@sintetico.test")).status_code)
    listas = [ay.lista(integ, a.profe, a.grupo) for a in aulas]
    aprobaciones = [[ay.decidir(integ, a.profe, a.grupo, s["id"], "aprobar").status_code
                     for s in lista] for a, lista in zip(aulas, listas, strict=True)]
    por_grupo = [ay.contar(integ, "select count(*) from memberships where tenant_id = :t "
                                  "and group_code = :g and is_active and role = 'student'",
                           t=a.tenant, g=a.codigo_de_grupo) for a in aulas]
    ids = [integ.valor("select id from profiles where documento_id = :d",
                       d=s["codigo_estudiantil"]) for lista in listas for s in lista]
    observado = {
        "estados": estados, "pendientes": [len(lista) for lista in listas],
        "nombres_del_primer_grupo": [s["nombre"] for s in listas[0]],
        "aprobadas": [a.count(200) for a in aprobaciones], "activos_por_grupo": por_grupo,
        "cuenta_igual_perfil": sum(1 for p in ids if p in cuentas.cuentas), "cuentas":
            len(cuentas.cuentas),
        "cruce_de_institucion": ay.decidir(integ, aulas[0].profe, aulas[2].grupo,
                                           listas[2][0]["id"], "rechazar").status_code,
    }
    assert observado == {
        "estados": {0: [201] * 5 + [403] * 3, 1: [201] * 8, 2: [201] * 8, 3: [201] * 8},
        "pendientes": [5, 8, 8, 8], "nombres_del_primer_grupo": list(NOMBRES[:5]),
        "aprobadas": [5, 8, 8, 8], "activos_por_grupo": [5, 8, 8, 8],
        "cuenta_igual_perfil": 29, "cuentas": 29, "cruce_de_institucion": 404,
    }, f"RA1: {observado}"
