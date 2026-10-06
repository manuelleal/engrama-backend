"""Lectura PURA del mapa generado (`curriculo/nodos.json`) — ESPEC_catalogo_nodos §1.2.

No toca la base. El id de un nodo es texto opaco: aquí solo se exige que sea
un texto de 1 a 128 caracteres sin espacios; no se mira su forma.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MAX_ID = 128
CAMPOS = ("tipo", "nivel", "nombre_es")


class MapaInvalido(Exception):
    """El archivo (o la carga) no cumple. `motivo` es un código; `ids`, a quién toca."""

    def __init__(self, motivo: str, ids: list[str] | None = None) -> None:
        super().__init__(motivo)
        self.motivo = motivo
        self.ids = ids or []


@dataclass(frozen=True)
class Nodo:
    id: str
    tipo: str
    nivel: str
    nombre_es: str


@dataclass(frozen=True)
class Mapa:
    """`reemplazos` ya viene resuelto: cada id apunta a un nodo VIGENTE."""

    version: str
    nodos: tuple[Nodo, ...]
    reemplazos: dict[str, str]


def id_valido(valor: Any) -> bool:
    return (isinstance(valor, str) and 1 <= len(valor) <= MAX_ID
            and not any(c.isspace() for c in valor))


def _id_de(crudo: Any, campo: str = "id") -> str:
    """El id (texto válido) de ese campo, o `id_invalido`."""
    valor = crudo.get(campo) if isinstance(crudo, dict) else None
    if not id_valido(valor):
        raise MapaInvalido("id_invalido", [str(valor)])
    return str(valor)


def exigir_id_nuevo(ident: str, vistos: set[str]) -> None:
    """Un id no puede venir dos veces en `nodos[]`."""
    if ident in vistos:
        raise MapaInvalido("id_repetido", [ident])
    vistos.add(ident)


def _leer_nodos(crudos: Any) -> tuple[Nodo, ...]:
    if not isinstance(crudos, list) or not crudos:
        raise MapaInvalido("sin_nodos")
    nodos: list[Nodo] = []
    vistos: set[str] = set()
    for crudo in crudos:
        ident = _id_de(crudo)
        exigir_id_nuevo(ident, vistos)
        if any(not isinstance(crudo.get(c), str) or not crudo[c].strip() for c in CAMPOS):
            raise MapaInvalido("campo_faltante", [ident])
        nodos.append(Nodo(ident, crudo["tipo"], crudo["nivel"], crudo["nombre_es"]))
    return tuple(nodos)


def _destino_final(origen: str, directos: dict[str, str], vigentes: set[str]) -> str:
    """Sigue la cadena A -> B -> C hasta un vigente; un ciclo o un hueco no valen."""
    actual, pasos = origen, 0
    while actual in directos:
        actual, pasos = directos[actual], pasos + 1
        if pasos > len(directos):
            raise MapaInvalido("reemplazo_invalido", [origen])
    if actual not in vigentes:
        raise MapaInvalido("reemplazo_invalido", [origen])
    return actual


def _leer_reemplazos(crudos: Any, vigentes: set[str]) -> dict[str, str]:
    if crudos is None:
        return {}
    if not isinstance(crudos, list):
        raise MapaInvalido("reemplazo_invalido")
    directos: dict[str, str] = {}
    for crudo in crudos:
        origen, destino = _id_de(crudo), _id_de(crudo, "reemplazado_por")
        if origen in vigentes or origen in directos:
            raise MapaInvalido("reemplazo_invalido", [origen])
        directos[origen] = destino
    return {o: _destino_final(o, directos, vigentes) for o in directos}


def leer_mapa(datos: Any) -> Mapa:
    """El mapa validado, o `MapaInvalido` con su motivo. No escribe nada."""
    if not isinstance(datos, dict):
        raise MapaInvalido("sin_nodos")
    version = datos.get("version")
    if not isinstance(version, str) or not version.strip():
        raise MapaInvalido("sin_version")
    nodos = _leer_nodos(datos.get("nodos"))
    reemplazos = _leer_reemplazos(datos.get("reemplazos"), {n.id for n in nodos})
    return Mapa(version=version, nodos=nodos, reemplazos=reemplazos)
