"""BUG-16: un `challenge_type` o `cefr_level` fuera del enum da 422, no 500 — `docs/ESPEC_bug16.md`.

  A16-1  C1  (integ) `challenge_type: "practice"` -> 422 `literal_error` en
             `["body", "challenge_type"]`, y 0 filas nuevas.
  A16-2  C2  (integ) `cefr_level: "B3"` -> 422 en `["body", "cefr_level"]`, 0 filas.
  S16    C3  (integ) identidad: los 4 tipos y los 11 niveles válidos, y el
             nivel ausente, dan 201 y la respuesta trae el valor tal cual.
  U16-1  C4  (integ) el enum del esquema es el CHECK de la base viva, como
             conjunto y en el mismo orden.
  U16-2  C5  (no-integ) `POST /challenges/generate` con `cefr_level: "B3"` ->
             422 SIN llamar a la IA.

Por U16-2 la marca `integ` va en cada test y no en `pytestmark`.

A16-1, A16-2 y U16-2 corrieron en el paso 1 (`5c9210c`) con
`xfail(strict=True, raises=AssertionError)`: el valor inválido llegaba a la
base y el CHECK lo rechazaba con un 500 (o, en `/generate`, se gastaba la
llamada a la IA). En el paso 2 dejan el xfail. El cliente usa
`raise_server_exceptions=False` para que un 500 sea una respuesta, y por tanto
un `AssertionError`, y no una excepción suelta.

U16-1 lee el `Literal` de `model_fields` (en el paso 1 leía las tuplas), para
que un tramposo que reemplace el campo (Y16-5) lo alcance.

Los valores válidos están escritos AQUÍ a mano (copiados de la migración 010),
no importados del esquema: si se importaran, S16 pasaría con cualquier enum.
"""
from __future__ import annotations

import re
from typing import Any, Literal, get_args, get_origin
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from src.auth.schemas import AuthContext
from src.challenge_engine import schemas as esquemas
from src.challenge_engine.service import generator as generator_mod
from src.main import app
from src.shared.deps import get_current_user

client = TestClient(app, raise_server_exceptions=False)

# `alembic/versions/010_create_challenges.py:30` y `:32`, en ese orden.
TIPOS = ("multiple_choice", "open", "fill_blank", "listening")
NIVELES = ("A1", "A1+", "A2", "A2+", "B1-", "B1", "B1+", "B2", "B2+", "C1", "C1+")


def _docente(integ: Any) -> UUID:
    docente: UUID = integ.crear_perfil(integ.crear_tenant(), rol="teacher")
    return docente


def cuerpo(**cambios: Any) -> dict[str, Any]:
    """Un reto mínimo válido; `cambios` pisa o agrega campos."""
    return {"title": "Reto sintético BUG-16", "description": "sintético",
            "questions": [{"question_text": "Pregunta 1", "correct_answer": "A"}], **cambios}


def crear(integ: Any, docente: UUID, **cambios: Any) -> httpx.Response:
    return client.post("/challenges/", json=cuerpo(**cambios), headers=integ.headers(docente))


def _errores(r: httpx.Response) -> list[tuple[Any, Any]]:
    """[(type, loc)] del 422 de FastAPI; [] si la respuesta no trae esa forma."""
    try:
        detalle = r.json().get("detail")
    except (ValueError, AttributeError):
        return []
    if not isinstance(detalle, list):
        return []
    return [(e.get("type"), e.get("loc")) for e in detalle if isinstance(e, dict)]


def _filas(integ: Any) -> dict[str, int]:
    return {t: int(integ.valor(f"select count(*) from {t}"))
            for t in ("challenges", "challenge_questions")}


def _rechazo(integ: Any, campo: str, valor: str) -> dict[str, Any]:
    """Lo que pasa al crear un reto con `campo = valor` (inválido)."""
    docente = _docente(integ)
    r = crear(integ, docente, **{campo: valor})
    return {"status": r.status_code, "errores": _errores(r), "filas": _filas(integ)}


def _esperado(campo: str) -> dict[str, Any]:
    return {"status": 422, "errores": [("literal_error", ["body", campo])],
            "filas": {"challenges": 0, "challenge_questions": 0}}


# =============================================================================
# A16-1, A16-2 — C1, C2: el valor fuera del enum
# =============================================================================
@pytest.mark.integ
def test_a16_1_challenge_type_fuera_del_enum_da_422(integ) -> None:
    """A16-1 (C1): `practice` -> 422 con el campo exacto, y nada en la base."""
    observado = _rechazo(integ, "challenge_type", "practice")
    assert observado == _esperado("challenge_type"), f"A16-1: {observado}"


@pytest.mark.integ
def test_a16_2_cefr_level_fuera_del_enum_da_422(integ) -> None:
    """A16-2 (C2): `B3` -> 422 con el campo exacto, y nada en la base."""
    observado = _rechazo(integ, "cefr_level", "B3")
    assert observado == _esperado("cefr_level"), f"A16-2: {observado}"


# =============================================================================
# S16 — C3: identidad de los valores válidos
# =============================================================================
@pytest.mark.integ
def test_s16_todos_los_valores_validos_siguen_dando_201(integ) -> None:
    """S16 (C3): cada tipo y cada nivel válido -> 201, y vuelve tal cual."""
    docente = _docente(integ)

    def ver(campo: str, **cambios: Any) -> tuple[int, Any]:
        r = crear(integ, docente, **cambios)
        datos = r.json() if r.status_code == 201 else {}
        return r.status_code, datos.get(campo)

    observado = {
        "tipos": {t: ver("challenge_type", challenge_type=t) for t in TIPOS},
        "niveles": {n: ver("cefr_level", cefr_level=n) for n in NIVELES},
        "nivel_ausente": ver("cefr_level"),
        "tipo_ausente": ver("challenge_type"),
    }
    assert observado == {
        "tipos": {t: (201, t) for t in TIPOS},
        "niveles": {n: (201, n) for n in NIVELES},
        "nivel_ausente": (201, None),
        "tipo_ausente": (201, "multiple_choice"),
    }, f"S16: {observado}"


# =============================================================================
# U16-1 — C4: el mismo enum que la base
# =============================================================================
def _valores_del_check(integ: Any, columna: str) -> list[tuple[str, ...]]:
    """Los valores de cada CHECK de `challenges` que nombra a `columna`, en su orden."""
    from sqlalchemy import text

    async def _q() -> list[str]:
        async with integ.Session() as db:
            filas = await db.execute(text(
                "select pg_get_constraintdef(oid) from pg_constraint "
                "where conrelid = 'challenges'::regclass and contype = 'c'"))
            return [str(d) for d in filas.scalars()]

    return [tuple(re.findall(r"'([^']+)'::text", d)) for d in integ.run(_q()) if columna in d]


def _literal(modelo: Any, campo: str) -> tuple[str, ...]:
    """Los valores del `Literal` del campo (también dentro de `Literal | None`)."""
    anotacion = modelo.model_fields[campo].annotation
    for candidata in (anotacion, *get_args(anotacion)):
        if get_origin(candidata) is Literal:
            return tuple(get_args(candidata))
    return ()


def enum_del_esquema() -> dict[str, Any]:
    """El enum que valida cada esquema de entrada, y las tuplas exportadas."""
    return {
        "challenge_type": _literal(esquemas.ChallengeCreate, "challenge_type"),
        "cefr_level": _literal(esquemas.ChallengeCreate, "cefr_level"),
        "cefr_level_de_generate": _literal(esquemas.ChallengeGenerateRequest, "cefr_level"),
        "tuplas": (tuple(esquemas.CHALLENGE_TYPES), tuple(esquemas.CEFR_LEVELS)),
    }


@pytest.mark.integ
def test_u16_1_el_enum_del_esquema_es_el_check_de_la_base(integ) -> None:
    """U16-1 (C4): mismo conjunto y mismo orden que el CHECK de la base viva."""
    en_la_base = {c: _valores_del_check(integ, c) for c in ("challenge_type", "cefr_level")}
    observado = {"base": en_la_base, "esquema": enum_del_esquema()}
    assert observado == {
        "base": {"challenge_type": [TIPOS], "cefr_level": [NIVELES]},
        "esquema": {"challenge_type": TIPOS, "cefr_level": NIVELES,
                    "cefr_level_de_generate": NIVELES, "tuplas": (TIPOS, NIVELES)},
    }, f"U16-1: {observado}"


# =============================================================================
# U16-2 — C5: /generate rechaza antes de llamar a la IA
# =============================================================================
def generar_b3(monkeypatch: pytest.MonkeyPatch, **cabeceras: Any) -> int:
    """`POST /challenges/generate` con `cefr_level: "B3"`, SIN clave de Anthropic.

    Con la clave vacía, si el 422 no llega el generador responde 503 local:
    nunca hay una llamada real a la IA, aunque quien corre la prueba tenga
    una clave en su entorno.
    """
    monkeypatch.setattr(generator_mod.settings, "anthropic_api_key", "")
    return client.post("/challenges/generate", **cabeceras, json={
        "cefr_level": "B3", "skill": "grammar", "topic": "sintético"}).status_code


def test_u16_2_generate_rechaza_el_nivel_antes_de_la_ia(monkeypatch) -> None:
    """U16-2 (C5): 422 sin llamar a la IA (si no, sería el 503 local)."""
    docente = AuthContext(profile_id=uuid4(), role="teacher", tenant_id=uuid4(),
                          group_code=None, is_teacher=True, is_admin=False)
    app.dependency_overrides[get_current_user] = lambda: docente
    try:
        status = generar_b3(monkeypatch)
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert status == 422, f"U16-2: /generate con B3 dio {status}"
