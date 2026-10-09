"""Ningún 422 de validación devuelve lo enviado, en TODA la API — `docs/ESPEC_422_sin_eco.md`.

  SE1  C2  `sin_valores_enviados` (pura): `input`, el `ctx` derivado del valor y el `msg`
  SE2  C3  todas las rutas con cuerpo (descubiertas de `app.routes`, no una lista a mano)
  SE3  C4  todos los parámetros de ruta
  SE4  C5  todos los parámetros de consulta
  SE5  C6  la forma que la web consume de las dos rutas ya cerradas
  SE6  C7  réplica: una ruta que hoy no existe entra sola
  (SE0, la identidad byte a byte de las dos rutas, vive en `test_422_dos_rutas_identidad.py`.)

Sin base de datos: un 422 de validación sale ANTES de entrar al manejador de la
ruta, así que TODAS las dependencias de todas las rutas se reemplazan por nada.

Cada caso se envía DOS veces, con dos centinelas distintos del mismo largo en
los mismos lugares. Se exige que el centinela no vuelva y, además, que las dos
respuestas sean idénticas byte a byte: la respuesta no puede depender del valor
enviado. Eso atrapa las fugas parciales (el `found `N` at 3` de un UUID), que
buscar el centinela entero no ve.

Las funciones se llaman por el módulo (`validacion.f(...)`) y el humo se escribe
en `RUTA_HUMO` para que los tramposos ZE1-ZE4
(`tests/tramposos/test_tramposos_422_sin_eco.py`) puedan reemplazarlos.
Todo es sintético.
"""
from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal, get_args
from uuid import UUID

import httpx
from fastapi import APIRouter
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from src.auth import politica_clave
from src.main import app
from src.shared import validacion

client = TestClient(app, raise_server_exceptions=False)

RUTA_HUMO = Path(__file__).resolve().parent.parent / "_salida" / "humo_422_sin_eco.json"

# Dos centinelas gemelos: el mismo largo y, en cada posición, la misma CLASE de
# carácter (mayúscula, guion, dígito, minúscula). Así los dos son igual de
# válidos o de inválidos para cualquier patrón o largo, y una diferencia entre
# las dos respuestas solo puede venir de que el valor viajó de vuelta. (Con un
# `+` en el segundo, un patrón `[A-Za-z0-9_-]` aceptaba uno y rechazaba el otro:
# eso medía la validez, no el eco. ESPEC §7, errata.)
# El primero trae letras hexadecimales al principio a propósito: el analizador de
# UUID tropieza en la `N` (posición 3) y, con el segundo, en la `Z` (posición 1).
CENTINELAS = ("CENTINELA-9f3a7c", "ZQWXKVJYP-8b2d4e")
# Los de la réplica (SE6): otros dos, nunca usados en el resto.
CENTINELAS_DE_REPLICA = ("RPLK-77aa-mmnn-0", "gHjK_55zz_ttuu_9")

# Lo medido sobre `59fe08a` (ESPEC §0). Son PISOS: una ruta nueva entra sola y
# sube la cuenta; si baja, alguien quitó rutas o el descubrimiento se rompió.
MIN_RUTAS_CON_CUERPO = 21
MIN_RUTAS_CON_PARAMETRO_DE_RUTA = 31
MIN_RUTAS_CON_CONSULTA = 4

_RELLENOS: dict[Any, str] = {UUID: "11111111-1111-4111-8111-111111111111", int: "1",
                             dt.date: "2026-01-01"}
_JSON = {"content-type": "application/json"}


# =============================================================================
# Descubrir: qué rutas hay y qué recibe cada una (todo sale de la app)
# =============================================================================
def _rutas() -> list[APIRoute]:
    return [r for r in app.routes if isinstance(r, APIRoute)]


def _llamadas(dependant: Dependant, vistas: set[Callable[..., Any]]) -> set[Callable[..., Any]]:
    """Toda dependencia de la ruta, a cualquier profundidad."""
    for sub in dependant.dependencies:
        if sub.call is not None:
            vistas.add(sub.call)
        _llamadas(sub, vistas)
    return vistas


def _anotacion(parametro: Any) -> Any:
    return parametro.field_info.annotation


def _admite_texto(anotacion: Any) -> bool:
    """Si un texto cualquiera es un valor válido (entonces el centinela NO da 422)."""
    return anotacion is str or anotacion is Any or str in get_args(anotacion)


def _relleno(anotacion: Any) -> str:
    return _RELLENOS.get(anotacion, "relleno")


def _url(ruta: APIRoute, cambios: dict[str, str] | None = None) -> str:
    """La ruta con cada parámetro puesto con un valor VÁLIDO, salvo los de `cambios`."""
    url = ruta.path
    for p in ruta.dependant.path_params:
        valor = (cambios or {}).get(p.alias, _relleno(_anotacion(p)))
        url = url.replace("{" + p.alias + "}", valor)
    return url


def _metodo(ruta: APIRoute) -> str:
    return sorted(ruta.methods - {"HEAD"})[0]


def _campos_del_cuerpo(ruta: APIRoute) -> list[str]:
    """Los nombres de los campos del modelo del cuerpo (vacío si el cuerpo no es un modelo)."""
    cuerpos = ruta.dependant.body_params
    if len(cuerpos) != 1:
        return []
    anotacion = _anotacion(cuerpos[0])
    # Un cuerpo opcional (`CodigoIn | None`) trae el modelo dentro de la unión.
    for modelo in (anotacion, *get_args(anotacion)):
        if isinstance(modelo, type) and issubclass(modelo, BaseModel):
            return [info.alias or nombre for nombre, info in modelo.model_fields.items()]
    return []


@contextmanager
def sin_dependencias() -> Iterator[None]:
    """Reemplaza por nada TODA dependencia de TODA ruta mientras dura el bloque."""
    async def nada() -> None:
        return None

    antes = dict(app.dependency_overrides)
    for ruta in _rutas():
        for llamada in _llamadas(ruta.dependant, set()):
            app.dependency_overrides[llamada] = nada
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(antes)


# =============================================================================
# Revisar una respuesta (y su gemela con el otro centinela)
# =============================================================================
def _errores(r: httpx.Response) -> list[Any] | None:
    """La lista de errores si es un 422 de validación; `None` si no lo es."""
    if r.status_code != 422:
        return None
    try:
        detalle = r.json().get("detail")
    except (ValueError, AttributeError):
        return None
    return detalle if isinstance(detalle, list) else None


def _ctx_permitido(error: dict[str, Any]) -> set[str]:
    claves = set(validacion.CLAVES_DE_CTX_DEL_SERVIDOR)
    if error.get("type") in validacion.TIPOS_QUE_CONSERVAN_SU_ERROR:
        claves.add("error")
    return claves


def _problemas(etiqueta: str, respuestas: tuple[httpx.Response, httpx.Response],
               centinelas: tuple[str, str], *, debe_422: bool,
               debe_traer_loc: list[str] | None = None) -> tuple[list[str], bool]:
    """(todo lo que está mal, si fue un 422 de validación). Vacío = bien."""
    a, b = respuestas
    errores = _errores(a)
    if errores is None:
        if debe_422:
            return [f"{etiqueta}: no dio 422 de validación (dio {a.status_code}: {a.text[:80]})"], False
        return [], False
    malos: list[str] = []
    for r, centinela in zip(respuestas, centinelas, strict=True):
        if centinela in r.text:
            malos.append(f"{etiqueta}: devolvió el centinela {centinela!r}")
    if not errores:
        malos.append(f"{etiqueta}: el 422 no trae ningún error")
    for error in errores:
        if not isinstance(error, dict) or "input" in error:
            malos.append(f"{etiqueta}: un error trae `input`: {str(error)[:160]}")
            continue
        if not all(error.get(clave) for clave in ("loc", "msg", "type")):
            malos.append(f"{etiqueta}: a un error le falta loc, msg o type: {error}")
        de_mas = set(error.get("ctx") or {}) - _ctx_permitido(error)
        if de_mas:
            malos.append(f"{etiqueta}: el ctx trae {sorted(de_mas)}: {error}")
    if a.text != b.text:
        malos.append(f"{etiqueta}: la respuesta depende del valor enviado: "
                     f"{a.text[:200]} CONTRA {b.text[:200]}")
    if debe_traer_loc is not None and not any(
            isinstance(e, dict) and e.get("loc") == debe_traer_loc for e in errores):
        malos.append(f"{etiqueta}: ningún error señala {debe_traer_loc}")
    return malos, True


def _anotar_humo(seccion: str, datos: dict[str, Any]) -> None:
    """El humo escribe su archivo ANTES de afirmar (una sección por test)."""
    try:
        humo = json.loads(RUTA_HUMO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        humo = {}
    humo[seccion] = datos
    RUTA_HUMO.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO.write_text(json.dumps(humo, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                         encoding="utf-8")


def _resumen(malos: list[str]) -> str:
    """Las rutas afectadas primero (para leerlo de un vistazo) y luego los primeros problemas."""
    rutas = sorted({m.split(" [", 1)[0] for m in malos})
    return f"{len(malos)} problemas en {len(rutas)} rutas {rutas}: {malos[:12]}"


# =============================================================================
# SE1 — C2: la función pura
# =============================================================================
def test_se1_sin_valores_enviados_quita_input_y_lo_derivado_del_valor() -> None:
    f = validacion.sin_valores_enviados
    detalle_uuid = "invalid character: expected an optional prefix of `urn:uuid:`, found `N` at 3"
    originales: list[dict[str, Any]] = [
        {"type": "uuid_parsing", "loc": ["path", "gid"],
         "msg": f"Input should be a valid UUID, {detalle_uuid}",
         "input": "CENTINELA-9f3a7c", "ctx": {"error": detalle_uuid}},
        {"type": "union_tag_invalid", "loc": ["body", "pieza"],
         "msg": "Input tag 'SECRETO' found using 'tipo' does not match any of the expected tags: 'a'",
         "input": {"tipo": "SECRETO"},
         "ctx": {"discriminator": "'tipo'", "tag": "SECRETO", "expected_tags": "'a'"}},
        {"type": "string_too_short", "loc": ["body", "nueva"],
         "msg": "String should have at least 10 characters", "input": "corta",
         "ctx": {"min_length": 10}, "url": "https://errores.test/a"},
        {"type": "value_error", "loc": ["body", "contrasena"],
         "msg": "Value error, la contraseña debe tener una letra", "input": "contraseña",
         "ctx": {"error": ValueError("la contraseña debe tener una letra")}},
        {"type": "json_invalid", "loc": ["body", 6], "msg": "JSON decode error", "input": {},
         "ctx": {"error": "Unterminated string starting at"}},
        {"type": "too_long", "loc": ["body", "items"],
         "msg": "List should have at most 3 items after validation, not 5", "input": [1, 2, 3, 4, 5],
         "ctx": {"field_type": "List", "max_length": 3, "actual_length": 5}},
        {"type": "missing", "loc": ["body", "nombre"], "msg": "Field required",
         "input": {"contrasena": "cuerpo entero"}},
    ]
    antes = repr(originales)
    limpios = f(originales)

    assert repr(originales) == antes, "SE1: modificó la lista que recibió"
    assert len(limpios) == len(originales), f"SE1: {len(limpios)} errores, no {len(originales)}"
    assert all("input" not in e for e in limpios), f"SE1: quedó un input: {limpios}"
    for original, limpio in zip(originales, limpios, strict=True):
        for clave in ("type", "loc", "url"):
            assert limpio.get(clave) == original.get(clave), f"SE1: cambió `{clave}`: {limpio}"
    uuid_, union, corta, propio, roto, larga, falta = limpios
    assert "ctx" not in uuid_, f"SE1: quedó el ctx del analizador de UUID: {uuid_}"
    assert uuid_["msg"] == "Input should be a valid UUID", f"SE1: msg del UUID: {uuid_['msg']!r}"
    assert union["ctx"] == {"discriminator": "'tipo'", "expected_tags": "'a'"}, (
        f"SE1: ctx de la unión: {union.get('ctx')}")
    assert union["msg"] == validacion.MENSAJE_NEUTRO, f"SE1: msg de la unión: {union['msg']!r}"
    assert corta == {k: v for k, v in originales[2].items() if k != "input"}, (
        f"SE1: cambió algo más que input en un error de largo: {corta}")
    assert propio["msg"] == originales[3]["msg"], (
        f"SE1: cambió el msg de un validador propio: {propio['msg']!r}")
    assert propio["ctx"] is not originales[3]["ctx"] and list(propio["ctx"]) == ["error"], (
        f"SE1: ctx del validador propio: {propio.get('ctx')}")
    assert roto == {k: v for k, v in originales[4].items() if k != "input"}, (
        f"SE1: cambió algo más que input en el JSON roto: {roto}")
    assert larga["ctx"] == {"field_type": "List", "max_length": 3}, f"SE1: ctx de la lista: {larga}"
    assert larga["msg"] == originales[5]["msg"], f"SE1: msg de la lista: {larga['msg']!r}"
    assert falta == {"type": "missing", "loc": ["body", "nombre"], "msg": "Field required"}, (
        f"SE1: el error del campo que falta: {falta}")
    assert f([]) == [], "SE1: una lista vacía no da una lista vacía"


# =============================================================================
# SE2 — C3: todas las rutas con cuerpo
# =============================================================================
Envio = Callable[[str], dict[str, Any]]


def _casos_de_cuerpo(campos: list[str]) -> list[tuple[str, Envio, bool]]:
    """(nombre, cómo se envía con un centinela, si DEBE dar 422 en toda ruta)."""
    casos: list[tuple[str, Envio, bool]] = [
        ("campo de mas", lambda c: {"json": {"campo_de_mas": c}}, True),
        ("cuerpo lista", lambda c: {"json": [c]}, True),
        ("cuerpo texto", lambda c: {"json": c}, True),
        ("json roto", lambda c: {"content": b'{"a": "' + c.encode(), "headers": _JSON}, True),
    ]
    for campo in campos:
        otros = [g for g in campos if g != campo]
        casos += [
            (f"falta {campo}", lambda c, otros=otros: {"json": {g: c for g in otros}}, False),
            (f"{campo} en lista", lambda c, campo=campo: {"json": {campo: [c]}}, False),
            (f"{campo} en objeto", lambda c, campo=campo: {"json": {campo: {"k": c}}}, False),
            (f"{campo} en texto", lambda c, campo=campo: {"json": {campo: c}}, False),
        ]
    return casos


def _par(metodo: str, url: str, envio: Envio, centinelas: tuple[str, str],
         ) -> tuple[httpx.Response, httpx.Response]:
    a, b = (client.request(metodo, url, **envio(c)) for c in centinelas)
    return a, b


def test_se2_ninguna_ruta_con_cuerpo_devuelve_lo_enviado() -> None:
    malos: list[str] = []
    recorridas: dict[str, dict[str, int]] = {}
    with sin_dependencias():
        for ruta in _rutas():
            if not ruta.dependant.body_params:
                continue
            nombre = f"{_metodo(ruta)} {ruta.path}"
            cuenta = {"casos": 0, "con_422_de_validacion": 0}
            for caso, envio, debe_422 in _casos_de_cuerpo(_campos_del_cuerpo(ruta)):
                respuestas = _par(_metodo(ruta), _url(ruta), envio, CENTINELAS)
                suyos, fue_422 = _problemas(f"{nombre} [{caso}]", respuestas, CENTINELAS,
                                            debe_422=debe_422)
                malos += suyos
                cuenta["casos"] += 1
                cuenta["con_422_de_validacion"] += fue_422
            recorridas[nombre] = cuenta
    _anotar_humo("SE2_cuerpo", {
        "rutas": len(recorridas), "casos": sum(c["casos"] for c in recorridas.values()),
        "con_422_de_validacion": sum(c["con_422_de_validacion"] for c in recorridas.values()),
        "por_ruta": recorridas, "problemas": malos})

    assert len(recorridas) >= MIN_RUTAS_CON_CUERPO, (
        f"SE2: solo {len(recorridas)} rutas con cuerpo, no {MIN_RUTAS_CON_CUERPO} o más")
    sin_campos = sorted(n for n, c in recorridas.items() if c["casos"] <= 4)
    assert sin_campos == [], f"SE2: rutas cuyo cuerpo no se pudo recorrer campo a campo: {sin_campos}"
    assert malos == [], f"SE2: {_resumen(malos)}"


# =============================================================================
# SE3 — C4: todos los parámetros de ruta
# =============================================================================
def test_se3_ningun_parametro_de_ruta_invalido_devuelve_lo_enviado() -> None:
    malos: list[str] = []
    recorridas: dict[str, dict[str, Any]] = {}
    with sin_dependencias():
        for ruta in _rutas():
            if not ruta.dependant.path_params:
                continue
            nombre = f"{_metodo(ruta)} {ruta.path}"
            cuenta: dict[str, Any] = {"parametros": 0, "con_422_de_validacion": 0}
            for p in ruta.dependant.path_params:
                debe_422 = not _admite_texto(_anotacion(p))
                respuestas = (client.request(_metodo(ruta), _url(ruta, {p.alias: CENTINELAS[0]})),
                              client.request(_metodo(ruta), _url(ruta, {p.alias: CENTINELAS[1]})))
                suyos, fue_422 = _problemas(
                    f"{nombre} [ruta {p.alias}]", respuestas, CENTINELAS, debe_422=debe_422,
                    debe_traer_loc=["path", p.alias] if debe_422 else None)
                malos += suyos
                cuenta["parametros"] += 1
                cuenta["con_422_de_validacion"] += fue_422
            recorridas[nombre] = cuenta
    _anotar_humo("SE3_ruta", {
        "rutas": len(recorridas),
        "parametros": sum(c["parametros"] for c in recorridas.values()),
        "con_422_de_validacion": sum(c["con_422_de_validacion"] for c in recorridas.values()),
        "por_ruta": recorridas, "problemas": malos})

    assert len(recorridas) >= MIN_RUTAS_CON_PARAMETRO_DE_RUTA, (
        f"SE3: solo {len(recorridas)} rutas con parámetros de ruta, "
        f"no {MIN_RUTAS_CON_PARAMETRO_DE_RUTA} o más")
    assert malos == [], f"SE3: {_resumen(malos)}"


# =============================================================================
# SE4 — C5: todos los parámetros de consulta
# =============================================================================
def test_se4_ningun_parametro_de_consulta_invalido_devuelve_lo_enviado() -> None:
    malos: list[str] = []
    recorridas: dict[str, dict[str, Any]] = {}
    with sin_dependencias():
        for ruta in _rutas():
            if not ruta.dependant.query_params:
                continue
            nombre = f"{_metodo(ruta)} {ruta.path}"
            cuenta: dict[str, Any] = {"parametros": 0, "con_422_de_validacion": 0}
            for q in ruta.dependant.query_params:
                debe_422 = not _admite_texto(_anotacion(q))
                respuestas = (
                    client.request(_metodo(ruta), _url(ruta), params={q.alias: CENTINELAS[0]}),
                    client.request(_metodo(ruta), _url(ruta), params={q.alias: CENTINELAS[1]}))
                suyos, fue_422 = _problemas(
                    f"{nombre} [consulta {q.alias}]", respuestas, CENTINELAS, debe_422=debe_422,
                    debe_traer_loc=["query", q.alias] if debe_422 else None)
                malos += suyos
                cuenta["parametros"] += 1
                cuenta["con_422_de_validacion"] += fue_422
            recorridas[nombre] = cuenta
    _anotar_humo("SE4_consulta", {
        "rutas": len(recorridas),
        "parametros": sum(c["parametros"] for c in recorridas.values()),
        "con_422_de_validacion": sum(c["con_422_de_validacion"] for c in recorridas.values()),
        "por_ruta": recorridas, "problemas": malos})

    assert len(recorridas) >= MIN_RUTAS_CON_CONSULTA, (
        f"SE4: solo {len(recorridas)} rutas con parámetros de consulta, "
        f"no {MIN_RUTAS_CON_CONSULTA} o más")
    assert malos == [], f"SE4: {_resumen(malos)}"


# =============================================================================
# SE5 — C6: la forma que la web consume (loc, msg con su prefijo, type)
# =============================================================================
def test_se5_la_web_sigue_leyendo_loc_msg_y_type_en_las_dos_rutas() -> None:
    registro = {"codigo": "MCODIGO-77", "nombre": "Nombre Marca", "correo": "marca77@engrama.test",
                "codigo_estudiantil": "MEST-77", "mayor_de_edad": True,
                "aviso_version": "2026-10-v1",
                # Solo letras, y además una palabra que ESTÁ en el mensaje del
                # validador: una limpieza que tachara del `msg` lo enviado lo dañaría.
                "contrasena": "contraseña"}
    with sin_dependencias():
        r1 = client.post("/auth/registro", json=registro)
        r2 = client.post("/auth/contrasena", json={"nueva": "corta-ma1"})
    visto = {"registro": (r1.status_code, r1.json().get("detail")),
             "contrasena": (r2.status_code, r2.json().get("detail"))}
    esperado = {
        "registro": (422, [{"loc": ["body", "contrasena"], "type": "value_error",
                            "msg": f"Value error, {politica_clave.MENSAJE_COMPOSICION}"}]),
        "contrasena": (422, [{"loc": ["body", "nueva"], "type": "string_too_short",
                              "msg": "String should have at least 10 characters"}]),
    }
    lo_que_lee_la_web = {
        ruta: (codigo, [{clave: e.get(clave) for clave in ("loc", "type", "msg")}
                        for e in (detalle if isinstance(detalle, list) else [])])
        for ruta, (codigo, detalle) in visto.items()}
    assert lo_que_lee_la_web == esperado, f"SE5: la web leería {lo_que_lee_la_web}"


# =============================================================================
# SE6 — C7: réplica con entradas nuevas: una ruta que hoy no existe
# =============================================================================
class _CuerpoSintetico(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    secreto: str
    cantidad: int


def _ruta_sintetica() -> list[Any]:
    router = APIRouter()

    @router.post("/sintetica/{cosa_id}/eco")
    async def sintetica(cosa_id: UUID, cuerpo: _CuerpoSintetico, pagina: int = 1,
                        modo: Literal["a", "b"] = "a") -> dict[str, str]:
        return {"dato": "de prueba"}

    return list(router.routes)


def test_se6_una_ruta_nueva_queda_cubierta_sin_tocar_nada() -> None:
    nuevas = _ruta_sintetica()
    relleno = _RELLENOS[UUID]
    cuerpo_valido: Envio = lambda c: {"json": {"secreto": "valido", "cantidad": 1}}  # noqa: E731
    casos: list[tuple[str, Callable[[str], str], Envio, list[str] | None]] = [
        ("falta cantidad", lambda c: f"/sintetica/{relleno}/eco",
         lambda c: {"json": {"secreto": c}}, ["body", "cantidad"]),
        ("secreto en lista y campo de mas", lambda c: f"/sintetica/{relleno}/eco",
         lambda c: {"json": {"secreto": [c], "cantidad": 1, "campo_de_mas": c}},
         ["body", "secreto"]),
        ("cuerpo lista", lambda c: f"/sintetica/{relleno}/eco", lambda c: {"json": [c]}, ["body"]),
        ("ruta", lambda c: f"/sintetica/{c}/eco", cuerpo_valido, ["path", "cosa_id"]),
        ("consulta entera", lambda c: f"/sintetica/{relleno}/eco",
         lambda c: {**cuerpo_valido(c), "params": {"pagina": c}}, ["query", "pagina"]),
        ("consulta literal", lambda c: f"/sintetica/{relleno}/eco",
         lambda c: {**cuerpo_valido(c), "params": {"modo": c}}, ["query", "modo"]),
    ]
    malos: list[str] = []
    app.router.routes.extend(nuevas)
    try:
        for caso, url, envio, loc in casos:
            a, b = (client.post(url(c), **envio(c)) for c in CENTINELAS_DE_REPLICA)
            suyos, _ = _problemas(f"POST /sintetica [{caso}]", (a, b), CENTINELAS_DE_REPLICA,
                                  debe_422=True, debe_traer_loc=loc)
            malos += suyos
        control = client.post(f"/sintetica/{relleno}/eco", **cuerpo_valido(""))
        if (control.status_code, control.json()) != (200, {"dato": "de prueba"}):
            malos.append(f"POST /sintetica [control]: el cuerpo válido dio {control.status_code}")
    finally:
        for ruta in nuevas:
            app.router.routes.remove(ruta)
    assert malos == [], f"SE6: {_resumen(malos)}"
