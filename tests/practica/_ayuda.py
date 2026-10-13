"""Ayudas de los tests del nivel de práctica y la tanda (no se recolecta).

Los retos se siembran con `tests/racha/_ayuda.sembrar` (por `POST /challenges/`),
con `nivel`, `topic` y `skill`, como lo hace el sembrador real.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from src.shared.config import settings
from tests.racha import _ayuda as ra
from tests.seguridad.veredictos import sembrar as sql

client = ra.client


def sin_escalera(mp: pytest.MonkeyPatch) -> None:
    """La escalera no se mueve (umbrales inalcanzables): el test mide otra cosa."""
    for nombre, valor in (("practica_sube", 99), ("practica_baja", -1),
                          ("practica_sube_rapida", 99), ("practica_baja_rapida", -1)):
        mp.setattr(settings, nombre, valor)


def reto(integ: Any, profe: UUID, titulo: str, n: int, *, grupo: UUID | None,
         nivel: str | None = "A2", topic: str = "a2-u01",
         skill: str | None = "grammar", **campos: Any) -> tuple[str, list[str]]:
    return ra.sembrar(integ, profe, titulo, n, grupo=grupo, nivel=nivel, topic=topic,
                      skill=skill, **campos)


def tanda(integ: Any, quien: UUID, metodo: str = "POST", **headers: str) -> Any:
    """El cuerpo de `/challenges/tanda`, o `(estado, detalle)` si no es 200."""
    r = client.request(metodo, "/challenges/tanda", headers={**integ.headers(quien), **headers})
    if r.status_code != 200:
        try:
            return r.status_code, r.json().get("detail")
        except (ValueError, AttributeError):
            return r.status_code, None
    return r.json()


def corta(c: Any) -> Any:
    """(nivel de práctica, ¿con SET?, tanda corta, tandas hoy, ¿otra?, ¿listo?, ¿sin nuevo?).

    La tanda corta: (número, modo, nivel, [(título, estado, paga)], preguntas, repasos, ¿completa?).
    """
    if not isinstance(c, dict):
        return c
    t = c.get("tanda")
    if isinstance(t, dict):
        t = (t.get("numero"), t.get("modo"), t.get("nivel"),
             [(r["reto"]["title"], r["estado"], r["paga"]) for r in t.get("retos", [])],
             t.get("preguntas"), len(t.get("repaso", [])), t.get("completa"))
    p = c.get("practica", {})
    return (p.get("nivel"), p.get("con_nivel_de_set"), t, c.get("tandas_hoy"),
            c.get("puede_pedir_otra"), c.get("listo_por_hoy"), c.get("sin_contenido_nuevo"))


def nivel(integ: Any, quien: UUID, **headers: str) -> Any:
    """`(nivel de práctica, ¿con SET?)` como lo dice el `GET` (no escribe)."""
    c = tanda(integ, quien, "GET", **headers)
    if not isinstance(c, dict):
        return c
    return (c["practica"]["nivel"], c["practica"]["con_nivel_de_set"])


def confirmar_con_set(integ: Any, tenant: UUID, perfil: UUID, cefr: str) -> None:
    """Deja un nivel confirmado como lo dejaría SET (sembrado directo en la base)."""
    sql(integ, "insert into confirmed_levels (tenant_id, profile_id, cefr, source, provisional, "
               "assessed_at) values (:t, :p, :c, 'set', false, :f)",
        t=tenant, p=perfil, c=cefr, f=datetime(2026, 9, 1, tzinfo=UTC))


def niveles_confirmados(integ: Any) -> list[tuple[str, str]]:
    from sqlalchemy import text

    async def _q() -> list[tuple[str, str]]:
        async with integ.Session() as db:
            filas = (await db.execute(text(
                "select cefr, source from confirmed_levels order by id"))).all()
            return [(str(c), str(s)) for c, s in filas]

    return list(integ.run(_q()))


def tandas_en_la_base(integ: Any, quien: UUID | None = None) -> int:
    if quien is None:
        return int(integ.valor("select count(*) from practice_tandas"))
    return int(integ.valor("select count(*) from practice_tandas where profile_id = :p", p=quien))
