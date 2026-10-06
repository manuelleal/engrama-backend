"""HP1 — Humo del login del piloto, de punta a punta — `docs/ESPEC_login_piloto.md` §4.

Datos sintéticos con semilla fija (`random.Random(8)`), que elige, en este
orden: los 19 documentos (8 a 10 dígitos, distintos), el orden de las filas de
cada CSV (un `shuffle` por institución: A, B y C) y cuál estudiante de C usa
`CODIGO`.

Siembra, toda por la CLI con el doble de GoTrue: `inst-a`, `inst-b` e `inst-c`
(en el papel de UIS, SENA y UNAD) con 1000 monedas cada una; en cada una, 1
admin, 1 profe y 4 estudiantes en un grupo. El profe D está en A y en B con la
misma CC (y otro correo en B).

Flujo:
  1. `alta` de A, B y C, y otra vez de A.
  2. Cada una de las 19 cuentas: `/auth/me`, y después `GET /challenges/` (403).
  3. `POST /auth/contrasena` de cada una; después, `GET /challenges/` (200).
  4. Un estudiante de A con `X-Tenant-ID` de B y de C.
  5. D sin encabezado y con B.
  6. M3 con `"12.345.678"`.
  7. `restablecer` de un estudiante de B, y después `GET /challenges/`.

Escribe `tests/_salida/humo_login_piloto.json` (en `.gitignore`) ANTES de
afirmar, con etiquetas y conteos: nunca ids, correos ni contraseñas.
"""
from __future__ import annotations

import json
import random
from typing import Any

import pytest

from tests.auth.test_login_piloto_clave import gotrue_falso
from tests.cuentas_falsas import CuentasFalsas
from tests.integ_db import RAIZ_BACKEND
from tests.onboarding._ayuda import alta, escribir_csv, restablecer

from . import _login_piloto as lp

pytestmark = pytest.mark.integ

RUTA_HUMO_LOGIN_PILOTO = RAIZ_BACKEND / "tests" / "_salida" / "humo_login_piloto.json"
SEMILLA = 8

# Contenido exacto (ESPEC §4). Si difiere se reporta; no se ajusta para que pase.
HUMO_ESPERADO: dict[str, Any] = {
    "semilla": 8, "instituciones": 3, "cuentas_nuevas": [7, 6, 6],
    "cuentas_existentes": [0, 1, 0], "perfiles": 19, "membresias": 20,
    "cuenta_igual_perfil": 19, "billeteras": [1000, 1000, 1000],
    "segunda_corrida": {"cuentas_nuevas": 0, "membresias_nuevas": 0, "billetera": 1000},
    "primer_ingreso": {"me_200": 19, "debe_cambiar": 19, "bloqueados_403": 19},
    "cambio": {"respuestas_204": 19, "desbloqueados_200": 19},
    "otro_colegio": [403, 403],
    "docente_compartido": {"sin_encabezado": "A", "con_B": "B", "nombre_de_la_membresia": True},
    "documento_con_puntos": 422, "codigo_con_prefijo": True,
    "restablecer": {"debe_cambiar": True, "bloqueado": 403},
}


def _billetera(integ: Any, letra: str) -> Any:
    return integ.valor(
        "select w.balance from coin_wallets w join tenants t on t.id = w.owner_id "
        "where t.slug = :s and w.owner_type = 'tenant'", s=lp.slug_de(letra))


def test_hp1_humo_login_piloto(integ, tmp_path, capsys) -> None:
    rng = random.Random(SEMILLA)
    docs = [str(d) for d in rng.sample(range(10**7, 10**10), 19)]
    doc_d = docs[18]
    csvs = {}
    for n, letra in enumerate(lp.LETRAS):
        filas = lp.filas_de(letra, docs[6 * n:6 * n + 6],
                            compartido=doc_d if letra in ("A", "B") else None)
        rng.shuffle(filas)
        csvs[letra] = filas
    con_codigo = rng.randrange(4)
    csvs["C"] = [(nom, correo, doc, "CODIGO" if correo == lp.correo_de(f"est{con_codigo + 1}", "C")
                  else tipo, grupo, rol) for nom, correo, doc, tipo, grupo, rol in csvs["C"]]
    codigo_c = next(doc for _n, _c, doc, tipo, _g, _r in csvs["C"] if tipo == "CODIGO")
    correos = sorted({f[1] for filas in csvs.values() for f in filas} - {lp.correo_de("d", "B")})

    # 1. alta de A, B y C, y otra vez de A.
    doble = CuentasFalsas()
    salida = tmp_path / "credenciales.csv"
    rutas = {letra: escribir_csv(tmp_path, f"{letra}.csv", csvs[letra]) for letra in lp.LETRAS}
    corridas = [alta(integ, doble, capsys, slug=lp.slug_de(letra), csv_=rutas[letra],
                     salida=salida, nombre=f"Institución Sintética {letra}")
                for letra in lp.LETRAS]
    otra_vez = alta(integ, doble, capsys, slug="inst-a", csv_=rutas["A"], salida=salida,
                    nombre="Institución Sintética A")
    ids = lp.tenants(integ)

    # 2. Primer ingreso de las 19 cuentas.
    ingresos = [lp.me(integ, doble, c) for c in correos]
    bloqueados = [lp.retos(integ, doble, c) for c in correos]

    # 3. Cada una cambia su contraseña (GoTrue es un doble) y vuelve a entrar.
    with gotrue_falso():
        cambios = [lp.cambiar_clave(integ, doble, c) for c in correos]
    desbloqueados = [lp.retos(integ, doble, c) for c in correos]

    # 4. Un estudiante de A pide otro colegio.
    estudiante_a = lp.correo_de("est1", "A")
    otro_colegio = [lp.retos(integ, doble, estudiante_a, ids.get(letra, "sin-tenant"))
                    for letra in ("B", "C")]

    # 5. D, el profe de A y de B.
    d = lp.correo_de("d", "A")
    _s, sin_encabezado = lp.me(integ, doble, d)
    _s, con_b = lp.me(integ, doble, d, ids.get("B", "sin-tenant"))

    # 6. M3 con un documento con puntos, por el admin de A.
    grupo_a = integ.valor("select g.id from groups g join tenants t on t.id = g.tenant_id "
                          "where t.slug = 'inst-a'")
    con_puntos = lp.client.post(
        f"/admin/groups/{grupo_a}/students",
        headers=lp.cabeceras(integ, doble, lp.correo_de("admin", "A")),
        json={"documento_id": "12.345.678", "nombre_completo": "Con Puntos"}).status_code

    # 7. Restablecer a un estudiante de B.
    estudiante_b = lp.correo_de("est1", "B")
    doc_b = next(doc for _n, correo, doc, _t, _g, _r in csvs["B"] if correo == estudiante_b)
    restablecer(integ, doble, capsys, slug="inst-b", documento=doc_b, salida=salida)
    _s, tras_restablecer = lp.me(integ, doble, estudiante_b)

    datos = {
        "semilla": SEMILLA,
        "instituciones": int(integ.valor("select count(*) from tenants")),
        "cuentas_nuevas": [c.resumen.get("cuentas_nuevas") for c in corridas],
        "cuentas_existentes": [c.resumen.get("cuenta_existente") for c in corridas],
        "perfiles": int(integ.valor("select count(*) from profiles")),
        "membresias": int(integ.valor("select count(*) from memberships")),
        "cuenta_igual_perfil": lp.cuenta_igual_perfil(integ, doble),
        "billeteras": [_billetera(integ, letra) for letra in lp.LETRAS],
        "segunda_corrida": {"cuentas_nuevas": otra_vez.resumen.get("cuentas_nuevas"),
                            "membresias_nuevas": otra_vez.resumen.get("membresias_nuevas"),
                            "billetera": _billetera(integ, "A")},
        "primer_ingreso": {
            "me_200": sum(1 for s, _c in ingresos if s == 200),
            "debe_cambiar": sum(1 for _s, c in ingresos if c.get("must_change_password") is True),
            "bloqueados_403": bloqueados.count(403)},
        "cambio": {"respuestas_204": cambios.count(204),
                   "desbloqueados_200": desbloqueados.count(200)},
        "otro_colegio": otro_colegio,
        "docente_compartido": {
            "sin_encabezado": lp.letra_de(ids, sin_encabezado.get("active_tenant_id")),
            "con_B": lp.letra_de(ids, con_b.get("active_tenant_id")),
            "nombre_de_la_membresia": (sin_encabezado.get("full_name"), con_b.get("full_name"))
            == ("Profe D en A", "Profe D en B")},
        "documento_con_puntos": con_puntos,
        "codigo_con_prefijo": integ.valor("select count(*) from profiles where documento_id = :d",
                                          d=f"inst-c_{codigo_c}") == 1,
        "restablecer": {"debe_cambiar": tras_restablecer.get("must_change_password"),
                        "bloqueado": lp.retos(integ, doble, estudiante_b)},
    }
    # Primero se escribe (para poder reportarlo), después se afirma.
    RUTA_HUMO_LOGIN_PILOTO.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO_LOGIN_PILOTO.write_text(
        json.dumps(datos, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    en_disco = json.loads(RUTA_HUMO_LOGIN_PILOTO.read_text(encoding="utf-8"))
    assert en_disco == HUMO_ESPERADO, f"humo login piloto: {en_disco} != {HUMO_ESPERADO}"
