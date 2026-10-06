"""Ayudas de los tests de `POST /events/batch` — `docs/ESPEC_eventos_anillo.md` §3.

No empieza por `test_`: pytest no lo recolecta. Hace de satélite: arma lotes
como EVA (`live`) y como SET (`set`) y los firma. Los secretos son SINTÉTICOS
y solo viven en `settings` mientras dura cada test.

Reglas (las del login piloto): el cliente con `raise_server_exceptions=False`
(un 500 es una respuesta, y por tanto un `AssertionError`), las claves con
`.get()`, y lo observado en un dict que se compara ENTERO y va en el mensaje.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from fastapi.testclient import TestClient

from src.main import app
from src.shared.config import settings

client = TestClient(app, raise_server_exceptions=False)

RUTA = "/events/batch"
SECRETO_LIVE = "secreto-sintetico-de-eva-solo-para-pytest-0001"
SECRETO_SET = "secreto-sintetico-de-set-solo-para-pytest-0002"
SECRETOS = {"live": SECRETO_LIVE, "set": SECRETO_SET}
NO_AUTORIZADO = (401, {"detail": "invalid_signature"})
HACE_DOS_DIAS = datetime.now(UTC).replace(microsecond=0) - timedelta(days=2)

# Lo que EVA manda por tipo: (source, ¿lleva sujeto?, payload). Escrito a mano,
# sin leer el catálogo del backend: es el contrato visto desde el satélite.
DE_EVA: dict[str, tuple[str, str, dict[str, Any]]] = {
    "live.session.started": ("teacher", "profe", {"n_items": 4}),
    "item.exposed": ("live", "nadie", {"kind": "original"}),
    "answer.submitted": ("live", "estudiante", {
        "kind": "original", "attempt": 1, "choice": "B", "correct": True, "distractor": None,
        "late": False, "response_ms": 5400, "structure": "comparativos"}),
    "coins.granted": ("live", "estudiante", {"amount": 2, "reason": "correct"}),
    "live.session.closed": ("teacher", "profe", {
        "goal_met": True, "fire_points": 3, "fire_attempts": 4}),
}


def preparar() -> None:
    settings.events_secret_live = SECRETO_LIVE
    settings.events_secret_set = SECRETO_SET


def soltar() -> None:
    settings.events_secret_live = ""
    settings.events_secret_set = ""


def serializar(objeto: Any) -> bytes:
    return json.dumps(objeto, ensure_ascii=False, separators=(",", ":")).encode()


def firma(secreto: str, timestamp: str, cuerpo: bytes) -> str:
    """La firma calculada AQUÍ, sin usar el código del backend."""
    mensaje = timestamp.encode() + b"." + cuerpo
    return "sha256=" + hmac.new(secreto.encode(), mensaje, hashlib.sha256).hexdigest()


def cabeceras(origen: str, cuerpo: bytes, *, secreto: str | None = None,
              hace_s: int = 0) -> dict[str, str]:
    ts = str(int(time.time()) - hace_s)
    return {"Content-Type": "application/json", "X-Engrama-Source": origen,
            "X-Engrama-Timestamp": ts,
            "X-Engrama-Signature": firma(secreto or SECRETOS.get(origen, "x" * 40), ts, cuerpo)}


def enviar_bytes(cuerpo: bytes, headers: dict[str, str]) -> httpx.Response:
    return client.post(RUTA, content=cuerpo, headers=headers)


def enviar(origen: str, lote_: dict[str, Any], cliente: TestClient | None = None,
           ) -> httpx.Response:
    cuerpo = serializar(lote_)
    return (cliente or client).post(RUTA, content=cuerpo, headers=cabeceras(origen, cuerpo))


def lote(eventos: list[Any], *, batch_id: str = "lote-sintetico-1", sesion: str | None = "aula-1",
         instance: str = "eva-aula", **extra: Any) -> dict[str, Any]:
    raiz: dict[str, Any] = {"schema_version": 1, "batch_id": batch_id, "instance": instance,
                            "events": eventos}
    if sesion is not None:
        raiz["session_id"] = sesion
    raiz.update(extra)
    return raiz


def evento(tipo: str, tenant: UUID, sujeto: UUID | None, *, source: str, payload: dict[str, Any],
           event_id: str | None = None, cuando: datetime | None = None,
           **extra: Any) -> dict[str, Any]:
    datos: dict[str, Any] = {
        "event_id": event_id or f"{payload.get('session_id', 'sin-sesion')}:{tipo}:{sujeto}",
        "tenant_id": str(tenant), "subject_id": None if sujeto is None else str(sujeto),
        "source": source, "type": tipo, "item_ref": None, "payload": payload,
        "occurred_at": (cuando or HACE_DOS_DIAS).isoformat(), "schema_version": 1,
    }
    datos.update(extra)
    return datos


@dataclass(frozen=True)
class Clase:
    """Una institución con su bolsa, un profe y estudiantes en un grupo."""

    tenant: UUID
    profe: UUID
    estudiantes: list[UUID]

    def de_eva(self, tipo: str, *, sesion: str = "aula-1", n: int = 0, sufijo: str = "",
               **payload: Any) -> dict[str, Any]:
        """Un evento de EVA de ese tipo, para el estudiante `n` (o el profe, o nadie)."""
        source, quien, base = DE_EVA[tipo]
        sujeto: UUID | None = None
        if quien == "profe":
            sujeto = self.profe
        elif quien == "estudiante":
            sujeto = self.estudiantes[n]
        cuerpo = {"session_id": sesion, **base, **payload}
        return evento(tipo, self.tenant, sujeto, source=source, payload=cuerpo,
                      event_id=f"{sesion}:{tipo}:{n}{sufijo}")

    def monedas(self, amount: int, *, n: int = 0, sesion: str = "aula-1",
                sufijo: str = "") -> dict[str, Any]:
        return self.de_eva("coins.granted", sesion=sesion, n=n, sufijo=sufijo, amount=amount)

    def cinco(self, *, amount: int = 2) -> list[dict[str, Any]]:
        """Uno de cada tipo, como una clase mínima."""
        return [self.monedas(amount) if tipo == "coins.granted" else self.de_eva(tipo)
                for tipo in DE_EVA]


def clase(integ: Any, *, estudiantes: int = 1, pool: int = 1000) -> Clase:
    tenant = integ.crear_tenant(pool=pool)
    integ.crear_grupo(tenant, "G1")
    return Clase(tenant, integ.crear_perfil(tenant, rol="teacher"),
                 [integ.crear_perfil(tenant, group_code="G1") for _ in range(estudiantes)])


def de_set(tenant: UUID, sujeto: UUID, nivel: str = "B1", *, cuando: datetime | None = None,
           provisional: bool = True, intento: str = "1234", event_id: str | None = None,
           **payload: Any) -> dict[str, Any]:
    """Un `level.assessed` como lo manda SET."""
    cuerpo = {"estado": "confirmado_por_set", "nivel_global": nivel, "score_total": 52,
              "provisional": provisional, "cortes": "set-cefr-2026",
              "destrezas": {"reading": {"nivel": nivel, "score": 56}},
              "evidencia": {"intento_id": intento, "instrumento": "cefr_general"}, **payload}
    return evento("level.assessed", tenant, sujeto, source="set", payload=cuerpo, cuando=cuando,
                  event_id=event_id or f"set:{intento}:{nivel}:{sujeto}")


def lote_de_set(*eventos: dict[str, Any]) -> dict[str, Any]:
    return lote(list(eventos), batch_id="set-1", sesion=None, instance="set-local")


def cuerpo_json(r: httpx.Response) -> Any:
    try:
        return r.json()
    except ValueError:
        return None


def resumen(r: httpx.Response) -> tuple[Any, ...]:
    """(estado, accepted, duplicates, [(id, reason)] rechazados, [(id, reason)] sin acreditar)."""
    datos = cuerpo_json(r)
    if not isinstance(datos, dict) or "accepted" not in datos:
        return (r.status_code, datos)

    def pares(clave: str) -> list[tuple[Any, Any]]:
        return [(x.get("event_id"), x.get("reason")) for x in datos.get(clave, [])]

    return (r.status_code, datos.get("accepted"), datos.get("duplicates"), pares("rejected"),
            pares("not_credited"))


def cortos(r: httpx.Response) -> tuple[Any, ...]:
    """Como `resumen`, pero solo los motivos (sin los ids)."""
    visto = resumen(r)
    if len(visto) < 5:
        return visto
    return (*visto[:3], [m for _, m in visto[3]], [m for _, m in visto[4]])


def filas(integ: Any) -> int:
    return int(integ.valor("select count(*) from learning_events"))


def saldo(integ: Any, perfil: UUID) -> int:
    return integ.saldo("profile", perfil) or 0


def libro(integ: Any) -> list[tuple[str, str | None, int]]:
    """Las filas del libro: (action, llave, monto), en orden."""
    from sqlalchemy import text

    async def _q() -> list[tuple[str, str | None, int]]:
        async with integ.Session() as db:
            r = await db.execute(text("select action, idempotency_key, amount from coin_ledger "
                                      "order by created_at, idempotency_key"))
            return [(str(a), k, int(m)) for a, k, m in r.all()]

    return list(integ.run(_q()))


def nivel(integ: Any, perfil: UUID, ruta: str = "/auth/me", **extra: str) -> Any:
    """`confirmed_level` de `/auth/me`; `"(sin la clave)"` si el campo no viene."""
    h = {**integ.headers(perfil), **extra}
    r = client.get(ruta, headers=h) if ruta == "/auth/me" else client.post(ruta, headers=h)
    datos = cuerpo_json(r)
    if not isinstance(datos, dict):
        return (r.status_code, datos)
    return datos.get("confirmed_level", "(sin la clave)")


def nivel_corto(integ: Any, perfil: UUID, **extra: str) -> Any:
    """(cefr, source, provisional) o lo que haya venido."""
    visto = nivel(integ, perfil, **extra)
    if not isinstance(visto, dict):
        return visto
    return (visto.get("cefr"), visto.get("source"), visto.get("provisional"))


def efectos(integ: Any) -> list[tuple[str, int]]:
    """(effect, coins) de cada fila del expediente, en orden de llegada."""
    from sqlalchemy import text

    async def _q() -> list[tuple[str, int]]:
        async with integ.Session() as db:
            r = await db.execute(text("select effect, coins from learning_events order by id"))
            return [(str(e), int(c)) for e, c in r.all()]

    return list(integ.run(_q()))
