"""El alta del operador contra la base real — `docs/ESPEC_login_piloto.md` §1.7, C16-C24.

  OP1  C16  institución: nace con su billetera; la 2.ª corrida no la recarga.
  OP2  C17  alta completa: la cuenta nace con `id == profiles.id` (el vínculo).
  OP3  C18  idempotencia: la 2.ª corrida no crea nada ni toca la bandera.
  OP4  C19  el profe de dos instituciones: 1 perfil, 1 cuenta, 2 membresías.
  OP5  C20  todo o nada: fila mala, choque en la base y `--salida` en el repo.
  OP6  C21  un perfil que ya creó M3 (HTTP) recibe su cuenta con ESE id.
  OP7  C22  restablecer: clave nueva, la bandera vuelve y se anota.
  OP8  C24  la bandera, commiteada, ANTES que la cuenta (H-3).

Reglas (ESPEC §3): cada test junta lo que observa en un dict y lo compara
ENTERO; el cliente usa `raise_server_exceptions=False`; lo que no es del
criterio (una siembra que no quedó) es `PruebaRota`, no `AssertionError`.
GoTrue es el doble `CuentasFalsas`; `--salida` va a `tmp_path` (fuera del repo).

Todo es sintético: documentos, nombres y correos inventados (`@engrama.test`).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.onboarding.salida import COLUMNAS_SALIDA
from tests.cuentas_falsas import CuentasFalsas, observar_bandera
from tests.integ_db import RAIZ_BACKEND
from tests.seguridad.veredictos import PruebaRota

from ._ayuda import (
    Fila,
    alta,
    bandera,
    cabecera_de,
    contar,
    escribir_csv,
    leer_salida,
    perfil_de,
    poner_bandera,
    restablecer,
    sembrar_institucion,
)

pytestmark = pytest.mark.integ
client = TestClient(app, raise_server_exceptions=False)

# admin, profe y 3 estudiantes en un grupo (C17).
CINCO: list[Fila] = [
    ("Ada Sintética", "ada@engrama.test", "1001", "CC", "", "admin"),
    ("Pepa Sintética", "pepa@engrama.test", "1002", "CC", "G1", "profe"),
    ("Ana Sintética", "ana@engrama.test", "1003", "CC", "G1", "estudiante"),
    ("Beto Sintético", "beto@engrama.test", "1004", "CC", "G1", "estudiante"),
    ("Caro Sintética", "caro@engrama.test", "1005", "CC", "G1", ""),
]
DOCS_CINCO = [f[2] for f in CINCO]


def _exigir_ok(corrida: Any, que: str) -> None:
    """Arnés: una corrida de PREPARACIÓN que no sale con 0 es `PruebaRota`."""
    if corrida.codigo != 0:
        raise PruebaRota(f"{que}: la CLI salió con {corrida.codigo}: {corrida.stdout}")


def _me(integ: Any, documento: str, tenant: Any = None) -> tuple[int, Any, Any]:
    """`/auth/me` con `headers(profiles.id)`: (status, must_change_password, colegio activo)."""
    h = integ.headers(perfil_de(integ, documento))
    if tenant is not None:
        h["X-Tenant-ID"] = str(tenant)
    r = client.get("/auth/me", headers=h)
    cuerpo = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    cuerpo = cuerpo if isinstance(cuerpo, dict) else {}
    return r.status_code, cuerpo.get("must_change_password"), cuerpo.get("active_tenant_id")


# =============================================================================
# OP1 — C16: la institución
# =============================================================================
def _institucion(integ: Any, slug: str) -> dict[str, Any]:
    return {
        "tenants": contar(integ, "tenants where slug = :s", s=slug),
        "coin_pool": integ.valor("select coin_pool from tenants where slug = :s", s=slug),
        "billetera": integ.valor(
            "select w.balance from coin_wallets w join tenants t on t.id = w.owner_id "
            "where t.slug = :s and w.owner_type = 'tenant'", s=slug),
        "ledger": contar(integ, "coin_ledger"),
    }


def test_op1_institucion_nace_con_billetera_y_no_se_recarga(integ, tmp_path, capsys) -> None:
    """OP1 (C16): 1000 al nacer; la 2.ª `alta` con 5000 no cambia nada."""
    doble = CuentasFalsas()
    vacio = escribir_csv(tmp_path, "vacio.csv", [])
    salida = tmp_path / "credenciales.csv"
    primera = alta(integ, doble, capsys, slug="inst-op1", csv_=vacio, salida=salida, monedas=1000)
    tras_primera = _institucion(integ, "inst-op1")
    segunda = alta(integ, doble, capsys, slug="inst-op1", csv_=vacio, salida=salida, monedas=5000)
    observado = {"codigos": [primera.codigo, segunda.codigo], "primera": tras_primera,
                 "segunda": _institucion(integ, "inst-op1")}
    assert observado == {
        "codigos": [0, 0],
        "primera": {"tenants": 1, "coin_pool": 1000, "billetera": 1000, "ledger": 0},
        "segunda": {"tenants": 1, "coin_pool": 1000, "billetera": 1000, "ledger": 0},
    }, f"OP1: {observado}"


# =============================================================================
# OP2 — C17: el alta completa y el vínculo
# =============================================================================
def test_op2_alta_completa_la_cuenta_nace_con_el_id_del_perfil(integ, tmp_path, capsys) -> None:
    """OP2 (C17): 5 perfiles y 5 cuentas con `id == profiles.id`, todas con la bandera."""
    doble = CuentasFalsas()
    salida = tmp_path / "credenciales.csv"
    corrida = alta(integ, doble, capsys, slug="inst-op2", salida=salida,
                   csv_=escribir_csv(tmp_path, "cinco.csv", CINCO))
    perfiles = {perfil_de(integ, d) for d in DOCS_CINCO}
    filas = leer_salida(salida)
    claves = {f.get("contrasena_temporal", "") for f in filas}
    observado = {
        "codigo": corrida.codigo,
        "perfiles": contar(integ, "profiles"),
        "cuentas": len(doble.cuentas),
        "cuentas_con_id_de_perfil": len(set(doble.cuentas) & perfiles),
        "con_bandera": contar(integ, "profiles where force_password_reset"),
        "salida": {"cabecera": cabecera_de(salida), "filas": len(filas), "claves": len(claves),
                   "claves_como_las_del_doble": claves == doble.claves(),
                   "con_documento": [d for d in DOCS_CINCO if d in salida.read_text("utf-8")]
                   if salida.exists() else None},
        "membresias": {rol: contar(integ, "memberships where role = :r", r=rol)
                       for rol in ("admin", "teacher", "student")},
        "teacher_groups": contar(integ, "teacher_groups"),
        "nombres_de_estudiantes": sorted(
            str(integ.valor("select m.full_name from memberships m join profiles p on p.id = "
                            "m.profile_id where p.documento_id = :d", d=d))
            for d in DOCS_CINCO[2:]),
        "me": [_me(integ, d)[:2] for d in DOCS_CINCO],
        "claves_en_stdout": [c for c in doble.claves() if c in corrida.stdout],
    }
    assert observado == {
        "codigo": 0, "perfiles": 5, "cuentas": 5, "cuentas_con_id_de_perfil": 5,
        "con_bandera": 5,
        "salida": {"cabecera": list(COLUMNAS_SALIDA), "filas": 5, "claves": 5,
                   "claves_como_las_del_doble": True, "con_documento": []},
        "membresias": {"admin": 1, "teacher": 1, "student": 3},
        "teacher_groups": 1,
        "nombres_de_estudiantes": ["Ana Sintética", "Beto Sintético", "Caro Sintética"],
        "me": [(200, True)] * 5,
        "claves_en_stdout": [],
    }, f"OP2: {observado}"


# =============================================================================
# OP3 — C18: idempotencia
# =============================================================================
def test_op3_segunda_corrida_no_crea_nada_ni_toca_la_bandera(integ, tmp_path, capsys) -> None:
    """OP3 (C18): quien ya cambió su clave (bandera en false) sigue así tras la 2.ª corrida."""
    doble = CuentasFalsas()
    salida = tmp_path / "credenciales.csv"
    cinco = escribir_csv(tmp_path, "cinco.csv", CINCO)
    _exigir_ok(alta(integ, doble, capsys, slug="inst-op3", csv_=cinco, salida=salida),
               "OP3, 1.ª corrida")
    poner_bandera(integ, "1003", False)  # Ana ya cambió su contraseña
    antes = (contar(integ, "profiles"), contar(integ, "memberships"), len(doble.cuentas))

    segunda = alta(integ, doble, capsys, slug="inst-op3", csv_=cinco, salida=salida)
    despues = (contar(integ, "profiles"), contar(integ, "memberships"), len(doble.cuentas))
    observado = {
        "codigo": segunda.codigo,
        "nuevos": tuple(d - a for a, d in zip(antes, despues, strict=True)),
        "filas_de_salida": len(leer_salida(salida)),
        "bandera_de_quien_ya_cambio": bandera(integ, "1003"),
    }
    assert observado == {"codigo": 0, "nuevos": (0, 0, 0), "filas_de_salida": 5,
                         "bandera_de_quien_ya_cambio": False}, f"OP3: {observado}"


# =============================================================================
# OP4 — C19: el profe de dos instituciones
# =============================================================================
def test_op4_profe_en_dos_instituciones_una_sola_cuenta(integ, tmp_path, capsys) -> None:
    """OP4 (C19): D (CC 7001) en A y en B con otro correo: 1 perfil, 1 cuenta, 2 membresías."""
    doble = CuentasFalsas()
    salida = tmp_path / "credenciales.csv"
    en_a = escribir_csv(tmp_path, "a.csv", [
        ("Profe D en A", "d.en.a@engrama.test", "7001", "CC", "GA", "profe")])
    en_b = escribir_csv(tmp_path, "b.csv", [
        ("Profe D en B", "d.en.b@engrama.test", "7001", "CC", "GB", "profe")])
    _exigir_ok(alta(integ, doble, capsys, slug="inst-a", csv_=en_a, salida=salida), "OP4, A")
    poner_bandera(integ, "7001", False)  # D ya cambió su contraseña antes de la corrida de B

    de_b = alta(integ, doble, capsys, slug="inst-b", csv_=en_b, salida=salida)
    tenant = {s: str(integ.valor("select id from tenants where slug = :s", s=s))
              for s in ("inst-a", "inst-b")}
    observado = {
        "codigo": de_b.codigo,
        "perfiles": contar(integ, "profiles where documento_id = '7001'"),
        "cuentas": sorted(c["correo"] for c in doble.cuentas.values()),
        "membresias_teacher": contar(integ, "memberships where role = 'teacher'"),
        "resumen_de_b": {k: de_b.resumen.get(k)
                         for k in ("cuenta_existente", "cuenta_con_otro_correo")},
        "llamadas_a_crear": len(doble.creadas),
        "bandera": bandera(integ, "7001"),
        "sin_encabezado": _me(integ, "7001")[2],
        "con_b": _me(integ, "7001", tenant["inst-b"])[2],
    }
    assert observado == {
        "codigo": 0, "perfiles": 1, "cuentas": ["d.en.a@engrama.test"], "membresias_teacher": 2,
        "resumen_de_b": {"cuenta_existente": 1, "cuenta_con_otro_correo": 1},
        "llamadas_a_crear": 1, "bandera": False,
        "sin_encabezado": tenant["inst-a"], "con_b": tenant["inst-b"],
    }, f"OP4: {observado}"


# =============================================================================
# OP5 — C20: todo o nada
# =============================================================================
def _huella(integ: Any, doble: CuentasFalsas) -> dict[str, int]:
    return {"tenants": contar(integ, "tenants"), "perfiles": contar(integ, "profiles"),
            "membresias": contar(integ, "memberships"), "grupos": contar(integ, "groups"),
            "cuentas": len(doble.cuentas)}


def test_op5_todo_o_nada(integ, tmp_path, capsys) -> None:
    """OP5 (C20): una fila mala, un choque en la base o `--salida` en el repo: 0 escrituras."""
    doble = CuentasFalsas()
    salida = tmp_path / "credenciales.csv"

    # (a) una fila mala (CC `12a`) entre filas buenas.
    con_mala = escribir_csv(tmp_path, "mala.csv", [
        *CINCO[:3], ("Mala Sintética", "mala@engrama.test", "12a", "CC", "G1", "estudiante")])
    mala = alta(integ, doble, capsys, slug="inst-op5", csv_=con_mala, salida=salida)
    tras_mala = {"codigo": mala.codigo, **_huella(integ, doble), "salida": salida.exists()}

    # (b) choque en la base: 5001 ya es estudiante de G1 en esa institución.
    tenant = sembrar_institucion(integ, "inst-op5b")
    integ.crear_grupo(tenant, "G1")
    previo = integ.crear_perfil(tenant, group_code="G1")
    from tests.seguridad.veredictos import sembrar
    sembrar(integ, "update profiles set documento_id = '5001' where id = :p", p=previo)
    antes = _huella(integ, doble)
    con_choque = escribir_csv(tmp_path, "choque.csv", [
        ("Uno Sintético", "uno@engrama.test", "5002", "CC", "G2", "estudiante"),
        ("Dos Sintética", "dos@engrama.test", "5003", "CC", "G2", "estudiante"),
        ("Previo Sintético", "previo@engrama.test", "5001", "CC", "G2", "estudiante")])
    choque = alta(integ, doble, capsys, slug="inst-op5b", csv_=con_choque, salida=salida)
    despues = _huella(integ, doble)
    tras_choque = {"codigo": choque.codigo, "salida": salida.exists(),
                   "fila": [e.get("fila") for e in choque.resumen.get("errores", [])],
                   "nuevos": {k: despues[k] - antes[k] for k in antes}}

    # (c) `--salida` dentro del repo del backend.
    en_repo = RAIZ_BACKEND / "tests" / "_salida" / "credenciales_que_no_debe_existir.csv"
    buena = escribir_csv(tmp_path, "buena.csv", CINCO)
    dentro = alta(integ, doble, capsys, slug="inst-op5c", csv_=buena, salida=en_repo)
    tras_repo = {"codigo": dentro.codigo, "archivo": en_repo.exists(),
                 "nuevos": {k: v - despues[k] for k, v in _huella(integ, doble).items()}}
    en_repo.unlink(missing_ok=True)  # si un tramposo lo escribió, no queda en el repo

    nada = {"tenants": 0, "perfiles": 0, "membresias": 0, "grupos": 0, "cuentas": 0}
    observado = {"fila_mala": tras_mala, "choque": tras_choque, "salida_en_repo": tras_repo}
    assert observado == {
        "fila_mala": {"codigo": 1, **nada, "salida": False},
        "choque": {"codigo": 1, "salida": False, "fila": [3], "nuevos": nada},
        "salida_en_repo": {"codigo": 2, "archivo": False, "nuevos": nada},
    }, f"OP5: {observado}"


# =============================================================================
# OP6 — C21: un perfil previo, creado por M3, sin cuenta
# =============================================================================
def test_op6_perfil_previo_de_m3_recibe_su_cuenta(integ, tmp_path, capsys) -> None:
    """OP6 (C21): el alta no crea otro perfil: la cuenta nace con el id del de M3."""
    tenant = sembrar_institucion(integ, "inst-op6")
    grupo = integ.crear_grupo(tenant, "G6")
    admin = integ.crear_perfil(tenant, rol="admin")
    r = client.post(f"/admin/groups/{grupo}/students", headers=integ.headers(admin),
                    json={"documento_id": "6001", "nombre_completo": "Xime Sintética"})
    if r.status_code != 201:
        raise PruebaRota(f"OP6: M3 no matriculó a X: {r.status_code} {r.text}")
    perfil_m3 = r.json()["profile_id"]

    doble = CuentasFalsas()
    corrida = alta(integ, doble, capsys, slug="inst-op6", salida=tmp_path / "credenciales.csv",
                   csv_=escribir_csv(tmp_path, "x.csv", [
                       ("Xime Sintética", "xime@engrama.test", "6001", "CC", "G6", "estudiante")]))
    observado = {
        "codigo": corrida.codigo,
        "la_cuenta_tiene_el_id_del_perfil_de_m3": [str(i) for i in doble.cuentas] == [perfil_m3],
        "perfiles_con_ese_documento": contar(integ, "profiles where documento_id = '6001'"),
        "ya_estaba": {k: corrida.resumen.get(k) for k in ("perfiles_nuevos", "membresias_nuevas")},
    }
    assert observado == {
        "codigo": 0, "la_cuenta_tiene_el_id_del_perfil_de_m3": True,
        "perfiles_con_ese_documento": 1,
        "ya_estaba": {"perfiles_nuevos": 0, "membresias_nuevas": 0},
    }, f"OP6: {observado}"


# =============================================================================
# OP7 — C22: restablecer
# =============================================================================
def test_op7_restablecer(integ, tmp_path, capsys) -> None:
    """OP7 (C22): clave nueva por la API admin, la bandera vuelve a true y se anota."""
    doble = CuentasFalsas()
    salida = tmp_path / "credenciales.csv"
    _exigir_ok(alta(integ, doble, capsys, slug="inst-op7", salida=salida,
                    csv_=escribir_csv(tmp_path, "cinco.csv", CINCO)), "OP7, el alta")
    poner_bandera(integ, "1003", False)  # Ana ya había cambiado su contraseña
    ana = perfil_de(integ, "1003")

    # Otra institución, con una persona que NO es de inst-op7, y alguien sin cuenta.
    otra = sembrar_institucion(integ, "inst-otra")
    ajeno = integ.crear_perfil(otra, group_code="GZ")
    sin_cuenta = integ.crear_perfil(
        integ.valor("select id from tenants where slug = 'inst-op7'"), group_code="G1")
    doc = {p: str(integ.valor("select documento_id from profiles where id = :p", p=p))
           for p in (ajeno, sin_cuenta)}

    hecho = restablecer(integ, doble, capsys, slug="inst-op7", documento="1003", salida=salida)
    filas = leer_salida(salida)
    tras_restablecer = {"codigo": hecho.codigo,
                        "cambio_la_clave_de_ana": [i for i, _c in doble.cambios] == [ana],
                        "bandera": bandera(integ, "1003"), "filas": len(filas),
                        "la_clave_anotada_es_la_del_doble":
                            bool(doble.cambios) and filas[-1].get("contrasena_temporal")
                            == doble.cambios[-1][1] == doble.cuentas[doble.cambios[-1][0]]["clave"],
                        "clave_en_stdout": any(c in hecho.stdout for c in doble.claves())}

    de_otra = restablecer(integ, doble, capsys, slug="inst-op7", documento=doc[ajeno],
                          salida=salida)
    sin = restablecer(integ, doble, capsys, slug="inst-op7", documento=doc[sin_cuenta],
                      salida=salida)
    observado = {
        "restablecer": tras_restablecer,
        "de_otra_institucion": de_otra.codigo, "sin_cuenta": sin.codigo,
        "cambios_al_final": len(doble.cambios), "filas_al_final": len(leer_salida(salida)),
        "banderas_ajenas": [bandera(integ, doc[ajeno]), bandera(integ, doc[sin_cuenta])],
    }
    assert observado == {
        "restablecer": {"codigo": 0, "cambio_la_clave_de_ana": True, "bandera": True, "filas": 6,
                        "la_clave_anotada_es_la_del_doble": True, "clave_en_stdout": False},
        "de_otra_institucion": 1, "sin_cuenta": 1,
        "cambios_al_final": 1, "filas_al_final": 6, "banderas_ajenas": [False, False],
    }, f"OP7: {observado}"


# =============================================================================
# OP8 — C24: la bandera antes que la cuenta (H-3)
# =============================================================================
TRES: list[Fila] = [
    ("Uno Sintético", "uno@engrama.test", "8001", "CC", "G8", "estudiante"),
    ("Dos Sintética", "dos@engrama.test", "8002", "CC", "G8", "estudiante"),
    ("Tres Sintético", "tres@engrama.test", "8003", "CC", "G8", "estudiante"),
]


def _estado_de(integ: Any, doble: CuentasFalsas, salida: Path) -> dict[str, Any]:
    docs = [f[2] for f in TRES]
    return {
        "con_cuenta": [perfil_de(integ, d) in doble.cuentas for d in docs],
        "banderas": [bandera(integ, d) for d in docs],
        "correos_en_salida": sorted(f.get("correo", "") for f in leer_salida(salida)),
    }


def test_op8_la_bandera_antes_que_la_cuenta(integ, tmp_path, capsys) -> None:
    """OP8 (C24): al entrar a `crear`, la bandera ya está commiteada; un fallo se completa solo."""
    doble = CuentasFalsas(sesiones=integ.Session, fallar_en={"8002"},
                          observador=observar_bandera(integ.Session))
    salida = tmp_path / "credenciales.csv"
    tres = escribir_csv(tmp_path, "tres.csv", TRES)

    primera = alta(integ, doble, capsys, slug="inst-op8", csv_=tres, salida=salida)
    tras_primera = {"codigo": primera.codigo, "visto_al_crear": list(doble.observado),
                    **_estado_de(integ, doble, salida)}

    doble.fallar_en.clear()
    cuentas_antes = len(doble.cuentas)
    segunda = alta(integ, doble, capsys, slug="inst-op8", csv_=tres, salida=salida)
    tras_segunda = {"codigo": segunda.codigo, "cuentas_nuevas": len(doble.cuentas) - cuentas_antes,
                    **_estado_de(integ, doble, salida)}

    observado = {"primera": tras_primera, "segunda": tras_segunda}
    assert observado == {
        "primera": {"codigo": 1, "visto_al_crear": [True, True, True],
                    "con_cuenta": [True, False, True], "banderas": [True, True, True],
                    "correos_en_salida": ["tres@engrama.test", "uno@engrama.test"]},
        "segunda": {"codigo": 0, "cuentas_nuevas": 1,
                    "con_cuenta": [True, True, True], "banderas": [True, True, True],
                    "correos_en_salida": ["dos@engrama.test", "tres@engrama.test",
                                          "uno@engrama.test"]},
    }, f"OP8: {observado}"
