"""Cierre de la auditoría de seguridad 03 — `docs/ESPEC_autorregistro.md` §11.

  AR12  C18  (S-7) si la segunda transacción falla, no queda una cuenta huérfana.
  AR13  C20  (S-3) los códigos inventados no agotan el registro de los demás.
  AR14  C22  la contraseña de más de 72 BYTES da 422 y no llega a GoTrue.
  AR15  C23  sin lista de versiones del aviso, el registro encendido responde 503.

Las piezas se llaman por su módulo (`service_mod.…`) para que los tramposos
ZR24 en adelante las alcancen.
"""
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text

from src.main import app
from src.registro import limite as limite_mod
from src.registro import service as service_mod
from src.registro.cuentas import get_cuentas_de_registro
from src.shared.config import settings
from tests.registro import _ayuda as ay

pytestmark = pytest.mark.integ

NO_DISPONIBLE = (502, {"detail": "registro_no_disponible"})


# =============================================================================
# AR12 — C18 (S-7)
# =============================================================================
async def _confirmar_que_falla(db: Any, reserva: Any, datos: Any) -> None:
    """Una T2 que falla DE VERDAD: SQL inválido, y la transacción queda rota."""
    await db.execute(text("select 1/0"))


def _tras_el_fallo(integ: Any, cuentas: Any, a: ay.Aula, n: int, r: Any) -> dict[str, Any]:
    pedido = cuentas.creadas[-1][0] if cuentas.creadas else None
    return {
        "respuesta": ay.estado_y_cuerpo(r),
        "borrar_la_cuenta_del_perfil": pedido is not None and cuentas.borradas[-1:] == [pedido],
        "cuenta": pedido in cuentas.cuentas,
        "perfil": ay.perfil_de(integ, a.doc(n)) is not None,
        "solicitudes": [e for _, e in ay.solicitudes(integ, group_id=a.grupo)],
        "usos": ay.usos(integ, a.grupo),
    }


def test_ar12_si_falla_la_confirmacion_no_queda_cuenta(integ, monkeypatch) -> None:
    """AR12 (C18): T2 falla -> 502, la cuenta se borra y no queda nada; el reintento entra."""
    cuentas = ay.preparar(integ)
    a = ay.aula(integ)
    buena = service_mod._confirmar
    monkeypatch.setattr(service_mod, "_confirmar", _confirmar_que_falla)
    caso_a = _tras_el_fallo(integ, cuentas, a, 1, ay.registrar(ay.cuerpo(a.codigo, 1)))
    monkeypatch.setattr(service_mod, "_confirmar", buena)
    caso_a["reintento"] = ay.registrar(ay.cuerpo(a.codigo, 1)).status_code
    caso_a["tras_el_reintento"] = [e for _, e in ay.solicitudes(integ, group_id=a.grupo)]

    # Si además GoTrue no deja borrar: no se puede afirmar que no haya cuenta,
    # así que las filas se quedan en `creando` (falla cerrado, §1.5).
    b = ay.aula(integ)
    monkeypatch.setattr(service_mod, "_confirmar", _confirmar_que_falla)
    cuentas.fallar_borrar = True
    caso_b = _tras_el_fallo(integ, cuentas, b, 2, ay.registrar(ay.cuerpo(b.codigo, 2)))
    caso_b["lista_del_profe"] = ay.lista(integ, b.profe, b.grupo)
    observado = {"t2_falla": caso_a, "y_no_se_puede_borrar": caso_b}
    assert observado == {
        "t2_falla": {"respuesta": NO_DISPONIBLE, "borrar_la_cuenta_del_perfil": True,
                     "cuenta": False, "perfil": False, "solicitudes": [], "usos": 0,
                     "reintento": 201, "tras_el_reintento": ["pendiente"]},
        "y_no_se_puede_borrar": {"respuesta": NO_DISPONIBLE,
                                 "borrar_la_cuenta_del_perfil": True, "cuenta": True,
                                 "perfil": True, "solicitudes": ["creando"], "usos": 1,
                                 "lista_del_profe": []},
    }, f"AR12: {observado}"


# =============================================================================
# AR13 — C20 (S-3 b)
# =============================================================================
def _desde(ip: str, datos: dict[str, Any]) -> Any:
    """Un registro que llega por el proxy desde esa IP (`PROXIES_DE_CONFIANZA = 1`)."""
    return ay.registrar(datos, **{"X-Forwarded-For": ip})


def test_ar13_los_codigos_inventados_no_agotan_el_registro(integ) -> None:
    """AR13 (C20): la basura de muchas IP no llena el tope global ni el de código."""
    ay.preparar(integ)
    a = ay.aula(integ)
    tope, saltos = limite_mod.GLOBAL.tope, settings.proxies_de_confianza
    try:
        limite_mod.GLOBAL.tope = 3
        settings.proxies_de_confianza = 1
        basura = [_desde(f"198.51.100.{i}", ay.cuerpo(f"ZZZZ{i:04d}", 1)).status_code
                  for i in range(5)]
        llaves_tras_la_basura = limite_mod.POR_CODIGO.llaves()
        validos = [_desde(f"203.0.113.{n}", ay.cuerpo(a.codigo, n)) for n in range(1, 5)]
        llaves_al_final = limite_mod.POR_CODIGO.llaves()
    finally:
        limite_mod.GLOBAL.tope, settings.proxies_de_confianza = tope, saltos
        limite_mod.reiniciar()
    observado = {
        "basura": basura, "llaves_por_codigo_tras_la_basura": llaves_tras_la_basura,
        "con_codigo_valido": [r.status_code for r in validos],
        "el_cuarto": (ay.campo(validos[3], "detail"),
                      int(validos[3].headers.get("Retry-After", "0")) > 0),
        "llaves_por_codigo_al_final": llaves_al_final,
        "solicitudes": len(ay.solicitudes(integ, group_id=a.grupo)),
    }
    assert observado == {
        "basura": [403] * 5, "llaves_por_codigo_tras_la_basura": 0,
        "con_codigo_valido": [201, 201, 201, 429], "el_cuarto": ("demasiados_intentos", True),
        "llaves_por_codigo_al_final": 1, "solicitudes": 3,
    }, f"AR13: {observado}"


# =============================================================================
# AR14 — C22 (la contraseña en bytes)
# =============================================================================
def test_ar14_la_contrasena_de_mas_de_72_bytes_da_422(integ) -> None:
    """AR14 (C22): 40 eñes (80 bytes) -> 422 sin escribir ni llamar a GoTrue; 36 entran."""
    cuentas = ay.preparar(integ)
    a = ay.aula(integ)
    larga = ay.registrar(ay.cuerpo(a.codigo, 1, contrasena="ñ" * 40))
    observado = {
        "de_80_bytes": larga.status_code,
        "dice_por_que": "72 bytes" in larga.text,
        "sin_escribir": (ay.estudiantes(integ), len(ay.solicitudes(integ)),
                         len(cuentas.creadas), ay.usos(integ, a.grupo)),
        "de_72_bytes": ay.registrar(ay.cuerpo(a.codigo, 2, contrasena="ñ" * 36)).status_code,
    }
    assert observado == {
        "de_80_bytes": 422, "dice_por_que": True, "sin_escribir": (0, 0, 0, 0),
        "de_72_bytes": 201,
    }, f"AR14: {observado}"


# =============================================================================
# AR15 — C23 (sin lista de avisos, el registro no abre)
# =============================================================================
def test_ar15_sin_lista_de_avisos_el_registro_no_abre(integ) -> None:
    """AR15 (C23): lista vacía -> 503 propio y nada escrito; con lista, 201."""
    cuentas = ay.preparar(integ)
    a = ay.aula(integ)
    lista = settings.aviso_versiones_validas
    try:
        settings.aviso_versiones_validas = ""
        vacia = ay.registrar(ay.cuerpo(a.codigo, 1))
        sin_escribir = (ay.estudiantes(integ), len(ay.solicitudes(integ)),
                        len(cuentas.creadas), ay.usos(integ, a.grupo))
        # Con el registro APAGADO (sin clave de servicio) manda el motivo de siempre.
        app.dependency_overrides[get_cuentas_de_registro] = lambda: None
        apagado = ay.registrar(ay.cuerpo(a.codigo, 1))
        app.dependency_overrides[get_cuentas_de_registro] = lambda: cuentas
    finally:
        settings.aviso_versiones_validas = lista
    observado = {
        "lista_vacia": ay.estado_y_cuerpo(vacia), "sin_escribir": sin_escribir,
        "lista_vacia_y_registro_apagado": ay.estado_y_cuerpo(apagado),
        "con_la_lista": ay.registrar(ay.cuerpo(a.codigo, 1)).status_code,
    }
    assert observado == {
        "lista_vacia": (503, {"detail": "registro_sin_aviso"}), "sin_escribir": (0, 0, 0, 0),
        "lista_vacia_y_registro_apagado": (503, {"detail": "registro_no_configurado"}),
        "con_la_lista": 201,
    }, f"AR15: {observado}"
