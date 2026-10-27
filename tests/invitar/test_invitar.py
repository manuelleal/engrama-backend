"""IP1-IP12: invitar profes por correo, contra Postgres real — `docs/ESPEC_invitar_profe.md` §4.

GoTrue es el doble `GoTrueFalso` (`_ayuda.py`), que imita lo medido en el banco.
TestClient corre las tareas en segundo plano ANTES de devolver la respuesta, así
que al volver de cada petición las llamadas a GoTrue ya están en `falso.llamadas`
(IP12 mide aparte que ocurren DESPUÉS de enviar la respuesta).

Cada test arma lo observado en un dict y lo compara ENTERO (el mensaje lo trae).
"""
from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.registro.cuentas import get_cuentas_de_invitacion
from src.shared.config import settings
from tests.invitar import _ayuda as ay

pytestmark = pytest.mark.integ

CLAVE_NUEVA = "Sintetica-123abc"


@pytest.fixture(autouse=True)
def _soltar_dobles() -> Iterator[None]:
    yield
    ay.soltar()


def _atrasar(integ: Any, inv_id: int, segundos: int = 61) -> None:
    """El último envío, `segundos` atrás: pasada la espera del reenvío."""
    ay.ejecutar(integ, "update invitaciones_docente set ultimo_envio_en = now() - "
                "make_interval(secs => :s) where id = :i", s=segundos, i=inv_id)


def _id(r: Any) -> int:
    return int((ay.json_de(r) or {}).get("id") or 0)


def test_ip1_invitar_un_correo_nuevo(integ: Any) -> None:
    falso = ay.preparar(integ)
    a = ay.colegio(integ)
    r = ay.invitar(integ, a, ay.cuerpo(a, 1, correo="Profe1@Sintetico.test"))
    cuerpo = ay.json_de(r) or {}
    pid = ay.perfil_de(integ, _id(r)) if _id(r) else None
    observado = {
        "status": r.status_code,
        "cuerpo": ay.sin_variables(cuerpo), "correo": cuerpo.get("correo"),
        "nombre": cuerpo.get("nombre"),
        "filas": ay.filas_de(integ, pid) if pid else None,
        "tenant_de_la_membresia": str(integ.valor(
            "select tenant_id from memberships where profile_id = :p", p=pid)) if pid else None,
        "auditorias": integ.valor("select count(*) from audit_logs where action_type = "
                                  "'invitacion_profe' and user_id = :a", a=a.admin),
        "gotrue": falso.llamadas,
    }
    correo = "profe1@sintetico.test"
    assert observado == {
        "status": 201,
        "cuerpo": {"group_id": str(a.grupo), "group_code": "G1", "estado": "enviada",
                   "envios": 1},
        "correo": correo, "nombre": "Profe Sintética 1",
        "filas": {"perfil": {"role": "teacher", "force_password_reset": True, "full_name": "",
                             "pin_hash": "", "prefijo": "inv_"},
                  "membresias": 1, "grupos": 1, "invitaciones": 1},
        "tenant_de_la_membresia": str(a.tenant),
        "auditorias": 1,
        "gotrue": [("estado_de_cuenta", str(pid)), ("crear_invitado", str(pid), correo),
                   ("invitar", correo)],
    }, f"IP1: {observado}"


def test_ip2_el_profe_acepta_y_entra_con_su_rol(integ: Any) -> None:
    ay.preparar(integ)
    a = ay.colegio(integ)
    r = ay.invitar(integ, a, ay.cuerpo(a))
    pid = ay.perfil_de(integ, _id(r))
    antes = ay.client.get("/auth/me", headers=integ.headers(pid))
    cambio = ay.client.post("/auth/contrasena", json={"nueva": CLAVE_NUEVA},
                            headers=integ.headers(pid))
    me = ay.json_de(ay.client.get("/auth/me", headers=integ.headers(pid))) or {}
    grupos = ay.json_de(ay.client.get("/teachers/groups", headers=integ.headers(pid))) or []
    lista = ay.json_de(ay.listar(integ, a.admin)) or []
    observado = {
        "antes_debe_cambiar": (ay.json_de(antes) or {}).get("must_change_password"),
        "cambio": cambio.status_code,
        "me": {"must_change_password": me.get("must_change_password"),
               "active_tenant_id": me.get("active_tenant_id"),
               "roles": [m.get("role") for m in me.get("memberships", [])],
               "nombre": me.get("full_name")},
        "grupos": [g.get("id") for g in grupos] if isinstance(grupos, list) else grupos,
        "estado_en_la_lista": [i.get("estado") for i in lista],
    }
    assert observado == {
        "antes_debe_cambiar": True, "cambio": 204,
        "me": {"must_change_password": False, "active_tenant_id": str(a.tenant),
               "roles": ["teacher"], "nombre": "Profe Sintética 1"},
        "grupos": [str(a.grupo)],
        "estado_en_la_lista": ["aceptada"],
    }, f"IP2: {observado}"


def test_ip3_correo_de_otra_institucion_se_ve_igual(integ: Any) -> None:
    falso = ay.preparar(integ)
    a, b = ay.colegio(integ, "GA"), ay.colegio(integ, "GB")
    integ.crear_perfil(b.tenant, rol="teacher")  # la persona de B, con su cuenta en GoTrue
    ajena = falso.sembrar("ajena@sintetico.test")
    cuenta_antes = dict(falso.cuentas[ajena])
    de_b_antes = integ.fila("select (select count(*) from memberships where tenant_id = :t) m, "
                            "(select count(*) from invitaciones_docente where tenant_id = :t) i",
                            t=b.tenant)
    nueva = ay.invitar(integ, a, ay.cuerpo(a, 1))
    otra = ay.invitar(integ, a, ay.cuerpo(a, 2, correo="AJENA@sintetico.test"))
    # Sin id (una respuesta que no es 201) no hay perfil: `None`, y el dict lo dice.
    p_nueva, p_otra = (ay.perfil_de(integ, _id(x)) if _id(x) else None for x in (nueva, otra))
    for inv in (_id(nueva), _id(otra)):
        _atrasar(integ, inv)
    re_nueva, re_otra = ay.reenviar(integ, a.admin, _id(nueva)), ay.reenviar(integ, a.admin,
                                                                               _id(otra))
    lista = ay.json_de(ay.listar(integ, a.admin)) or []
    observado = {
        "status": (nueva.status_code, otra.status_code),
        "mismo_cuerpo": ay.sin_variables(ay.json_de(nueva) or {})
        == ay.sin_variables(ay.json_de(otra) or {}),
        "mismas_filas": p_otra is not None and p_nueva is not None
        and ay.filas_de(integ, p_nueva) == ay.filas_de(integ, p_otra),
        "reenvio": (re_nueva.status_code, re_otra.status_code),
        "mismo_reenvio": ay.sin_variables(ay.json_de(re_nueva) or {})
        == ay.sin_variables(ay.json_de(re_otra) or {}),
        "estados": sorted(i.get("estado") for i in lista),
        "correo_a_la_ajena": [c for c in falso.llamadas
                              if c[0] in ("invitar", "recuperar") and c[1] == "ajena@sintetico.test"],
        "cuenta_ajena_igual": falso.cuentas.get(ajena) == cuenta_antes,
        "cuentas_con_ese_correo": sum(1 for c in falso.cuentas.values()
                                      if c["correo"] == "ajena@sintetico.test"),
        "b_igual": integ.fila(
            "select (select count(*) from memberships where tenant_id = :t) m, "
            "(select count(*) from invitaciones_docente where tenant_id = :t) i",
            t=b.tenant) == de_b_antes,
        "b_en_la_respuesta": str(b.tenant) in (otra.text + re_otra.text),
    }
    assert observado == {
        "status": (201, 201), "mismo_cuerpo": True, "mismas_filas": True,
        "reenvio": (202, 202), "mismo_reenvio": True, "estados": ["enviada", "enviada"],
        "correo_a_la_ajena": [], "cuenta_ajena_igual": True, "cuentas_con_ese_correo": 1,
        "b_igual": True, "b_en_la_respuesta": False,
    }, f"IP3: {observado}"


def test_ip4_solo_el_admin_de_esa_institucion(integ: Any) -> None:
    ay.preparar(integ)
    a, b = ay.colegio(integ, "GA"), ay.colegio(integ, "GB")
    inv = _id(ay.invitar(integ, a, ay.cuerpo(a)))
    profe_a = ay.profe_de(integ, a)
    estudiante_a = integ.crear_perfil(a.tenant, rol="student", group_code="GA")
    filas_antes = integ.valor("select count(*) from invitaciones_docente")
    observado = {
        "lista_de_b": ay.json_de(ay.listar(integ, b.admin)),
        "b_reenvia_la_de_a": ay.reenviar(integ, b.admin, inv).status_code,
        "b_invita_al_grupo_de_a": ay.invitar(integ, b, ay.cuerpo(a, 7), quien=b.admin)
        .status_code,
        "filas_nuevas": integ.valor("select count(*) from invitaciones_docente") - filas_antes,
        "no_admin": {
            nombre: (ay.invitar(integ, a, ay.cuerpo(a, 8), quien=quien).status_code,
                     ay.listar(integ, quien).status_code,
                     ay.reenviar(integ, quien, inv).status_code)
            for nombre, quien in (("profe", profe_a), ("estudiante", estudiante_a))},
        "lista_de_a": len(ay.json_de(ay.listar(integ, a.admin)) or []),
    }
    assert observado == {
        "lista_de_b": [], "b_reenvia_la_de_a": 404, "b_invita_al_grupo_de_a": 404,
        "filas_nuevas": 0,
        "no_admin": {"profe": (403, 403, 403), "estudiante": (403, 403, 403)},
        "lista_de_a": 1,
    }, f"IP4: {observado}"


def test_ip5_mismo_correo_dos_veces_en_la_misma_institucion(integ: Any) -> None:
    falso = ay.preparar(integ)
    a = ay.colegio(integ)
    primera = ay.invitar(integ, a, ay.cuerpo(a, 1))
    segunda = ay.invitar(integ, a, ay.cuerpo(a, 1, correo="PROFE1@SINTETICO.TEST",
                                             nombre="Otra Persona"))
    observado = {
        "status": (primera.status_code, segunda.status_code),
        "detalle": (ay.json_de(segunda) or {}).get("detail"),
        "invitaciones": integ.valor("select count(*) from invitaciones_docente"),
        "perfiles_teacher": integ.valor("select count(*) from profiles where role = 'teacher'"),
        "invitaciones_a_gotrue": len(falso.de_correo("invitar")),
    }
    assert observado == {"status": (201, 409), "detalle": "ya_invitado", "invitaciones": 1,
                         "perfiles_teacher": 1, "invitaciones_a_gotrue": 1}, f"IP5: {observado}"


def test_ip6_tope_por_admin(integ: Any) -> None:
    falso = ay.preparar(integ)
    antes = settings.invitaciones_por_hora
    settings.invitaciones_por_hora = 3
    try:
        a = ay.colegio(integ)
        otro_admin = integ.crear_perfil(a.tenant, rol="admin")
        uno = ay.invitar(integ, a, ay.cuerpo(a, 1))
        dos = ay.invitar(integ, a, ay.cuerpo(a, 2))
        _atrasar(integ, _id(uno))
        re_uno = ay.reenviar(integ, a.admin, _id(uno))
        filas = integ.valor("select count(*) from invitaciones_docente")
        cuarto = ay.invitar(integ, a, ay.cuerpo(a, 3))
        _atrasar(integ, _id(dos))
        quinto = ay.reenviar(integ, a.admin, _id(dos))
        del_otro = ay.invitar(integ, a, ay.cuerpo(a, 4), quien=otro_admin)
    finally:
        settings.invitaciones_por_hora = antes
    espera = int(cuarto.headers.get("retry-after", "0") or 0)
    observado = {
        "primeros_tres": (uno.status_code, dos.status_code, re_uno.status_code),
        "cuarto": (cuarto.status_code, (ay.json_de(cuarto) or {}).get("detail"),
                   0 < espera <= 3600),
        "quinto_reenvio": quinto.status_code,
        "filas_del_cuarto": integ.valor("select count(*) from invitaciones_docente") - filas - 1,
        "otro_admin": del_otro.status_code,
        "correos_pedidos": len(falso.de_correo("invitar")),
    }
    assert observado == {
        "primeros_tres": (201, 201, 202),
        "cuarto": (429, "demasiadas_invitaciones", True),
        "quinto_reenvio": 429,
        "filas_del_cuarto": 0,
        "otro_admin": 201,
        "correos_pedidos": 4,
    }, f"IP6: {observado}"


def test_ip7_espera_del_reenvio_y_aceptada(integ: Any) -> None:
    falso = ay.preparar(integ)
    a = ay.colegio(integ)
    inv = _id(ay.invitar(integ, a, ay.cuerpo(a)))
    inmediato = ay.reenviar(integ, a.admin, inv)
    _atrasar(integ, inv)
    luego = ay.reenviar(integ, a.admin, inv)
    pid = ay.perfil_de(integ, inv)
    ay.ejecutar(integ, "update profiles set force_password_reset = false where id = :p", p=pid)
    _atrasar(integ, inv)
    aceptada = ay.reenviar(integ, a.admin, inv)
    espera = int(inmediato.headers.get("retry-after", "0") or 0)
    observado = {
        "inmediato": (inmediato.status_code, (ay.json_de(inmediato) or {}).get("detail"),
                      0 < espera <= 60),
        "luego": (luego.status_code, (ay.json_de(luego) or {}).get("envios")),
        "aceptada": (aceptada.status_code, (ay.json_de(aceptada) or {}).get("detail")),
        "invitaciones_a_gotrue": len(falso.de_correo("invitar")),
    }
    assert observado == {
        "inmediato": (429, "espera_para_reenviar", True),
        "luego": (202, 2),
        "aceptada": (409, "ya_aceptada"),
        "invitaciones_a_gotrue": 2,
    }, f"IP7: {observado}"


def test_ip8_abrio_el_enlace_y_no_termino_recibe_recuperar(integ: Any) -> None:
    falso = ay.preparar(integ)
    a = ay.colegio(integ)
    inv = _id(ay.invitar(integ, a, ay.cuerpo(a)))
    pid = ay.perfil_de(integ, inv)
    falso.cuentas[pid]["confirmada"] = True  # canjeó el enlace (P4) y no puso la contraseña
    _atrasar(integ, inv)
    falso.llamadas.clear()
    r = ay.reenviar(integ, a.admin, inv)
    observado = {"status": r.status_code, "gotrue": falso.llamadas}
    assert observado == {
        "status": 202,
        "gotrue": [("estado_de_cuenta", str(pid)), ("recuperar", "profe1@sintetico.test")],
    }, f"IP8: {observado}"


def test_ip9_gotrue_caido_no_rompe_y_el_reenvio_recupera(integ: Any) -> None:
    falso = ay.preparar(integ)
    falso.fallar = True
    a = ay.colegio(integ)
    r = ay.invitar(integ, a, ay.cuerpo(a))
    inv = _id(r)
    pid = ay.perfil_de(integ, inv) if inv else None
    falso.fallar = False
    falso.llamadas.clear()
    _atrasar(integ, inv)
    re = ay.reenviar(integ, a.admin, inv)
    observado = {"alta": r.status_code, "filas": ay.filas_de(integ, pid)["invitaciones"]
                 if pid else None, "reenvio": re.status_code, "gotrue": falso.llamadas}
    correo = "profe1@sintetico.test"
    assert observado == {
        "alta": 201, "filas": 1, "reenvio": 202,
        "gotrue": [("estado_de_cuenta", str(pid)), ("crear_invitado", str(pid), correo),
                   ("invitar", correo)],
    }, f"IP9: {observado}"


def test_ip10_sin_clave_de_servicio_503(integ: Any) -> None:
    ay.preparar(integ)
    app.dependency_overrides[get_cuentas_de_invitacion] = lambda: None
    a = ay.colegio(integ)
    r = ay.invitar(integ, a, ay.cuerpo(a))
    observado = {"status": r.status_code, "detalle": (ay.json_de(r) or {}).get("detail"),
                 "filas": integ.valor("select count(*) from invitaciones_docente"),
                 "perfiles_teacher": integ.valor(
                     "select count(*) from profiles where role = 'teacher'")}
    assert observado == {"status": 503, "detalle": "invitar_no_configurado", "filas": 0,
                         "perfiles_teacher": 0}, f"IP10: {observado}"


def test_ip11_cuerpo_invalido_422_sin_eco(integ: Any) -> None:
    ay.preparar(integ)
    a = ay.colegio(integ)
    malos = {
        "correo_sin_arroba": ay.cuerpo(a, correo="profe-sintetica.test"),
        "nombre_vacio": ay.cuerpo(a, nombre=""),
        "campo_extra": ay.cuerpo(a, tenant_id=str(a.tenant)),
        "grupo_no_uuid": ay.cuerpo(a, group_id="grupo-zzz-sintetico"),
        "sin_correo": ay.cuerpo(a, correo=...),
    }
    vistos = {}
    for nombre, datos in malos.items():
        r = ay.invitar(integ, a, datos)
        valores = [str(v) for v in datos.values() if str(v) and str(v) != str(a.grupo)]
        vistos[nombre] = (r.status_code, [v for v in valores if v in r.text])
    observado = {"respuestas": vistos,
                 "filas": integ.valor("select count(*) from invitaciones_docente")}
    assert observado == {"respuestas": dict.fromkeys(malos, (422, [])), "filas": 0}, \
        f"IP11: {observado}"


def test_ip12_gotrue_se_llama_despues_de_responder(integ: Any) -> None:
    """La respuesta sale ANTES de cualquier llamada a GoTrue (§1.3): se mide el orden en ASGI."""
    falso = ay.preparar(integ)
    eventos: list[str] = []
    for nombre in ("estado_de_cuenta", "crear_invitado", "invitar", "recuperar"):
        original = getattr(falso, nombre)

        def envuelta(*args: Any, _o: Any = original, _n: str = nombre) -> Any:
            eventos.append(f"gotrue:{_n}")
            return _o(*args)
        setattr(falso, nombre, envuelta)

    async def app_que_marca(scope: Any, receive: Any, send: Any) -> None:
        async def enviar(mensaje: MutableMapping[str, Any]) -> None:
            await send(mensaje)
            if mensaje["type"] == "http.response.body" and not mensaje.get("more_body"):
                eventos.append("respuesta_enviada")
        await app(scope, receive, enviar)

    cliente = TestClient(app_que_marca, raise_server_exceptions=False)
    a = ay.colegio(integ)
    r = cliente.post(ay.RUTA, json=ay.cuerpo(a), headers=integ.headers(a.admin))
    observado = {"status": r.status_code, "eventos": eventos}
    assert observado == {
        "status": 201,
        "eventos": ["respuesta_enviada", "gotrue:estado_de_cuenta", "gotrue:crear_invitado",
                    "gotrue:invitar"],
    }, f"IP12: {observado}"


def test_ip14_el_resultado_del_envio_queda_solo_para_el_operador(integ: Any) -> None:
    """IP14 (H-3): `ultimo_resultado` guarda lo que dijo el envío; ninguna respuesta lo trae."""
    falso = ay.preparar(integ)
    a, b = ay.colegio(integ, "GA"), ay.colegio(integ, "GB")
    integ.crear_perfil(b.tenant, rol="teacher")
    falso.sembrar("ajena@sintetico.test")
    nueva = ay.invitar(integ, a, ay.cuerpo(a, 1))
    ajena = ay.invitar(integ, a, ay.cuerpo(a, 2, correo="ajena@sintetico.test"))
    falso.limite = True
    llena = ay.invitar(integ, a, ay.cuerpo(a, 3))
    falso.limite, falso.fallar = False, True
    caida = ay.invitar(integ, a, ay.cuerpo(a, 4))
    falso.fallar = False
    lista = ay.listar(integ, a.admin)
    textos = " ".join(r.text for r in (nueva, ajena, llena, caida, lista))
    observado = {
        "resultados": [ay.resultado_de(integ, _id(r)) for r in (nueva, ajena, llena, caida)],
        "estados_hacia_afuera": sorted(i.get("estado") for i in (ay.json_de(lista) or [])),
        "claves": sorted({k for i in (ay.json_de(lista) or []) for k in i}),
        "el_interno_en_alguna_respuesta": any(x in textos for x in (
            "ultimo_resultado", "cuenta_ajena", "limite_de_correos", "fallo")),
    }
    assert observado == {
        "resultados": ["enviada", "cuenta_ajena", "limite_de_correos", "fallo"],
        "estados_hacia_afuera": ["enviada"] * 4,
        "claves": ["correo", "enviada_en", "envios", "estado", "group_code", "group_id", "id",
                   "nombre"],
        "el_interno_en_alguna_respuesta": False,
    }, f"IP14: {observado}"


def test_ip15_tope_global_de_todas_las_instituciones(integ: Any) -> None:
    """IP15 (H-3): la suma de todos los admins no pasa de `invitaciones_globales_por_hora`."""
    ay.preparar(integ)
    antes = settings.invitaciones_globales_por_hora
    settings.invitaciones_globales_por_hora = 3
    try:
        a, b = ay.colegio(integ, "GA"), ay.colegio(integ, "GB")
        pasan = [ay.invitar(integ, a, ay.cuerpo(a, 1)).status_code,
                 ay.invitar(integ, a, ay.cuerpo(a, 2)).status_code,
                 ay.invitar(integ, b, ay.cuerpo(b, 3)).status_code]
        de_b = ay.invitar(integ, b, ay.cuerpo(b, 4))
        de_a = ay.invitar(integ, a, ay.cuerpo(a, 5))
    finally:
        settings.invitaciones_globales_por_hora = antes
    observado = {
        "primeras_tres": pasan,
        "cuarta_de_b": (de_b.status_code, (ay.json_de(de_b) or {}).get("detail"),
                        bool(de_b.headers.get("retry-after"))),
        "quinta_de_a": de_a.status_code,
        "filas": integ.valor("select count(*) from invitaciones_docente"),
    }
    assert observado == {
        "primeras_tres": [201, 201, 201],
        "cuarta_de_b": (429, "demasiadas_invitaciones", True),
        "quinta_de_a": 429,
        "filas": 3,
    }, f"IP15: {observado}"


def _filas_de_todo(integ: Any, pid: Any) -> dict[str, Any]:
    return {t: integ.valor(f"select count(*) from {t} where {c} = :p", p=pid) for t, c in (
        ("profiles", "id"), ("memberships", "profile_id"), ("teacher_groups", "teacher_id"),
        ("invitaciones_docente", "profile_id"))}


def test_ip16_cancelar_una_invitacion_no_aceptada(integ: Any) -> None:
    """IP16 (H-4a): borra todo lo que nació con la invitación; la cuenta de GoTrue solo si es nuestra."""
    falso = ay.preparar(integ)
    a, b = ay.colegio(integ, "GA"), ay.colegio(integ, "GB")
    ajena = falso.sembrar("ajena@sintetico.test")
    nueva = _id(ay.invitar(integ, a, ay.cuerpo(a, 1)))
    otra = _id(ay.invitar(integ, a, ay.cuerpo(a, 2, correo="ajena@sintetico.test")))
    abierta = _id(ay.invitar(integ, a, ay.cuerpo(a, 3)))
    aceptada = _id(ay.invitar(integ, a, ay.cuerpo(a, 4)))
    p_nueva, p_otra, p_abierta, p_aceptada = (ay.perfil_de(integ, i) for i in (nueva, otra, abierta, aceptada))
    falso.cuentas[p_abierta]["confirmada"] = True  # abrió el enlace y no terminó
    ay.ejecutar(integ, "update profiles set force_password_reset = false where id = :p", p=p_aceptada)
    profe_a = ay.profe_de(integ, a)
    ajenos = {"b": ay.cancelar(integ, b.admin, nueva).status_code,
              "profe": ay.cancelar(integ, profe_a, nueva).status_code}
    falso.fallar = True
    caido = ay.cancelar(integ, a.admin, nueva).status_code
    falso.fallar = False
    falso.llamadas.clear()
    codigos = [ay.cancelar(integ, a.admin, i).status_code for i in (nueva, otra, abierta, aceptada)]
    observado = {
        "ajenos": ajenos, "gotrue_caido": caido, "codigos": codigos,
        "llamadas_borrar": [c[1] for c in falso.llamadas if c[0] == "borrar"],
        "filas_nueva": _filas_de_todo(integ, p_nueva), "filas_otra": _filas_de_todo(integ, p_otra),
        "filas_aceptada": _filas_de_todo(integ, p_aceptada),
        "cuenta_ajena_sigue": ajena in falso.cuentas, "cuenta_abierta_sigue": p_abierta in falso.cuentas,
        "otra_vez_el_mismo_correo": ay.invitar(integ, a, ay.cuerpo(a, 1)).status_code,
    }
    vacias = {"profiles": 0, "memberships": 0, "teacher_groups": 0, "invitaciones_docente": 0}
    assert observado == {
        "ajenos": {"b": 404, "profe": 403}, "gotrue_caido": 502, "codigos": [204, 204, 204, 409],
        "llamadas_borrar": [str(p_nueva)],
        "filas_nueva": vacias, "filas_otra": vacias,
        "filas_aceptada": {"profiles": 1, "memberships": 1, "teacher_groups": 1,
                           "invitaciones_docente": 1},
        "cuenta_ajena_sigue": True, "cuenta_abierta_sigue": True,
        "otra_vez_el_mismo_correo": 201,
    }, f"IP16: {observado}"


def test_ip17_los_invitados_pendientes_no_entran_al_reparto(integ: Any) -> None:
    """IP17 (H-4b): sin aceptar no salen en /admin/presupuestos ni se les recarga; al aceptar, sí."""
    falso = ay.preparar(integ)
    a = ay.colegio(integ)
    falso.sembrar("ajena@sintetico.test")
    p_nueva = ay.perfil_de(integ, _id(ay.invitar(integ, a, ay.cuerpo(a, 1))))
    p_otra = ay.perfil_de(integ, _id(ay.invitar(integ, a, ay.cuerpo(a, 2, correo="ajena@sintetico.test"))))
    de_cli = integ.crear_perfil(a.tenant, rol="teacher")  # alta de la CLI con contraseña temporal
    ay.ejecutar(integ, "update profiles set force_password_reset = true where id = :p", p=de_cli)

    def en_el_panel() -> list[str]:
        r = ay.client.get("/admin/presupuestos", headers=integ.headers(a.admin))
        return sorted(str(f.get("teacher_id")) for f in (ay.json_de(r) or {}).get("profes", []))

    antes = en_el_panel()
    recarga = ay.client.post(f"/admin/presupuestos/{p_nueva}/recargar", json={"monto": 5, "llave": "llave-ip17-sint"},
                             headers=integ.headers(a.admin))
    ay.client.post("/auth/contrasena", json={"nueva": CLAVE_NUEVA}, headers=integ.headers(p_nueva))
    despues = en_el_panel()
    observado = {
        "antes": [x in antes for x in (str(p_nueva), str(p_otra), str(de_cli), str(a.admin))],
        "recarga_pendiente": (recarga.status_code, (ay.json_de(recarga) or {}).get("detail")),
        "despues": [x in despues for x in (str(p_nueva), str(p_otra), str(de_cli), str(a.admin))],
    }
    assert observado == {
        "antes": [False, False, True, True],
        "recarga_pendiente": (404, "Profe no encontrado en tu institución."),  # el detail del bolsillo
        "despues": [True, False, True, True],
    }, f"IP17: {observado}"
