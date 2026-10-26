"""PA2 a PA10: el pase acotado, por HTTP y contra la base real — `docs/ESPEC_pase_acotado.md` §3.

Cada test arma un `observado` y lo compara ENTERO con lo esperado: un tramposo
(`tests/tramposos/test_tramposos_pase.py`) lo pone rojo y el mensaje dice qué
cambió. Las funciones del servicio se llaman por el módulo (`pase_service.f`)
para que el tramposo que las reemplaza las alcance. Todo es sintético.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from src.anillo import service as pase_service
from src.main import app
from src.shared.models import Membership, TeacherGroup
from tests.integ_ayudante import Integ
from tests.seguridad.veredictos import sembrar
from tests.teachers.test_access import guardia

pytestmark = pytest.mark.integ
client = TestClient(app, raise_server_exceptions=False)

FORMA = re.compile(r"pa1_[A-Za-z0-9_-]{43}")
INVALIDO = (401, "pase_invalido")
# Lo único que el carné trae (§1.3). Ni documento_id, ni xp, ni level, ni rachas.
CLAVES_DEL_CARNE = ["active_tenant_id", "audiencia", "consent_version", "full_name", "grupos_docente",
                    "id", "is_active", "memberships", "must_change_password"]


# =============================================================================
# Ayudas
# =============================================================================
def emitir(integ: Integ, perfil: UUID, audiencia: str, tenant: UUID | None = None) -> Any:
    headers = integ.headers(perfil)
    if tenant is not None:
        headers["X-Tenant-ID"] = str(tenant)
    return client.post("/anillo/pases", headers=headers, json={"audiencia": audiencia})


def pase_de(integ: Integ, perfil: UUID, audiencia: str, tenant: UUID | None = None) -> str:
    r = emitir(integ, perfil, audiencia, tenant)
    assert r.status_code == 201, f"no se pudo emitir el pase de la prueba: {r.status_code} {r.text}"
    return str(r.json()["pase"])


def canjear(pase: str, audiencia: str) -> Any:
    return client.post("/anillo/canje", json={"pase": pase, "audiencia": audiencia})


def detalle(r: Any) -> tuple[int, Any]:
    try:
        cuerpo = r.json()
    except ValueError:
        cuerpo = None
    return r.status_code, cuerpo.get("detail") if isinstance(cuerpo, dict) else None


def sha(pase: str) -> str:
    return hashlib.sha256(pase.encode("utf-8")).hexdigest()


def usado(integ: Integ, pase: str) -> bool | None:
    """¿Está gastado? `None` si no hay fila con esa huella."""
    fila = integ.fila("select usado_en is not null as usado from anillo_pases where hash = :h",
                      h=sha(pase))
    return None if fila is None else bool(fila["usado"])


def estudiante_en_dos(integ: Integ) -> tuple[UUID, UUID, UUID]:
    """Una estudiante en A (la más antigua, la institución por defecto) y en B."""
    a, b = integ.crear_tenant(), integ.crear_tenant()
    est = integ.crear_perfil(a, group_code="G-A", creada_hace=timedelta(days=2))
    integ._insertar(Membership(tenant_id=b, profile_id=est, role="student", group_code="G-B",
                               is_active=True, full_name="Nombre en B"))
    return est, a, b


def docente_con_grupos(integ: Integ) -> tuple[UUID, UUID]:
    """Una docente con G-2 y G-1 asignados y G-3 (de su institución) sin asignar."""
    t = integ.crear_tenant()
    profe = integ.crear_perfil(t, rol="teacher")
    for codigo, suyo in (("G-2", True), ("G-3", False), ("G-1", True)):
        grupo = integ.crear_grupo(t, codigo)
        if suyo:
            integ._insertar(TeacherGroup(tenant_id=t, teacher_id=profe, group_id=grupo))
    return profe, t


# =============================================================================
# PA2 · Emitir
# =============================================================================
def test_pa2_emitir(integ) -> None:
    est, _a, b = estudiante_en_dos(integ)
    r = emitir(integ, est, "set", tenant=b)
    cuerpo = r.json() if r.status_code == 201 else {}
    pase = str(cuerpo.get("pase", ""))
    filas = integ.valor("select count(*) from anillo_pases")
    fila = integ.fila(
        "select hash, profile_id, tenant_id, audiencia, usado_en, "
        "extract(epoch from expira_en - creado_en)::int as vida, row_to_json(p)::text as todo "
        "from anillo_pases p") or {}
    todo = str(fila.get("todo", ""))
    observado = {
        "status": r.status_code,
        "claves": sorted(cuerpo),
        "audiencia": cuerpo.get("audiencia"),
        "expira_en_s": cuerpo.get("expira_en_s"),
        "no_store": r.headers.get("cache-control"),
        "forma": FORMA.fullmatch(pase) is not None,
        "filas": filas,
        "hash_es_sha256_del_pase": fila.get("hash") == sha(pase),
        "de_quien_y_donde": (fila.get("profile_id") == est, fila.get("tenant_id") == b),
        "audiencia_en_la_base": fila.get("audiencia"),
        "vida_s": fila.get("vida"),
        "sin_usar": fila.get("usado_en") is None,
        "el_pase_en_la_base": bool(pase) and (pase in todo or pase[len("pa1_"):] in todo),
    }
    assert observado == {
        "status": 201, "claves": ["audiencia", "expira_en_s", "pase"], "audiencia": "set",
        "expira_en_s": 300, "no_store": "no-store", "forma": True, "filas": 1,
        "hash_es_sha256_del_pase": True, "de_quien_y_donde": (True, True),
        "audiencia_en_la_base": "set", "vida_s": 300, "sin_usar": True,
        "el_pase_en_la_base": False,
    }, f"PA2: {observado}"


# =============================================================================
# PA3 · El carné mínimo
# =============================================================================
def test_pa3_canjear_da_el_carne_minimo(integ) -> None:
    est, _a, b = estudiante_en_dos(integ)
    r = canjear(pase_de(integ, est, "set", tenant=b), "set")
    carne = r.json() if r.status_code == 200 else {}
    profe, t = docente_con_grupos(integ)
    admin = integ.crear_perfil(t, rol="admin")
    del_profe_set = canjear(pase_de(integ, profe, "set"), "set").json()
    del_profe_eva = canjear(pase_de(integ, profe, "eva"), "eva").json()
    del_admin_set = canjear(pase_de(integ, admin, "set"), "set").json()
    observado = {
        "status": r.status_code,
        "no_store": r.headers.get("cache-control"),
        "claves": sorted(carne),
        "id": carne.get("id") == str(est),
        "activa_la_del_pase": carne.get("active_tenant_id") == str(b),
        "membresias": [(m.get("tenant_id") == str(b), m.get("role"), m.get("group_code"))
                       for m in carne.get("memberships", [])],
        "nombre": carne.get("full_name"),
        "estado": (carne.get("is_active"), carne.get("must_change_password"),
                   carne.get("consent_version")),
        "audiencia": carne.get("audiencia"),
        "grupos": {"estudiante_set": carne.get("grupos_docente", "falta"),
                   "docente_set": del_profe_set.get("grupos_docente", "falta"),
                   "docente_eva": del_profe_eva.get("grupos_docente", "falta"),
                   "admin_set": del_admin_set.get("grupos_docente", "falta")},
    }
    assert observado == {
        "status": 200, "no_store": "no-store", "claves": CLAVES_DEL_CARNE, "id": True,
        "activa_la_del_pase": True, "membresias": [(True, "student", "G-B")],
        "nombre": "Nombre en B", "estado": (True, False, None), "audiencia": "set",
        "grupos": {"estudiante_set": None, "docente_set": ["G-1", "G-2"],
                   "docente_eva": None, "admin_set": None},
    }, f"PA3: {observado}"


# =============================================================================
# PA4 · Un solo uso
# =============================================================================
def test_pa4_un_solo_uso(integ) -> None:
    est = integ.crear_perfil(integ.crear_tenant())
    pase = pase_de(integ, est, "eva")
    primero = canjear(pase, "eva").status_code
    segundo = detalle(canjear(pase, "eva"))
    observado = {"primero": primero, "segundo": segundo, "gastado": usado(integ, pase)}
    assert observado == {"primero": 200, "segundo": INVALIDO, "gastado": True}, f"PA4: {observado}"


# =============================================================================
# PA5 · Audiencia
# =============================================================================
def test_pa5_audiencia(integ) -> None:
    est = integ.crear_perfil(integ.crear_tenant())
    pase = pase_de(integ, est, "eva")
    cruzado = detalle(canjear(pase, "set"))
    despues = detalle(canjear(pase, "eva"))
    control = canjear(pase_de(integ, est, "eva"), "eva").status_code  # el canje SÍ funciona
    observado = {"cruzado": cruzado, "despues_en_su_audiencia": despues, "control": control}
    assert observado == {"cruzado": INVALIDO, "despues_en_su_audiencia": INVALIDO,
                         "control": 200}, f"PA5: {observado}"


# =============================================================================
# PA6 · Vencido
# =============================================================================
def test_pa6_vencido(integ) -> None:
    est = integ.crear_perfil(integ.crear_tenant())
    pase = pase_de(integ, est, "set")
    sembrar(integ, "update anillo_pases set expira_en = now() - interval '1 second' "
                   "where hash = :h", h=sha(pase))
    vencido = detalle(canjear(pase, "set"))
    control = canjear(pase_de(integ, est, "set"), "set").status_code
    observado = {"vencido": vencido, "control": control}
    assert observado == {"vencido": INVALIDO, "control": 200}, f"PA6: {observado}"


# =============================================================================
# PA7 · Las revisiones de la cuenta, y el primer intento gasta el pase
# =============================================================================
def _revisar_y_reparar(integ: Integ, perfil: UUID, romper: str, reparar: str,
                       tenant: UUID | None = None, **params: Any) -> dict[str, Any]:
    pase = pase_de(integ, perfil, "eva", tenant)
    sembrar(integ, romper, p=perfil, **params)
    primero = detalle(canjear(pase, "eva"))
    sembrar(integ, reparar, p=perfil, **params)
    return {"primero": primero, "reparada_el_mismo_pase": detalle(canjear(pase, "eva")),
            "reparada_uno_nuevo": canjear(pase_de(integ, perfil, "eva", tenant), "eva").status_code}


def test_pa7_revisiones_de_la_cuenta_y_el_gasto(integ) -> None:
    t = integ.crear_tenant()
    suspendida = integ.crear_perfil(t)
    temporal = integ.crear_perfil(t)
    profe = integ.crear_perfil(t, rol="teacher", creada_hace=timedelta(days=2))
    otra = integ.crear_tenant()
    integ.afiliar(profe, otra, rol="teacher")
    observado = {
        "suspendida": _revisar_y_reparar(
            integ, suspendida, "update profiles set is_active = false where id = :p",
            "update profiles set is_active = true where id = :p"),
        "contrasena_temporal": _revisar_y_reparar(
            integ, temporal, "update profiles set force_password_reset = true where id = :p",
            "update profiles set force_password_reset = false where id = :p"),
        "sin_membresia_en_la_del_pase": _revisar_y_reparar(
            integ, profe,
            "update memberships set is_active = false where profile_id = :p and tenant_id = :t",
            "update memberships set is_active = true where profile_id = :p and tenant_id = :t",
            tenant=otra, t=otra),
    }
    def esperado(detail: str) -> dict[str, Any]:
        return {"primero": (403, detail), "reparada_el_mismo_pase": INVALIDO,
                "reparada_uno_nuevo": 200}
    assert observado == {
        "suspendida": esperado("account_suspended"),
        "contrasena_temporal": esperado("must_change_password"),
        "sin_membresia_en_la_del_pase": esperado("User is not a member of the requested tenant"),
    }, f"PA7: {observado}"


# =============================================================================
# PA8 · El pase no sirve para nada más
# =============================================================================
def rutas_no_publicas() -> list[tuple[str, str]]:
    return sorted({(r.path, m) for r in app.routes if isinstance(r, APIRoute)
                   and guardia(r) != "public" for m in r.methods})


def _llamar(ruta: str, metodo: str, headers: dict[str, str]) -> int:
    url = re.sub(r"\{[^}]+\}", "11111111-1111-4111-8111-111111111111", ruta)
    return client.request(metodo, url, headers=headers).status_code


def test_pa8_el_pase_no_sirve_para_nada_mas(integ) -> None:
    t = integ.crear_tenant()
    profe = integ.crear_perfil(t, rol="admin")  # admin: la guarda más amplia
    pase = pase_de(integ, profe, "eva")
    rutas = rutas_no_publicas()
    respuestas = {f"{m} {p}": _llamar(p, m, {"Authorization": f"Bearer {pase}"}) for p, m in rutas}
    como_bearer = {ruta: s for ruta, s in respuestas.items() if s != 401}
    sin_gastar = usado(integ, pase) is False
    token_de_sesion = integ.headers(profe)["Authorization"].removeprefix("Bearer ")
    observado = {
        "rutas_medidas": len(rutas) >= 40,
        "no_dieron_401": como_bearer,
        "sigue_sin_gastar": sin_gastar,
        "y_canjea": canjear(pase, "eva").status_code,
        "el_token_de_sesion_en_el_canje": detalle(canjear(token_de_sesion, "eva")),
    }
    assert observado == {"rutas_medidas": True, "no_dieron_401": {}, "sigue_sin_gastar": True,
                         "y_canjea": 200, "el_token_de_sesion_en_el_canje": INVALIDO,
                         }, f"PA8: {observado}"


# =============================================================================
# PA9 · Tope de pases vivos
# =============================================================================
def test_pa9_tope_de_pases_vivos(integ) -> None:
    est = integ.crear_perfil(integ.crear_tenant())
    primeros = [emitir(integ, est, "eva") for _ in range(10)]
    once = emitir(integ, est, "eva")
    filas_tras_el_429 = integ.valor("select count(*) from anillo_pases")
    canjear(primeros[0].json()["pase"], "eva")  # uno gastado deja de contar
    tras_gastar = emitir(integ, est, "eva").status_code
    sembrar(integ, "update anillo_pases set expira_en = now() - interval '1 second' "
                   "where hash = :h", h=sha(primeros[1].json()["pase"]))  # y uno vencido
    tras_vencer = emitir(integ, est, "eva").status_code
    observado = {"los_10": [r.status_code for r in primeros], "el_11": detalle(once),
                 "filas_tras_el_429": filas_tras_el_429, "tras_gastar_uno": tras_gastar,
                 "tras_vencer_uno": tras_vencer}
    assert observado == {"los_10": [201] * 10, "el_11": (429, "demasiados_pases"),
                         "filas_tras_el_429": 10, "tras_gastar_uno": 201,
                         "tras_vencer_uno": 201}, f"PA9: {observado}"


# =============================================================================
# PA10 · Dos canjes a la vez
# =============================================================================
def test_pa10_dos_canjes_a_la_vez(integ) -> None:
    est = integ.crear_perfil(integ.crear_tenant())
    pase = pase_de(integ, est, "eva")

    async def uno() -> str:
        async with integ.Session() as db:
            try:
                await pase_service.gastar(db, pase, "eva")
            except HTTPException as e:
                return str(e.status_code)
            return "gastado"

    async def ambos() -> list[str]:
        return list(await asyncio.gather(uno(), uno()))

    observado = {"resultados": sorted(integ.run(ambos())), "gastado": usado(integ, pase)}
    assert observado == {"resultados": ["401", "gastado"], "gastado": True}, f"PA10: {observado}"
