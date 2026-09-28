"""U5 y U6 — ESPEC §2.3, §4: el distractor y la supresión de T7, sin DB."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from src.teachers.service.achievement import AttemptRow
from src.teachers.service.item_errors import QuestionMeta, compute_item_errors

AHORA = datetime(2026, 9, 25, tzinfo=UTC)
OPCIONES = [
    {"label": "A", "value": "gato"},
    {"label": "B", "value": "perro"},
    {"label": "C", "value": "loro"},
]


def _pregunta(qid, *, correct: str = "A", opciones=OPCIONES) -> QuestionMeta:
    return QuestionMeta(question_id=qid, order_index=1, question_text="¿Cuál?",
                        options_json=opciones, correct_answer=correct)


def _fila(student_id, qid, dado: str, correcta: bool):
    intento = AttemptRow(
        attempt_id=uuid4(), challenge_id=uuid4(), title="Reto", skill="grammar",
        cefr_level=None, challenge_type="multiple_choice",
        answers=[{"question_id": str(qid), "given_answer": dado, "correct_answer": "A",
                  "is_correct": correcta}],
        score_percent=100.0 if correcta else 0.0, is_correct=correcta,
        started_at=AHORA, completed_at=AHORA,
    )
    return (student_id, intento)


def _calificados(qid, respuestas: list[tuple[str, bool]]):
    return [_fila(uuid4(), qid, dado, ok) for dado, ok in respuestas]


# =============================================================================
# U5 — el distractor.
# =============================================================================
def test_u5_distractor() -> None:
    qid = uuid4()
    # 5 respondientes: 2 "perro"(B), 1 "loro"(C), 1 "A" (correcta, no cuenta),
    # 1 vacía (no cuenta). Gana "perro".
    calif = _calificados(qid, [
        ("perro", False), ("perro", False), ("loro", False),
        ("A", False),  # respondió el label de la correcta -> nunca cuenta
        ("", False),
    ])
    r = compute_item_errors(calif, {qid: _pregunta(qid)})
    item = r["items"][0]
    assert item["respondents"] == 5 and item["errors"] == 5
    assert item["top_distractor"].label == "B" and item["top_distractor"].count == 2

    # La opción correcta NUNCA cuenta, ni aunque tenga más respuestas que la
    # que sí gana (X19: si se contara, "A" ganaría con 3 en vez de "B" con 1).
    qid_correcta = uuid4()
    calif_correcta = _calificados(qid_correcta, [
        ("A", False), ("A", False), ("A", False), ("perro", False), ("gato", True),
    ])
    r_correcta = compute_item_errors(calif_correcta, {qid_correcta: _pregunta(qid_correcta)})
    distractor = r_correcta["items"][0]["top_distractor"]
    assert distractor.label == "B" and distractor.count == 1

    # Empate B/C (1 cada uno) -> gana la primera en options_json (B).
    qid2 = uuid4()
    calif2 = _calificados(qid2, [
        ("perro", False), ("loro", False), ("gato", True), ("gato", True), ("gato", True),
    ])
    r2 = compute_item_errors(calif2, {qid2: _pregunta(qid2)})
    assert r2["items"][0]["top_distractor"].label == "B"

    # Sin opciones -> null. Sin coincidencias -> null.
    qid3 = uuid4()
    calif3 = _calificados(qid3, [("gato", True)] * 4 + [("marciano", False)])
    r3 = compute_item_errors(calif3, {qid3: _pregunta(qid3, opciones=[])})
    assert r3["items"][0]["top_distractor"] is None

    qid4 = uuid4()
    calif4 = _calificados(qid4, [("gato", True)] * 4 + [("marciano", False)])
    r4 = compute_item_errors(calif4, {qid4: _pregunta(qid4)})
    assert r4["items"][0]["top_distractor"] is None  # "marciano" no coincide con ninguna opción


# =============================================================================
# U6 — la supresión (< 5 respondientes).
# =============================================================================
def test_u6_supresion_4_suprime_5_visible() -> None:
    qid_4 = uuid4()
    calif_4 = _calificados(qid_4, [("perro", False)] * 4)
    r4 = compute_item_errors(calif_4, {qid_4: _pregunta(qid_4)})
    assert r4["items"] == [] and r4["suppressed_items"] == 1

    qid_5 = uuid4()
    calif_5 = _calificados(qid_5, [("perro", False)] * 5)
    r5 = compute_item_errors(calif_5, {qid_5: _pregunta(qid_5)})
    assert len(r5["items"]) == 1 and r5["suppressed_items"] == 0
    assert r5["items"][0]["respondents"] == 5

    # Un ítem cuya pregunta ya no existe se OMITE (ni cuenta ni suprime).
    qid_fantasma = uuid4()
    calif_fantasma = _calificados(qid_fantasma, [("perro", False)] * 10)
    r_omite = compute_item_errors(calif_fantasma, {})
    assert r_omite == {"items": [], "suppressed_items": 0}
