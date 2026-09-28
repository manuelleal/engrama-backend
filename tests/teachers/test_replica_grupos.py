"""Réplica de `/teachers` y `/admin` — ESPEC §5. Entradas NUEVAS, no usadas
al desarrollar (METODO.md regla 7): activa con `ENGRAMA_REPLICA_GRUPOS=1`.

Sin la bandera, cada test se salta (no suma a las cuentas de §4/§8 — la
espec cuenta "240/269 passed", no "passed + skipped"). Con ella, corren
contra el MISMO arnés (`tests.integ_ayudante.Integ`) pero con datos que la
espec nunca vio mientras se escribía el código.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.shared.models import TeacherGroup
from tests.teachers._actores import armar

pytestmark = [
    pytest.mark.integ,
    pytest.mark.skipif(
        os.environ.get("ENGRAMA_REPLICA_GRUPOS") != "1",
        reason="réplica: exporta ENGRAMA_REPLICA_GRUPOS=1 (ESPEC §5)",
    ),
]
client = TestClient(app)


def test_replica_codigo_de_grupo_con_tilde_y_espacio(integ) -> None:
    esc = armar(integ, codigo_a="Sección Ñoño 1")
    r = client.get("/teachers/groups", headers=esc.h(integ, esc.d))
    assert r.status_code == 200, r.text
    assert r.json()[0]["group_code"] == "Sección Ñoño 1"


def test_replica_csv_40_filas_punto_y_coma_y_bom(integ) -> None:
    esc = armar(integ)
    filas = [f"doc-r{i};Estudiante {i}" for i in range(40)]
    csv_texto = "documento_id;nombre_completo\n" + "\n".join(filas) + "\n"
    r = client.post(
        f"/admin/groups/{esc.grupo_a}/students/import",
        headers={**esc.h(integ, esc.aa), "Content-Type": "text/csv"},
        content=csv_texto.encode("utf-8-sig"),
    )
    assert r.status_code == 201, r.text
    assert r.json() == {"creados": 40, "ya_estaban": 0, "total": 40}


def test_replica_docente_con_2_grupos(integ) -> None:
    esc = armar(integ)
    grupo_2 = integ.crear_grupo(esc.tenant_a, "GA-2")
    integ._insertar(TeacherGroup(tenant_id=esc.tenant_a, teacher_id=esc.d, group_id=grupo_2))
    r = client.get("/teachers/groups", headers=esc.h(integ, esc.d))
    assert r.status_code == 200, r.text
    assert {g["group_code"] for g in r.json()} == {esc.codigo_a, "GA-2"}


def test_replica_b_con_codigo_identico_a_ga_no_se_filtra(integ) -> None:
    """T2 de GA no puede listar a los estudiantes de B, aunque compartan `group_code`."""
    esc = armar(integ, codigo_a="MISMO-CODIGO", codigo_b="MISMO-CODIGO")
    estudiante_b = integ.crear_perfil(esc.tenant_b, group_code="MISMO-CODIGO")
    r = client.get(f"/teachers/groups/{esc.grupo_a}/students", headers=esc.h(integ, esc.d))
    assert r.status_code == 200, r.text
    ids = {s["profile_id"] for s in r.json()}
    assert str(estudiante_b) not in ids
    assert ids == {str(esc.e)}


def test_replica_t5_skills_con_mayusculas_y_espacios(integ) -> None:
    """Un eje con EXACTAMENTE 8 ítems de 3 retos y 60 % -> en_desarrollo."""
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    esc = armar(integ)
    ahora = datetime.now(UTC)

    def _respuestas(correctas: int, total: int) -> list[dict[str, object]]:
        return [{"question_id": str(uuid4()), "given_answer": "x", "correct_answer": "x",
                  "is_correct": i < correctas} for i in range(total)]

    cid_a, _ = integ.crear_challenge(esc.tenant_a, esc.d, respuestas=tuple("ABCD"),
                                     group_id=esc.grupo_a, skill="Listening")
    cid_b, _ = integ.crear_challenge(esc.tenant_a, esc.d, respuestas=tuple("ABC"),
                                     group_id=esc.grupo_a, skill="vocabulary ")  # otro eje (Accuracy)
    cid_c, _ = integ.crear_challenge(esc.tenant_a, esc.d, respuestas=tuple("AB"),
                                     group_id=esc.grupo_a, skill="Listening")
    cid_d, _ = integ.crear_challenge(esc.tenant_a, esc.d, respuestas=tuple("AB"),
                                     group_id=esc.grupo_a, skill="listening")
    # Comprehension: 3 retos (cid_a 4, cid_c 2, cid_d 2) = 8 ítems, 60% -> en_desarrollo.
    integ.crear_intento(esc.tenant_a, cid_a, esc.e, answers=_respuestas(2, 4),
                        completed_at=ahora - timedelta(days=1))
    integ.crear_intento(esc.tenant_a, cid_c, esc.e, answers=_respuestas(1, 2),
                        completed_at=ahora - timedelta(days=1))
    integ.crear_intento(esc.tenant_a, cid_d, esc.e, answers=_respuestas(2, 2),
                        completed_at=ahora - timedelta(days=1))
    integ.crear_intento(esc.tenant_a, cid_b, esc.e, answers=_respuestas(0, 3),
                        completed_at=ahora - timedelta(days=1))

    r = client.get(f"/teachers/groups/{esc.grupo_a}/achievement", headers=esc.h(integ, esc.d))
    assert r.status_code == 200, r.text
    est = r.json()["students"][0]
    comprehension = next(a for a in est["axes"] if a["axis"] == "Comprehension")
    assert (comprehension["items"], comprehension["correct"]) == (8, 5)  # 2+1+2 = 5/8 = 62.5%
    assert comprehension["status"] == "en_desarrollo"


def test_replica_t7_exactamente_5_respondientes_respuesta_como_label(integ) -> None:
    esc = armar(integ)
    cid, qids = integ.crear_challenge(esc.tenant_a, esc.d, respuestas=("A",),
                                      group_id=esc.grupo_a, skill="grammar")
    qid = qids[0]
    for i in range(5):
        alumno = integ.crear_perfil(esc.tenant_a, group_code=esc.codigo_a)
        # Responde con el LABEL de una opción incorrecta ("B"), no su value.
        dado = "B" if i < 3 else "opcion uno"
        ok = dado == "opcion uno"
        integ.crear_intento(esc.tenant_a, cid, alumno,
                            answers=[{"question_id": str(qid), "given_answer": dado,
                                      "correct_answer": "A", "is_correct": ok}])
    r = client.get(f"/teachers/groups/{esc.grupo_a}/item-errors", headers=esc.h(integ, esc.d))
    assert r.status_code == 200, r.text
    item = next(it for it in r.json()["items"] if it["question_id"] == str(qid))
    assert item["respondents"] == 5
    assert item["top_distractor"] == {"label": "B", "value": "opcion dos", "count": 3}
