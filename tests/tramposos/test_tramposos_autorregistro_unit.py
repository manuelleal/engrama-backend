"""Tramposos no-integ ZR20-ZR23 del autorregistro — `docs/ESPEC_autorregistro.md` §3.

Mismo patrón que `test_tramposos_login_piloto_unit.py`: se rompe la pieza en
el módulo donde el test la usa y se exige `AssertionError` con el mecanismo.

  ZR20  otro módulo usa la clave de servicio            -> SR1
  ZR21  la huella del código es SHA-256 sin llave       -> UR1
  ZR22  la ventana del limitador nunca vence            -> UL1
  ZR23  `RegistroIn.contrasena` con mínimo 6            -> UR2
  ZR28  (§11.2) IPv6 por dirección completa, como antes  -> UL3
"""
from __future__ import annotations

import hashlib
from collections import deque
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import Field, create_model

from src.registro import codigos as codigos_mod
from src.registro import limite as limite_mod
from src.registro import schemas as schemas_mod
from tests.registro import test_limite as tl
from tests.registro import test_unit as tu

Aplicar = Callable[[pytest.MonkeyPatch], None]

_LEER_BUENO = tu.leer_fuentes


def _con_un_modulo_que_usa_la_clave() -> dict[str, str]:
    """ZR20: como si `auth/router.py` armara su propio adaptador con la clave."""
    fuentes = _LEER_BUENO()
    fuentes["auth/router.py"] += (
        "\nadmin = GoTrueAdmin(url, settings.supabase_service_role_key)\n")
    return fuentes


def _huella_sin_llave(codigo: str) -> str:
    """ZR21: con un volcado de la base, todos los códigos saldrían en segundos."""
    return hashlib.sha256(codigos_mod.normalizar(codigo).encode()).hexdigest()


def _nunca_vence(self: limite_mod.Limitador, llave: str, ahora: float) -> deque[float] | None:
    """ZR22: los eventos viejos se quedan para siempre."""
    return self._eventos.get(llave)


_ClaveCorta = create_model("RegistroConClaveCorta", __base__=schemas_mod.RegistroIn,
                           contrasena=(str, Field(min_length=6, max_length=72)))


def _parche(modulo: Any, nombre: str, valor: Any) -> Aplicar:
    return lambda mp: mp.setattr(modulo, nombre, valor)


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[[], None], str]] = {
    "ZR20": (_parche(tu, "leer_fuentes", _con_un_modulo_que_usa_la_clave),
             tu.test_sr1_la_clave_de_servicio_esta_cercada,
             r"SR1: \{'fuera': \{'supabase_service_role_key': \['auth/router\.py'\], "
             r"'GoTrueAdmin\(': \['auth/router\.py'\]"),
    "ZR21": (_parche(codigos_mod, "huella", _huella_sin_llave), tu.test_ur1_el_codigo_puro,
             r"'es_sha256_a_secas': True"),
    "ZR22": (_parche(limite_mod.Limitador, "_vigentes", _nunca_vence),
             tl.test_ul1_el_limitador_puro, r"'vencio_el_primero': 1,"),
    "ZR23": (_parche(schemas_mod, "RegistroIn", _ClaveCorta),
             tu.test_ur2_una_sola_politica_de_contrasena, r"'registro': \(6, 72\)"),
    # Auditoría 03 (ESPEC §11.2): sin agrupar, cada dirección de un /64 es una llave.
    "ZR28": (_parche(limite_mod, "_agrupar", lambda valor: valor),
             tl.test_ul3_ipv6_se_cuenta_por_su_red_64,
             r"UL3: \{'una_del_64': '2001:db8:1:2:aaaa::1', "
             r"'otra_del_mismo_64': '2001:db8:1:2:bbbb:cccc:dddd:eeee'"),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        test_real()
