"""Tests del submódulo challenges — SPECS/03-challenges.md §10.

Niveles:
  1. Contract HTTP (sin DB) — los 3 casos del checklist §11:
       - GET  /challenges/ sin auth        → 401
       - POST /challenges/ con JWT student → 403 (observable; en smoke el
         JWT fabricado sin memberships también da 403)
       - correct_answer NO aparece en salidas al estudiante (verificado
         a nivel Pydantic: inspect ChallengeQuestionOut.model_fields)
  2. Unit (sin DB) — schema contract del ChallengeQuestionOut.
  3. Integration (con DB) — CRUD completo + listado filtrado por grupo;
     `@pytest.mark.skip` hasta que exista fixture de testcontainers.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.auth.schemas import AuthContext
from src.challenge_engine.schemas import ChallengeOut, ChallengeQuestionOut
from src.main import app
from src.shared.deps import get_current_user

from tests.auth.conftest import make_jwt  # noqa: F401  (export for other tests)

client = TestClient(app)


def _student_auth_context() -> AuthContext:
    """AuthContext de un usuario student (sin teacher ni admin).

    Se usa con `app.dependency_overrides` para bypasear la DB en tests de
    contract HTTP que solo quieren verificar el contrato de permisos.
    """
    return AuthContext(
        profile_id=uuid4(),
        role="student",
        tenant_id=uuid4(),
        group_code=None,
        is_teacher=False,
        is_admin=False,
    )


# =============================================================================
# 1. Contract HTTP — sin DB
# =============================================================================
def test_list_challenges_without_auth_returns_401() -> None:
    response = client.get("/challenges/")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


def test_create_challenge_without_auth_returns_401() -> None:
    response = client.post(
        "/challenges/",
        json={
            "title": "Test",
            "description": "x",
            "questions": [
                {
                    "question_text": "Q?",
                    "correct_answer": "A",
                    "options_json": [{"label": "A", "value": "A"}],
                }
            ],
        },
    )
    assert response.status_code == 401


def test_get_all_without_auth_returns_401() -> None:
    response = client.get("/challenges/all")
    assert response.status_code == 401


def test_attempts_history_without_auth_returns_401() -> None:
    response = client.get("/challenges/attempts/history")
    assert response.status_code == 401


def test_generate_without_auth_returns_401() -> None:
    response = client.post(
        "/challenges/generate",
        json={"cefr_level": "B1", "skill": "grammar", "topic": "past simple"},
    )
    assert response.status_code == 401


def test_create_challenge_with_student_role_returns_403() -> None:
    """Checklist §11 caso 2: JWT con rol student → 403.

    Usamos `app.dependency_overrides` para inyectar un AuthContext con
    `role='student'` sin tocar DB ni Supabase. `require_teacher` debe
    rechazar el request con 403.
    """
    app.dependency_overrides[get_current_user] = _student_auth_context
    try:
        response = client.post(
            "/challenges/",
            json={
                "title": "Test",
                "description": "x",
                "questions": [
                    {
                        "question_text": "Q?",
                        "correct_answer": "A",
                        "options_json": [{"label": "A", "value": "A"}],
                    }
                ],
            },
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 403
    assert "teacher" in response.json()["detail"].lower()


def test_generate_with_student_role_returns_403() -> None:
    """POST /challenges/generate también exige teacher role."""
    app.dependency_overrides[get_current_user] = _student_auth_context
    try:
        response = client.post(
            "/challenges/generate",
            json={
                "cefr_level": "B1",
                "skill": "grammar",
                "topic": "past simple",
            },
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 403


def test_get_all_with_student_role_returns_403() -> None:
    """GET /challenges/all es vista docente → 403 para student."""
    app.dependency_overrides[get_current_user] = _student_auth_context
    try:
        response = client.get("/challenges/all")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 403


# =============================================================================
# 2. Unit — contrato de schemas
# =============================================================================
def test_challenge_question_out_omits_correct_answer() -> None:
    """Regla crítica §9: correct_answer NUNCA sale al estudiante.

    El schema público del ChallengeQuestionOut no debe incluir el
    campo `correct_answer`. Ni en declaración ni como Optional.
    """
    fields = ChallengeQuestionOut.model_fields
    assert "correct_answer" not in fields, (
        "ChallengeQuestionOut debe omitir correct_answer — ver SPECS §9"
    )


def test_challenge_out_questions_do_not_leak_correct_answer() -> None:
    """Los tipos anidados de ChallengeOut tampoco exponen correct_answer."""
    # `questions` es List[ChallengeQuestionOut] — reusamos el test anterior
    # verificando que la anotación del field es precisamente ese tipo.
    annotation = ChallengeOut.model_fields["questions"].annotation
    # `list[ChallengeQuestionOut]`: extraemos arg 0.
    args = getattr(annotation, "__args__", ())
    assert args and args[0] is ChallengeQuestionOut


# =============================================================================
# 3. Integration DB-bound — skipped hasta fixture de Postgres
# =============================================================================
@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_create_challenge_teacher_returns_201() -> None:
    """Teacher con JWT + memberships válidos → 201 y ChallengeOut completo."""
    ...


@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_list_challenges_student_filters_by_group() -> None:
    """Student solo ve challenges globales o de su grupo."""
    ...


@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_list_challenges_hides_correct_answer_at_http() -> None:
    """En el JSON de /challenges/ no debe aparecer 'correct_answer' (smoke real)."""
    ...


@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_patch_status_updates_row() -> None:
    """PATCH /{id}/status con teacher → status actualizado."""
    ...


@pytest.mark.skip(reason="Needs testcontainers Postgres fixture (Fase 1 integ)")
def test_list_excludes_full_capacity() -> None:
    """Challenges con current_winners == max_winners no aparecen en el feed."""
    ...
