"""Arnés del humo HE0 y de la réplica RE0 — `docs/ESPEC_economia_oleada0.md` §3.4 y §3.5.

No empieza por `test_`: pytest no lo recolecta. Aquí vive "hacer de aula": el
profe abre la sesión, los estudiantes marcan, se crean y se responden retos, y
al final se lee el libro. Todo por las rutas HTTP reales, con el reloj de la
asistencia fijado por la costura `attendance._ahora`.

Las claves de las respuestas se leen con `.get()` y los estados se CUENTAN (no
se exigen): si una regla está rota, el humo debe terminar y mostrar números
distintos, no morir a mitad con una excepción.

Lo que NO se cuenta como un número más es un 500: el cliente deja pasar las
excepciones del servidor. Si la máquina se queda sin sockets a mitad del humo
(`OSError WinError 10055`), eso se ve como lo que es, una excepción del arnés, y
no como "una paga menos".
"""
from __future__ import annotations

import random
from collections import Counter
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.engrama_core.service import attendance as attendance_mod
from src.main import app

client = TestClient(app)
BOGOTA = timezone(timedelta(hours=-5))
MUY_ACTIVO, TIPICO, SOLO_ASISTE = "muy_activo", "tipico", "solo_asiste"
PERFILES = (MUY_ACTIVO, TIPICO, SOLO_ASISTE)


def a_las(dia: date, hora: int, minuto: int = 0) -> datetime:
    """Ese día a esa hora DE BOGOTÁ, como instante UTC (las 19:30 ya son otro día en UTC)."""
    return datetime(dia.year, dia.month, dia.day, hora, minuto, tzinfo=BOGOTA).astimezone(UTC)


def cabeceras(integ: Any, perfil: UUID, tenant: UUID | None = None) -> dict[str, str]:
    h: dict[str, str] = integ.headers(perfil)
    return h if tenant is None else {**h, "X-Tenant-ID": str(tenant)}


def repartir(rng: random.Random, alumnos: list[UUID], cuantos: tuple[int, int, int],
             ) -> dict[UUID, str]:
    """La semilla decide quién es de cada perfil (muy activo, típico, solo asiste)."""
    barajados = rng.sample(alumnos, len(alumnos))
    cortes = (cuantos[0], cuantos[0] + cuantos[1])
    return {a: MUY_ACTIVO if i < cortes[0] else TIPICO if i < cortes[1] else SOLO_ASISTE
            for i, a in enumerate(barajados)}


# =============================================================================
# La asistencia
# =============================================================================
def abrir_sesion(integ: Any, mp: pytest.MonkeyPatch, docente: UUID, inicio: datetime, *,
                 minutos: int, tenant: UUID | None = None) -> str | None:
    """El profe abre la sesión de G1 a las `inicio` (por la ruta). Devuelve el código."""
    mp.setattr(attendance_mod, "_ahora", lambda: inicio)
    r = client.post("/core/attendance/sessions", headers=cabeceras(integ, docente, tenant),
                    json={"group_code": "G1", "duration_minutes": minutos})
    codigo = r.json().get("session_code") if r.status_code == 201 else None
    return str(codigo) if codigo else None


def llegar(integ: Any, mp: pytest.MonkeyPatch, alumno: UUID, codigo: str | None,
           instante: datetime, tenant: UUID | None = None) -> int:
    """El estudiante marca a las `instante`. Devuelve el estado HTTP."""
    mp.setattr(attendance_mod, "_ahora", lambda: instante)
    return client.post("/core/attendance/check-in", json={"session_code": codigo or "sin-sesion"},
                       headers=cabeceras(integ, alumno, tenant)).status_code


def pasar_lista(integ: Any, mp: pytest.MonkeyPatch, rng: random.Random, docente: UUID,
                inicio: datetime, puntuales: dict[UUID, bool], *, limite_s: int,
                minutos: int = 30) -> Counter[int]:
    """Una sesión entera: cada estudiante llega dentro de su franja (el segundo lo da la semilla)."""
    codigo = abrir_sesion(integ, mp, docente, inicio, minutos=minutos)
    estados: Counter[int] = Counter()
    for alumno in rng.sample(list(puntuales), len(puntuales)):
        tarde_hasta = minutos * 60 - 60
        segundos = rng.randint(0, limite_s) if puntuales[alumno] \
            else rng.randint(limite_s + 1, tarde_hasta)
        estados[llegar(integ, mp, alumno, codigo, inicio + timedelta(seconds=segundos))] += 1
    return estados


# =============================================================================
# Los retos
# =============================================================================
class Reto:
    def __init__(self, id_: UUID, preguntas: list[UUID], correctas: list[str],
                 cupo: Any = None) -> None:
        self.id, self.preguntas, self.correctas, self.cupo = id_, preguntas, correctas, cupo


def crear_reto(integ: Any, rng: random.Random, docente: UUID, grupo: UUID, titulo: str, *,
               preguntas: int, **extra: Any) -> tuple[int, Reto | None]:
    """`POST /challenges/` SIN `coins_reward` ni `max_winners` (salvo que `extra` los ponga)."""
    correctas = [rng.choice("AB") for _ in range(preguntas)]
    cuerpo = {"title": titulo, "description": "sintético", "skill": "grammar",
              "group_id": str(grupo),
              "questions": [{"question_text": f"Pregunta {i}", "correct_answer": c,
                             "order_index": i,
                             "options_json": [{"label": "A", "value": "uno"},
                                              {"label": "B", "value": "dos"}]}
                            for i, c in enumerate(correctas, start=1)], **extra}
    r = client.post("/challenges/", headers=integ.headers(docente), json=cuerpo)
    if r.status_code != 201:
        return r.status_code, None
    datos = r.json()
    orden = sorted(datos.get("questions", []), key=lambda q: q.get("order_index", 0))
    return 201, Reto(UUID(datos["id"]), [UUID(q["id"]) for q in orden], correctas,
                     datos.get("max_winners"))


def intentar(integ: Any, alumno: UUID, reto: Reto, *, falla: int | None = None,
             tenant: UUID | None = None) -> dict[str, Any]:
    """Abre el reto y lo envía; con `falla`, esa pregunta va mal. Devuelve lo que respondió."""
    h = cabeceras(integ, alumno, tenant)
    inicio = client.post(f"/challenges/{reto.id}/attempt", headers=h)
    if inicio.status_code != 201:
        return {"estado": inicio.status_code}
    respuestas = [{"question_id": str(q), "answer": ("B" if c == "A" else "A") if i == falla else c}
                  for i, (q, c) in enumerate(zip(reto.preguntas, reto.correctas, strict=True))]
    r = client.post(f"/challenges/attempts/{inicio.json().get('attempt_id')}/submit", headers=h,
                    json={"answers": respuestas})
    datos = r.json() if r.status_code == 200 else {}
    return {"estado": r.status_code, "acierto": bool(datos.get("is_correct")),
            "monedas": int(datos.get("coins_earned") or 0)}


def sin_paga(resultados: list[dict[str, Any]]) -> int:
    """Aciertos que no cobraron (antes pasaba del 11.º en adelante: la carrera por el cupo)."""
    return sum(1 for r in resultados if r.get("acierto") and not r.get("monedas"))


# =============================================================================
# Leer el libro
# =============================================================================
def filas(integ: Any, sql: str, **params: Any) -> list[tuple[Any, ...]]:
    async def _q() -> list[tuple[Any, ...]]:
        async with integ.Session() as db:
            return [tuple(f) for f in (await db.execute(text(sql), params)).all()]
    return integ.run(_q())  # type: ignore[no-any-return]


def cobrado(integ: Any, tenant: UUID) -> dict[UUID, Counter[str]]:
    """Por estudiante, lo que el LIBRO de esa institución le pagó, por acción."""
    datos: dict[UUID, Counter[str]] = {}
    for perfil, accion, monedas in filas(
            integ, "select w.owner_id, l.action, sum(l.amount) from coin_ledger l "
                   "join coin_wallets w on w.id = l.to_wallet_id "
                   "where l.tenant_id = :t and w.owner_type = 'profile' group by 1, 2", t=tenant):
        datos.setdefault(UUID(str(perfil)), Counter())[str(accion)] = int(monedas)
    return datos


def comun(valores: list[int]) -> Any:
    """El valor si todos cobraron lo mismo; si no, la lista de los distintos (se verá en el JSON)."""
    distintos = sorted(set(valores))
    return distintos[0] if len(distintos) == 1 else distintos


def por_perfil(perfil_de: dict[UUID, str], pagado: dict[UUID, Counter[str]],
               acciones: dict[str, str]) -> dict[str, dict[str, Any]]:
    """{perfil: {n, <rubro>..., total}}; `acciones` = {rubro del informe: action del libro}."""
    informe: dict[str, dict[str, Any]] = {}
    for perfil in PERFILES:
        suyos = [pagado.get(a, Counter()) for a, p in perfil_de.items() if p == perfil]
        fila: dict[str, Any] = {"n": len(suyos)}
        for rubro, accion in acciones.items():
            fila[rubro] = comun([c[accion] for c in suyos])
        fila["total"] = comun([sum(c[a] for a in acciones.values()) for c in suyos])
        informe[perfil] = fila
    return informe


def emision(integ: Any, tenant: UUID) -> Counter[str]:
    """Lo que salió de la bolsa de esa institución, por acción (las recargas no son emisión a personas)."""
    return Counter({str(a): int(m) for a, m in filas(
        integ, "select action, sum(amount) from coin_ledger where tenant_id = :t "
               "and from_wallet_id is not null group by 1", t=tenant)})


def asistencia_en_numeros(integ: Any, tenant: UUID) -> dict[str, int]:
    def uno(sql: str) -> int:
        return int(integ.valor(sql, t=tenant) or 0)
    return {
        "asistencias_registradas": uno("select count(*) from attendance where tenant_id = :t"),
        "pagos_de_asistencia": uno("select count(*) from coin_ledger where tenant_id = :t "
                                   "and action = 'attendance'"),
        "asistencias_sin_paga": uno("select count(*) from attendance where tenant_id = :t "
                                    "and coins_awarded = 0"),
        "max_pagos_de_asistencia_por_estudiante_y_dia": uno(
            "select max(n) from (select count(*) as n from coin_ledger where tenant_id = :t "
            "and action = 'attendance' group by to_wallet_id, metadata->>'dia') x"),
        "mayor_pago_de_asistencia": uno("select max(amount) from coin_ledger where "
                                        "tenant_id = :t and action = 'attendance'"),
        "pagos_de_reto": uno("select count(*) from coin_ledger where tenant_id = :t "
                             "and action = 'challenge'"),
        "mayor_pago_de_reto": uno("select max(amount) from coin_ledger where tenant_id = :t "
                                  "and action = 'challenge'"),
    }


def rachas(integ: Any, alumnos: list[UUID]) -> Counter[int]:
    return Counter(int(r) for (r,) in filas(
        integ, "select current_streak from profiles where id = any(:ids)", ids=alumnos))
