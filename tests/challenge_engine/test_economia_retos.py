"""El valor de un reto: tope de `coins_reward` — `docs/ESPEC_economia_oleada0.md` §1.4.

  UE6  C12  (no-integ) 21 se rechaza en `coins_reward`; 20 y 0 pasan; con el tope en
            30, 25 pasa; `recompensa_del_reto(50, 20) = 20`
  ET1  C13  `POST /challenges/` con 21 -> 422 y 0 filas; con 20 -> 201. Un reto YA
            guardado con 50: quien lo gana recibe 20 (respuesta, asiento y saldo) y
            el `GET` lo muestra con 20

Los tramposos ZE6, ZT11 y ZT12 están en `tests/tramposos/test_tramposos_economia*.py`.
Cada test llama a las reglas por el módulo (`economia.f`) para que se puedan reemplazar.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.challenge_engine.schemas import ChallengeCreate
from src.engrama_core.service import economia
from src.main import app
from src.shared.config import settings
from tests.challenge_engine import test_bug13_una_paga as b13

client = TestClient(app)


def _cuerpo(coins: int) -> dict[str, Any]:
    return {"title": "Reto sintético", "description": "sintético", "skill": "grammar",
            "coins_reward": coins,
            "questions": [{"question_text": "Pregunta 1", "correct_answer": "A",
                           "options_json": [{"label": "A", "value": "uno"},
                                            {"label": "B", "value": "dos"}]}]}


def _se_rechaza_en_coins_reward(coins: int) -> bool:
    """¿El esquema rechaza ese valor, y SOLO por el campo `coins_reward`?"""
    try:
        ChallengeCreate.model_validate(_cuerpo(coins))
    except ValidationError as exc:
        assert [e["loc"] for e in exc.errors()] == [("coins_reward",)], f"UE6: {exc.errors()}"
        return True
    return False


# =============================================================================
# UE6 — C12: el esquema y la función pura
# =============================================================================
def test_ue6_el_tope_se_valida_y_se_aplica() -> None:
    assert _se_rechaza_en_coins_reward(21), "UE6: 21 pasó la validación del tope"
    assert not _se_rechaza_en_coins_reward(20), "UE6: 20 (el tope) se rechazó"
    assert not _se_rechaza_en_coins_reward(0), "UE6: 0 se rechazó"
    assert not _se_rechaza_en_coins_reward(10), "UE6: 10 (el defecto) se rechazó"

    # El tope es configuración: con 30, el 25 pasa y el 31 no.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "reto_monedas_tope", 30)
        assert not _se_rechaza_en_coins_reward(25), "UE6: con tope 30, 25 se rechazó"
        assert _se_rechaza_en_coins_reward(31), "UE6: con tope 30, 31 pasó"

    pagos = {"50 con tope 20": economia.recompensa_del_reto(50, 20),
             "20 con tope 20": economia.recompensa_del_reto(20, 20),
             "10 con tope 20": economia.recompensa_del_reto(10, 20),
             "0 con tope 20": economia.recompensa_del_reto(0, 20)}
    assert pagos == {"50 con tope 20": 20, "20 con tope 20": 20, "10 con tope 20": 10,
                     "0 con tope 20": 0}, f"UE6: {pagos}"
    assert settings.reto_monedas_tope == 20, "UE6: el defecto del tope no es 20"


# =============================================================================
# ET1 — C13: por la API
# =============================================================================
def _ganar(integ: Any, alumno: UUID, reto: UUID, preguntas: list[UUID]) -> dict[str, Any]:
    """El estudiante abre el reto y acierta todo: devuelve el cuerpo de `/submit`."""
    inicio = client.post(f"/challenges/{reto}/attempt", headers=integ.headers(alumno))
    b13._exigir(inicio, 201, "ET1, arrancar")
    r = b13._enviar(client, integ, alumno, UUID(inicio.json()["attempt_id"]), preguntas)
    b13._exigir(r, 200, "ET1, enviar")
    return r.json()  # type: ignore[no-any-return]


@pytest.mark.integ
def test_et1_el_tope_al_crear_al_pagar_y_al_mostrar(integ) -> None:
    tenant = integ.crear_tenant(pool=1000)
    docente = integ.crear_perfil(tenant, rol="teacher")
    h = integ.headers(docente)

    # Al crear: 21 -> 422 con el campo, y no se crea nada; 20 -> 201.
    r21 = client.post("/challenges/", headers=h, json=_cuerpo(21))
    assert r21.status_code == 422, f"ET1: crear con 21 respondió {r21.status_code} {r21.text}"
    campos = [e["loc"][-1] for e in r21.json()["detail"]]
    assert campos == ["coins_reward"], f"ET1: el 422 señala {campos}"
    assert integ.valor("select count(*) from challenges") == 0, "ET1: el reto de 21 se creó"
    r20 = client.post("/challenges/", headers=h, json=_cuerpo(20))
    assert r20.status_code == 201, f"ET1: crear con 20 respondió {r20.status_code} {r20.text}"
    assert integ.valor("select count(*) from challenges") == 1, "ET1: no hay 1 reto tras el 20"

    # Al pagar y al mostrar: un reto YA guardado con 50 (sembrado antes del tope).
    alumno = integ.crear_perfil(tenant, saldo=0)
    viejo, preguntas = integ.crear_challenge(tenant, docente, coins=50)
    ganado = _ganar(integ, alumno, viejo, preguntas)
    assert ganado["coins_earned"] == 20, f"ET1: quien lo gana recibe {ganado['coins_earned']}, no 20"
    asiento = integ.valor("select amount from coin_ledger where action = 'challenge'")
    assert asiento == 20, f"ET1: el asiento es de {asiento}, no 20"
    assert integ.saldo("profile", alumno) == 20, "ET1: el saldo del estudiante no es 20"
    assert integ.saldo("tenant", tenant) == 980, "ET1: la bolsa no bajó 20"
    # Lo que se muestra es lo que se paga.
    visto = client.get(f"/challenges/{viejo}", headers=integ.headers(alumno))
    assert visto.status_code == 200, f"ET1: {visto.text}"
    assert visto.json()["coins_reward"] == 20, \
        f"ET1: el GET muestra {visto.json()['coins_reward']}, no 20"
    # La columna no se reescribe: el valor viejo sigue ahí.
    assert integ.valor("select coins_reward from challenges where id = :c", c=viejo) == 50, \
        "ET1: la columna se reescribió"
