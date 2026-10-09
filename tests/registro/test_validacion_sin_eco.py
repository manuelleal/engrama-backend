"""El 422 no devuelve lo que se envió — `docs/ESPEC_autorregistro.md` §13.1.

  VE1  C36  `sin_valores_enviados` (pura): quita `input` y nada más
  VE2  C37  `POST /auth/registro`: ningún 422 trae de vuelta la contraseña, el código de
            grupo, el correo, el código estudiantil ni el nombre
  VE3  C38  `POST /auth/contrasena`: lo mismo con la contraseña nueva

Sin base de datos: un 422 de validación sale ANTES de entrar al manejador, así que
las dependencias que tocarían la base o GoTrue se reemplazan por nada. Cada caso
lleva una MARCA reconocible en cada valor que manda; se exige que ninguna marca
vuelva en la respuesta (ni en el texto, ni en ningún `input`), y que cada error
conserve `loc`, `msg` y `type` (la web ya lee `msg`).

La función se llama por el módulo (`validacion.f(...)`) para que sus tramposos
(ZV1-ZV3, `tests/tramposos/test_tramposos_validacion_sin_eco.py`) puedan reemplazarla.
Todo es sintético: ninguna contraseña ni correo de aquí existe.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from src.auth import politica_clave
from src.auth.cuentas import get_cambio_de_clave
from src.auth.schemas import AuthContext
from src.main import app
from src.registro import limite
from src.registro.cuentas import get_cuentas_de_registro
from src.shared import validacion
from src.shared.db import get_db
from src.shared.deps import get_current_user

client = TestClient(app, raise_server_exceptions=False)

# El cuerpo válido del registro: cada valor es una marca que NO debe volver.
VALIDO: dict[str, Any] = {
    "codigo": "MCODIGO-77",
    "nombre": "Nombre Marca",
    "correo": "marca77@engrama.test",
    "codigo_estudiantil": "MEST-77",
    "contrasena": "marca-clave-77x",
    "mayor_de_edad": True,
    "aviso_version": "2026-10-v1",
}
MARCAS_DEL_VALIDO = ("MCODIGO-77", "Nombre Marca", "marca77@engrama.test", "MEST-77",
                     "marca-clave-77x")


@contextmanager
def dependencias(cambios: dict[Any, Any]) -> Iterator[None]:
    """Reemplaza dependencias de la app mientras dura el bloque (y las devuelve siempre)."""
    async def sin_base() -> Any:
        yield None

    puestas: dict[Any, Any] = {get_db: sin_base}
    for dependencia, valor in cambios.items():
        puestas[dependencia] = lambda valor=valor: valor  # type: ignore[misc]
    antes = dict(app.dependency_overrides)
    app.dependency_overrides.update(puestas)
    limite.reiniciar()
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(antes)
        limite.reiniciar()


def _con(**campos: Any) -> dict[str, Any]:
    """El cuerpo válido con campos cambiados; un valor `...` quita el campo."""
    cuerpo = dict(VALIDO)
    for nombre, valor in campos.items():
        if valor is ...:
            cuerpo.pop(nombre, None)
        else:
            cuerpo[nombre] = valor
    return cuerpo


def _marcas_de(valor: Any) -> list[str]:
    """Todo texto de 4 o más caracteres que viaja en el cuerpo, a cualquier profundidad."""
    if isinstance(valor, str):
        return [valor] if len(valor) >= 4 else []
    if isinstance(valor, dict):
        return [m for v in valor.values() for m in _marcas_de(v)]
    if isinstance(valor, list):
        return [m for v in valor for m in _marcas_de(v)]
    return []


def _errores(r: httpx.Response) -> list[Any]:
    try:
        detalle = r.json().get("detail")
    except (ValueError, AttributeError):
        return []
    return detalle if isinstance(detalle, list) else []


def _problemas(nombre: str, r: httpx.Response, marcas: list[str]) -> list[str]:
    """Todo lo que está mal en la respuesta de un caso (vacío = bien)."""
    malos: list[str] = []
    if r.status_code != 422:
        return [f"{nombre}: respondió {r.status_code}, esperado 422 ({r.text[:120]})"]
    visto = r.text + json.dumps(_errores(r), ensure_ascii=False)
    for marca in marcas:
        if marca in visto:
            malos.append(f"{nombre}: devolvió la marca {marca!r}")
    errores = _errores(r)
    if not errores:
        malos.append(f"{nombre}: el 422 no trae una lista de errores")
    for error in errores:
        if not isinstance(error, dict) or "input" in error:
            malos.append(f"{nombre}: un error trae `input`: {error}")
        elif not all(error.get(clave) for clave in ("loc", "msg", "type")):
            malos.append(f"{nombre}: a un error le falta loc, msg o type: {error}")
    return malos


# =============================================================================
# VE1 — C36: la función pura
# =============================================================================
def test_ve1_sin_valores_enviados_quita_input_y_nada_mas() -> None:
    f = validacion.sin_valores_enviados
    originales: list[dict[str, Any]] = [
        {"type": "string_too_short", "loc": ["body", "contrasena"], "msg": "corta",
         "input": "texto", "ctx": {"min_length": 10}, "url": "https://errores.test/a"},
        {"type": "missing", "loc": ["body", "nombre"], "msg": "falta",
         "input": {"contrasena": "cuerpo entero"}},
        {"type": "int_type", "loc": ["body", "n"], "msg": "no es entero", "input": 12345},
        {"type": "model_type", "loc": ["body"], "msg": "no es objeto", "input": ["a", "b"]},
        {"type": "json_invalid", "loc": ["body", 3], "msg": "roto"},  # ya sin input
    ]
    antes = json.dumps(originales, sort_keys=True)
    limpios = f(originales)

    assert json.dumps(originales, sort_keys=True) == antes, "VE1: modificó la lista que recibió"
    assert len(limpios) == len(originales), f"VE1: {len(limpios)} errores, no {len(originales)}"
    assert all("input" not in e for e in limpios), f"VE1: quedó un input: {limpios}"
    esperados = [{k: v for k, v in e.items() if k != "input"} for e in originales]
    assert limpios == esperados, f"VE1: cambió algo más que input: {limpios}"
    assert f([]) == [], "VE1: una lista vacía no da una lista vacía"


# =============================================================================
# VE2 — C37: POST /auth/registro
# =============================================================================
def _casos_del_registro() -> list[tuple[str, dict[str, Any] | None, bytes | None, list[str]]]:
    """(nombre, cuerpo JSON, cuerpo crudo, marcas extra que no deben volver)."""
    casos: list[tuple[str, dict[str, Any] | None, bytes | None, list[str]]] = []

    def json_(nombre: str, cuerpo: Any, *extra: str) -> None:
        casos.append((nombre, cuerpo, None, list(extra)))

    # Un valor inválido en cada campo.
    json_("codigo largo", _con(codigo="MCODIGO-77" + "x" * 11), "MCODIGO-77xxxxxxxxxxx")
    json_("nombre con espacio al borde", _con(nombre=" Nombre Marca"))
    json_("correo sin arroba", _con(correo="marca77 sin arroba"), "marca77 sin arroba")
    json_("codigo estudiantil con símbolos", _con(codigo_estudiantil="MEST 77!"), "MEST 77!")
    json_("contrasena corta", _con(contrasena="marca1"), "marca1")
    json_("contrasena de solo letras", _con(contrasena="marcaclavesola"), "marcaclavesola")
    json_("contrasena de solo numeros", _con(contrasena="1357924680"), "1357924680")
    json_("contrasena de mas de 72 bytes", _con(contrasena="marca-" + "ñ" * 40 + "1"),
          "marca-ñññ")
    json_("contrasena de mas de 72 caracteres", _con(contrasena="marca-" + "x" * 80 + "1"),
          "marca-xxxx")
    json_("menor de edad", _con(mayor_de_edad=False))
    json_("aviso con espacio al borde", _con(aviso_version=" 2026-10-v1"))
    # Un campo omitido (el `input` del error es el CUERPO ENTERO).
    for campo in VALIDO:
        json_(f"falta {campo}", _con(**{campo: ...}))
    # Campos de más, tipos equivocados y cuerpos que no son un objeto.
    json_("campo de mas", _con(rol="MARCA-EXTRA-ROL", tenant_id="MARCA-EXTRA-TENANT"),
          "MARCA-EXTRA-ROL", "MARCA-EXTRA-TENANT")
    json_("contrasena numerica", _con(contrasena=1357924680123))
    json_("codigo en lista", _con(codigo=["MARCA-LISTA"]), "MARCA-LISTA")
    json_("nombre en diccionario", _con(nombre={"k": "MARCA-DICT"}), "MARCA-DICT")
    json_("cuerpo vacio", {})
    json_("cuerpo lista", ["MARCA-ARR", "marca-clave-77x"], "MARCA-ARR")
    json_("cuerpo texto", "MARCA-TEXTO-SUELTO", "MARCA-TEXTO-SUELTO")  # type: ignore[arg-type]
    casos.append(("json roto", None, b'{"contrasena": "marca-rota-77', ["marca-rota-77"]))
    casos.append(("sin cuerpo", None, b"", []))
    return casos


def test_ve2_el_422_del_registro_no_devuelve_valores() -> None:
    malos: list[str] = []
    n = 0
    with dependencias({get_cuentas_de_registro: None}):
        for nombre, cuerpo, crudo, extra in _casos_del_registro():
            if crudo is not None:
                r = client.post("/auth/registro", content=crudo,
                                headers={"content-type": "application/json"})
            else:
                r = client.post("/auth/registro", json=cuerpo)
            marcas = [*MARCAS_DEL_VALIDO, *extra, *_marcas_de(cuerpo)]
            malos += _problemas(nombre, r, [m for m in marcas if m != "2026-10-v1"])
            n += 1

        # Los mensajes de la contraseña siguen siendo los de §11.5 y §12.1.
        solo_letras = client.post("/auth/registro", json=_con(contrasena="marcaclavesola"))
        mensajes = [e.get("msg", "") for e in _errores(solo_letras)]
        if not any(m == f"Value error, {politica_clave.MENSAJE_COMPOSICION}" for m in mensajes):
            malos.append(f"mensaje de composición cambió: {mensajes}")
        largas = client.post("/auth/registro", json=_con(contrasena="marca-" + "ñ" * 40 + "1"))
        if not any("72 bytes" in e.get("msg", "") for e in _errores(largas)):
            malos.append(f"mensaje de los 72 bytes cambió: {[e.get('msg') for e in _errores(largas)]}")

        # Control: el cuerpo válido NO es 422 (llega al manejador y cae en 503 por no haber GoTrue).
        valido = client.post("/auth/registro", json=VALIDO)
        if valido.status_code != 503:
            malos.append(f"control: el cuerpo válido respondió {valido.status_code}, no 503")
    assert malos == [], f"VE2: {len(malos)} problemas en {n} casos: {malos}"


# =============================================================================
# VE3 — C38: POST /auth/contrasena
# =============================================================================
def test_ve3_el_422_del_cambio_de_contrasena_no_devuelve_valores() -> None:
    sesion = AuthContext(profile_id=uuid4(), role="student", tenant_id=uuid4())
    casos: list[tuple[str, Any, list[str]]] = [
        ("nueva corta", {"nueva": "corta-ma1"}, ["corta-ma1"]),
        ("nueva larga", {"nueva": "clave-larga-MARCA" + "x" * 60}, ["clave-larga-MARCA"]),
        ("falta nueva y campo de mas", {"viejo": "MARCA-VIEJA"}, ["MARCA-VIEJA"]),
        ("nueva numerica", {"nueva": 1357924680123}, []),
        ("nueva en lista", {"nueva": ["MARCA-NUEVA-LISTA"]}, ["MARCA-NUEVA-LISTA"]),
        ("cuerpo lista", ["MARCA-ARR-CLAVE"], ["MARCA-ARR-CLAVE"]),
        ("cuerpo vacio", {}, []),
    ]
    malos: list[str] = []
    with dependencias({get_current_user: sesion, get_cambio_de_clave: None}):
        for nombre, cuerpo, extra in casos:
            r = client.post("/auth/contrasena", json=cuerpo,
                            headers={"Authorization": "Bearer sintetico"})
            malos += _problemas(nombre, r, [*extra, *_marcas_de(cuerpo)])
        roto = client.post("/auth/contrasena", content=b'{"nueva": "marca-rota-88',
                           headers={"content-type": "application/json",
                                    "Authorization": "Bearer sintetico"})
        malos += _problemas("json roto", roto, ["marca-rota-88"])

        # Control: una contraseña válida NO es 422 (sin GoTrue configurado cae en 503).
        valida = client.post("/auth/contrasena", json={"nueva": "marca-clave-88x"},
                             headers={"Authorization": "Bearer sintetico"})
        if valida.status_code != 503:
            malos.append(f"control: la contraseña válida respondió {valida.status_code}, no 503")
    assert malos == [], f"VE3: {len(malos)} problemas: {malos}"
