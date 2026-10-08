"""Cierre de la auditoría de seguridad 03 — `docs/ESPEC_autorregistro.md` §11.

  AR12  C18  (S-7) si la segunda transacción falla, no queda una cuenta huérfana.

Las piezas se llaman por su módulo (`service_mod.…`) para que los tramposos
ZR24 en adelante las alcancen.
"""
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text

from src.registro import service as service_mod
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
