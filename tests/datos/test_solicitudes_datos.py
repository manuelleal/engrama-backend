"""Solicitudes sobre datos personales (Ley 1581) — `docs/ESPEC_solicitud_datos.md`.

  SD1  C1  crear y ver: `abierta`, la persona del token, la institución activa, la fecha del servidor.
  SD2  C2  nadie lee ni crea por otro.
  SD3  C3  tipo inventado o mensaje de 1001: 422 y nada escrito.
  SD4  C4  a lo sumo 5 sin cerrar por persona.
  SD5  C5  el admin, solo su institución, y con traza de quién y cuándo.
  SD6  C6  con contraseña temporal no; sin consentimiento sí; responder NO ejecuta nada.

Reglas (las del login piloto): el cliente con `raise_server_exceptions=False`
(un 500 es una respuesta, y por tanto un `AssertionError`), las claves con
`.get()`, y lo observado en un dict que se compara ENTERO y va en el mensaje.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.seguridad.veredictos import sembrar

pytestmark = pytest.mark.integ
client = TestClient(app, raise_server_exceptions=False)

RUTA = "/auth/solicitudes-datos"
RUTA_ADMIN = "/admin/solicitudes-datos"


def _json(r: httpx.Response) -> Any:
    try:
        return r.json()
    except ValueError:
        return None


def campo(r: httpx.Response, clave: str) -> Any:
    datos = _json(r)
    return datos.get(clave) if isinstance(datos, dict) else None


def crear(integ: Any, quien: UUID, cuerpo: Any, **extra: str) -> httpx.Response:
    return client.post(RUTA, json=cuerpo, headers={**integ.headers(quien), **extra})


def pedir(tipo: str = "conocer", mensaje: str = "Quiero saber qué datos míos tienen."
          ) -> dict[str, Any]:
    return {"tipo": tipo, "mensaje": mensaje}


def mias(integ: Any, quien: UUID, **extra: str) -> Any:
    return _json(client.get(RUTA, headers={**integ.headers(quien), **extra}))


def del_admin(integ: Any, admin: UUID, sufijo: str = "") -> httpx.Response:
    return client.get(RUTA_ADMIN + sufijo, headers=integ.headers(admin))


def responder(integ: Any, admin: UUID, sid: Any, cuerpo: Any) -> httpx.Response:
    return client.put(f"{RUTA_ADMIN}/{sid}", json=cuerpo, headers=integ.headers(admin))


def filas(integ: Any, **filtro: Any) -> list[dict[str, Any]]:
    """Las filas de `solicitudes_datos`, en orden de id."""
    from sqlalchemy import text

    donde = " and ".join(f"{k} = :{k}" for k in filtro) or "true"

    async def _q() -> list[dict[str, Any]]:
        async with integ.Session() as db:
            r = await db.execute(text("select id, profile_id, tenant_id, tipo, estado, "
                                      "respuesta, respondida_por, respondida_en, created_at "
                                      f"from solicitudes_datos where {donde} order by id"),
                                 filtro)
            return [dict(f) for f in r.mappings().all()]

    return list(integ.run(_q()))


def auditorias(integ: Any, accion: str) -> int:
    return int(integ.valor("select count(*) from audit_logs where action_type = :a", a=accion))


def _mismo_instante(texto: Any, en_base: Any) -> bool:
    if not isinstance(texto, str) or en_base is None:
        return False
    try:
        leida = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return False
    return leida.tzinfo is not None and leida == en_base


# =============================================================================
# SD1 — C1
# =============================================================================
def test_sd1_crear_y_ver(integ) -> None:
    """SD1 (C1): 201 `abierta`; la fila es del token y de la institución activa."""
    a, b = integ.crear_tenant(), integ.crear_tenant()
    ana = integ.crear_perfil(a, rol="teacher")
    integ.afiliar(ana, b, rol="teacher")
    r = crear(integ, ana, pedir("rectificar", "Mi nombre está mal escrito."))
    en_b = crear(integ, ana, pedir(), **{"X-Tenant-ID": str(b)})
    todas = filas(integ)
    primera = todas[0] if todas else {}
    lista = mias(integ, ana)
    metadatos = str(integ.valor("select string_agg(metadata::text, ' ') from audit_logs "
                                "where action_type = 'datos_solicitud_creada'") or "")
    observado = {
        "respuesta": (r.status_code, campo(r, "tipo"), campo(r, "mensaje"), campo(r, "estado"),
                      campo(r, "respuesta"), campo(r, "respondida_en")),
        "claves": sorted(_json(r) or {}),
        "fecha_de_la_fila": _mismo_instante(campo(r, "creada_en"), primera.get("created_at")),
        "de_quien_y_donde": [(f["profile_id"] == ana, f["tenant_id"] == t)
                             for f, t in zip(todas, (a, b), strict=False)],
        "con_otra_institucion_activa": en_b.status_code,
        "lista": [(s.get("id"), s.get("estado")) for s in lista],
        "auditorias": auditorias(integ, "datos_solicitud_creada"),
        "el_mensaje_en_la_auditoria": "mal escrito" in metadatos,
    }
    ids = [f["id"] for f in todas]
    assert observado == {
        "respuesta": (201, "rectificar", "Mi nombre está mal escrito.", "abierta", None, None),
        "claves": ["creada_en", "estado", "id", "mensaje", "respondida_en", "respuesta", "tipo"],
        "fecha_de_la_fila": True, "de_quien_y_donde": [(True, True), (True, True)],
        "con_otra_institucion_activa": 201,
        "lista": [(i, "abierta") for i in reversed(ids)],
        "auditorias": 2, "el_mensaje_en_la_auditoria": False,
    }, f"SD1: {observado}"


# =============================================================================
# SD2 — C2
# =============================================================================
def test_sd2_nadie_lee_ni_crea_por_otro(integ) -> None:
    """SD2 (C2): B no ve las de A; mandar `profile_id`, `tenant_id`, `estado` o fecha da 422."""
    tenant = integ.crear_tenant()
    a, b = integ.crear_perfil(tenant), integ.crear_perfil(tenant)
    creadas = [crear(integ, a, pedir()).status_code for _ in range(2)]
    de_mas = {
        "profile_id": {**pedir(), "profile_id": str(b)},
        "tenant_id": {**pedir(), "tenant_id": str(tenant)},
        "estado": {**pedir(), "estado": "resuelta"},
        "created_at": {**pedir(), "created_at": "2020-01-01T00:00:00Z"},
    }
    observado = {
        "a_crea": creadas,
        "con_campos_de_mas": {k: crear(integ, a, c).status_code for k, c in de_mas.items()},
        "lista_de_b": mias(integ, b),
        "lista_de_a": len(mias(integ, a) or []),
        "filas_de_a": len(filas(integ, profile_id=a)),
        "filas_de_b": len(filas(integ, profile_id=b)),
        "filas_en_total": len(filas(integ)),
    }
    assert observado == {
        "a_crea": [201, 201], "con_campos_de_mas": dict.fromkeys(de_mas, 422),
        "lista_de_b": [], "lista_de_a": 2, "filas_de_a": 2, "filas_de_b": 0, "filas_en_total": 2,
    }, f"SD2: {observado}"


# =============================================================================
# SD3 — C3
# =============================================================================
INVALIDOS: dict[str, Any] = {
    "tipo_inventado": pedir("borrar"),
    "tipo_ausente": {"mensaje": "hola"},
    "tipo_en_mayusculas": pedir("SUPRIMIR"),
    "mensaje_de_1001": pedir(mensaje="m" * 1001),
    "mensaje_vacio": pedir(mensaje=""),
    "mensaje_solo_espacios": pedir(mensaje="   \n "),
    "mensaje_numerico": {"tipo": "conocer", "mensaje": 7},
    "mensaje_ausente": {"tipo": "conocer"},
}


def test_sd3_tipo_o_mensaje_invalido_da_422(integ) -> None:
    """SD3 (C3): nada mal formado se guarda; un mensaje de exactamente 1000 sí."""
    ana = integ.crear_perfil(integ.crear_tenant())
    estados = {nombre: crear(integ, ana, cuerpo).status_code
               for nombre, cuerpo in INVALIDOS.items()}
    sin_escribir = (len(filas(integ)), auditorias(integ, "datos_solicitud_creada"))
    observado = {"invalidos": estados, "sin_escribir": sin_escribir,
                 "control_de_1000": crear(integ, ana, pedir(mensaje="m" * 1000)).status_code}
    assert observado == {
        "invalidos": dict.fromkeys(INVALIDOS, 422), "sin_escribir": (0, 0),
        "control_de_1000": 201,
    }, f"SD3: {observado}"


# =============================================================================
# SD4 — C4
# =============================================================================
def test_sd4_a_lo_sumo_cinco_sin_cerrar(integ) -> None:
    """SD4 (C4): la sexta da 409; `en_tramite` sigue contando; al cerrar una, cabe otra."""
    tenant = integ.crear_tenant()
    ana, admin = integ.crear_perfil(tenant), integ.crear_perfil(tenant, rol="admin")
    cinco = [crear(integ, ana, pedir()).status_code for _ in range(5)]
    sexta = crear(integ, ana, pedir())
    filas_tras_la_sexta = len(filas(integ))
    una = filas(integ)[0]["id"] if filas(integ) else 0
    en_tramite = responder(integ, admin, una, {"estado": "en_tramite", "respuesta": "La miro."})
    con_una_en_tramite = crear(integ, ana, pedir()).status_code
    cerrar = responder(integ, admin, una, {"estado": "resuelta", "respuesta": "Hecho."})
    observado = {
        "cinco": cinco, "la_sexta": (sexta.status_code, campo(sexta, "detail")),
        "filas_tras_la_sexta": filas_tras_la_sexta,
        "en_tramite": en_tramite.status_code, "con_una_en_tramite": con_una_en_tramite,
        "cerrar": cerrar.status_code, "tras_cerrar_una": crear(integ, ana, pedir()).status_code,
        "filas": len(filas(integ)),
    }
    assert observado == {
        "cinco": [201] * 5, "la_sexta": (409, "demasiadas_solicitudes_abiertas"),
        "filas_tras_la_sexta": 5, "en_tramite": 200, "con_una_en_tramite": 409, "cerrar": 200,
        "tras_cerrar_una": 201, "filas": 6,
    }, f"SD4: {observado}"


# =============================================================================
# SD5 — C5
# =============================================================================
def test_sd5_el_admin_solo_su_institucion_y_con_traza(integ) -> None:
    """SD5 (C5): cada admin ve y responde solo lo de su institución; queda quién y cuándo."""
    a, b = integ.crear_tenant(), integ.crear_tenant()
    a1, b1 = integ.crear_perfil(a), integ.crear_perfil(b)
    admin_a, admin_b = integ.crear_perfil(a, rol="admin"), integ.crear_perfil(b, rol="admin")
    profe_a = integ.crear_perfil(a, rol="teacher")
    crear(integ, a1, pedir("rectificar", "Corrijan mi nombre."))
    crear(integ, b1, pedir())
    de_a = (filas(integ, tenant_id=a) or [{}])[0].get("id", 0)
    nombre_a1 = integ.valor("select full_name from memberships where profile_id = :p", p=a1)
    lista_a = _json(del_admin(integ, admin_a)) or []
    ve = {
        "admin_a": [(s.get("id"), (s.get("solicitante") or {}).get("profile_id"),
                     (s.get("solicitante") or {}).get("nombre")) for s in lista_a],
        "admin_b": [(s.get("solicitante") or {}).get("profile_id")
                    for s in _json(del_admin(integ, admin_b)) or []],
        "filtro_por_estado": [len(_json(del_admin(integ, admin_a, "?estado=abierta")) or []),
                              len(_json(del_admin(integ, admin_a, "?estado=resuelta")) or []),
                              del_admin(integ, admin_a, "?estado=borrada").status_code],
    }
    bien = {"estado": "resuelta", "respuesta": "Ya quedó corregido."}
    cruce = responder(integ, admin_b, de_a, bien).status_code
    barreras = {
        "admin_b_responde_la_de_a": (cruce, filas(integ, id=de_a)[0]["estado"]),
        "estudiante": (del_admin(integ, a1).status_code,
                       responder(integ, a1, de_a, bien).status_code),
        "docente": (del_admin(integ, profe_a).status_code,
                    responder(integ, profe_a, de_a, bien).status_code),
        "cuerpos_invalidos": [responder(integ, admin_a, de_a, c).status_code for c in (
            {"estado": "abierta", "respuesta": "x"}, {"estado": "resuelta", "respuesta": ""},
            {"estado": "resuelta", "respuesta": "r" * 1001}, {"estado": "resuelta"})],
    }
    pasos = [responder(integ, admin_a, de_a, {"estado": "en_tramite", "respuesta": "En eso."}),
             responder(integ, admin_a, de_a, bien)]
    fila = filas(integ, id=de_a)[0]
    otra_vez = responder(integ, admin_a, de_a, {"estado": "rechazada", "respuesta": "No."})
    la_ve_a1 = (mias(integ, a1) or [{}])[0]
    traza = {
        "pasos": [p.status_code for p in pasos],
        "quien_y_cuando": (fila["respondida_por"] == admin_a, fila["respondida_en"] is not None),
        "auditorias": auditorias(integ, "datos_solicitud_respondida"),
        "ya_cerrada": (otra_vez.status_code, campo(otra_vez, "detail"),
                       filas(integ, id=de_a)[0]["respuesta"]),
        "lo_que_ve_a1": (la_ve_a1.get("estado"), la_ve_a1.get("respuesta"),
                         la_ve_a1.get("respondida_en") is not None,
                         "respondida_por" in la_ve_a1 or "solicitante" in la_ve_a1),
    }
    observado = {"ve": ve, "barreras": barreras, "traza": traza}
    assert observado == {
        "ve": {"admin_a": [(de_a, str(a1), nombre_a1)], "admin_b": [str(b1)],
               "filtro_por_estado": [1, 0, 422]},
        "barreras": {"admin_b_responde_la_de_a": (404, "abierta"), "estudiante": (403, 403),
                     "docente": (403, 403), "cuerpos_invalidos": [422, 422, 422, 422]},
        "traza": {"pasos": [200, 200], "quien_y_cuando": (True, True), "auditorias": 2,
                  "ya_cerrada": (409, "solicitud_cerrada", "Ya quedó corregido."),
                  "lo_que_ve_a1": ("resuelta", "Ya quedó corregido.", True, False)},
    }, f"SD5: {observado}"


# =============================================================================
# SD6 — C6
# =============================================================================
def _foto(integ: Any, perfil: UUID, tenant: UUID) -> tuple[Any, ...]:
    """Lo que una solicitud de `suprimir` NO debe tocar."""
    return (
        integ.valor("select count(*) from profiles where id = :p and is_active", p=perfil),
        integ.valor("select count(*) from memberships where profile_id = :p and tenant_id = :t "
                    "and is_active", p=perfil, t=tenant),
        integ.valor("select count(*) from consentimientos where profile_id = :p", p=perfil),
        integ.saldo("profile", perfil),
    )


def test_sd6_barreras_y_no_ejecuta_nada(integ) -> None:
    """SD6 (C6): contraseña temporal, 403; sin consentimiento, 201; `suprimir` no borra nada."""
    tenant = integ.crear_tenant()
    temporal, ana = integ.crear_perfil(tenant), integ.crear_perfil(tenant, saldo=30)
    admin = integ.crear_perfil(tenant, rol="admin")
    sembrar(integ, "update profiles set force_password_reset = true where id = :p", p=temporal)
    sembrar(integ, "insert into consentimientos (profile_id, version) values (:p, 'v-vieja')",
            p=ana)
    con_temporal = [crear(integ, temporal, pedir()),
                    client.get(RUTA, headers=integ.headers(temporal))]
    sin_aviso = integ.crear_perfil(tenant)
    me = client.get("/auth/me", headers=integ.headers(sin_aviso))
    antes = _foto(integ, ana, tenant)
    pedido = crear(integ, ana, pedir("suprimir", "Borren mi cuenta."))
    resuelta = responder(integ, admin, campo(pedido, "id"),
                         {"estado": "resuelta", "respuesta": "Se tramita a mano."})
    observado = {
        "con_clave_temporal": [(r.status_code, campo(r, "detail")) for r in con_temporal],
        "filas_del_temporal": len(filas(integ, profile_id=temporal)),
        "sin_consentimiento": (campo(me, "consent_version"),
                               crear(integ, sin_aviso, pedir()).status_code),
        "suprimir": (pedido.status_code, resuelta.status_code),
        "nada_cambio": (antes, _foto(integ, ana, tenant) == antes),
        "puede_seguir_entrando": client.get("/auth/me",
                                            headers=integ.headers(ana)).status_code,
    }
    assert observado == {
        "con_clave_temporal": [(403, "must_change_password")] * 2, "filas_del_temporal": 0,
        "sin_consentimiento": (None, 201), "suprimir": (201, 200),
        "nada_cambio": ((1, 1, 1, 30), True), "puede_seguir_entrando": 200,
    }, f"SD6: {observado}"
