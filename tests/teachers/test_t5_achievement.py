"""F5 y las celdas de T5 — ESPEC §2, §2.1, §2.4, §3: `GET /teachers/groups/{gid}/achievement`.

F5 siembra (§4): un estudiante con 1er intento fallado + reintento acertado
(X11), un reto de OTRO grupo del mismo colegio (X6), y dos estudiantes cuyo
orden alfabético es el INVERSO de su logro (X18). Afirma el orden alfabético,
`method` constante (incluido `status_scope`, pedagogo P1), la ausencia de
monedas y la ausencia de `weak`/`débil`/`debil` en el cuerpo (X17).

`only_assigned=True` hace que hasta AA (admin del colegio) reciba 404 si no
está en `teacher_groups` de este grupo — por eso T5/T7 agregan AA a las
celdas prohibidas (§3).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.teachers._actores import armar

pytestmark = pytest.mark.integ
client = TestClient(app)


def _respuestas(n_correctas: int, n_total: int) -> list[dict[str, object]]:
    return [{"question_id": str(uuid4()), "given_answer": "x", "correct_answer": "x",
              "is_correct": i < n_correctas} for i in range(n_total)]


def _sembrar_logro(integ, esc) -> tuple[str, str]:
    """3 retos de GA (grammar, 3 preguntas c/u) + un reto de OTRO grupo (X6).

    AAA (peor, 0/9) y ZZZ (mejor, 9/9) — inverso del orden alfabético (X18).
    Devuelve (nombre_aaa, nombre_zzz).
    """
    aaa = integ.crear_perfil(esc.tenant_a, group_code=esc.codigo_a)
    zzz = integ.crear_perfil(esc.tenant_a, group_code=esc.codigo_a)
    from sqlalchemy import text

    async def _renombrar() -> None:
        async with integ.Session() as db:
            await db.execute(text("update profiles set full_name = 'AAA Estudiante' "
                                  "where id = :p"), {"p": aaa})
            await db.execute(text("update profiles set full_name = 'ZZZ Estudiante' "
                                  "where id = :p"), {"p": zzz})
            await db.commit()

    integ.run(_renombrar())

    challenges = [integ.crear_challenge(esc.tenant_a, esc.d, respuestas=("A", "B", "C"),
                                        group_id=esc.grupo_a, skill="grammar")[0]
                  for _ in range(3)]
    ahora = datetime.now(UTC)
    for cid in challenges:
        integ.crear_intento(esc.tenant_a, cid, aaa, answers=_respuestas(0, 3),
                            completed_at=ahora - timedelta(days=1))
        integ.crear_intento(esc.tenant_a, cid, zzz, answers=_respuestas(3, 3),
                            completed_at=ahora - timedelta(days=1))
    # X11: un reto APARTE para AAA con "1er intento falla (viejo), reintento
    # acierta (nuevo)" — así no altera los 9 ítems ya sembrados arriba y el
    # test puede afirmar que cuenta el PRIMERO (falla), no el reintento.
    reto_reintento = integ.crear_challenge(esc.tenant_a, esc.d, respuestas=("A",),
                                           group_id=esc.grupo_a, skill="grammar")[0]
    integ.crear_intento(esc.tenant_a, reto_reintento, aaa, answers=_respuestas(0, 1),
                        completed_at=ahora - timedelta(days=20))  # 1er intento: falla
    integ.crear_intento(esc.tenant_a, reto_reintento, aaa, answers=_respuestas(1, 1),
                        completed_at=ahora - timedelta(days=1))   # reintento: acierta

    # X6: un reto de OTRO grupo del mismo colegio, con intento de AAA.
    grupo_c = integ.crear_grupo(esc.tenant_a, "GC")
    reto_otro_grupo = integ.crear_challenge(esc.tenant_a, esc.d, respuestas=("A", "B"),
                                            group_id=grupo_c, skill="grammar")[0]
    integ.crear_intento(esc.tenant_a, reto_otro_grupo, aaa, answers=_respuestas(2, 2),
                        completed_at=ahora - timedelta(days=1))
    return "AAA Estudiante", "ZZZ Estudiante"


def test_f5_orden_alfabetico_method_y_sin_weak(integ) -> None:
    esc = armar(integ)
    nombre_aaa, nombre_zzz = _sembrar_logro(integ, esc)

    r = client.get(f"/teachers/groups/{esc.grupo_a}/achievement", headers=esc.h(integ, esc.d))
    assert r.status_code == 200, r.text
    body = r.json()

    nombres = [s["full_name"] for s in body["students"]]
    assert nombres.index(nombre_aaa) < nombres.index(nombre_zzz), (
        "el orden debe ser alfabético (§2.2), no por logro"
    )

    metodo = body["method"]
    assert metodo == {
        "window_days": 28, "first_attempt_only": True, "min_items": 8, "min_challenges": 3,
        "thresholds": {"logrado": 80, "en_desarrollo": 60}, "excluded_types": ["open"],
        "axis_mapping": "fijo por la skill del reto",
        "cefr_filter": "no_aplicado: no existe nivel MCER asignado por estudiante",
        "status_scope": "desempeño en los retos asignados al grupo; no es nivel MCER del estudiante",
    }

    aaa = next(s for s in body["students"] if s["full_name"] == nombre_aaa)
    zzz = next(s for s in body["students"] if s["full_name"] == nombre_zzz)
    eje_aaa = next(a for a in aaa["axes"] if a["axis"] == "Accuracy")
    eje_zzz = next(a for a in zzz["axes"] if a["axis"] == "Accuracy")
    # X6: el reto de GC (2 ítems más de AAA) NO debe colarse en Accuracy.
    assert eje_aaa["items"] == 10, f"el reto de OTRO grupo se coló: {eje_aaa['items']} ítems"
    assert eje_aaa["correct"] == 0  # 9 + el 1er fallo del reto con reintento
    assert eje_aaa["status"] == "a_reforzar"
    assert eje_zzz["items"] == 9 and eje_zzz["correct"] == 9
    assert eje_zzz["status"] == "logrado"

    # Ausencia de monedas y de "weak"/"débil"/"debil" en TODO el cuerpo.
    crudo = r.text.lower()
    for prohibido in ("coins", "moneda", "weak", "débil", "debil"):
        assert prohibido not in crudo, f"{prohibido!r} sale en la respuesta de T5"


def test_t5_e_403(integ) -> None:
    esc = armar(integ)
    r = client.get(f"/teachers/groups/{esc.grupo_a}/achievement", headers=esc.h(integ, esc.e))
    assert r.status_code == 403, r.text


def test_t5_do_404(integ) -> None:
    esc = armar(integ)
    r = client.get(f"/teachers/groups/{esc.grupo_a}/achievement", headers=esc.h(integ, esc.do))
    assert r.status_code == 404, r.text


def test_t5_dt_404(integ) -> None:
    esc = armar(integ)
    r = client.get(f"/teachers/groups/{esc.grupo_a}/achievement", headers=esc.h(integ, esc.dt))
    assert r.status_code == 404, r.text


def test_t5_dm_404(integ) -> None:
    esc = armar(integ)
    r = client.get(f"/teachers/groups/{esc.grupo_a}/achievement",
                    headers=esc.h(integ, esc.dm, tenant=esc.tenant_b))
    assert r.status_code == 404, r.text


def test_t5_ab_404(integ) -> None:
    esc = armar(integ)
    r = client.get(f"/teachers/groups/{esc.grupo_a}/achievement", headers=esc.h(integ, esc.ab))
    assert r.status_code == 404, r.text


def test_t5_aa_404(integ) -> None:
    """`only_assigned=True`: AA (admin del MISMO colegio, sin `teacher_groups`) -> 404."""
    esc = armar(integ)
    r = client.get(f"/teachers/groups/{esc.grupo_a}/achievement", headers=esc.h(integ, esc.aa))
    assert r.status_code == 404, r.text
