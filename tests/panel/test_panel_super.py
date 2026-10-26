"""PS1-PS7, AM1-AM4 y RO1 — docs/ESPEC_panel_super_admin.md §2. Contra Postgres real.

Cada test siembra A y B (`_siembra.py`) con el reloj del panel fijo y compara las
cifras EXACTAS. Los mensajes de cada `assert` empiezan con su id: los tramposos
(`tests/tramposos/test_tramposos_panel_super.py`) los buscan.
"""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.panel import ventanas
from src.shared.config import settings
from tests.panel import _siembra as sb

pytestmark = pytest.mark.integ
client = TestClient(app)


def _con_tenant(integ: Any, pid: Any, tid: Any) -> dict[str, str]:
    return {**integ.headers(pid), "X-Tenant-ID": str(tid)}


def _cliente(cuerpo: dict[str, Any], tid: Any) -> dict[str, Any]:
    return next(c for c in cuerpo["clientes"] if c["id"] == str(tid))


def test_ps1_super_ve_todos_los_clientes_con_sus_cifras(integ, monkeypatch) -> None:
    s, a, b = sb.sembrar(integ, monkeypatch)
    sup = sb.super_admin(s)
    r = client.get("/super/clientes", headers=integ.headers(sup))
    assert r.status_code == 200, f"PS1: {r.status_code} {r.text}"
    cuerpo = r.json()
    ca, cb = _cliente(cuerpo, a.id), _cliente(cuerpo, b.id)
    vistos = {"A": ca["metricas"], "B": cb["metricas"]}
    assert vistos == {"A": sb.ESPERADO_A, "B": sb.ESPERADO_B}, f"PS1: {vistos}"
    # Códigos neutros por fecha de creación (A nació antes) y la etiqueta privada.
    assert (ca["codigo"], cb["codigo"], ca["etiqueta"], cb["etiqueta"]) == (
        "Cliente 01", "Cliente 02", sb.NOMBRE_A, sb.NOMBRE_B), f"PS1: {ca} {cb}"
    esperado_total = {
        k: sb.ESPERADO_A[k] + sb.ESPERADO_B[k] for k in sb.ESPERADO_A if k != "monedas"
    } | {"monedas": {k: sb.ESPERADO_A["monedas"][k] + sb.ESPERADO_B["monedas"][k]
                     for k in sb.ESPERADO_A["monedas"]}}
    assert cuerpo["totales"] == esperado_total, f"PS1 totales: {cuerpo['totales']}"
    assert len(cuerpo["registros_por_dia"]) == 30 and len(cuerpo["monedas_por_semana"]) == 8
    assert sum(d["n"] for d in cuerpo["registros_por_dia"]) == 7, "PS1: registros globales"


def test_ps2_solo_el_super_admin_entra(integ, monkeypatch) -> None:
    s, a, _b = sb.sembrar(integ, monkeypatch)
    p = a.personas
    vistos: dict[str, list[int]] = {}
    for quien in ("admin", "p1", "s1"):
        h = _con_tenant(integ, p[quien], a.id)
        vistos[quien] = [client.get("/super/clientes", headers=h).status_code,
                         client.get(f"/super/clientes/{a.id}", headers=h).status_code]
    vistos["sin_token"] = [client.get("/super/clientes").status_code,
                           client.get(f"/super/clientes/{a.id}").status_code]
    esperado = {"admin": [403, 403], "p1": [403, 403], "s1": [403, 403], "sin_token": [401, 401]}
    assert vistos == esperado, f"PS2: {vistos}"


def test_ps3_super_suspendido_o_con_clave_temporal_no_entra(integ, monkeypatch) -> None:
    s, _a, _b = sb.sembrar(integ, monkeypatch)
    suspendido = sb.super_admin(s, activo=False)
    temporal = sb.super_admin(s, temporal=True)
    r1 = client.get("/super/clientes", headers=integ.headers(suspendido))
    r2 = client.get("/super/clientes", headers=integ.headers(temporal))
    vistos = {"suspendido": (r1.status_code, r1.json().get("detail")),
              "temporal": (r2.status_code, r2.json().get("detail"))}
    assert vistos == {"suspendido": (403, "account_suspended"),
                      "temporal": (403, "must_change_password")}, f"PS3: {vistos}"


def test_ps4_detalle_de_un_cliente(integ, monkeypatch) -> None:
    s, a, _b = sb.sembrar(integ, monkeypatch)
    h = integ.headers(sb.super_admin(s))
    r = client.get(f"/super/clientes/{a.id}", headers=h)
    assert r.status_code == 200, f"PS4: {r.text}"
    d = r.json()
    assert (d["codigo"], d["etiqueta"], d["metricas"]) == ("Cliente 01", sb.NOMBRE_A,
                                                           sb.ESPERADO_A), f"PS4: {d}"
    assert len(d["registros_por_dia"]) == 30 and len(d["monedas_por_semana"]) == 8, "PS4 series"
    vistos = (client.get(f"/super/clientes/{uuid4()}", headers=h).status_code,
              client.get("/super/clientes/no-es-uuid", headers=h).status_code)
    assert vistos == (404, 422), f"PS4: {vistos}"


def test_ps5_registros_por_dia_30_dias_locales_hasta_hoy(integ, monkeypatch) -> None:
    s, a, _b = sb.sembrar(integ, monkeypatch)
    d = client.get(f"/super/clientes/{a.id}", headers=integ.headers(sb.super_admin(s))).json()
    dias = d["registros_por_dia"]
    hoy = sb.hoy_local(s.ahora)
    fechas = [x["dia"] for x in dias]
    esperadas = [(hoy - timedelta(days=29 - i)).isoformat() for i in range(30)]
    por_dia = {x["dia"]: x["n"] for x in dias if x["n"]}
    esperado = {(hoy - timedelta(days=k)).isoformat(): 1 for k in (0, 2, 5, 29)}
    vistos = {"fechas_ok": fechas == esperadas, "por_dia": por_dia,
              "total": d["metricas"]["registros_30d"]}
    assert vistos == {"fechas_ok": True, "por_dia": esperado, "total": 4}, f"PS5: {vistos}"


def test_ps6_activos_7d_por_tenant_y_ventana(integ, monkeypatch) -> None:
    s, a, b = sb.sembrar(integ, monkeypatch)
    cuerpo = client.get("/super/clientes", headers=integ.headers(sb.super_admin(s))).json()
    vistos = {"A": _cliente(cuerpo, a.id)["metricas"]["activos_7d"],
              "B": _cliente(cuerpo, b.id)["metricas"]["activos_7d"]}
    assert vistos == {"A": 3, "B": 1}, f"PS6: {vistos}"


def _semana_de(s: sb.Sembrador, hace: timedelta) -> str:
    dia = ventanas.hoy_local(s.ahora - hace, settings.engrama_utc_offset_hours)
    return ventanas.lunes_de(dia).isoformat()


def test_ps7_monedas_por_direccion(integ, monkeypatch) -> None:
    s, a, _b = sb.sembrar(integ, monkeypatch)
    d = client.get(f"/super/clientes/{a.id}", headers=integ.headers(sb.super_admin(s))).json()
    semanas = {x["semana"]: (x["emitidas"], x["gastadas"])
               for x in d["monedas_por_semana"] if x["emitidas"] or x["gastadas"]}
    esperado_semanas: dict[str, tuple[int, int]] = {}
    for hace, e, g in ((timedelta(minutes=1), 38, 15), (timedelta(days=21), 10, 0)):
        clave = _semana_de(s, hace)
        pe, pg = esperado_semanas.get(clave, (0, 0))
        esperado_semanas[clave] = (pe + e, pg + g)
    vistos = {"monedas": d["metricas"]["monedas"], "semanas": semanas}
    assert vistos == {"monedas": sb.ESPERADO_A["monedas"], "semanas": esperado_semanas}, (
        f"PS7: {vistos}")


def test_am1_el_admin_ve_solo_su_institucion(integ, monkeypatch) -> None:
    s, a, b = sb.sembrar(integ, monkeypatch)
    vistos: dict[str, Any] = {}
    for nombre, c in (("A", a), ("B", b)):
        r = client.get("/admin/metricas", headers=integ.headers(c.personas["admin"]))
        assert r.status_code == 200, f"AM1: {nombre} {r.status_code} {r.text}"
        vistos[nombre] = r.json()["metricas"]
    assert vistos == {"A": sb.ESPERADO_A, "B": sb.ESPERADO_B}, f"AM1: {vistos}"
    sup = client.get(f"/super/clientes/{a.id}", headers=integ.headers(sb.super_admin(s))).json()
    adm = client.get("/admin/metricas", headers=integ.headers(a.personas["admin"])).json()
    iguales = {k: sup[k] == adm[k] for k in ("metricas", "registros_por_dia", "monedas_por_semana")}
    assert all(iguales.values()), f"AM1: el admin y el super no coinciden en A: {iguales}"


def test_am2_admin_no_puede_pedir_otro_tenant(integ, monkeypatch) -> None:
    s, a, b = sb.sembrar(integ, monkeypatch)
    ajeno = client.get("/admin/metricas", headers=_con_tenant(integ, a.personas["admin"], b.id))
    # El admin de A también es profe en B: en B su rol es profe, no admin.
    integ.afiliar(a.personas["admin"], b.id, "teacher")
    como_profe = client.get("/admin/metricas",
                            headers=_con_tenant(integ, a.personas["admin"], b.id))
    vistos = (ajeno.status_code, como_profe.status_code)
    assert vistos == (403, 403), f"AM2: {vistos}"


def test_am3_profe_y_estudiante_no_ven_metricas(integ, monkeypatch) -> None:
    _s, a, _b = sb.sembrar(integ, monkeypatch)
    vistos = [client.get("/admin/metricas", headers=integ.headers(a.personas[q])).status_code
              for q in ("p1", "s1")]
    assert vistos == [403, 403], f"AM3: {vistos}"


def test_am4_la_respuesta_del_admin_no_trae_nombre(integ, monkeypatch) -> None:
    _s, a, b = sb.sembrar(integ, monkeypatch)
    r = client.get("/admin/metricas", headers=integ.headers(a.personas["admin"]))
    texto = r.text
    prohibidos = {"etiqueta", "codigo", "slug", "id", "nombre", "name"}
    claves = set(r.json()) if r.status_code == 200 else set()
    filtrado = {
        "status": r.status_code,
        "claves_prohibidas": sorted(claves & prohibidos),
        "nombre_a": sb.NOMBRE_A in texto, "nombre_b": sb.NOMBRE_B in texto,
        "id_a": str(a.id) in texto, "id_b": str(b.id) in texto,
    }
    assert filtrado == {"status": 200, "claves_prohibidas": [], "nombre_a": False,
                        "nombre_b": False, "id_a": False, "id_b": False}, f"AM4: {filtrado}"
    assert set(json.loads(texto)) == {"hoy", "metricas", "registros_por_dia",
                                      "monedas_por_semana"}, f"AM4: {sorted(claves)}"


def test_h4_las_tres_rutas_no_se_guardan_en_cache(integ, monkeypatch) -> None:
    """H-4: `Cache-Control: no-store` en las tres respuestas del panel."""
    s, a, _b = sb.sembrar(integ, monkeypatch)
    sup = integ.headers(sb.super_admin(s))
    vistos = {
        "lista": client.get("/super/clientes", headers=sup).headers.get("cache-control"),
        "detalle": client.get(f"/super/clientes/{a.id}", headers=sup).headers.get("cache-control"),
        "admin": client.get("/admin/metricas",
                            headers=integ.headers(a.personas["admin"])).headers.get("cache-control"),
    }
    assert vistos == {"lista": "no-store", "detalle": "no-store", "admin": "no-store"}, f"H4: {vistos}"


_FOTO = """
select (select count(*) from tenants) t, (select count(*) from memberships) m,
       (select count(*) from profiles) p, (select count(*) from coin_ledger) l,
       (select coalesce(sum(balance), 0) from coin_wallets) w,
       (select max(updated_at) from coin_wallets) wu, (select max(updated_at) from tenants) tu,
       (select max(updated_at) from profiles) pu
"""


def test_ro1_las_rutas_no_escriben(integ, monkeypatch) -> None:
    s, a, _b = sb.sembrar(integ, monkeypatch)
    sup = sb.super_admin(s)
    antes = integ.fila(_FOTO)
    client.get("/super/clientes", headers=integ.headers(sup))
    client.get(f"/super/clientes/{a.id}", headers=integ.headers(sup))
    client.get("/admin/metricas", headers=integ.headers(a.personas["admin"]))
    assert integ.fila(_FOTO) == antes, "RO1: el panel cambió la base"
