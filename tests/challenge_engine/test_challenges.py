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
@pytest.mark.integ
def test_create_challenge_teacher_returns_201(integ) -> None:
    """Teacher con JWT + memberships válidos → 201 y ChallengeOut completo."""
    tenant = integ.crear_tenant()
    teacher = integ.crear_perfil(tenant, rol="teacher")
    payload = {
        "title": "At the Airport",
        "description": "Check-in y seguridad",
        "cefr_level": "A2",
        "skill": "vocabulary",
        "topic": "travel",
        "coins_reward": 20,
        "xp_reward": 15,
        "max_attempts": 3,
        "max_winners": 5,
        "questions": [
            {
                "question_text": "Where do you show your passport?",
                "correct_answer": "B",
                "options_json": [{"label": "A", "value": "Gate"},
                                 {"label": "B", "value": "Immigration"}],
                "order_index": 1,
            },
            {
                "question_text": "What do you check in?",
                "correct_answer": "A",
                "options_json": [{"label": "A", "value": "Luggage"},
                                 {"label": "B", "value": "Ticket"}],
                "order_index": 2,
            },
        ],
    }

    r = client.post("/challenges/", json=payload, headers=integ.headers(teacher))
    assert r.status_code == 201
    body = r.json()

    # ChallengeOut completo: exactamente sus campos, con los valores enviados.
    assert set(body) == set(ChallengeOut.model_fields)
    esperado = {
        "title": "At the Airport",
        "description": "Check-in y seguridad",
        "challenge_type": "multiple_choice",
        "cefr_level": "A2",
        "skill": "vocabulary",
        "topic": "travel",
        "coins_reward": 20,
        "xp_reward": 15,
        "max_attempts": 3,
        "max_winners": 5,
        "current_winners": 0,
        "status": "active",
    }
    assert {k: body[k] for k in esperado} == esperado
    assert [q["question_text"] for q in body["questions"]] == [
        "Where do you show your passport?",
        "What do you check in?",
    ]
    assert [q["order_index"] for q in body["questions"]] == [1, 2]
    assert all(set(q) == set(ChallengeQuestionOut.model_fields)
               for q in body["questions"])

    # Persistido en el tenant del teacher, con las respuestas guardadas.
    fila = integ.fila(
        "select tenant_id, created_by from challenges where id = :c", c=body["id"]
    )
    assert fila == {"tenant_id": tenant, "created_by": teacher}
    assert integ.valor(
        "select string_agg(correct_answer, ',' order by order_index) "
        "from challenge_questions where challenge_id = :c", c=body["id"]
    ) == "B,A"


@pytest.mark.integ
def test_list_challenges_student_filters_by_group(integ) -> None:
    """Student solo ve challenges globales o de su grupo."""
    tenant = integ.crear_tenant()
    g1 = integ.crear_grupo(tenant, "G1")
    g2 = integ.crear_grupo(tenant, "G2")
    teacher = integ.crear_perfil(tenant, rol="teacher")
    alumno = integ.crear_perfil(tenant, group_code="G1")

    global_id, _ = integ.crear_challenge(tenant, teacher, group_id=None)
    del_g1, _ = integ.crear_challenge(tenant, teacher, group_id=g1)
    del_g2, _ = integ.crear_challenge(tenant, teacher, group_id=g2)

    r = client.get("/challenges/", headers=integ.headers(alumno))
    assert r.status_code == 200
    vistos = {c["id"] for c in r.json()}
    assert vistos == {str(global_id), str(del_g1)}
    assert str(del_g2) not in vistos


@pytest.mark.integ
def test_list_challenges_hides_correct_answer_at_http(integ) -> None:
    """En el JSON de /challenges/ no debe aparecer 'correct_answer' (smoke real)."""
    tenant = integ.crear_tenant()
    teacher = integ.crear_perfil(tenant, rol="teacher")
    alumno = integ.crear_perfil(tenant)
    secreto = "RESPUESTA_SECRETA_XYZ"
    cid, qids = integ.crear_challenge(tenant, teacher, respuestas=(secreto, "B"))

    r = client.get("/challenges/", headers=integ.headers(alumno))
    assert r.status_code == 200
    body = r.json()
    # El reto está en el feed y trae sus preguntas: la ausencia significa algo.
    assert [c["id"] for c in body] == [str(cid)]
    assert [q["id"] for q in body[0]["questions"]] == [str(q) for q in qids]
    assert "correct_answer" not in r.text
    assert secreto not in r.text


@pytest.mark.integ
def test_patch_status_updates_row(integ) -> None:
    """PATCH /{id}/status con teacher → status actualizado."""
    tenant = integ.crear_tenant()
    teacher = integ.crear_perfil(tenant, rol="teacher")
    cid, _ = integ.crear_challenge(tenant, teacher, status="active")

    r = client.patch(
        f"/challenges/{cid}/status",
        json={"status": "inactive"},
        headers=integ.headers(teacher),
    )
    assert r.status_code == 200
    assert r.json()["id"] == str(cid)
    assert r.json()["status"] == "inactive"
    assert integ.valor("select status from challenges where id = :c", c=cid) == "inactive"


@pytest.mark.integ
def test_list_excludes_full_capacity(integ) -> None:
    """Challenges con current_winners == max_winners no aparecen en el feed."""
    tenant = integ.crear_tenant()
    teacher = integ.crear_perfil(tenant, rol="teacher")
    alumno = integ.crear_perfil(tenant)
    lleno, _ = integ.crear_challenge(tenant, teacher, max_winners=3, current_winners=3)
    con_cupo, _ = integ.crear_challenge(tenant, teacher, max_winners=3, current_winners=2)

    r = client.get("/challenges/", headers=integ.headers(alumno))
    assert r.status_code == 200
    vistos = [c["id"] for c in r.json()]
    assert vistos == [str(con_cupo)]
    assert str(lleno) not in vistos
