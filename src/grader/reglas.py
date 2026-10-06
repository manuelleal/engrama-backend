"""Reglas PURAS de una hoja calificada — ESPEC_grader_anillo §1.3 y §9.3.

No toca la base: recibe la hoja, los ítems del examen y la lista de números.
El backend NO confía en el cliente: recalcula los aciertos y no acepta `dudosa`.
"""
from __future__ import annotations

from collections.abc import Collection, Sequence
from uuid import UUID

from src.grader.schemas import HojaIn, ItemHojaIn

# Nunca `dudosa`: el Grader no envía una hoja con dudosas sin resolver.
ESTADOS = ("marcada", "vacia", "doble")

EVENT_ID_INVALIDO = "event_id_invalido"
ESTADO_INVALIDO = "estado_invalido"
ITEMS_NO_COINCIDEN = "items_no_coinciden"
TOTAL_NO_COINCIDE = "total_no_coincide"
ACIERTOS_NO_COINCIDEN = "aciertos_no_coinciden"
RESUELTA_POR_INVALIDO = "resuelta_por_invalido"
NUMERO_SIN_ESTUDIANTE = "numero_sin_estudiante"


def event_id_de(codigo: str, numero: int) -> str:
    """El `event_id` determinista de una hoja: reenviarla es la MISMA hoja."""
    return f"grd:{codigo}:{numero}"


def es_acierto(item: ItemHojaIn) -> bool:
    """Solo una `marcada` puede ser un acierto; `vacia` y `doble` nunca, digan lo que digan."""
    return item.estado == "marcada" and item.correcta


def aciertos_de(hoja: HojaIn) -> int:
    """Los aciertos RECALCULADOS (no se usa `hoja.aciertos`)."""
    return sum(1 for item in hoja.items if es_acierto(item))


def motivo_de_rechazo(hoja: HojaIn, *, codigo: str, items_del_examen: Sequence[str],
                      numeros: Collection[int], profe_id: UUID) -> str | None:
    """Por qué esta hoja no entra, o `None`. El primer motivo que falle, en orden fijo."""
    if hoja.event_id != event_id_de(codigo, hoja.numero):
        return EVENT_ID_INVALIDO
    if any(item.estado not in ESTADOS for item in hoja.items):
        return ESTADO_INVALIDO
    if sorted(item.item_id for item in hoja.items) != sorted(items_del_examen):
        return ITEMS_NO_COINCIDEN
    if hoja.total != len(items_del_examen):
        return TOTAL_NO_COINCIDE
    if hoja.aciertos != aciertos_de(hoja):
        return ACIERTOS_NO_COINCIDEN
    if any(item.resuelta_por not in (None, profe_id) for item in hoja.items):
        return RESUELTA_POR_INVALIDO
    if hoja.numero not in numeros:
        return NUMERO_SIN_ESTUDIANTE
    return None
