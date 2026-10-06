"""Tramposos Y16-1..5 de BUG-16 — `docs/ESPEC_bug16.md` §3.

Una versión ROTA a propósito, se corre el cuerpo del test real y se exige
`AssertionError` con el mensaje del mecanismo. Aquí se automatiza la DIAGONAL;
la matriz completa (30 celdas) se mide aparte (ERR-15 y ERR-19).

  Y16-1  la ruta `POST /challenges/` con `challenge_type: str`         -> A16-1
  Y16-2  la ruta con un `Literal` SIN `"listening"`                    -> S16
  Y16-3  la ruta con `cefr_level: str | None`                          -> A16-2
  Y16-4  (no-integ) `/challenges/generate` con `cefr_level: str`       -> U16-2
  Y16-5  `ChallengeCreate.model_fields["challenge_type"]` declara un
         `Literal` de 3 valores (la validación compilada no cambia)    -> U16-1

Por qué se reemplaza la RUTA (Y16-1 a Y16-4): el modelo del cuerpo queda
fijado al decorar la ruta, así que parchear el módulo no cambia lo que valida
la API. Se arma una `APIRoute` con el mismo path, método, `status_code` y
`response_model`, cuyo endpoint llama a la función ORIGINAL del router con un
modelo derivado, y se pone en su mismo lugar de `app.router.routes`.

`monkeypatch.setitem` no sirve para una lista: se reemplaza la lista entera
por una copia con la ruta cambiada, y `undo` devuelve la original (lo mismo
que ZP9 en `test_tramposos_login_piloto.py`).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

import pytest
from fastapi import Depends
from fastapi.routing import APIRoute
from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.challenge_engine import router as retos_router
from src.challenge_engine.schemas import ChallengeCreate, ChallengeGenerateRequest, ChallengeOut
from src.main import app
from src.shared.db import get_db
from src.shared.deps import require_teacher
from tests.challenge_engine import test_bug16_enum as b16

Aplicar = Callable[[pytest.MonkeyPatch], None]

SIN_LISTENING = Literal["multiple_choice", "open", "fill_blank"]


def _ruta_con(path: str, original: Callable[..., Any], modelo: type[BaseModel]) -> Aplicar:
    """Reemplaza la ruta `POST path` por una igual cuyo cuerpo se valida con `modelo`."""
    async def endpoint(payload: Any, auth: AuthContext = Depends(require_teacher),
                       db: AsyncSession = Depends(get_db)) -> Any:
        return await original(payload, auth, db)

    # Las anotaciones se fijan a mano: con `from __future__ import annotations`
    # FastAPI no podría resolver un modelo que solo existe en esta clausura.
    endpoint.__annotations__ = {"payload": modelo, "auth": AuthContext, "db": AsyncSession,
                                "return": ChallengeOut}

    def aplicar(mp: pytest.MonkeyPatch) -> None:
        rutas = list(app.router.routes)
        i = next(i for i, r in enumerate(rutas) if isinstance(r, APIRoute)
                 and r.path == path and r.methods == {"POST"})
        # Sin `dependency_overrides_provider`, la ruta nueva ignoraría el
        # `get_db` del fixture y el `get_current_user` de U16-2.
        rutas[i] = APIRoute(path, endpoint, methods=["POST"], response_model=ChallengeOut,
                            status_code=201,
                            dependency_overrides_provider=app.router.dependency_overrides_provider)
        mp.setattr(app.router, "routes", rutas)
    return aplicar


def _crear_con(**campos: Any) -> Aplicar:
    modelo = create_model("ChallengeCreateRoto", __base__=ChallengeCreate, **campos)
    return _ruta_con("/challenges/", retos_router.create_challenge, modelo)


def _generar_con(**campos: Any) -> Aplicar:
    modelo = create_model("ChallengeGenerateRoto", __base__=ChallengeGenerateRequest, **campos)
    return _ruta_con("/challenges/generate", retos_router.generate_challenge_endpoint, modelo)


def _campo_con_tres_valores(mp: pytest.MonkeyPatch) -> None:
    """Y16-5: el campo DECLARA otro enum; lo que valida la API no cambia."""
    mp.setitem(ChallengeCreate.model_fields, "challenge_type",
               FieldInfo(annotation=SIN_LISTENING,  # type: ignore[arg-type]
                         default="multiple_choice"))


# id -> (¿integ?, cómo romper, test real, mensaje con el que debe caer)
TRAMPOSOS: dict[str, tuple[bool, Aplicar, Callable[..., None], str]] = {
    "Y16-1": (True, _crear_con(challenge_type=(str, "multiple_choice")),
              b16.test_a16_1_challenge_type_fuera_del_enum_da_422, r"A16-1: \{'status': 500"),
    "Y16-2": (True, _crear_con(challenge_type=(SIN_LISTENING, "multiple_choice")),
              b16.test_s16_todos_los_valores_validos_siguen_dando_201,
              r"'listening': \(422, None\)"),
    "Y16-3": (True, _crear_con(cefr_level=(str | None, None)),
              b16.test_a16_2_cefr_level_fuera_del_enum_da_422, r"A16-2: \{'status': 500"),
    "Y16-4": (False, _generar_con(cefr_level=(str, ...)),
              b16.test_u16_2_generate_rechaza_el_nivel_antes_de_la_ia,
              r"U16-2: /generate con B3 dio 503"),
    "Y16-5": (True, _campo_con_tres_valores,
              b16.test_u16_1_el_enum_del_esquema_es_el_check_de_la_base,
              r"'esquema': \{'challenge_type': \('multiple_choice', 'open', 'fill_blank'\)"),
}

_INTEG = [pytest.param(c, id=c) for c, t in TRAMPOSOS.items() if t[0]]
_SIN_BASE = [pytest.param(c, id=c) for c, t in TRAMPOSOS.items() if not t[0]]


@pytest.mark.integ
@pytest.mark.parametrize("clave", _INTEG)
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    _integ, aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        test_real(integ)


@pytest.mark.parametrize("clave", _SIN_BASE)
def test_tramposo_sin_base_pone_rojo_su_test(monkeypatch, clave: str) -> None:
    _integ, aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        test_real(monkeypatch)
