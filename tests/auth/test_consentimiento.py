"""Registro del consentimiento (aviso de datos, Ley 1581) — `docs/ESPEC_consentimiento.md`.

  CN1  C1  aceptar y verlo en `/auth/me` y `/auth/session`; una fila y una auditoría.
  CN2  C2  nadie registra por otro: ni por error del servidor ni mandando `profile_id`.
  CN3  C3  repetir la versión no cambia nada; otra versión deja historial y pasa a ser la última.
  CN4  C4  una versión vacía, con espacios al borde, larga, numérica o ausente da 422.
  CN5  C5  con contraseña temporal, 403; sin consentimiento, el servidor no bloquea.

Reglas (las de `test_login_piloto.py`): el cliente con
`raise_server_exceptions=False` (un 500 es una respuesta, y por tanto un
`AssertionError`), las claves con `.get()`, y lo observado en un dict que se
compara ENTERO y va en el mensaje, para que la regex de cada tramposo vea el
mecanismo. Datos sintéticos.
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

V1 = "2026-10-v1"
V2 = "2026-11-v2"


def _json(r: httpx.Response) -> dict[str, Any]:
    try:
        datos = r.json()
    except ValueError:
        return {}
    return datos if isinstance(datos, dict) else {}


def aceptar(integ: Any, perfil: UUID, cuerpo: Any, **extra: str) -> httpx.Response:
    return client.post("/auth/consentimiento", json=cuerpo,
                       headers={**integ.headers(perfil), **extra})


def version_en_me(integ: Any, perfil: UUID, ruta: str = "/auth/me", **extra: str) -> Any:
    """`consent_version` de `/auth/me`; `"(sin la clave)"` si el campo no viene."""
    h = {**integ.headers(perfil), **extra}
    r = client.get(ruta, headers=h) if ruta == "/auth/me" else client.post(ruta, headers=h)
    return _json(r).get("consent_version", "(sin la clave)")


def filas(integ: Any, perfil: UUID) -> list[str]:
    """Las versiones guardadas de ese perfil, en el orden en que se crearon."""
    from sqlalchemy import text

    async def _q() -> list[str]:
        async with integ.Session() as db:
            r = await db.execute(text("select version from consentimientos "
                                      "where profile_id = :p order by id"), {"p": perfil})
            return [str(v) for v in r.scalars()]

    return list(integ.run(_q()))


def auditorias(integ: Any, perfil: UUID) -> int:
    return int(integ.valor("select count(*) from audit_logs where user_id = :p "
                           "and action_type = 'consent_accept' and result = 'success'", p=perfil))


def _fecha_en_base(integ: Any, perfil: UUID, version: str) -> Any:
    return integ.valor("select accepted_at from consentimientos "
                       "where profile_id = :p and version = :v", p=perfil, v=version)


def _misma_fecha(texto: Any, en_base: Any) -> bool:
    """El `accepted_at` de la respuesta es, con zona, el instante guardado."""
    if not isinstance(texto, str) or en_base is None:
        return False
    try:
        leida = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return False
    return leida.tzinfo is not None and leida == en_base


# =============================================================================
# CN1 — C1: aceptar y verlo
# =============================================================================
def test_cn1_aceptar_y_verlo_en_auth_me(integ) -> None:
    """CN1 (C1): null antes; después, la versión en me y session, 1 fila y 1 auditoría."""
    ana = integ.crear_perfil(integ.crear_tenant())
    antes = version_en_me(integ, ana)
    r = aceptar(integ, ana, {"version": V1})
    observado = {
        "antes": antes,
        "respuesta": (r.status_code, _json(r).get("version")),
        "fecha_de_la_fila": _misma_fecha(_json(r).get("accepted_at"),
                                         _fecha_en_base(integ, ana, V1)),
        "me": version_en_me(integ, ana),
        "session": version_en_me(integ, ana, "/auth/session"),
        "filas": filas(integ, ana),
        "auditorias": auditorias(integ, ana),
    }
    assert observado == {
        "antes": None, "respuesta": (200, V1), "fecha_de_la_fila": True,
        "me": V1, "session": V1, "filas": [V1], "auditorias": 1,
    }, f"CN1: {observado}"


# =============================================================================
# CN2 — C2: nadie registra por otro
# =============================================================================
def test_cn2_nadie_registra_el_consentimiento_de_otro(integ) -> None:
    """CN2 (C2): A acepta y B queda intacto; `profile_id` o `accepted_at` en el cuerpo, 422."""
    tenant = integ.crear_tenant()
    a, b = integ.crear_perfil(tenant), integ.crear_perfil(tenant)
    observado = {
        "a_acepta": aceptar(integ, a, {"version": V1}).status_code,
        "con_profile_id_de_b": aceptar(integ, a, {"version": V2,
                                                 "profile_id": str(b)}).status_code,
        "con_fecha_del_cliente": aceptar(
            integ, a, {"version": V2, "accepted_at": "2020-01-01T00:00:00Z"}).status_code,
        "de_a": (version_en_me(integ, a), filas(integ, a)),
        "de_b": (version_en_me(integ, b), filas(integ, b), auditorias(integ, b)),
        "filas_en_total": int(integ.valor("select count(*) from consentimientos")),
    }
    assert observado == {
        "a_acepta": 200, "con_profile_id_de_b": 422, "con_fecha_del_cliente": 422,
        "de_a": (V1, [V1]), "de_b": (None, [], 0), "filas_en_total": 1,
    }, f"CN2: {observado}"


# =============================================================================
# CN3 — C3: idempotencia e historial
# =============================================================================
def test_cn3_idempotente_por_version_y_con_historial(integ) -> None:
    """CN3 (C3): la misma versión no cambia nada; otra queda de última; la vieja no vuelve."""
    ana = integ.crear_perfil(integ.crear_tenant())
    primera = _json(aceptar(integ, ana, {"version": V1})).get("accepted_at")
    repetida = aceptar(integ, ana, {"version": V1})
    tras_repetir = {"status": repetida.status_code,
                    "misma_fecha": primera is not None
                    and _json(repetida).get("accepted_at") == primera,
                    "filas": filas(integ, ana), "auditorias": auditorias(integ, ana)}
    otra = aceptar(integ, ana, {"version": V2})
    tras_otra = {"status": otra.status_code, "me": version_en_me(integ, ana),
                 "filas": filas(integ, ana), "auditorias": auditorias(integ, ana)}
    vieja = aceptar(integ, ana, {"version": V1})
    tras_la_vieja = {"status": vieja.status_code,
                     "su_fecha_original": _json(vieja).get("accepted_at") == primera,
                     "me": version_en_me(integ, ana), "filas": filas(integ, ana)}
    observado = {"repetir": tras_repetir, "otra_version": tras_otra,
                 "la_vieja_otra_vez": tras_la_vieja}
    assert observado == {
        "repetir": {"status": 200, "misma_fecha": True, "filas": [V1], "auditorias": 1},
        "otra_version": {"status": 200, "me": V2, "filas": [V1, V2], "auditorias": 2},
        "la_vieja_otra_vez": {"status": 200, "su_fecha_original": True, "me": V2,
                              "filas": [V1, V2]},
    }, f"CN3: {observado}"


# =============================================================================
# CN4 — C4: versiones inválidas
# =============================================================================
INVALIDOS: dict[str, Any] = {
    "vacia": {"version": ""},
    "solo_espacios": {"version": " "},
    "espacio_al_principio": {"version": " v1"},
    "espacio_al_final": {"version": "v1 "},
    "de_33": {"version": "x" * 33},
    "numero": {"version": 1},
    "ausente": {},
}


def test_cn4_version_invalida_da_422_sin_escribir(integ) -> None:
    """CN4 (C4): ninguna versión mal formada se guarda; 32 caracteres sí."""
    ana = integ.crear_perfil(integ.crear_tenant())
    estados = {nombre: aceptar(integ, ana, cuerpo).status_code
               for nombre, cuerpo in INVALIDOS.items()}
    sin_escribir = (filas(integ, ana), auditorias(integ, ana), version_en_me(integ, ana))
    observado = {"invalidos": estados, "sin_escribir": sin_escribir,
                 "control_de_32": aceptar(integ, ana, {"version": "x" * 32}).status_code}
    assert observado == {
        "invalidos": dict.fromkeys(INVALIDOS, 422), "sin_escribir": ([], 0, None),
        "control_de_32": 200,
    }, f"CN4: {observado}"


# =============================================================================
# CN5 — C5: las barreras
# =============================================================================
def test_cn5_contrasena_temporal_bloquea_y_sin_consentimiento_no(integ) -> None:
    """CN5 (C5): con la contraseña temporal, 403; sin consentimiento, la API no bloquea."""
    tenant = integ.crear_tenant()
    temporal, normal = integ.crear_perfil(tenant), integ.crear_perfil(tenant)
    sembrar(integ, "update profiles set force_password_reset = true where id = :p", p=temporal)
    r = aceptar(integ, temporal, {"version": V1})
    observado = {
        "con_clave_temporal": (r.status_code, _json(r).get("detail"), filas(integ, temporal)),
        "sin_consentimiento": (version_en_me(integ, normal),
                               client.get("/challenges/",
                                          headers=integ.headers(normal)).status_code),
    }
    assert observado == {
        "con_clave_temporal": (403, "must_change_password", []),
        "sin_consentimiento": (None, 200),
    }, f"CN5: {observado}"
