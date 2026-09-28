"""U3a-U3g — ESPEC §2.1, §4: el logro de T5, sin DB (funciones puras).

`compute_achievement_for_student` recibe `now` como parámetro (METODO.md:
"la excepción es todo lo que genera... no, aquí NO es LLM, pero `now` se
inyecta igual para que el test controle el tiempo sin `sleep`).
"""
from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.teachers.schemas import (
    AchievementMethodOut,
    AttemptDetailOut,
    AxisOut,
    SkillDetailOut,
    StudentAchievementOut,
)
from src.teachers.service.achievement import AttemptRow, compute_achievement_for_student

AHORA = datetime(2026, 9, 25, tzinfo=UTC)


def _respuestas(n_correctas: int, n_total: int) -> list[dict[str, object]]:
    return [{"question_id": str(uuid4()), "given_answer": "x", "correct_answer": "x",
              "is_correct": i < n_correctas} for i in range(n_total)]


def _intento(
    *, cid=None, skill: str | None = "grammar", tipo: str = "multiple_choice",
    n_correctas: int = 8, n_total: int = 8, hace_dias: float = 1,
    started_offset_s: int = 0, cefr: str | None = None,
) -> AttemptRow:
    completado = AHORA - timedelta(days=hace_dias)
    return AttemptRow(
        attempt_id=uuid4(), challenge_id=cid or uuid4(), title="Reto",
        skill=skill, cefr_level=cefr, challenge_type=tipo,
        answers=_respuestas(n_correctas, n_total),
        score_percent=100.0 * n_correctas / n_total if n_total else 0.0,
        is_correct=n_correctas == n_total,
        started_at=completado - timedelta(seconds=started_offset_s),
        completed_at=completado,
    )


# =============================================================================
# U3a — el primer intento manda; el reintento no cuenta.
# =============================================================================
def test_u3a_primer_intento_manda_no_el_reintento() -> None:
    cid = uuid4()
    primero = _intento(cid=cid, n_correctas=0, n_total=8, hace_dias=5)  # falla
    reintento = _intento(cid=cid, n_correctas=8, n_total=8, hace_dias=1)  # acierta
    resultado = compute_achievement_for_student([reintento, primero], AHORA)
    eje = next(a for a in resultado["axes"] if a.axis == "Accuracy")
    assert (eje.items, eje.correct) == (8, 0)  # cuenta el PRIMERO (falló), no el reintento
    assert resultado["attempts"][0].first_attempt is True  # el más viejo es el primero
    assert len(resultado["attempts"]) == 2  # ambos están DENTRO de la ventana


# =============================================================================
# U3b — la ventana: borde exacto de 28 días (entra) y 28+1s (sale); un primer
# intento fuera de la ventana no deja entrar al reintento.
# =============================================================================
def test_u3b_ventana_de_28_dias() -> None:
    en_el_borde = _intento(n_correctas=8, n_total=8, hace_dias=28)
    r_borde = compute_achievement_for_student([en_el_borde], AHORA)
    assert next(a for a in r_borde["axes"] if a.axis == "Accuracy").items == 8  # el borde ENTRA

    justo_afuera = dataclasses.replace(en_el_borde,
                                       completed_at=AHORA - timedelta(days=28, seconds=1))
    r_afuera = compute_achievement_for_student([justo_afuera], AHORA)
    assert next(a for a in r_afuera["axes"] if a.axis == "Accuracy").items == 0
    assert r_afuera["attempts"] == []

    cid = uuid4()
    primero_viejo = _intento(cid=cid, n_correctas=8, n_total=8, hace_dias=40)
    reintento_reciente = _intento(cid=cid, n_correctas=8, n_total=8, hace_dias=1,
                                  started_offset_s=1)
    r_reintento = compute_achievement_for_student([primero_viejo, reintento_reciente], AHORA)
    eje = next(a for a in r_reintento["axes"] if a.axis == "Accuracy")
    assert eje.items == 0, "el reto no debe aportar ítems: su PRIMER intento está fuera"
    # El reintento SÍ aparece en 'attempts' (detalle: está dentro de la ventana él solo).
    assert len(r_reintento["attempts"]) == 1
    assert r_reintento["attempts"][0].first_attempt is False


# =============================================================================
# U3c — el mínimo (8 ítems, 3 retos).
# =============================================================================
def test_u3c_minimo_8_items_3_retos() -> None:
    siete_de_3_cids = [uuid4(), uuid4(), uuid4()]
    siete_de_3 = [_intento(cid=siete_de_3_cids[i % 3], n_correctas=1, n_total=1)
                  for i in range(7)]
    r = compute_achievement_for_student(siete_de_3, AHORA)
    assert next(a for a in r["axes"] if a.axis == "Accuracy").status == "datos_insuficientes"

    # 8 ítems, pero de solo 2 retos distintos (4 preguntas cada uno).
    cid_a, cid_b = uuid4(), uuid4()
    ocho_de_2 = [_intento(cid=cid_a, n_correctas=4, n_total=4),
                 _intento(cid=cid_b, n_correctas=4, n_total=4)]
    r2 = compute_achievement_for_student(ocho_de_2, AHORA)
    assert next(a for a in r2["axes"] if a.axis == "Accuracy").status == "datos_insuficientes"

    cid_c = uuid4()
    ocho_de_3 = [_intento(cid=cid_a, n_correctas=3, n_total=3),
                 _intento(cid=cid_b, n_correctas=3, n_total=3),
                 _intento(cid=cid_c, n_correctas=2, n_total=2)]
    r3 = compute_achievement_for_student(ocho_de_3, AHORA)
    eje3 = next(a for a in r3["axes"] if a.axis == "Accuracy")
    assert eje3.items == 8 and eje3.challenges == 3
    assert eje3.status != "datos_insuficientes"


# =============================================================================
# U3d — los umbrales, n = 10.
# =============================================================================
def test_u3d_umbrales_n_10() -> None:
    def _estado(correctas: int) -> str:
        cid_a, cid_b, cid_c = uuid4(), uuid4(), uuid4()
        faltan = 10 - correctas
        intentos = [
            _intento(cid=cid_a, n_correctas=min(correctas, 4), n_total=4),
            _intento(cid=cid_b, n_correctas=max(0, min(correctas - 4, 3)), n_total=3),
            _intento(cid=cid_c, n_correctas=max(0, correctas - 7), n_total=3),
        ]
        r = compute_achievement_for_student(intentos, AHORA)
        eje = next(a for a in r["axes"] if a.axis == "Accuracy")
        assert eje.items == 10, (eje.items, correctas, faltan)
        return eje.status

    assert _estado(8) == "logrado"          # 80/100
    assert _estado(7) == "en_desarrollo"    # 70/100
    assert _estado(6) == "en_desarrollo"    # 60/100 (umbral inclusive)
    assert _estado(5) == "a_reforzar"       # 50/100


# =============================================================================
# U3e — el mapeo de skill a eje.
# =============================================================================
def test_u3e_mapeo_normaliza_y_desconocidas_van_a_unmapped() -> None:
    intentos = [
        _intento(cid=uuid4(), skill=" Reading ", n_correctas=1, n_total=1),
        _intento(cid=uuid4(), skill="GRAMMAR", n_correctas=1, n_total=1),
        _intento(cid=uuid4(), skill="pronunciation", n_correctas=1, n_total=1),
        _intento(cid=uuid4(), skill=None, n_correctas=1, n_total=1),
    ]
    r = compute_achievement_for_student(intentos, AHORA)
    comprehension = next(a for a in r["axes"] if a.axis == "Comprehension")
    accuracy = next(a for a in r["axes"] if a.axis == "Accuracy")
    assert comprehension.items == 1  # "Reading" normalizado -> Comprehension
    assert accuracy.items == 1       # "GRAMMAR" normalizado -> Accuracy
    assert r["unmapped_items"] == 2  # pronunciation + NULL
    skills_por_nombre = {s.skill: s for s in r["skills"]}
    assert set(skills_por_nombre) == {"reading", "grammar", "pronunciation", None}


# =============================================================================
# U3f — el lenguaje: nunca "weak"/"débil"/"debil"; la etiqueta exacta.
# =============================================================================
def test_u3f_lenguaje_sin_weak_y_etiqueta_a_reforzar() -> None:
    cid_a, cid_b, cid_c = uuid4(), uuid4(), uuid4()
    intentos = [
        _intento(cid=cid_a, skill="writing", n_correctas=0, n_total=4),
        _intento(cid=cid_b, skill="speaking", n_correctas=0, n_total=3),
        _intento(cid=cid_c, skill="writing", n_correctas=0, n_total=3),
    ]
    r = compute_achievement_for_student(intentos, AHORA)
    expression = next(a for a in r["axes"] if a.axis == "Expression")
    assert expression.status == "a_reforzar"
    assert expression.label == "a reforzar: Expression"

    for esquema in (AchievementMethodOut, AxisOut, SkillDetailOut,
                    AttemptDetailOut, StudentAchievementOut):
        for campo in esquema.model_fields:
            bajo = campo.lower()
            assert "weak" not in bajo and "débil" not in bajo and "debil" not in bajo
    assert "weak" not in expression.label.lower()


# =============================================================================
# U3g — un reto `open` no aporta ítems.
# =============================================================================
def test_u3g_reto_open_no_aporta_items() -> None:
    solo_open = [_intento(tipo="open", n_correctas=8, n_total=8)]
    r = compute_achievement_for_student(solo_open, AHORA)
    assert all(a.items == 0 for a in r["axes"])
    assert r["attempts"] == []
