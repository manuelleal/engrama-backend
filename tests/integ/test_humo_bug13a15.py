"""H1 — Humo de BUG-13, 14 y 15 de punta a punta — `docs/ESPEC_bug13a15.md` §5.

Datos sintéticos con semilla fija (`random.Random(13)`), que elige, en este
orden: las 3 respuestas correctas (de "ABCD"), el orden en que actúan los
estudiantes (un `shuffle` por grupo, G1 y después G2) y cuál estudiante de G1
hace el doble envío.

Siembra con las fábricas: tenant con pool 100000, grupos `H13-G1` y `H13-G2`,
docente D y 4 estudiantes por grupo. Todo lo demás, por la API:
  1. D crea R1 (de G1) y R2 (de G2) con `POST /challenges/` (20 monedas,
     15 XP, `max_attempts` 3 y `max_winners` 30).
  2. Cada estudiante de G2 hace `GET R1` y `POST R1/attempt`; cada uno de G1,
     `GET R1`.
  3. Cada estudiante de G1 arranca R1, lo gana, lo arranca otra vez y lo gana
     otra vez. El elegido envía DOS veces su segundo intento, en secuencia.
  4. D abre una sesión de `H13-G1`; marcan los 4 de G2 y después los 4 de G1.

Escribe `tests/_salida/humo_bug13a15.json` (en `.gitignore`) ANTES de afirmar,
y afirma que su contenido, leído del disco, es exactamente el esperado.
"""
from __future__ import annotations

import json
import random
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.integ_db import RAIZ_BACKEND
from tests.seguridad.veredictos import PruebaRota

pytestmark = pytest.mark.integ
client = TestClient(app)

RUTA_HUMO_BUG13A15 = RAIZ_BACKEND / "tests" / "_salida" / "humo_bug13a15.json"
SEMILLA = 13

# Contenido exacto (ESPEC §5). Si difiere se reporta; no se ajusta para que pase.
HUMO_ESPERADO: dict[str, Any] = {
    "alembic_version": "033_una_paga_por_reto", "semilla": 13, "estudiantes": [4, 4],
    "reto_propio": [200, 200, 200, 200], "reto_otro_grupo": [404, 404, 404, 404],
    "intento_otro_grupo": [404, 404, 404, 404], "intentos_otro_grupo_en_base": 0,
    "primera_victoria": [20, 20, 20, 20], "segunda_victoria": [0, 0, 0, 0],
    "doble_envio": [200, 409], "paga_una_vez": 1, "filas_reto": 4,
    "checkin_propio": [200, 200, 200, 200], "checkin_otro_grupo": [404, 404, 404, 404],
    "asistencias": 4, "monedas_otro_grupo": 0,
}


def _exigir(r: httpx.Response, status: int, que: str) -> httpx.Response:
    """Arnés: un paso de preparación que no da lo esperado es `PruebaRota`."""
    if r.status_code != status:
        raise PruebaRota(f"{que}: se esperaba {status} y llegó {r.status_code}: {r.text}")
    return r


def _crear_reto(integ: Any, docente: UUID, grupo: UUID, correctas: list[str]) -> str:
    cuerpo = {
        "title": f"H13 reto {grupo.hex[:6]}", "description": "sintético H13",
        "coins_reward": 20, "xp_reward": 15, "max_attempts": 3, "max_winners": 30,
        "group_id": str(grupo),
        "questions": [{"question_text": f"Pregunta {i}", "correct_answer": c,
                       "options_json": [{"label": x, "value": f"opcion {x}"} for x in "ABCD"],
                       "order_index": i} for i, c in enumerate(correctas, start=1)],
    }
    r = client.post("/challenges/", json=cuerpo, headers=integ.headers(docente))
    return str(_exigir(r, 201, "D crea un reto").json()["id"])


def _ganar(integ: Any, alumno: UUID, reto: str, correctas: list[str], *,
           veces: int = 1) -> list[httpx.Response]:
    """Arranca `reto` (201) y envía sus respuestas correctas `veces` veces."""
    h = integ.headers(alumno)
    inicio = _exigir(client.post(f"/challenges/{reto}/attempt", headers=h), 201, "arrancar")
    preguntas = [q["id"] for q in inicio.json()["challenge"]["questions"]]
    cuerpo = {"answers": [{"question_id": q, "answer": c}
                          for q, c in zip(preguntas, correctas, strict=True)]}
    intento = inicio.json()["attempt_id"]
    return [client.post(f"/challenges/attempts/{intento}/submit", json=cuerpo, headers=h)
            for _ in range(veces)]


def _marcar(integ: Any, alumno: UUID, codigo: str) -> int:
    return client.post("/core/attendance/check-in", json={"session_code": codigo},
                       headers=integ.headers(alumno)).status_code


def test_h1_humo_bug13a15(integ) -> None:
    rng = random.Random(SEMILLA)
    correctas = [rng.choice("ABCD") for _ in range(3)]

    tenant = integ.crear_tenant(pool=100000)
    g1, g2 = integ.crear_grupo(tenant, "H13-G1"), integ.crear_grupo(tenant, "H13-G2")
    docente = integ.crear_perfil(tenant, rol="teacher")
    de_g1 = [integ.crear_perfil(tenant, group_code="H13-G1") for _ in range(4)]
    de_g2 = [integ.crear_perfil(tenant, group_code="H13-G2") for _ in range(4)]
    rng.shuffle(de_g1)
    rng.shuffle(de_g2)
    elegido = rng.choice(de_g1)

    # 1. D crea R1 (G1) y R2 (G2).
    r1 = _crear_reto(integ, docente, g1, correctas)
    _crear_reto(integ, docente, g2, correctas)

    # 2. Visibilidad del reto.
    reto_otro = [client.get(f"/challenges/{r1}", headers=integ.headers(e)).status_code
                 for e in de_g2]
    intento_otro = [client.post(f"/challenges/{r1}/attempt",
                                headers=integ.headers(e)).status_code for e in de_g2]
    reto_propio = [client.get(f"/challenges/{r1}", headers=integ.headers(e)).status_code
                   for e in de_g1]

    # 3. Dos victorias por estudiante de G1; el elegido envía dos veces la segunda.
    primera, segunda, doble = [], [], []
    for e in de_g1:
        primera.append(_ganar(integ, e, r1, correctas)[0].json()["coins_earned"])
        envios = _ganar(integ, e, r1, correctas, veces=2 if e == elegido else 1)
        segunda.append(envios[0].json()["coins_earned"])
        if e == elegido:
            doble = [r.status_code for r in envios]

    # 4. Asistencia: sesión de G1; marcan G2 y después G1.
    sesion = client.post("/core/attendance/sessions", json={"group_code": "H13-G1"},
                         headers=integ.headers(docente))
    codigo = _exigir(sesion, 201, "D abre la sesión de H13-G1").json()["session_code"]
    checkin_otro = [_marcar(integ, e, codigo) for e in de_g2]
    checkin_propio = [_marcar(integ, e, codigo) for e in de_g1]

    datos = {
        "alembic_version": integ.valor("select version_num from alembic_version"),
        "semilla": SEMILLA,
        "estudiantes": [len(de_g1), len(de_g2)],
        "reto_propio": reto_propio,
        "reto_otro_grupo": reto_otro,
        "intento_otro_grupo": intento_otro,
        "intentos_otro_grupo_en_base": integ.valor(
            "select count(*) from challenge_attempts a join memberships m "
            "on m.profile_id = a.student_id and m.tenant_id = a.tenant_id "
            "where m.group_code = 'H13-G2'"),
        "primera_victoria": primera,
        "segunda_victoria": segunda,
        "doble_envio": doble,
        "paga_una_vez": integ.valor(
            "select coalesce(max(n), 0) from (select count(*) n from coin_ledger l "
            "join coin_wallets w on w.id = l.to_wallet_id where l.action = 'challenge' "
            "group by l.metadata->>'challenge_id', w.owner_id) s"),
        "filas_reto": integ.valor("select count(*) from coin_ledger where action = 'challenge'"),
        "checkin_propio": checkin_propio,
        "checkin_otro_grupo": checkin_otro,
        "asistencias": integ.valor("select count(*) from attendance"),
        "monedas_otro_grupo": sum(integ.saldo("profile", e) or 0 for e in de_g2),
    }
    # Primero se escribe (para poder reportarlo), después se afirma.
    RUTA_HUMO_BUG13A15.parent.mkdir(parents=True, exist_ok=True)
    RUTA_HUMO_BUG13A15.write_text(
        json.dumps(datos, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    en_disco = json.loads(RUTA_HUMO_BUG13A15.read_text(encoding="utf-8"))
    assert en_disco == HUMO_ESPERADO, f"humo BUG-13a15: {en_disco} != {HUMO_ESPERADO}"
