"""El límite de intentos — `docs/ESPEC_autorregistro.md` §1.6, C10, C15 y C15b.

  AR10  C10   (integ) 60 códigos malos por IP; el encabezado falso no ayuda; tope por código.
  UL1   C15   el limitador, puro, con el reloj inyectado.
  UL2   C15b  la IP del visitante, pura: nunca un valor que el visitante pudo escribir.
  UL3   C19   (auditoría 03, S-3) una dirección IPv6 se cuenta por su red /64.

AR10 llama a las funciones por el módulo (`limite.…`) para que un tramposo que
las reemplace ahí (ZR3, ZR4) las alcance.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.registro import limite
from src.shared.config import settings
from tests.registro import _ayuda as ay

MALO = "ZZZZ{:04d}"


def _malos(desde: int, cuantos: int, **headers: str) -> list[int]:
    return [ay.registrar(ay.cuerpo(MALO.format(i), 1), **headers).status_code
            for i in range(desde, desde + cuantos)]


def _con_reloj(desfase: list[float]) -> dict[limite.Limitador, Any]:
    """Pone a los cuatro contadores un reloj que el test adelanta. Devuelve los originales."""
    originales = {lim: lim.reloj for lim in limite._TODOS}
    for lim, reloj in originales.items():
        lim.reloj = lambda reloj=reloj: reloj() + desfase[0]  # type: ignore[misc]
    return originales


@pytest.mark.integ
def test_ar10_limite_de_intentos(integ) -> None:
    """AR10 (C10): el 61 da 429; ni un encabezado falso ni un código bueno lo saltan."""
    ay.preparar(integ)
    a = ay.aula(integ)
    desfase = [0.0]
    originales = _con_reloj(desfase)
    tope_por_codigo, saltos = limite.POR_CODIGO.tope, settings.proxies_de_confianza
    try:
        sesenta = _malos(0, 60)
        r61 = ay.registrar(ay.cuerpo(MALO.format(60), 1))
        falsos = {"X-Forwarded-For": "198.51.100.7", "X-Real-IP": "198.51.100.7",
                  "Forwarded": "for=198.51.100.7"}
        por_ip = {
            "sesenta": sorted(set(sesenta)),
            "el_61": (r61.status_code, ay.campo(r61, "detail"),
                      int(r61.headers.get("Retry-After", "0")) > 0),
            "con_encabezados_falsos": _malos(61, 1, **falsos),
            "con_un_codigo_bueno": ay.registrar(ay.cuerpo(a.codigo, 1)).status_code,
        }
        desfase[0] = limite.VENTANA_S + 1
        por_ip["pasada_la_ventana"] = _malos(62, 1)

        limite.reiniciar()
        settings.proxies_de_confianza = 1
        tras_proxy = [ay.registrar(ay.cuerpo(MALO.format(i), 1),
                                   **{"X-Forwarded-For": f"198.51.100.{i}, 203.0.113.9"}
                                   ).status_code for i in range(61)]
        limite.reiniciar()
        limite.POR_CODIGO.tope = 3
        no_cabe = ay.cuerpo(a.codigo, 1, codigo_estudiantil="9" * 24)
        por_codigo = [ay.registrar(no_cabe, **{"X-Forwarded-For": f"203.0.113.{i}"}).status_code
                      for i in range(4)]
    finally:
        limite.POR_CODIGO.tope, settings.proxies_de_confianza = tope_por_codigo, saltos
        for lim, reloj in originales.items():
            lim.reloj = reloj
        limite.reiniciar()
    observado = {"por_ip": por_ip,
                 "detras_de_un_proxy": (sorted(set(tras_proxy[:60])), tras_proxy[60]),
                 "por_codigo": por_codigo}
    assert observado == {
        "por_ip": {"sesenta": [403], "el_61": (429, "demasiados_intentos", True),
                   "con_encabezados_falsos": [429], "con_un_codigo_bueno": 429,
                   "pasada_la_ventana": [403]},
        "detras_de_un_proxy": ([403], 429),
        "por_codigo": [403, 403, 403, 429],
    }, f"AR10: {observado}"


def test_ul1_el_limitador_puro() -> None:
    """UL1 (C15): tope, segundos de espera, ventana que vence, purga y tabla llena."""
    ahora = [1000.0]
    lim = limite.Limitador(3, ventana_s=600, max_llaves=2, reloj=lambda: ahora[0])
    esperas = []
    for _ in range(3):
        esperas.append(lim.espera("a"))
        lim.anotar("a")
        ahora[0] += 10
    al_tope = lim.espera("a")                      # el primero fue en t=1000; ahora t=1030
    ahora[0] = 1000 + 600
    vencio_el_primero = lim.espera("a")            # quedan 2 vigentes: ya cabe otro
    lim.anotar("b")
    tabla_llena = (lim.llaves(), lim.espera("c"))  # 2 llaves vigentes y una nueva
    ahora[0] += 601
    tras_purgar = (lim.espera("c"), lim.llaves())
    observado = {"esperas": esperas, "al_tope": al_tope, "vencio_el_primero": vencio_el_primero,
                 "tabla_llena": tabla_llena, "tras_purgar": tras_purgar}
    assert observado == {
        "esperas": [0, 0, 0], "al_tope": 570, "vencio_el_primero": 0, "tabla_llena": (2, 600),
        "tras_purgar": (0, 0),
    }, f"UL1: {observado}"


def test_ul2_la_ip_del_visitante_pura() -> None:
    """UL2 (C15b): lo que el visitante escribe a la izquierda nunca decide la llave."""
    ip = limite.ip_del_visitante
    observado = {
        "sin_proxies_ignora_el_encabezado": ip("10.0.0.9", "198.51.100.7", 0),
        "sin_proxies_sin_conexion": ip(None, "198.51.100.7", 0),
        "un_proxy": ip("172.18.0.5", "198.51.100.7, 203.0.113.9", 1),
        "un_proxy_con_otra_mentira": ip("172.18.0.5", "evil, 6.6.6.6, 203.0.113.9", 1),
        "dos_proxies": ip("172.18.0.5", "198.51.100.7, 203.0.113.9, 10.1.1.1", 2),
        "con_espacios_y_vacios": ip("172.18.0.5", " 198.51.100.7 ,, 203.0.113.9 , ", 1),
        "menos_valores_que_saltos": ip("172.18.0.5", "203.0.113.9", 2),
        "sin_encabezado": ip("172.18.0.5", None, 1),
    }
    assert observado == {
        "sin_proxies_ignora_el_encabezado": "10.0.0.9", "sin_proxies_sin_conexion": "desconocida",
        "un_proxy": "203.0.113.9", "un_proxy_con_otra_mentira": "203.0.113.9",
        "dos_proxies": "203.0.113.9", "con_espacios_y_vacios": "203.0.113.9",
        "menos_valores_que_saltos": "desconocida", "sin_encabezado": "desconocida",
    }, f"UL2: {observado}"


def test_ul3_ipv6_se_cuenta_por_su_red_64() -> None:
    """UL3 (C19): rotar direcciones dentro de un /64 no cambia la llave; IPv4 no se agrupa."""
    ip = limite.ip_del_visitante
    casa = "2001:db8:1:2"
    observado = {
        "una_del_64": ip("172.18.0.5", f"198.51.100.7, {casa}:aaaa::1", 1),
        "otra_del_mismo_64": ip("172.18.0.5", f"{casa}:bbbb:cccc:dddd:eeee", 1),
        "en_mayusculas_y_larga": ip("172.18.0.5", "2001:0DB8:0001:0002:0000:0000:0000:0009", 1),
        "sin_proxies": ip(f"{casa}::7", None, 0),
        "otro_64": ip("172.18.0.5", "2001:db8:1:3::1", 1),
        "ipv4_envuelta": ip("172.18.0.5", "::ffff:203.0.113.9", 1),
        "ipv4_entera": (ip("172.18.0.5", "203.0.113.9", 1), ip("172.18.0.5", "203.0.113.10", 1)),
        "lo_que_no_es_una_ip": ip("testclient", None, 0),
    }
    red = f"{casa}::/64"
    assert observado == {
        "una_del_64": red, "otra_del_mismo_64": red, "en_mayusculas_y_larga": red,
        "sin_proxies": red, "otro_64": "2001:db8:1:3::/64", "ipv4_envuelta": "203.0.113.9",
        "ipv4_entera": ("203.0.113.9", "203.0.113.10"), "lo_que_no_es_una_ip": "testclient",
    }, f"UL3: {observado}"
