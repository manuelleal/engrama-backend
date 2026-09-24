"""Tests de los esquemas de entrada con `UUIDIn` — ESPEC_bug1_strict_uuid.md §3.

Sin DB. Un caso por esquema afectado (`AnswerSubmit.question_id`,
`ChallengeCreate.group_id`, `ChallengeGenerateRequest.group_id`): el string
UUID que manda el JSON pasa a `UUID`, un string que no es UUID sigue dando
`uuid_parsing` y una clave extra sigue dando `extra_forbidden` (el resto del
modelo no perdió su `strict=True` / `extra="forbid"`).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ValidationError

from src.challenge_engine.schemas import (
    AnswerSubmit,
    ChallengeCreate,
    ChallengeGenerateRequest,
)


def _cuerpo_answer_submit(uuid_str: str) -> dict[str, Any]:
    return {"question_id": uuid_str, "answer": "A"}


def _cuerpo_challenge_create(uuid_str: str) -> dict[str, Any]:
    return {
        "title": "t",
        "description": "d",
        "group_id": uuid_str,
        "questions": [{"question_text": "q", "correct_answer": "A"}],
    }


def _cuerpo_challenge_generate(uuid_str: str) -> dict[str, Any]:
    return {
        "cefr_level": "B1",
        "skill": "grammar",
        "topic": "food",
        "group_id": uuid_str,
    }


_CASOS: list[tuple[type[BaseModel], Callable[[str], dict[str, Any]], str]] = [
    (AnswerSubmit, _cuerpo_answer_submit, "question_id"),
    (ChallengeCreate, _cuerpo_challenge_create, "group_id"),
    (ChallengeGenerateRequest, _cuerpo_challenge_generate, "group_id"),
]
_IDS = [cls.__name__ for cls, _, _ in _CASOS]


@pytest.mark.parametrize("schema_cls, cuerpo, campo", _CASOS, ids=_IDS)
def test_uuid_in_acepta_texto_rechaza_formato_y_extra(
    schema_cls: type[BaseModel],
    cuerpo: Callable[[str], dict[str, Any]],
    campo: str,
) -> None:
    """El campo UUIDIn acepta el string del JSON, y sigue siendo estricto en lo demás."""
    u = uuid4()

    # El string UUID del JSON pasa a UUID (el bug era exactamente esto).
    valido = schema_cls.model_validate(cuerpo(str(u)))
    valor = getattr(valido, campo)
    assert valor == u
    assert isinstance(valor, UUID)

    # Un string que no es UUID sigue rechazado, y con el tipo de error correcto.
    with pytest.raises(ValidationError) as no_uuid:
        schema_cls.model_validate(cuerpo("no-es-uuid"))
    assert any(e["type"] == "uuid_parsing" for e in no_uuid.value.errors())

    # `extra="forbid"` del modelo no se perdió por el campo laxo.
    con_extra = cuerpo(str(u))
    con_extra["campo_que_no_existe"] = "x"
    with pytest.raises(ValidationError) as extra:
        schema_cls.model_validate(con_extra)
    assert any(e["type"] == "extra_forbidden" for e in extra.value.errors())
