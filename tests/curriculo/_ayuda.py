"""Ayudas de los tests del catálogo de nodos (no empieza por `test_`: no se recolecta).

Los mapas son SINTÉTICOS: ids inventados con la forma del mapa real. Los usan
también los bloques que guardan nodos (Grader, foco y refuerzo).
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.curriculo import __main__ as orden_mod
from src.curriculo import service as service_mod
from src.curriculo.mapa import MapaInvalido
from src.main import app

client = TestClient(app, raise_server_exceptions=False)

VIGENTES_V1 = ("ds.b2.cinco", "fn.a2.tres", "gr.a1.dos", "gr.a1.uno", "lx.b1.cuatro",
               "pr.c1.seis")
# Una cadena: mas-viejo -> viejo -> uno. Los dos deben resolver a `gr.a1.uno`.
REEMPLAZOS_V1 = {"gr.a1.viejo": "gr.a1.uno", "gr.a1.mas-viejo": "gr.a1.viejo"}
TIPOS = {"gr": "gramatica", "fn": "funcion", "lx": "lexico", "ds": "discurso",
         "pr": "pronunciacion"}


def nodo(ident: str) -> dict[str, Any]:
    """Un nodo con la forma del mapa real, más un campo pedagógico que el backend ignora."""
    prefijo, nivel = ident.split(".")[:2]
    return {"id": ident, "tipo": TIPOS.get(prefijo, "gramatica"), "nivel": nivel.upper(),
            "nombre_es": f"nombre de {ident}", "can_do": "se ignora"}


def mapa(version: str, vigentes: tuple[str, ...] | list[str],
         reemplazos: dict[str, str] | None = None) -> dict[str, Any]:
    return {"version": version, "generado": "sintético", "nodos": [nodo(i) for i in vigentes],
            "reemplazos": [{"id": v, "reemplazado_por": d, "motivo": "sintético"}
                           for v, d in (reemplazos or {}).items()]}


def mapa_v1() -> dict[str, Any]:
    return mapa("v1", VIGENTES_V1, REEMPLAZOS_V1)


def cargar(integ: Any, datos: Any) -> Any:
    """El resumen de la carga, o `("rechazada", motivo, ids)`. Lo mismo que hace la orden."""
    try:
        return integ.run(orden_mod.correr_carga(datos, integ.Session))
    except MapaInvalido as exc:
        return ("rechazada", exc.motivo, exc.ids)


def tabla(integ: Any) -> dict[str, str | None]:
    """`{id: replaced_by}` de todo el catálogo."""
    from sqlalchemy import text

    async def _q() -> dict[str, str | None]:
        async with integ.Session() as db:
            filas = (await db.execute(text(
                "select id, replaced_by from curriculum_nodes order by id"))).all()
            return {f[0]: f[1] for f in filas}

    return integ.run(_q())


def resolver(integ: Any, ids: list[str]) -> Any:
    """Lo que devuelve `canonicos`, o `(422, detalle)`."""
    async def _q() -> Any:
        async with integ.Session() as db:
            try:
                return await service_mod.canonicos(db, ids)
            except HTTPException as exc:
                return (exc.status_code, exc.detail)

    return integ.run(_q())


def leer(integ: Any, quien: Any) -> tuple[int, Any, list[str]]:
    """`GET /teachers/curriculo/nodos`: (estado, versión, ids)."""
    r = client.get("/teachers/curriculo/nodos", headers=integ.headers(quien))
    if r.status_code != 200:
        return r.status_code, None, []
    cuerpo = r.json()
    return r.status_code, cuerpo["version"], [n["id"] for n in cuerpo["nodos"]]
