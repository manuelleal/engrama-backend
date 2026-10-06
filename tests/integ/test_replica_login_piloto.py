"""RP1 y RP2 — réplica del login del piloto — `docs/ESPEC_login_piloto.md` §4.

Entradas que no se usaron al desarrollar. Solo corren con la bandera
`ENGRAMA_REPLICA_LOGIN_PILOTO=1`; sin ella se saltan (2 skipped).

  RP1  semilla 9. Nombres con tildes y ñ. Tres CSV escritos de tres maneras:
       A con `;` y BOM (UTF-8), B con `;` en cp1252 y C con `,` en UTF-8. Una CE
       con puntos (`1.234.567`), un `CODIGO` con guion y un profe en TRES
       instituciones. Se afirma: cada cuenta tiene el `id` de su perfil; el
       estudiante de A no entra ni a B ni a C; el profe triple tiene 1 cuenta
       y 3 membresías, y sin encabezado cae en A (la más antigua).
  RP2  40 estudiantes en un grupo, en una sola corrida: 40 cuentas, 40 claves
       distintas y 40 filas. `restablecer` dos veces a la misma persona: 2
       filas más, y la última clave anotada es la que tiene GoTrue (el doble).
"""
from __future__ import annotations

import os
import random
from typing import Any
from uuid import UUID

import pytest

from tests.auth.test_login_piloto_clave import gotrue_falso
from tests.cuentas_falsas import CuentasFalsas
from tests.onboarding._ayuda import Fila, alta, escribir_csv, leer_salida, restablecer
from tests.seguridad.veredictos import PruebaRota

from . import _login_piloto as lp

REPLICA = os.environ.get("ENGRAMA_REPLICA_LOGIN_PILOTO") == "1"
pytestmark = [
    pytest.mark.integ,
    pytest.mark.skipif(not REPLICA,
                       reason="réplica del login piloto: ENGRAMA_REPLICA_LOGIN_PILOTO=1"),
]

SEMILLA = 9
NOMBRES = ("Íñigo Peña", "Begoña Núñez", "Raúl Ibáñez", "Zoé Güiraldes")
# Cómo se escribe el CSV de cada institución: (separador, codificación).
ESCRITURA = {"A": (";", "utf-8-sig"), "B": (";", "cp1252"), "C": (",", "utf-8")}
NO_ES_MIEMBRO = "User is not a member of the requested tenant"


def _filas(letra: str, docs: list[str], doc_del_triple: str) -> list[Fila]:
    grupo = f"R{letra}"
    filas: list[Fila] = [
        (f"Coordinación {letra}", lp.correo_de("admin", letra), docs[0], "CC", "", "admin"),
        (f"Docente Ñandú {letra}", lp.correo_de("profe", letra), docs[1], "TI", grupo, "profe"),
        ("Profe Triple en " + letra, lp.correo_de("triple", letra), doc_del_triple, "CC", grupo,
         "profe"),
    ]
    for i, nombre in enumerate(NOMBRES):
        filas.append((f"{nombre} {letra}", lp.correo_de(f"est{i + 1}", letra), docs[2 + i], "CC",
                      grupo, "estudiante"))
    return filas


def test_rp1_tildes_tres_codificaciones_y_profe_triple(integ, tmp_path, capsys) -> None:
    rng = random.Random(SEMILLA)
    docs = [str(d) for d in rng.sample(range(10**7, 10**10), 19)]
    doble = CuentasFalsas()
    salida = tmp_path / "credenciales.csv"
    esperados: dict[str, str] = {}  # correo -> nombre que escribió su institución
    for n, letra in enumerate(lp.LETRAS):
        filas = _filas(letra, docs[6 * n:6 * n + 6], docs[18])
        if letra == "A":   # una CE con puntos
            filas[3] = (filas[3][0], filas[3][1], "1.234.567", "CE", filas[3][4], filas[3][5])
        if letra == "B":   # un código interno con guion
            filas[4] = (filas[4][0], filas[4][1], "b-07", "CODIGO", filas[4][4], filas[4][5])
        rng.shuffle(filas)
        esperados.update({f[1]: f[0] for f in filas})
        sep, codificacion = ESCRITURA[letra]
        corrida = alta(integ, doble, capsys, slug=lp.slug_de(letra), salida=salida,
                       csv_=escribir_csv(tmp_path, f"{letra}.csv", filas, sep=sep,
                                         encoding=codificacion))
        if corrida.codigo != 0:
            raise PruebaRota(f"RP1: el alta de {letra} salió con {corrida.codigo}: "
                             f"{corrida.stdout}")
    ids = lp.tenants(integ)
    estudiante_a, triple = lp.correo_de("est1", "A"), lp.correo_de("triple", "A")
    with gotrue_falso():
        cambios = [lp.cambiar_clave(integ, doble, c) for c in (estudiante_a, triple)]

    def ajeno(letra: str) -> tuple[int, Any]:
        r = lp.client.get("/challenges/", headers=lp.cabeceras(integ, doble, estudiante_a,
                                                                 ids[letra]))
        return r.status_code, r.json().get("detail")

    _s, del_triple = lp.me(integ, doble, triple)
    _s, de_inigo = lp.me(integ, doble, estudiante_a)
    observado = {
        "cambios": cambios,
        "perfiles": int(integ.valor("select count(*) from profiles")),
        "cuentas": len(doble.cuentas),
        "cuenta_igual_perfil": lp.cuenta_igual_perfil(integ, doble),
        "otro_colegio": [ajeno("B"), ajeno("C")],
        "ce_sin_puntos": int(integ.valor(
            "select count(*) from profiles where documento_id = '1234567'")),
        "codigo_con_guion": int(integ.valor(
            "select count(*) from profiles where documento_id = 'inst-b_b-07'")),
        "nombre_con_tildes": de_inigo.get("full_name"),
        "nombres_mal_leidos": int(integ.valor("select count(*) from memberships")) - sum(
            int(integ.valor("select count(*) from memberships where full_name = :n", n=nombre))
            for nombre in set(esperados.values())),
        "triple": {
            "cuentas": sum(1 for c in doble.cuentas.values() if "triple" in c["correo"]),
            "membresias": len(del_triple.get("memberships", [])),
            "sin_encabezado": lp.letra_de(ids, del_triple.get("active_tenant_id")),
            "orden": [lp.letra_de(ids, m.get("tenant_id"))
                      for m in del_triple.get("memberships", [])],
        },
    }
    assert observado == {
        "cambios": [204, 204], "perfiles": 19, "cuentas": 19, "cuenta_igual_perfil": 19,
        "otro_colegio": [(403, NO_ES_MIEMBRO), (403, NO_ES_MIEMBRO)],
        "ce_sin_puntos": 1, "codigo_con_guion": 1,
        "nombre_con_tildes": "Íñigo Peña A", "nombres_mal_leidos": 0,
        "triple": {"cuentas": 1, "membresias": 3, "sin_encabezado": "A",
                   "orden": ["A", "B", "C"]},
    }, f"RP1: {observado}"


def test_rp2_cuarenta_en_una_corrida_y_restablecer_dos_veces(integ, tmp_path, capsys) -> None:
    rng = random.Random(SEMILLA + 1)
    docs = [str(d) for d in rng.sample(range(10**7, 10**10), 40)]
    filas: list[Fila] = [(f"Estudiante Nº {i + 1}", f"rp2.{i + 1}@engrama.test", doc, "TI",
                          "R2", "estudiante") for i, doc in enumerate(docs)]
    doble = CuentasFalsas()
    salida = tmp_path / "credenciales.csv"
    corrida = alta(integ, doble, capsys, slug="inst-rp2", salida=salida,
                   csv_=escribir_csv(tmp_path, "cuarenta.csv", filas))
    tras_alta = {"codigo": corrida.codigo, "cuentas": len(doble.cuentas),
                 "claves_distintas": len(doble.claves()), "filas": len(leer_salida(salida)),
                 "cuenta_igual_perfil": lp.cuenta_igual_perfil(integ, doble)}

    elegido = rng.randrange(40)
    codigos = [restablecer(integ, doble, capsys, slug="inst-rp2", documento=docs[elegido],
                           salida=salida).codigo for _ in range(2)]
    anotadas = [f.get("contrasena_temporal") for f in leer_salida(salida)]
    del_doble = doble.cuentas.get(doble.id_de(f"rp2.{elegido + 1}@engrama.test") or UUID(int=0),
                                  {}).get("clave")
    observado = {
        "alta": tras_alta, "restablecer": codigos, "filas": len(anotadas),
        "cambios_de_clave": len(doble.cambios),
        "las_dos_claves_son_distintas": len(set(anotadas[-2:])) == 2,
        "la_ultima_es_la_del_doble": anotadas[-1] == del_doble,
        "claves_distintas_en_total": len(set(anotadas)),
    }
    assert observado == {
        "alta": {"codigo": 0, "cuentas": 40, "claves_distintas": 40, "filas": 40,
                 "cuenta_igual_perfil": 40},
        "restablecer": [0, 0], "filas": 42, "cambios_de_clave": 2,
        "las_dos_claves_son_distintas": True, "la_ultima_es_la_del_doble": True,
        "claves_distintas_en_total": 42,
    }, f"RP2: {observado}"
