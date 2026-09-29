"""Login del piloto: el backend reconoce al usuario por el `sub` — `docs/ESPEC_login_piloto.md`.

Paso 1 del plan (ESPEC §6): los tests por la API, antes de tocar el código.

  AP1  C1   JWT de otro proyecto -> 401 en `/auth/me` y `GET /challenges/`; control 200.
  AP2  C2   JWT vencido hace 60 s -> 401; control 200.
  AP3  C3   `sub` sin perfil -> 403 `Account has no ENGRAMA profile`, 0 filas nuevas.
  AP4  C4   el choque: `sub[:8]` igual al `documento_id` de otro perfil. Antes del paso 2, 500.
  AP5  C5   perfil sin membresía activa -> 403 `User has no active tenant memberships`.
  AP6  C6   tres instituciones: el `X-Tenant-ID` ajeno da 403, el gid ajeno 404, `xyz` 400.
  AP7  C7   docente en dos instituciones: sin encabezado, la más antigua; con B, B.
  AP8  C8   el nombre de `/auth/me` es el de la membresía (el perfil de M3 lo tiene vacío).
  SP1  C12  `/auth/me` de un estudiante, byte a byte contra `snapshot_me_antes.json`.

AP9 y AP10 (contraseña temporal) llegan en el paso 4, y AP11 vive en
`tests/teachers/test_m3_documento.py`.

AP3, AP4, AP7 y AP8 corrieron en el paso 1 (`b81d373`) con `xfail(strict=True,
raises=AssertionError)`: el hueco se vio por la API. En el paso 2 (`get_profile`,
sin respaldo) AP3 y AP4 dejan el xfail; en el paso 3 (colegio activo y nombre),
AP7 y AP8. Cada uno junta lo que
observa en un dict y lo compara ENTERO con lo esperado, así el rojo muestra de
una vez todas las diferencias. Las claves se leen con `.get()`: un campo que
falta también es `AssertionError`. El cliente usa `raise_server_exceptions=False`,
para que un 500 sea una respuesta y no una excepción (ESPEC §3).

Una siembra rota es `PruebaRota`, no `AssertionError`: no se confunde con el
hueco (ni con el xfail estricto ni con los tramposos). El estado previo se
siembra en la base (ERR-9): cada test depende solo de la ruta que prueba.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.shared.models import Membership, Profile, Tenant
from tests.seguridad.veredictos import PruebaRota, sembrar

from .conftest import make_jwt

pytestmark = pytest.mark.integ
client = TestClient(app, raise_server_exceptions=False)

RUTA_SNAPSHOT = Path(__file__).with_name("snapshot_me_antes.json")

SIN_PERFIL = "Account has no ENGRAMA profile"
SIN_MEMBRESIA = "User has no active tenant memberships"

# =============================================================================
# Siembra y lectura
# =============================================================================
def _perfil(integ: Any, *, nombre: str, documento: str | None = None,
            rol: str = "student") -> UUID:
    """Un perfil SIN membresías (las pone `_membresia`)."""
    pid = uuid4()
    integ._insertar(Profile(id=pid, documento_id=documento or f"doc-{pid.hex[:12]}",
                            full_name=nombre, pin_hash="sintetico", role=rol))
    return pid


def _membresia(integ: Any, perfil: UUID, tenant: UUID, *, rol: str = "student",
               nombre: str | None = None, grupo: str | None = None,
               activa: bool = True) -> None:
    integ._insertar(Membership(tenant_id=tenant, profile_id=perfil, role=rol,
                               group_code=grupo, is_active=activa, full_name=nombre))


def _cuerpo(r: httpx.Response) -> dict[str, Any]:
    """El JSON si es un objeto; si no (un 500 en texto plano, una lista), `{}`."""
    try:
        datos = r.json()
    except ValueError:
        return {}
    return datos if isinstance(datos, dict) else {}


def _estado(r: httpx.Response) -> tuple[int, Any]:
    """(status, detail): lo que distingue un 401, un 403 u otro 403."""
    return r.status_code, _cuerpo(r).get("detail")


def _conteos(integ: Any) -> dict[str, int]:
    return {t: int(integ.valor(f"select count(*) from {t}")) for t in ("profiles", "memberships")}


# =============================================================================
# AP1, AP2 — C1, C2: la firma y el vencimiento (verdes antes y después)
# =============================================================================
def test_ap1_jwt_de_otro_proyecto_da_401(integ) -> None:
    """AP1 (C1): un usuario CON membresía y un token de otro secreto -> 401; control 200."""
    alumno = integ.crear_perfil(integ.crear_tenant())
    ajeno = {"Authorization": f"Bearer {make_jwt(sub=str(alumno), secret='otro-proyecto')}"}
    propio = {"Authorization": f"Bearer {make_jwt(sub=str(alumno))}"}
    for ruta in ("/auth/me", "/challenges/"):
        r = client.get(ruta, headers=ajeno)
        assert r.status_code == 401, f"{ruta} con el token de otro proyecto: {r.status_code}"
        ok = client.get(ruta, headers=propio)  # control: los mismos claims, bien firmados
        assert ok.status_code == 200, f"control {ruta}: {ok.status_code} {ok.text}"


def test_ap2_jwt_vencido_da_401(integ) -> None:
    """AP2 (C2): `exp` = ahora - 60 s, usuario con membresía -> 401; control 200."""
    alumno = integ.crear_perfil(integ.crear_tenant())
    vencido = {"Authorization": f"Bearer {make_jwt(sub=str(alumno), expires_in=-60)}"}
    vigente = {"Authorization": f"Bearer {make_jwt(sub=str(alumno))}"}
    for ruta in ("/auth/me", "/challenges/"):
        r = client.get(ruta, headers=vencido)
        assert r.status_code == 401, f"{ruta} con el token vencido: {r.status_code}"
        ok = client.get(ruta, headers=vigente)
        assert ok.status_code == 200, f"control {ruta}: {ok.status_code} {ok.text}"


# =============================================================================
# AP3, AP4 — C3, C4: un `sub` sin perfil no crea nada
# =============================================================================
def _sin_perfil(integ: Any, sub: str) -> dict[str, Any]:
    """`/auth/me` y `/auth/session` con un `sub` sin perfil; conteos antes y después."""
    antes = _conteos(integ)
    h = {"Authorization": f"Bearer {make_jwt(sub=sub)}"}
    me = _estado(client.get("/auth/me", headers=h))
    session = _estado(client.post("/auth/session", headers=h))
    return {
        "me": me,
        "session": session,
        "filas_nuevas": {t: n - antes[t] for t, n in _conteos(integ).items()},
        "perfil_con_id_sub": int(integ.valor("select count(*) from profiles where id = :p",
                                             p=UUID(sub))),
    }


ESPERADO_SIN_PERFIL = {
    "me": (403, SIN_PERFIL),
    "session": (403, SIN_PERFIL),
    "filas_nuevas": {"profiles": 0, "memberships": 0},
    "perfil_con_id_sub": 0,
}


def test_ap3_sin_perfil_da_403_sin_crear_filas(integ) -> None:
    """AP3 (C3): JWT válido, `sub` sin perfil -> 403 en me y session, 0 filas nuevas.

    Antes del paso 2, el respaldo de desarrollo creaba el perfil stub y respondía el 403 de
    "sin membresía".
    """
    integ.crear_perfil(integ.crear_tenant())  # la base no está vacía
    assert _sin_perfil(integ, str(uuid4())) == ESPERADO_SIN_PERFIL


def test_ap4_choque_de_documento_da_403_no_500(integ) -> None:
    """AP4 (C4): hay un perfil con `documento_id = '12345678'` y llega el `sub` que empieza igual.

    Antes del paso 2, el stub escribía `documento_id = sub[:8]`, violaba el UNIQUE y daba 500.
    """
    otro = _perfil(integ, nombre="Persona Sintética", documento="12345678")
    _membresia(integ, otro, integ.crear_tenant(), nombre="Persona Sintética", grupo="G1")
    sub = "12345678-0000-4000-8000-000000000001"
    if sub.replace("-", "")[:8] != "12345678":
        raise PruebaRota("el sub no reproduce el choque de sub[:8]")
    assert _sin_perfil(integ, sub) == ESPERADO_SIN_PERFIL


# =============================================================================
# AP5 — C5: perfil sin membresía activa (verde antes y después)
# =============================================================================
def test_ap5_sin_membresia_activa_da_403(integ) -> None:
    """AP5 (C5): sin membresías, o con una inactiva -> 403 de "sin membresía"."""
    sin_nada = _perfil(integ, nombre="Sin Membresía")
    inactiva = _perfil(integ, nombre="Con Membresía Inactiva")
    _membresia(integ, inactiva, integ.crear_tenant(), nombre="Con Membresía Inactiva",
               grupo="G1", activa=False)
    for quien, pid in (("sin membresías", sin_nada), ("con una inactiva", inactiva)):
        r = client.get("/auth/me", headers=integ.headers(pid))
        assert _estado(r) == (403, SIN_MEMBRESIA), f"{quien}: {r.status_code} {r.text}"


# =============================================================================
# AP6 — C6: tres instituciones (verde antes y después)
# =============================================================================
def test_ap6_tres_instituciones_aisladas(integ) -> None:
    """AP6 (C6): nadie de A entra a B ni a C, ni por encabezado ni por gid."""
    a, b, c = integ.crear_tenant(), integ.crear_tenant(), integ.crear_tenant()
    integ.crear_grupo(a, "GA")
    grupo_b = integ.crear_grupo(b, "GB")
    alumno = integ.crear_perfil(a, group_code="GA")
    docente = integ.crear_perfil(a, rol="teacher")
    admin = integ.crear_perfil(a, rol="admin")

    def h(pid: UUID, tenant: Any) -> dict[str, str]:
        return {**integ.headers(pid), "X-Tenant-ID": str(tenant)}

    # Controles: con su propio colegio, sí entran.
    assert client.get("/auth/me", headers=h(alumno, a)).status_code == 200
    assert client.get("/teachers/groups", headers=h(docente, a)).status_code == 200

    for ruta in ("/auth/me", "/challenges/"):
        for nombre, ajeno in (("B", b), ("C", c)):
            r = client.get(ruta, headers=h(alumno, ajeno))
            assert r.status_code == 403, f"estudiante de A en {ruta} con {nombre}: {r.status_code}"

    r = client.get("/teachers/groups", headers=h(docente, b))
    assert r.status_code == 403, f"docente de A con B: {r.status_code}"

    r = client.post("/admin/groups", headers=h(admin, c), json={"group_code": "GX"})
    assert r.status_code == 403, f"admin de A crea grupo en C: {r.status_code}"
    assert integ.valor("select count(*) from groups where tenant_id = :t", t=c) == 0

    en_b = integ.valor("select count(*) from memberships where tenant_id = :t", t=b)
    r = client.post(f"/admin/groups/{grupo_b}/students", headers=integ.headers(admin),
                    json={"documento_id": "SINT-LP-0601", "nombre_completo": "Intruso"})
    assert r.status_code == 404, f"admin de A matricula en un grupo de B: {r.status_code}"
    assert integ.valor("select count(*) from memberships where tenant_id = :t", t=b) == en_b

    r = client.get("/auth/me", headers=h(alumno, "xyz"))
    assert r.status_code == 400, f"X-Tenant-ID: xyz -> {r.status_code}"


# =============================================================================
# AP7 — C7: el docente de dos instituciones
# =============================================================================
def test_ap7_docente_en_dos_instituciones(integ) -> None:
    """AP7 (C7): sin encabezado, la membresía más antigua (A); con B, B; con C, 403.

    B se inserta ANTES que A y A se fecha un día atrás por SQL: el orden
    físico (B, A) no coincide con el cronológico (A, B). Antes del paso 3,
    `get_memberships` no tenía ORDER BY y `/auth/me` no decía qué colegio
    quedó activo.
    """
    a, b, c = integ.crear_tenant(), integ.crear_tenant(), integ.crear_tenant()
    d = _perfil(integ, nombre="Nombre del Perfil", rol="teacher")
    _membresia(integ, d, b, rol="teacher", nombre="Profe Beta")   # B primero
    _membresia(integ, d, a, rol="teacher", nombre="Profe Alfa")
    sembrar(integ, "update memberships set created_at = now() "
                   "where profile_id = :p and tenant_id = :t", p=d, t=b)
    sembrar(integ, "update memberships set created_at = now() - interval '1 day' "
                   "where profile_id = :p and tenant_id = :t", p=d, t=a)
    if integ.valor("select count(*) from memberships where profile_id = :p "
                   "and created_at < now() - interval '23 hours'", p=d) != 1:
        raise PruebaRota("AP7: A no quedó un día atrás")

    def ver(tenant: UUID | None) -> tuple[int, Any, Any]:
        h = integ.headers(d)
        if tenant is not None:
            h["X-Tenant-ID"] = str(tenant)
        r = client.get("/auth/me", headers=h)
        cuerpo = _cuerpo(r)
        return r.status_code, cuerpo.get("active_tenant_id"), cuerpo.get("full_name")

    cuerpo = _cuerpo(client.get("/auth/me", headers=integ.headers(d)))
    observado = {
        "sin_encabezado": [ver(None) for _ in range(3)],
        "con_B": ver(b),
        "memberships": [(m.get("tenant_id"), m.get("full_name"))
                        for m in cuerpo.get("memberships", [])],
        "con_C": ver(c)[0],
    }
    assert observado == {
        "sin_encabezado": [(200, str(a), "Profe Alfa")] * 3,
        "con_B": (200, str(b), "Profe Beta"),
        "memberships": [(str(a), "Profe Alfa"), (str(b), "Profe Beta")],
        "con_C": 403,
    }


# =============================================================================
# AP8 — C8: el nombre sale de la membresía
# =============================================================================
def test_ap8_nombre_de_la_membresia(integ) -> None:
    """AP8 (C8): perfil como lo deja M3 (`full_name = ''`) y membresía "Ana Sintética"."""
    tenant = integ.crear_tenant()
    alumno = _perfil(integ, nombre="")
    _membresia(integ, alumno, tenant, nombre="Ana Sintética", grupo="G1")
    r = client.get("/auth/me", headers=integ.headers(alumno))
    cuerpo = _cuerpo(r)
    observado = {
        "status": r.status_code,
        "full_name": cuerpo.get("full_name"),
        "memberships": [m.get("full_name") for m in cuerpo.get("memberships", [])],
    }
    assert observado == {"status": 200, "full_name": "Ana Sintética",
                         "memberships": ["Ana Sintética"]}


# =============================================================================
# SP1 — C12: identidad de `/auth/me` para el caso de siempre
# =============================================================================
# Las claves que agrega esta espec (§1.4); SP1 las quita antes de comparar.
CLAVES_NUEVAS_RAIZ = ("active_tenant_id", "must_change_password")
CLAVES_NUEVAS_MEMBRESIA = ("full_name",)


def _canonico(datos: Any) -> str:
    """El JSON como lo escribe `JSONResponse` de Starlette (compacto, sin escapar)."""
    return json.dumps(datos, ensure_ascii=False, allow_nan=False, indent=None,
                      separators=(",", ":"))


def capturar_sp1(integ: Any) -> str:
    """Un estudiante con una sola membresía, todo con valores fijos; `/auth/me` normalizado.

    Tenant, documento y nombre son fijos (las fábricas usan hex al azar). El
    nombre es el mismo en el perfil y en la membresía, como en `crear_perfil`.
    Ids por posición: el perfil es `P1` y el tenant `T1`. Las claves nuevas
    (§1.4) se quitan y el resto se re-escribe en la forma canónica, que es
    byte a byte la cruda (lo exige el arnés).
    """
    tenant = uuid4()
    integ._insertar(Tenant(id=tenant, name="Institución Sintética SP1", slug="inst-sp1",
                           coin_pool=1000))
    alumno = _perfil(integ, nombre="Sara Sintética", documento="SINT-LP-0001")
    _membresia(integ, alumno, tenant, nombre="Sara Sintética", grupo="G1")

    r = client.get("/auth/me", headers=integ.headers(alumno))
    if r.status_code != 200:
        raise PruebaRota(f"SP1: /auth/me dio {r.status_code}: {r.text}")
    crudo = r.text.replace(str(alumno), "P1").replace(str(tenant), "T1")
    datos = json.loads(crudo)
    if _canonico(datos) != crudo:
        raise PruebaRota("SP1: la forma canónica no es la respuesta cruda")
    for clave in CLAVES_NUEVAS_RAIZ:
        datos.pop(clave, None)
    for m in datos.get("memberships", []):
        for clave in CLAVES_NUEVAS_MEMBRESIA:
            m.pop(clave, None)
    return _canonico(datos)


def test_sp1_auth_me_identico_al_snapshot(integ) -> None:
    """SP1 (C12): `/auth/me` byte a byte contra `snapshot_me_antes.json` (paso 1, `c9fd7d3`)."""
    congelado = json.loads(RUTA_SNAPSHOT.read_text(encoding="utf-8"))
    assert capturar_sp1(integ) == congelado["me"], "/auth/me cambió para el caso de siempre"
