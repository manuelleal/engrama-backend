"""Tests del submódulo attempts — SPECS/03-challenges.md §10.

Niveles:
  1. Unit (sin DB) — grading logic (grade_answers, is_attempt_correct).
  2. Unit (sin DB) — generator prompt building y parsing de JSON de IA.
  3. Contract HTTP (sin DB) — endpoints /attempts/* sin auth → 401.
  4. Integration DB-bound — start/submit reales; skipped.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.challenge_engine.schemas import AnswerSubmit
from src.challenge_engine.service.attempts import (
    grade_answers,
    is_attempt_correct,
)
from src.challenge_engine.service.generator import (
    build_prompt,
    parse_model_output,
)
from src.main import app

client = TestClient(app)


# =============================================================================
# 1. grade_answers — tabla de casos
# =============================================================================
def _mock_question(qid, correct: str, qtype: str = "multiple_choice"):
    """Mínimo shape que grade_answers necesita (id, correct_answer)."""
    return SimpleNamespace(id=qid, correct_answer=correct, question_type=qtype)


class TestGradeAnswers:
    def test_all_correct_returns_100(self) -> None:
        q1_id = uuid4()
        q2_id = uuid4()
        questions = [_mock_question(q1_id, "A"), _mock_question(q2_id, "B")]
        submitted = [
            AnswerSubmit(question_id=q1_id, answer="A"),
            AnswerSubmit(question_id=q2_id, answer="B"),
        ]
        score, details = grade_answers(questions, submitted)
        assert score == 100.0
        assert all(d["is_correct"] for d in details)

    def test_all_wrong_returns_0(self) -> None:
        q_id = uuid4()
        questions = [_mock_question(q_id, "A")]
        submitted = [AnswerSubmit(question_id=q_id, answer="Z")]
        score, _ = grade_answers(questions, submitted)
        assert score == 0.0

    def test_partial_correct(self) -> None:
        q1_id, q2_id, q3_id, q4_id = uuid4(), uuid4(), uuid4(), uuid4()
        questions = [
            _mock_question(q1_id, "A"),
            _mock_question(q2_id, "B"),
            _mock_question(q3_id, "C"),
            _mock_question(q4_id, "D"),
        ]
        submitted = [
            AnswerSubmit(question_id=q1_id, answer="A"),  # ok
            AnswerSubmit(question_id=q2_id, answer="X"),  # no
            AnswerSubmit(question_id=q3_id, answer="C"),  # ok
            AnswerSubmit(question_id=q4_id, answer="X"),  # no
        ]
        score, _ = grade_answers(questions, submitted)
        assert score == 50.0

    def test_case_insensitive_and_strip(self) -> None:
        q_id = uuid4()
        questions = [_mock_question(q_id, "Paris")]
        submitted = [AnswerSubmit(question_id=q_id, answer="  paris  ")]
        score, _ = grade_answers(questions, submitted)
        assert score == 100.0

    def test_missing_answer_counts_as_wrong(self) -> None:
        q1_id, q2_id = uuid4(), uuid4()
        questions = [_mock_question(q1_id, "A"), _mock_question(q2_id, "B")]
        submitted = [AnswerSubmit(question_id=q1_id, answer="A")]  # solo 1
        score, details = grade_answers(questions, submitted)
        assert score == 50.0
        assert details[0]["is_correct"] is True
        assert details[1]["is_correct"] is False
        assert details[1]["given_answer"] == ""

    def test_empty_questions_returns_zero(self) -> None:
        score, details = grade_answers([], [])
        assert score == 0.0
        assert details == []


class TestIsAttemptCorrect:
    @pytest.mark.parametrize("qtype", ["multiple_choice", "listening"])
    def test_exact_types_require_100(self, qtype: str) -> None:
        assert is_attempt_correct(qtype, 100.0) is True
        assert is_attempt_correct(qtype, 99.99) is False

    @pytest.mark.parametrize("qtype", ["open", "fill_blank"])
    def test_partial_types_accept_70(self, qtype: str) -> None:
        assert is_attempt_correct(qtype, 70.0) is True
        assert is_attempt_correct(qtype, 69.99) is False
        assert is_attempt_correct(qtype, 100.0) is True


# =============================================================================
# 2. generator helpers — sin red
# =============================================================================
class TestBuildPrompt:
    def test_includes_topic_and_level(self) -> None:
        prompt = build_prompt(
            cefr_level="B1",
            skill="grammar",
            topic="past simple",
            num_questions=3,
            specific_instructions=None,
        )
        assert "B1" in prompt
        assert "past simple" in prompt
        assert "3" in prompt
        assert "grammar" in prompt
        # El prompt pide JSON puro.
        assert "JSON" in prompt

    def test_extra_instructions_included(self) -> None:
        prompt = build_prompt(
            cefr_level="A2",
            skill="vocabulary",
            topic="food",
            num_questions=5,
            specific_instructions="Focus on Latin American dishes.",
        )
        assert "Latin American" in prompt


class TestParseModelOutput:
    def test_direct_json(self) -> None:
        raw = '{"title": "T", "questions": []}'
        result = parse_model_output(raw)
        assert result == {"title": "T", "questions": []}

    def test_wrapped_in_markdown(self) -> None:
        raw = '```json\n{"title": "T"}\n```'
        result = parse_model_output(raw)
        assert result == {"title": "T"}

    def test_extra_prose_around(self) -> None:
        raw = 'Sure! Here is the JSON:\n{"title": "T"}\nThanks!'
        result = parse_model_output(raw)
        assert result == {"title": "T"}

    def test_no_json_raises_502(self) -> None:
        with pytest.raises(HTTPException) as exc:
            parse_model_output("just text, no braces here")
        assert exc.value.status_code == 502

    def test_malformed_json_raises_502(self) -> None:
        with pytest.raises(HTTPException) as exc:
            parse_model_output('{"title": unterminated')
        assert exc.value.status_code == 502


# =============================================================================
# 3. Contract HTTP — sin DB
# =============================================================================
def test_start_attempt_without_auth_returns_401() -> None:
    fake_id = uuid4()
    response = client.post(f"/challenges/{fake_id}/attempt")
    assert response.status_code == 401


def test_submit_without_auth_returns_401() -> None:
    fake_id = uuid4()
    q_id = uuid4()
    response = client.post(
        f"/challenges/attempts/{fake_id}/submit",
        json={"answers": [{"question_id": str(q_id), "answer": "A"}]},
    )
    assert response.status_code == 401


def test_get_challenge_detail_without_auth_returns_401() -> None:
    fake_id = uuid4()
    response = client.get(f"/challenges/{fake_id}")
    assert response.status_code == 401


# =============================================================================
# 4. Integration DB-bound — skipped
# =============================================================================
# BUG-1 (encontrado por esta fixture; src/ no se toca): AnswerSubmit hereda
# ConfigDict(strict=True) (src/challenge_engine/schemas.py:22) y declara
# `question_id: UUID` (schemas.py:141). FastAPI valida el body en modo Python,
# donde strict exige una instancia de UUID y rechaza el string del JSON: todo
# POST /challenges/attempts/{id}/submit con un cuerpo válido da 422
# (type=is_instance_of, loc=body.answers.0.question_id). strict=True: cuando se
# arregle, estos tests pasan a XPASS, que cuenta como fallo, y hay que quitar la marca.
_BUG_1 = pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="BUG-1: submit da 422 a todo JSON válido (strict=True + UUID en AnswerSubmit)",
)


def _responder(respuestas: list[tuple[object, str]]) -> dict:
    """Cuerpo de submit: [(question_id, answer), ...]."""
    return {"answers": [{"question_id": str(q), "answer": a} for q, a in respuestas]}


@pytest.mark.integ
def test_start_attempt_creates_in_progress(integ) -> None:
    tenant = integ.crear_tenant()
    teacher = integ.crear_perfil(tenant, rol="teacher")
    alumno = integ.crear_perfil(tenant)
    cid, _ = integ.crear_challenge(tenant, teacher)

    r = client.post(f"/challenges/{cid}/attempt", headers=integ.headers(alumno))
    assert r.status_code == 201
    body = r.json()
    assert body["attempt_number"] == 1
    assert body["challenge"]["id"] == str(cid)

    fila = integ.fila(
        "select id, status, student_id, tenant_id, challenge_id "
        "from challenge_attempts"
    )
    assert fila is not None
    assert str(fila["id"]) == body["attempt_id"]
    assert fila["status"] == "in_progress"
    assert (fila["student_id"], fila["tenant_id"], fila["challenge_id"]) == (
        alumno, tenant, cid
    )
    assert integ.valor("select count(*) from challenge_attempts") == 1


@pytest.mark.integ
def test_start_attempt_max_attempts_exceeded_returns_429(integ) -> None:
    tenant = integ.crear_tenant()
    teacher = integ.crear_perfil(tenant, rol="teacher")
    alumno = integ.crear_perfil(tenant)
    cid, _ = integ.crear_challenge(tenant, teacher, respuestas=("A",), max_attempts=1)
    # El único intento permitido ya se gastó (sembrado directo en la base: este
    # test es sobre start_attempt; no depende del submit por HTTP, ver BUG-1).
    integ.crear_intento(tenant, cid, alumno, status="completed")
    h = integ.headers(alumno)

    otra_vez = client.post(f"/challenges/{cid}/attempt", headers=h)
    assert otra_vez.status_code == 429
    assert otra_vez.json()["detail"] == "No attempts remaining for this challenge"
    assert integ.valor("select count(*) from challenge_attempts") == 1


@pytest.mark.integ
@_BUG_1
def test_submit_all_correct_awards_coins_and_xp(integ) -> None:
    tenant = integ.crear_tenant(pool=1000)
    teacher = integ.crear_perfil(tenant, rol="teacher")
    alumno = integ.crear_perfil(tenant)
    cid, qids = integ.crear_challenge(tenant, teacher, respuestas=("A", "B"),
                                      coins=20, xp=15)
    h = integ.headers(alumno)
    intento = client.post(f"/challenges/{cid}/attempt", headers=h).json()["attempt_id"]

    r = client.post(
        f"/challenges/attempts/{intento}/submit",
        json=_responder([(qids[0], "A"), (qids[1], " b ")]),  # strip + minúsculas
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_correct"] is True
    assert body["score_percent"] == 100.0
    assert body["coins_earned"] == 20
    assert body["xp_earned"] == 15
    assert body["correct_answers"] == [
        {"question_id": str(qids[0]), "correct_answer": "A"},
        {"question_id": str(qids[1]), "correct_answer": "B"},
    ]

    assert integ.saldo("profile", alumno) == 20
    assert integ.saldo("tenant", tenant) == 980
    assert integ.valor("select xp from profiles where id = :p", p=alumno) == 15
    assert integ.valor(
        "select current_winners from challenges where id = :c", c=cid
    ) == 1
    assert integ.valor(
        "select status from challenge_attempts where id = :a", a=intento
    ) == "completed"


@pytest.mark.integ
@_BUG_1
def test_submit_all_wrong_awards_nothing(integ) -> None:
    tenant = integ.crear_tenant(pool=1000)
    teacher = integ.crear_perfil(tenant, rol="teacher")
    alumno = integ.crear_perfil(tenant)
    cid, qids = integ.crear_challenge(tenant, teacher, respuestas=("A", "B"),
                                      coins=20, xp=15)
    h = integ.headers(alumno)
    intento = client.post(f"/challenges/{cid}/attempt", headers=h).json()["attempt_id"]

    r = client.post(
        f"/challenges/attempts/{intento}/submit",
        json=_responder([(qids[0], "Z"), (qids[1], "Z")]),
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_correct"] is False
    assert body["score_percent"] == 0.0
    assert body["coins_earned"] == 0
    assert body["xp_earned"] == 0

    assert integ.saldo("profile", alumno) in (None, 0)
    assert integ.saldo("tenant", tenant) == 1000
    assert integ.valor("select count(*) from coin_ledger") == 0
    assert integ.valor("select xp from profiles where id = :p", p=alumno) == 0
    assert integ.valor(
        "select current_winners from challenges where id = :c", c=cid
    ) == 0
    assert integ.valor(
        "select status from challenge_attempts where id = :a", a=intento
    ) == "completed"


@pytest.mark.integ
@_BUG_1
def test_submit_partial_correct_computes_score(integ) -> None:
    tenant = integ.crear_tenant(pool=1000)
    teacher = integ.crear_perfil(tenant, rol="teacher")
    alumno = integ.crear_perfil(tenant)
    cid, qids = integ.crear_challenge(tenant, teacher, respuestas=("A", "B", "C", "D"))
    h = integ.headers(alumno)
    intento = client.post(f"/challenges/{cid}/attempt", headers=h).json()["attempt_id"]

    r = client.post(
        f"/challenges/attempts/{intento}/submit",
        json=_responder([(qids[0], "A"), (qids[1], "B"), (qids[2], "C"), (qids[3], "X")]),
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["score_percent"] == 75.0  # 3 de 4
    # multiple_choice exige 100 %: 75 no gana ni cobra.
    assert body["is_correct"] is False
    assert body["coins_earned"] == 0
    assert float(integ.valor(
        "select score_percent from challenge_attempts where id = :a", a=intento
    )) == 75.0


@pytest.mark.integ
@_BUG_1
def test_submit_twice_returns_409(integ) -> None:
    tenant = integ.crear_tenant(pool=1000)
    teacher = integ.crear_perfil(tenant, rol="teacher")
    alumno = integ.crear_perfil(tenant)
    cid, qids = integ.crear_challenge(tenant, teacher, respuestas=("A",), coins=20)
    h = integ.headers(alumno)
    intento = client.post(f"/challenges/{cid}/attempt", headers=h).json()["attempt_id"]
    respuestas = _responder([(qids[0], "A")])

    primero = client.post(
        f"/challenges/attempts/{intento}/submit", json=respuestas, headers=h
    )
    assert primero.status_code == 200, primero.text

    segundo = client.post(
        f"/challenges/attempts/{intento}/submit", json=respuestas, headers=h
    )
    assert segundo.status_code == 409
    assert segundo.json()["detail"] == "Attempt already completed or abandoned"
    # No se paga dos veces.
    assert integ.saldo("profile", alumno) == 20
    assert integ.valor("select count(*) from coin_ledger") == 1


@pytest.mark.integ
@_BUG_1
def test_submit_increments_current_winners_only_if_correct(integ) -> None:
    tenant = integ.crear_tenant(pool=1000)
    teacher = integ.crear_perfil(tenant, rol="teacher")
    falla = integ.crear_perfil(tenant)
    acierta = integ.crear_perfil(tenant)
    cid, qids = integ.crear_challenge(tenant, teacher, respuestas=("A",))

    def enviar(alumno, respuesta: str) -> dict:
        h = integ.headers(alumno)
        intento = client.post(f"/challenges/{cid}/attempt", headers=h).json()["attempt_id"]
        r = client.post(
            f"/challenges/attempts/{intento}/submit",
            json=_responder([(qids[0], respuesta)]),
            headers=h,
        )
        assert r.status_code == 200, r.text
        return r.json()

    assert enviar(falla, "Z")["is_correct"] is False
    assert integ.valor(
        "select current_winners from challenges where id = :c", c=cid
    ) == 0

    assert enviar(acierta, "A")["is_correct"] is True
    assert integ.valor(
        "select current_winners from challenges where id = :c", c=cid
    ) == 1
