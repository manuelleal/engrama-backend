"""Schemas Pydantic del módulo leaderboard — SPECS/04-leaderboard.md §2.

Pydantic v2 strict con `extra="forbid"` (WINDSURF §4). El ranking es
solo-lectura, así que solo hay schemas de salida.
"""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


_STRICT = ConfigDict(strict=True, extra="forbid")


class LeaderboardEntry(BaseModel):
    """Una fila del ranking: un estudiante con su posición y métricas."""

    model_config = _STRICT

    rank: int
    profile_id: UUID
    full_name: str
    coins: int
    xp: int
    level: int
    current_streak: int
    is_me: bool = False


class LeaderboardOut(BaseModel):
    """Respuesta de GET /leaderboard.

    `entries` trae solo el top-N (parámetro `limit`). `me` trae la fila del
    propio usuario con su rank real, aunque caiga fuera del top-N — así el
    front siempre puede mostrar "tú estás en el puesto 47" sin pedir más datos.
    `total` es la cantidad total de estudiantes rankeados en el scope.
    """

    model_config = _STRICT

    scope: str  # 'group' | 'tenant'
    group_code: str | None = None
    entries: list[LeaderboardEntry]
    me: LeaderboardEntry | None = None
    total: int
