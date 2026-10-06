"""Mientras espera, aprobar y rechazar — `docs/ESPEC_autorregistro.md` C5 y C6.

  AR5  C5  antes de aprobar no entra a nada (403 `pending_approval`); después, sí.
  AR6  C6  quién puede decidir y sobre qué; rechazar borra la cuenta y el perfil.
"""
from __future__ import annotations

from typing import Any

import pytest

from tests.registro import _ayuda as ay

pytestmark = pytest.mark.integ


def _me_y_retos(integ: Any, perfil: Any) -> list[tuple[int, Any]]:
    h = integ.headers(perfil)
    return [(r.status_code, ay.campo(r, "detail"))
            for r in (ay.client.get("/auth/me", headers=h),
                      ay.client.get("/challenges/", headers=h))]


# =============================================================================
# AR5 — C5
# =============================================================================
def test_ar5_pendiente_no_entra_y_aprobado_si(integ) -> None:
    """AR5 (C5): 403 `pending_approval` antes; después entra sin cambiar la contraseña."""
    ay.preparar(integ)
    a = ay.aula(integ)
    ay.registrar(ay.cuerpo(a.codigo, 1, nombre="Íñigo Peña"))
    perfil = ay.perfil_de(integ, a.doc(1))
    antes = _me_y_retos(integ, perfil)
    pendientes = ay.lista(integ, a.profe, a.grupo)
    sid = pendientes[0].get("id") if isinstance(pendientes, list) and pendientes else 0
    aprobar = ay.decidir(integ, a.profe, a.grupo, sid, "aprobar")
    me = ay.client.get("/auth/me", headers=integ.headers(perfil))
    roster = ay.cuerpo_json(ay.client.get(f"/teachers/groups/{a.grupo}/students",
                                          headers=integ.headers(a.profe)))
    observado = {
        "antes": antes,
        "en_la_lista": [(s.get("nombre"), s.get("codigo_estudiantil")) for s in pendientes],
        "aprobar": ay.estado_y_cuerpo(aprobar),
        "me": (me.status_code, ay.campo(me, "must_change_password"),
               ay.campo(me, "consent_version"), ay.campo(me, "full_name")),
        "retos": ay.client.get("/challenges/", headers=integ.headers(perfil)).status_code,
        "en_el_roster": [e.get("profile_id") for e in roster] == [str(perfil)],
        "lista_despues": ay.lista(integ, a.profe, a.grupo),
    }
    assert observado == {
        "antes": [(403, "pending_approval"), (403, "pending_approval")],
        "en_la_lista": [("Íñigo Peña", a.doc(1))],
        "aprobar": (200, {"id": sid, "estado": "aprobada"}),
        "me": (200, False, ay.AVISO, "Íñigo Peña"), "retos": 200, "en_el_roster": True,
        "lista_despues": [],
    }, f"AR5: {observado}"


# =============================================================================
# AR6 — C6
# =============================================================================
def _sid(integ: Any, perfil: Any) -> int:
    filas = ay.solicitudes(integ, profile_id=perfil)
    return filas[0][0] if filas else 0


def test_ar6_quien_decide_y_que_deja_el_rechazo(integ) -> None:
    """AR6 (C6): las barreras de aprobar; rechazar borra cuenta y perfil; aprobar es idempotente."""
    cuentas = ay.preparar(integ)
    g1 = ay.aula(integ, grupo="G1")
    g2 = ay.aula(integ, grupo="G2", tenant=g1.tenant)
    estudiante = integ.crear_perfil(g1.tenant, group_code="G1")
    sin_grupo = integ.crear_perfil(g1.tenant, rol="teacher")
    de_otra = integ.crear_perfil(integ.crear_tenant(), rol="teacher")
    for n in (1, 2, 3):
        ay.registrar(ay.cuerpo(g1.codigo, n))
    ay.registrar(ay.cuerpo(g2.codigo, 9))
    x1, x2, x3 = (ay.perfil_de(integ, g1.doc(n)) for n in (1, 2, 3))
    y = ay.perfil_de(integ, g2.doc(9))
    s1, s2, s3, sy = (_sid(integ, p) for p in (x1, x2, x3, y))

    barreras = {
        "estudiante": ay.decidir(integ, estudiante, g1.grupo, s1, "aprobar").status_code,
        "docente_sin_ese_grupo": ay.decidir(integ, sin_grupo, g1.grupo, s1,
                                            "aprobar").status_code,
        "docente_de_otra_institucion": ay.decidir(integ, de_otra, g1.grupo, s1,
                                                  "aprobar").status_code,
        "la_de_g2_por_la_ruta_de_g1": [
            ay.decidir(integ, g1.profe, g1.grupo, sy, accion).status_code
            for accion in ("aprobar", "rechazar")],
        "siguen_pendientes": [e for _, e in ay.solicitudes(integ)],
    }
    aprobar = [ay.decidir(integ, g1.profe, g1.grupo, s1, "aprobar").status_code
               for _ in range(2)]
    aprobada = {
        "estados": aprobar, "membresia_activa": (ay.membresia(integ, x1, g1.tenant) or ())[1:2],
        "auditorias": ay.contar(integ, "select count(*) from audit_logs where action_type = "
                                       "'registro_aprobado' and user_id = :p", p=g1.profe),
        "quien": integ.valor("select decidida_por from solicitudes_inscripcion where id = :s",
                             s=s1) == g1.profe,
    }
    rechazo = ay.decidir(integ, g1.profe, g1.grupo, s2, "rechazar")
    rechazada = {
        "respuesta": ay.estado_y_cuerpo(rechazo), "borrar_en_gotrue": cuentas.borradas == [x2],
        "cuenta": x2 in cuentas.cuentas, "perfil": ay.perfil_de(integ, g1.doc(2)),
        "membresia": ay.membresia(integ, x2, g1.tenant),
        "solicitud": ay.solicitudes(integ, profile_id=x2),
        "se_registra_otra_vez": ay.registrar(ay.cuerpo(g1.codigo, 2)).status_code,
        "con_solicitud_nueva": [e for _, e in ay.solicitudes(
            integ, profile_id=ay.perfil_de(integ, g1.doc(2)))],
    }
    ya_aprobado = {
        "rechazar": ay.decidir(integ, g1.profe, g1.grupo, s1, "rechazar").status_code,
        "sigue_activo": (ay.membresia(integ, x1, g1.tenant) or ())[1:2],
    }
    cuentas.fallar_borrar = True
    sin_gotrue = ay.decidir(integ, g1.profe, g1.grupo, s3, "rechazar")
    gotrue_caido = {"respuesta": ay.estado_y_cuerpo(sin_gotrue),
                    "sigue": ay.solicitudes(integ, profile_id=x3),
                    "perfil_intacto": ay.perfil_de(integ, g1.doc(3)) == x3}
    observado = {"barreras": barreras, "aprobar": aprobada, "rechazar": rechazada,
                 "rechazar_al_aprobado": ya_aprobado, "gotrue_caido": gotrue_caido}
    assert observado == {
        "barreras": {"estudiante": 403, "docente_sin_ese_grupo": 404,
                     "docente_de_otra_institucion": 404,
                     "la_de_g2_por_la_ruta_de_g1": [404, 404],
                     "siguen_pendientes": ["pendiente"] * 4},
        "aprobar": {"estados": [200, 200], "membresia_activa": (True,), "auditorias": 1,
                    "quien": True},
        "rechazar": {"respuesta": (200, {"id": s2, "estado": "rechazada"}),
                     "borrar_en_gotrue": True, "cuenta": False, "perfil": None,
                     "membresia": None, "solicitud": [], "se_registra_otra_vez": 201,
                     "con_solicitud_nueva": ["pendiente"]},
        "rechazar_al_aprobado": {"rechazar": 404, "sigue_activo": (True,)},
        "gotrue_caido": {"respuesta": (502, {"detail": "registro_no_disponible"}),
                         "sigue": [(s3, "pendiente")], "perfil_intacto": True},
    }, f"AR6: {observado}"
