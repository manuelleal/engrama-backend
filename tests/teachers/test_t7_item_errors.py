"""F13 y las celdas de T7 — ESPEC §2.3, §3, §4: `GET /teachers/groups/{gid}/item-errors`.

F13 siembra (§4): un ítem con 5 respondientes y 3 errores (2 en la misma
opción, 1 en blanco); un ítem con 4 respondientes (X20, suprimido); un reto
de OTRO grupo con 5+ respondientes (X21, no debe colarse).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.teachers._actores import armar

pytestmark = pytest.mark.integ
client = TestClient(app)


def _sembrar(integ, esc):
    """Devuelve (question_id del ítem visible, challenge_id del ítem suprimido)."""
    # --- Ítem 1: 5 respondientes, 3 errores (2 en "B", 1 en blanco).
    cid1, qids1 = integ.crear_challenge(esc.tenant_a, esc.d, respuestas=("A",),
                                        group_id=esc.grupo_a, skill="grammar")
    qid1 = qids1[0]
    respuestas_1 = [
        ("opcion uno", True), ("opcion uno", True),
        ("opcion dos", False), ("opcion dos", False),
        ("", False),
    ]
    for dado, ok in respuestas_1:
        alumno = integ.crear_perfil(esc.tenant_a, group_code=esc.codigo_a)
        integ.crear_intento(esc.tenant_a, cid1, alumno,
                            answers=[{"question_id": str(qid1), "given_answer": dado,
                                      "correct_answer": "A", "is_correct": ok}])

    # --- Ítem 2 (X20): 4 respondientes -> suprimido.
    cid2, qids2 = integ.crear_challenge(esc.tenant_a, esc.d, respuestas=("A",),
                                        group_id=esc.grupo_a, skill="grammar")
    qid2 = qids2[0]
    for _ in range(4):
        alumno = integ.crear_perfil(esc.tenant_a, group_code=esc.codigo_a)
        integ.crear_intento(esc.tenant_a, cid2, alumno,
                            answers=[{"question_id": str(qid2), "given_answer": "opcion dos",
                                      "correct_answer": "A", "is_correct": False}])

    # --- X21: reto de OTRO grupo, 5 respondientes — pero estudiantes DE GA
    # (roster de esc.grupo_a), para que el bug de X21 (sin filtro de
    # `group_id`) sea el ÚNICO motivo por el que podría colarse: si los
    # respondientes fueran de otro grupo, el filtro por `student_ids` del
    # roster ya los excluiría y el tramposo no se notaría.
    grupo_c = integ.crear_grupo(esc.tenant_a, "GC")
    cid3, qids3 = integ.crear_challenge(esc.tenant_a, esc.d, respuestas=("A",),
                                        group_id=grupo_c, skill="grammar")
    qid3 = qids3[0]
    for _ in range(5):
        alumno_de_ga = integ.crear_perfil(esc.tenant_a, group_code=esc.codigo_a)
        integ.crear_intento(esc.tenant_a, cid3, alumno_de_ga,
                            answers=[{"question_id": str(qid3), "given_answer": "opcion dos",
                                      "correct_answer": "A", "is_correct": False}])
    return qid1, qid2, qid3


def test_f13_agregado_supresion_y_sin_filtracion_de_otro_grupo(integ) -> None:
    esc = armar(integ)
    qid1, qid2, qid3 = _sembrar(integ, esc)

    r = client.get(f"/teachers/groups/{esc.grupo_a}/item-errors", headers=esc.h(integ, esc.d))
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["method"] == {
        "window_days": 28, "first_attempt_only": True, "min_respondents": 5,
        "excluded_types": ["open"],
    }
    assert body["suppressed_items"] == 1  # el ítem de 4 respondientes (X20)

    ids_mostrados = {it["question_id"] for it in body["items"]}
    assert str(qid1) in ids_mostrados
    assert str(qid2) not in ids_mostrados, "el ítem de 4 respondientes no debe mostrarse (X20)"
    assert str(qid3) not in ids_mostrados, "el reto de OTRO grupo se coló (X21)"

    item1 = next(it for it in body["items"] if it["question_id"] == str(qid1))
    assert (item1["respondents"], item1["errors"], item1["blank_answers"]) == (5, 3, 1)
    assert item1["top_distractor"] == {"label": "B", "value": "opcion dos", "count": 2}

    # Nunca sale profile_id ni respuestas individuales.
    assert "profile_id" not in r.text


def test_t7_e_403(integ) -> None:
    esc = armar(integ)
    r = client.get(f"/teachers/groups/{esc.grupo_a}/item-errors", headers=esc.h(integ, esc.e))
    assert r.status_code == 403, r.text


def test_t7_do_404(integ) -> None:
    esc = armar(integ)
    r = client.get(f"/teachers/groups/{esc.grupo_a}/item-errors", headers=esc.h(integ, esc.do))
    assert r.status_code == 404, r.text


def test_t7_dt_404(integ) -> None:
    esc = armar(integ)
    r = client.get(f"/teachers/groups/{esc.grupo_a}/item-errors", headers=esc.h(integ, esc.dt))
    assert r.status_code == 404, r.text


def test_t7_dm_404(integ) -> None:
    esc = armar(integ)
    r = client.get(f"/teachers/groups/{esc.grupo_a}/item-errors",
                    headers=esc.h(integ, esc.dm, tenant=esc.tenant_b))
    assert r.status_code == 404, r.text


def test_t7_ab_404(integ) -> None:
    esc = armar(integ)
    r = client.get(f"/teachers/groups/{esc.grupo_a}/item-errors", headers=esc.h(integ, esc.ab))
    assert r.status_code == 404, r.text


def test_t7_aa_404(integ) -> None:
    """`only_assigned=True`: AA (admin del MISMO colegio, sin `teacher_groups`) -> 404."""
    esc = armar(integ)
    r = client.get(f"/teachers/groups/{esc.grupo_a}/item-errors", headers=esc.h(integ, esc.aa))
    assert r.status_code == 404, r.text
