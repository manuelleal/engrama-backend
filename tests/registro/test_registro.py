"""`POST /auth/registro` — `docs/ESPEC_autorregistro.md` C2, C7, C8, C9 y C11.

  AR2   C2   el registro normal: qué queda escrito y qué NO sale.
  AR7   C7   no revela si un correo o un código estudiantil ya existen; no duplica.
  AR8   C8   si GoTrue falla, se deshace; el que queda a medias falla cerrado y se recoge.
  AR9   C9   cuerpo inválido (menor, sin aviso, clave corta, campos de más): 422 y nada.
  AR11  C11  el código de un grupo inscribe solo en ese grupo.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import pytest

from src.shared.models import Membership, Profile
from tests.registro import _ayuda as ay
from tests.seguridad.veredictos import sembrar

pytestmark = pytest.mark.integ


# =============================================================================
# AR2 — C2
# =============================================================================
def test_ar2_registro_normal(integ, caplog) -> None:
    """AR2 (C2): 201 exacto; perfil, membresía inactiva, solicitud, aviso y cuenta con su id."""
    cuentas = ay.preparar(integ)
    a = ay.aula(integ)
    caplog.set_level(logging.DEBUG)
    correo = "Ana.Sintetica@Sintetico.Test"
    r = ay.registrar(ay.cuerpo(a.codigo, 1, correo=correo, nombre="Ana Sintética"))
    perfil = ay.perfil_de(integ, a.doc(1))
    cuenta = cuentas.cuentas.get(perfil) if perfil is not None else None
    auditoria = integ.fila("select user_id, metadata from audit_logs "
                           "where action_type = 'registro_solicitado'") or {}
    logs = caplog.text.lower()
    guardado = str(integ.valor(
        "select coalesce((select string_agg(metadata::text, ' ') from audit_logs), '') || "
        "(select string_agg(full_name || documento_id, ' ') from profiles) || "
        "(select string_agg(coalesce(full_name, ''), ' ') from memberships)") or "")
    observado = {
        "respuesta": ay.estado_y_cuerpo(r),
        "perfiles_del_registro": ay.estudiantes(integ),
        "clave_temporal": integ.valor("select force_password_reset from profiles "
                                      "where id = :p", p=perfil),
        "membresia": ay.membresia(integ, perfil, a.tenant),
        "solicitudes": [e for _, e in ay.solicitudes(integ, profile_id=perfil)],
        "aviso": integ.valor("select version from consentimientos where profile_id = :p",
                             p=perfil),
        "usos": ay.usos(integ, a.grupo),
        "auditoria": (auditoria.get("user_id"),
                      (auditoria.get("metadata") or {}).get("declara_mayor_de_edad")),
        "crear": [(i == perfil and i is not None, c) for i, c in cuentas.creadas],
        "cuenta_con_el_id_del_perfil": cuenta == {"correo": correo.lower(), "clave": ay.CLAVE},
        "clave_o_correo_en_la_respuesta": ay.CLAVE in r.text or correo.lower() in r.text.lower(),
        "clave_o_correo_en_los_logs": ay.CLAVE.lower() in logs or correo.lower() in logs,
        "correo_guardado_en_la_base": "sintetico.test" in guardado.lower(),
    }
    assert observado == {
        "respuesta": (201, ay.PENDIENTE), "perfiles_del_registro": 1, "clave_temporal": False,
        "membresia": ("student", False, "G1", "Ana Sintética"), "solicitudes": ["pendiente"],
        "aviso": ay.AVISO, "usos": 1, "auditoria": (None, True),
        "crear": [(True, correo.lower())], "cuenta_con_el_id_del_perfil": True,
        "clave_o_correo_en_la_respuesta": False, "clave_o_correo_en_los_logs": False,
        "correo_guardado_en_la_base": False,
    }, f"AR2: {observado}"


# =============================================================================
# AR7 — C7
# =============================================================================
def _matricular_por_lista(integ: Any, a: ay.Aula, n: int) -> Any:
    """Un estudiante matriculado por la institución (como M3): activo y sin cuenta."""
    pid = uuid4()
    integ._insertar(
        Profile(id=pid, documento_id=a.doc(n), full_name="", pin_hash="", role="student"),
        Membership(tenant_id=a.tenant, profile_id=pid, role="student",
                   group_code=a.codigo_de_grupo, is_active=True, full_name="Por Lista"))
    return pid


def test_ar7_no_revela_ni_duplica(integ) -> None:
    """AR7 (C7): correo en uso, documento ya registrado, doble envío y matriculado por lista."""
    cuentas = ay.preparar(integ)
    a = ay.aula(integ)
    integ.run(cuentas.crear(uuid4(), "ocupado@sintetico.test", "otra-clave-ajena"))

    r_a = ay.registrar(ay.cuerpo(a.codigo, 1, correo="ocupado@sintetico.test"))
    caso_a = {"respuesta": ay.estado_y_cuerpo(r_a), "perfil": ay.perfil_de(integ, a.doc(1)),
              "solicitudes": len(ay.solicitudes(integ)), "usos": ay.usos(integ, a.grupo)}

    primero = ay.registrar(ay.cuerpo(a.codigo, 2)).status_code
    pid = ay.perfil_de(integ, a.doc(2))
    n_crear = len(cuentas.creadas)
    r_b = ay.registrar(ay.cuerpo(a.codigo, 2, correo="otro@sintetico.test",
                                 contrasena="otra-clave-distinta"))
    caso_b = {"primero": primero, "respuesta": ay.estado_y_cuerpo(r_b),
              "otro_crear": len(cuentas.creadas) - n_crear,
              "la_cuenta_no_cambio": pid is not None and cuentas.cuentas.get(pid) == {
                  "correo": "persona2@sintetico.test", "clave": ay.CLAVE}}

    dobles = [ay.estado_y_cuerpo(ay.registrar(ay.cuerpo(a.codigo, 3))) for _ in range(2)]
    caso_c = {"respuestas": dobles,
              "perfiles": ay.contar(integ, "select count(*) from profiles "
                                           "where documento_id = :d", d=a.doc(3)),
              "cuentas": sum(1 for c in cuentas.cuentas.values()
                             if c["correo"] == "persona3@sintetico.test")}

    por_lista = _matricular_por_lista(integ, a, 4)
    r_d = ay.registrar(ay.cuerpo(a.codigo, 4))
    caso_d = {"respuesta": ay.estado_y_cuerpo(r_d),
              "membresia": ay.membresia(integ, por_lista, a.tenant),
              "cuenta": por_lista in cuentas.cuentas,
              "solicitudes": len(ay.solicitudes(integ, profile_id=por_lista))}
    observado = {"correo_en_uso": caso_a, "documento_ya_registrado": caso_b,
                 "doble_envio": caso_c, "matriculado_por_lista": caso_d,
                 "usos": ay.usos(integ, a.grupo)}
    ok = (201, ay.PENDIENTE)
    assert observado == {
        "correo_en_uso": {"respuesta": ok, "perfil": None, "solicitudes": 0, "usos": 0},
        "documento_ya_registrado": {"primero": 201, "respuesta": ok, "otro_crear": 0,
                                    "la_cuenta_no_cambio": True},
        "doble_envio": {"respuestas": [ok, ok], "perfiles": 1, "cuentas": 1},
        "matriculado_por_lista": {"respuesta": ok,
                                  "membresia": ("student", True, "G1", "Por Lista"),
                                  "cuenta": False, "solicitudes": 0},
        "usos": 2,
    }, f"AR7: {observado}"


# =============================================================================
# AR8 — C8
# =============================================================================
def test_ar8_compensacion_y_huerfano(integ) -> None:
    """AR8 (C8): GoTrue falla -> nada queda; si no se puede confirmar, `creando` y cerrado."""
    cuentas = ay.preparar(integ)
    a = ay.aula(integ)
    cuentas.fallar_crear = True
    r = ay.registrar(ay.cuerpo(a.codigo, 1))
    caso_a = {"respuesta": ay.estado_y_cuerpo(r), "perfil": ay.perfil_de(integ, a.doc(1)),
              "solicitudes": len(ay.solicitudes(integ)), "usos": ay.usos(integ, a.grupo),
              "borrar_pedidos": len(cuentas.borradas)}
    cuentas.fallar_crear = False
    caso_a["reintento"] = ay.registrar(ay.cuerpo(a.codigo, 1)).status_code

    b = ay.aula(integ)
    cuentas.fallar_crear = cuentas.fallar_borrar = True
    r = ay.registrar(ay.cuerpo(b.codigo, 2))
    huerfano = ay.perfil_de(integ, b.doc(2))
    a_medias = ay.solicitudes(integ, group_id=b.grupo)
    sid = a_medias[0][0] if a_medias else 0
    me = ay.client.get("/auth/me", headers=integ.headers(huerfano or uuid4()))
    caso_b = {"respuesta": ay.estado_y_cuerpo(r), "solicitudes": [e for _, e in a_medias],
              "lista_del_profe": ay.lista(integ, b.profe, b.grupo),
              "aprobarla": ay.decidir(integ, b.profe, b.grupo, sid, "aprobar").status_code,
              "auth_me": (me.status_code, ay.campo(me, "detail")),
              "usos": ay.usos(integ, b.grupo)}

    cuentas.fallar_crear = cuentas.fallar_borrar = False
    pronto = ay.registrar(ay.cuerpo(b.codigo, 2))
    caso_c: dict[str, Any] = {"antes_de_60_s": (ay.estado_y_cuerpo(pronto),
                                                ay.solicitudes(integ, group_id=b.grupo)
                                                == a_medias)}
    sembrar(integ, "update solicitudes_inscripcion set created_at = now() - interval "
                   "'61 seconds' where id = :s", s=sid)
    tarde = ay.registrar(ay.cuerpo(b.codigo, 2))
    nuevo = ay.perfil_de(integ, b.doc(2))
    despues = ay.solicitudes(integ, group_id=b.grupo)
    caso_c["despues_de_60_s"] = {
        "respuesta": ay.estado_y_cuerpo(tarde), "estados": [e for _, e in despues],
        "es_otra_solicitud": bool(despues) and despues[0][0] != sid,
        "es_otro_perfil": nuevo is not None and nuevo != huerfano,
        "usos": ay.usos(integ, b.grupo), "cuenta_del_perfil_nuevo": nuevo in cuentas.cuentas,
        "cuenta_del_huerfano": huerfano in cuentas.cuentas,
    }
    observado = {"crear_falla": caso_a, "tampoco_se_puede_borrar": caso_b, "reintentos": caso_c}
    no_disponible = (502, {"detail": "registro_no_disponible"})
    assert observado == {
        "crear_falla": {"respuesta": no_disponible, "perfil": None, "solicitudes": 0, "usos": 0,
                        "borrar_pedidos": 1, "reintento": 201},
        "tampoco_se_puede_borrar": {
            "respuesta": no_disponible, "solicitudes": ["creando"], "lista_del_profe": [],
            "aprobarla": 404, "auth_me": (403, "pending_approval"), "usos": 1},
        "reintentos": {
            "antes_de_60_s": ((201, ay.PENDIENTE), True),
            "despues_de_60_s": {
                "respuesta": (201, ay.PENDIENTE), "estados": ["pendiente"],
                "es_otra_solicitud": True, "es_otro_perfil": True, "usos": 1,
                "cuenta_del_perfil_nuevo": True, "cuenta_del_huerfano": False}},
    }, f"AR8: {observado}"


# =============================================================================
# AR9 — C9
# =============================================================================
INVALIDOS: dict[str, dict[str, Any]] = {
    "menor": {"mayor_de_edad": False},
    "sin_declarar": {"mayor_de_edad": ...},
    "mayor_como_texto": {"mayor_de_edad": "true"},
    "mayor_como_numero": {"mayor_de_edad": 1},
    "sin_aviso": {"aviso_version": ...},
    "aviso_vacio": {"aviso_version": ""},
    "clave_de_9": {"contrasena": "x" * 9},
    "clave_de_73": {"contrasena": "x" * 73},
    "correo_sin_arroba": {"correo": "persona.sintetico.test"},
    "nombre_vacio": {"nombre": ""},
    "nombre_de_121": {"nombre": "n" * 121},
    "codigo_estudiantil_con_dos_puntos": {"codigo_estudiantil": "sena:001"},
    "codigo_estudiantil_de_25": {"codigo_estudiantil": "9" * 25},
    "sin_codigo": {"codigo": ...},
    "codigo_vacio": {"codigo": ""},
    "con_tenant_id": {"tenant_id": str(uuid4())},
    "con_group_id": {"group_id": str(uuid4())},
    "con_role": {"role": "admin"},
    "con_fecha_de_nacimiento": {"fecha_nacimiento": "2012-01-01"},
}


def test_ar9_cuerpo_invalido_da_422_sin_escribir(integ) -> None:
    """AR9 (C9): ningún cuerpo inválido escribe ni llega a GoTrue; 10 y 72 sí entran."""
    cuentas = ay.preparar(integ)
    a = ay.aula(integ)
    estados = {nombre: ay.registrar(ay.cuerpo(a.codigo, 1, **cambio)).status_code
               for nombre, cambio in INVALIDOS.items()}
    sin_escribir = (ay.estudiantes(integ), len(ay.solicitudes(integ)), len(cuentas.creadas),
                    ay.usos(integ, a.grupo))
    observado = {
        "invalidos": estados, "sin_escribir": sin_escribir,
        "control_de_10": ay.registrar(ay.cuerpo(a.codigo, 2, contrasena="x" * 10)).status_code,
        "control_de_72": ay.registrar(ay.cuerpo(a.codigo, 3, contrasena="x" * 72)).status_code,
    }
    assert observado == {
        "invalidos": dict.fromkeys(INVALIDOS, 422), "sin_escribir": (0, 0, 0, 0),
        "control_de_10": 201, "control_de_72": 201,
    }, f"AR9: {observado}"


# =============================================================================
# AR11 — C11
# =============================================================================
def test_ar11_el_codigo_inscribe_solo_en_su_grupo(integ) -> None:
    """AR11 (C11): con el código de A se queda en A y en su grupo; B no ve nada."""
    ay.preparar(integ)
    a, b = ay.aula(integ, grupo="G5"), ay.aula(integ, grupo="G7")
    integ.crear_grupo(a.tenant, "G0")  # otro grupo de A, antes en el orden: no es el del código
    con_a = ay.registrar(ay.cuerpo(a.codigo, 1)).status_code
    en_a = ay.perfil_de(integ, a.doc(1))
    tras_a = {
        "estado": con_a, "membresia_en_a": ay.membresia(integ, en_a, a.tenant),
        "membresias_en_b": ay.contar(integ, "select count(*) from memberships where "
                                            "tenant_id = :t and role = 'student'", t=b.tenant),
        "solicitudes_en_b": len(ay.solicitudes(integ, tenant_id=b.tenant)),
        "lista_de_b": ay.lista(integ, b.profe, b.grupo),
        "lista_de_a": [s.get("codigo_estudiantil") for s in ay.lista(integ, a.profe, a.grupo)],
    }
    con_b = ay.registrar(ay.cuerpo(b.codigo, 1, correo="persona1b@sintetico.test")).status_code
    en_b = ay.perfil_de(integ, b.doc(1))
    observado = {
        "con_el_codigo_de_a": tras_a, "con_el_codigo_de_b": con_b,
        "es_otro_perfil": en_b is not None and en_b != en_a,
        "membresia_en_b": ay.membresia(integ, en_b, b.tenant),
        "membresias_del_de_a": ay.contar(integ, "select count(*) from memberships "
                                                "where profile_id = :p", p=en_a),
    }
    assert observado == {
        "con_el_codigo_de_a": {
            "estado": 201, "membresia_en_a": ("student", False, "G5", "Persona Sintética 1"),
            "membresias_en_b": 0, "solicitudes_en_b": 0, "lista_de_b": [],
            "lista_de_a": [a.doc(1)]},
        "con_el_codigo_de_b": 201, "es_otro_perfil": True,
        "membresia_en_b": ("student", False, "G7", "Persona Sintética 1"),
        "membresias_del_de_a": 1,
    }, f"AR11: {observado}"
