"""`max_winners` por defecto = tamaño del grupo, con piso — `docs/ESPEC_economia_oleada0.md` §1.5.

  EG1  C14  sin `max_winners`: grupo de 12 activos (más 1 inactivo y el docente) -> 12 con
            piso 1 y 40 con piso 40; reto global -> los activos de la institución;
            `max_winners: 3` explícito -> 3
  EG2  C15  se acabó la carrera: 13 estudiantes de un grupo de 13 ganan el mismo reto
            creado sin `max_winners` -> los 13 cobran

Los tramposos (ZT13) están en `tests/tramposos/test_tramposos_economia.py`.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.main import app
from src.shared.config import settings
from tests.challenge_engine import test_bug13_una_paga as b13

pytestmark = pytest.mark.integ
client = TestClient(app)

POOL = 10_000


def _cuerpo(group_id: UUID | None, **extra: Any) -> dict[str, Any]:
    """Un reto de dos preguntas ("A" y "B") SIN `max_winners` (salvo que `extra` lo ponga)."""
    return {"title": "Reto sintético", "description": "sintético", "skill": "grammar",
            "group_id": str(group_id) if group_id else None, "max_attempts": 2,
            "questions": [{"question_text": f"Pregunta {i}", "correct_answer": resp,
                           "order_index": i,
                           "options_json": [{"label": "A", "value": "uno"},
                                            {"label": "B", "value": "dos"}]}
                          for i, resp in enumerate(("A", "B"), start=1)],
            **extra}


def _crear(integ: Any, docente: UUID, cuerpo: dict[str, Any]) -> dict[str, Any]:
    r = client.post("/challenges/", headers=integ.headers(docente), json=cuerpo)
    assert r.status_code == 201, f"crear el reto respondió {r.status_code} {r.text}"
    return r.json()  # type: ignore[no-any-return]


def _desactivar(integ: Any, perfil: UUID) -> None:
    async def _q() -> None:
        async with integ.engine.begin() as conn:
            await conn.execute(text("update memberships set is_active = false "
                                    "where profile_id = :p"), {"p": perfil})
    integ.run(_q())


# =============================================================================
# EG1 — C14: el cupo por defecto
# =============================================================================
def test_eg1_el_cupo_por_defecto_es_el_tamano_del_grupo(integ, monkeypatch) -> None:
    tenant = integ.crear_tenant(pool=POOL)
    g1 = integ.crear_grupo(tenant, "G1")
    integ.crear_grupo(tenant, "G2")
    docente = integ.crear_perfil(tenant, rol="teacher", group_code="G1")
    for _ in range(12):
        integ.crear_perfil(tenant, group_code="G1")
    _desactivar(integ, integ.crear_perfil(tenant, group_code="G1"))  # el inactivo no cuenta
    for _ in range(5):
        integ.crear_perfil(tenant, group_code="G2")
    # Otro colegio con su propio G1: tampoco cuenta.
    otro = integ.crear_tenant(pool=POOL)
    integ.crear_grupo(otro, "G1")
    for _ in range(3):
        integ.crear_perfil(otro, group_code="G1")

    monkeypatch.setattr(settings, "reto_ganadores_piso", 1)
    de_grupo = _crear(integ, docente, _cuerpo(g1))["max_winners"]
    assert de_grupo == 12, f"EG1: grupo de 12 activos con piso 1: max_winners {de_grupo}, no 12"
    # Un reto global cuenta a los estudiantes activos de la institución (12 + 5).
    global_ = _crear(integ, docente, _cuerpo(None))["max_winners"]
    assert global_ == 17, f"EG1: reto global con piso 1: max_winners {global_}, no 17"

    monkeypatch.setattr(settings, "reto_ganadores_piso", 40)
    con_piso = _crear(integ, docente, _cuerpo(g1))["max_winners"]
    assert con_piso == 40, f"EG1: grupo de 12 con piso 40: max_winners {con_piso}, no 40"

    # Uno explícito se respeta tal cual (también por debajo del piso).
    explicito = _crear(integ, docente, _cuerpo(g1, max_winners=3))["max_winners"]
    assert explicito == 3, f"EG1: max_winners explícito 3 quedó en {explicito}"
    assert integ.valor("select max_winners from challenges where id = :c",
                       c=UUID(_crear(integ, docente, _cuerpo(g1))["id"])) == 40, \
        "EG1: la columna no guardó el cupo resuelto"


# =============================================================================
# EG2 — C15: se acabó la carrera
# =============================================================================
def test_eg2_los_13_de_un_grupo_de_13_cobran(integ) -> None:
    """Antes el cupo era 10: del 11.º en adelante acertaban y no cobraban."""
    tenant = integ.crear_tenant(pool=POOL)
    g1 = integ.crear_grupo(tenant, "G1")
    docente = integ.crear_perfil(tenant, rol="teacher", group_code="G1")
    alumnos = [integ.crear_perfil(tenant, group_code="G1", saldo=0) for _ in range(13)]
    reto = _crear(integ, docente, _cuerpo(g1))
    preguntas = [UUID(q["id"]) for q in reto["questions"]]

    ganadas = []
    for alumno in alumnos:
        inicio = client.post(f"/challenges/{reto['id']}/attempt", headers=integ.headers(alumno))
        b13._exigir(inicio, 201, "EG2, arrancar")
        r = b13._enviar(client, integ, alumno, UUID(inicio.json()["attempt_id"]), preguntas)
        b13._exigir(r, 200, "EG2, enviar")
        cuerpo = r.json()
        ganadas.append((cuerpo["is_correct"], cuerpo["coins_earned"]))

    aciertos = sum(1 for correcto, _ in ganadas if correcto)
    cobraron = sum(1 for correcto, monedas in ganadas if correcto and monedas > 0)
    sin_paga = aciertos - cobraron
    assert (aciertos, cobraron, sin_paga) == (13, 13, 0), \
        f"EG2: aciertos {aciertos}, cobraron {cobraron}, sin paga por cupo {sin_paga}"
    assert integ.valor("select count(*) from coin_ledger where action = 'challenge'") == 13, \
        "EG2: el libro no tiene 13 pagas de reto"
    assert integ.valor("select current_winners from challenges where id = :c",
                       c=UUID(reto["id"])) == 13, "EG2: current_winners no es 13"
