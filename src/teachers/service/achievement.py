"""T5 — logro por eje del grupo — ESPEC §2.1 (corregida por ERR-16, con P1/P4).

Reemplaza a `weak_skills` (nunca se escribió, §0): todo se calcula con datos
que ya existen (`challenge_attempts.answers`, `challenges.skill/cefr_level`),
en funciones PURAS (reciben `now`, no tocan la DB) — así U3a-U3g las prueban
sin Docker. `build_response` (al final) es la única que sabe de DB.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.models import Challenge, ChallengeAttempt, Group
from src.teachers.schemas import (
    AchievementMethodOut,
    AchievementOut,
    AttemptDetailOut,
    AxisOut,
    SkillDetailOut,
    StudentAchievementOut,
)
from src.teachers.service import panel as panel_service

# =============================================================================
# Constantes (ESPEC §2.1, respuesta de T5).
# =============================================================================
WINDOW_DAYS = 28
MIN_ITEMS = 8
MIN_CHALLENGES = 3
THRESHOLD_LOGRADO = 80
THRESHOLD_EN_DESARROLLO = 60
EXCLUDED_TYPES = ("open",)
AXIS_ORDER = ("Comprehension", "Expression", "Accuracy")

_AXIS_MAP: dict[str, str] = {
    "reading": "Comprehension", "listening": "Comprehension",
    "writing": "Expression", "speaking": "Expression",
    "grammar": "Accuracy", "vocabulary": "Accuracy",
}

_LABELS: dict[str, str] = {
    "logrado": "logrado: {eje}",
    "en_desarrollo": "en desarrollo: {eje}",
    "a_reforzar": "a reforzar: {eje}",
    "datos_insuficientes": "datos insuficientes: {eje}",
}

METHOD = AchievementMethodOut(
    window_days=WINDOW_DAYS,
    first_attempt_only=True,
    min_items=MIN_ITEMS,
    min_challenges=MIN_CHALLENGES,
    thresholds={"logrado": THRESHOLD_LOGRADO, "en_desarrollo": THRESHOLD_EN_DESARROLLO},
    excluded_types=list(EXCLUDED_TYPES),
    axis_mapping="fijo por la skill del reto",
    cefr_filter="no_aplicado: no existe nivel MCER asignado por estudiante",
    status_scope="desempeño en los retos asignados al grupo; no es nivel MCER del estudiante",
)


# =============================================================================
# Helpers puros de mapeo (U3e).
# =============================================================================
def normalize_skill(skill: str | None) -> str | None:
    """minúsculas y sin espacios (§2.1.4); `None` o vacío -> `None`."""
    if skill is None:
        return None
    normalizado = skill.strip().lower().replace(" ", "")
    return normalizado or None


def skill_to_axis(skill: str | None) -> str | None:
    """Tabla fija de §2.1.4. `None` si no mapea (entra a `unmapped_items`)."""
    normalizado = normalize_skill(skill)
    if normalizado is None:
        return None
    return _AXIS_MAP.get(normalizado)


# =============================================================================
# Entrada pura: un intento `completed`, tal como lo guarda `attempts.py`.
# =============================================================================
@dataclass(frozen=True)
class AttemptRow:
    """Un `ChallengeAttempt` `completed`, ya unido con su `Challenge` (§0)."""

    attempt_id: UUID
    challenge_id: UUID
    title: str
    skill: str | None
    cefr_level: str | None
    challenge_type: str
    answers: list[dict[str, Any]] = field(default_factory=list)
    score_percent: float = 0.0
    is_correct: bool = False
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime = field(default_factory=datetime.now)


def _primeros_intentos(intentos: list[AttemptRow]) -> dict[UUID, AttemptRow]:
    """El primer intento (§2.1.1) de CADA challenge, sobre TODA la historia."""
    por_challenge: dict[UUID, list[AttemptRow]] = defaultdict(list)
    for a in intentos:
        por_challenge[a.challenge_id].append(a)
    return {
        cid: min(lst, key=lambda a: (a.completed_at, a.started_at, str(a.attempt_id)))
        for cid, lst in por_challenge.items()
    }


def primeros_en_ventana(intentos: list[AttemptRow], now: datetime) -> list[AttemptRow]:
    """El PRIMER intento de cada challenge, sin `open`, dentro de la ventana de
    28 días — el alcance compartido de T5 (§2.1, puntos 1-3) y T7 (§2.3).

    Cada `AttemptRow` devuelto ES el que aporta ítems (uno por challenge).
    """
    en_alcance = [a for a in intentos if a.challenge_type not in EXCLUDED_TYPES]
    primeros = _primeros_intentos(en_alcance)
    limite = now - timedelta(days=WINDOW_DAYS)
    return [p for p in primeros.values() if p.completed_at >= limite]


def _axis_status(items: int, correct: int, n_retos: int) -> str:
    """§2.1.5-6: mínimo (8 ítems, 3 retos) y umbrales, con enteros (nunca float)."""
    if items >= MIN_ITEMS and n_retos >= MIN_CHALLENGES:
        if 100 * correct >= THRESHOLD_LOGRADO * items:
            return "logrado"
        if 100 * correct >= THRESHOLD_EN_DESARROLLO * items:
            return "en_desarrollo"
        return "a_reforzar"
    return "datos_insuficientes"


def compute_achievement_for_student(
    intentos: list[AttemptRow], now: datetime
) -> dict[str, Any]:
    """El logro de UN estudiante — ESPEC §2.1, puntos 1-6.

    `intentos`: intentos `completed` YA filtrados por alcance (grupo del
    roster) salvo el tipo `open`, que se excluye AQUÍ (§2.1.3, U3g) — así
    U3g lo prueba sin tocar la base.
    """
    en_alcance = [a for a in intentos if a.challenge_type not in EXCLUDED_TYPES]
    primeros = _primeros_intentos(en_alcance)
    calificados = {p.challenge_id: p for p in primeros_en_ventana(intentos, now)}

    ejes: dict[str, dict[str, Any]] = {
        ax: {"items": 0, "correct": 0, "challenges": set(), "cefr_levels": Counter()}
        for ax in AXIS_ORDER
    }
    skills: dict[str | None, dict[str, Any]] = {}
    unmapped_items = 0

    for cid, primero in calificados.items():
        axis = skill_to_axis(primero.skill)
        skill_norm = normalize_skill(primero.skill)
        bucket = skills.setdefault(
            skill_norm, {"skill": skill_norm, "axis": axis, "items": 0, "correct": 0}
        )
        for item in primero.answers:
            ok = bool(item.get("is_correct"))
            bucket["items"] += 1
            bucket["correct"] += int(ok)
            if axis is None:
                unmapped_items += 1
                continue
            eje = ejes[axis]
            eje["items"] += 1
            eje["correct"] += int(ok)
            eje["challenges"].add(cid)
            eje["cefr_levels"][primero.cefr_level or "sin_nivel"] += 1

    axes_out = []
    for nombre in AXIS_ORDER:
        d = ejes[nombre]
        items, correct, n_retos = d["items"], d["correct"], len(d["challenges"])
        estado = _axis_status(items, correct, n_retos)
        axes_out.append(
            AxisOut(
                axis=nombre, status=estado, label=_LABELS[estado].format(eje=nombre),
                items=items, correct=correct, challenges=n_retos,
                cefr_levels=dict(d["cefr_levels"]),
            )
        )

    skills_out = [
        SkillDetailOut(**s)
        for s in sorted(skills.values(), key=lambda s: (s["skill"] is None, s["skill"] or ""))
    ]

    limite = now - timedelta(days=WINDOW_DAYS)
    attempts_out = sorted(
        (
            AttemptDetailOut(
                challenge_id=a.challenge_id, title=a.title, skill=a.skill,
                score_percent=a.score_percent, is_correct=a.is_correct,
                completed_at=a.completed_at,
                first_attempt=primeros.get(a.challenge_id) is a,
            )
            for a in en_alcance
            if a.completed_at >= limite
        ),
        key=lambda a: a.completed_at,
    )

    return {
        "axes": axes_out, "skills": skills_out,
        "unmapped_items": unmapped_items, "attempts": attempts_out,
    }


# =============================================================================
# DB wiring — la única parte que no es pura.
# =============================================================================
async def intentos_del_grupo(
    db: AsyncSession, group: Group, student_ids: list[UUID]
) -> dict[UUID, list[AttemptRow]]:
    """Todos los `completed` de retos con `group_id = group.id`, por estudiante."""
    if not student_ids:
        return {}
    stmt = (
        select(ChallengeAttempt, Challenge)
        .join(Challenge, Challenge.id == ChallengeAttempt.challenge_id)
        .where(
            Challenge.group_id == group.id,
            ChallengeAttempt.student_id.in_(student_ids),
            ChallengeAttempt.status == "completed",
        )
    )
    rows = (await db.execute(stmt)).all()
    por_estudiante: dict[UUID, list[AttemptRow]] = defaultdict(list)
    for intento, challenge in rows:
        por_estudiante[intento.student_id].append(
            AttemptRow(
                attempt_id=intento.id, challenge_id=challenge.id, title=challenge.title,
                skill=challenge.skill, cefr_level=challenge.cefr_level,
                challenge_type=challenge.challenge_type,
                answers=list(intento.answers or []),
                score_percent=float(intento.score_percent),
                is_correct=bool(intento.is_correct),
                started_at=intento.started_at,
                completed_at=intento.completed_at or intento.started_at,
            )
        )
    return por_estudiante


async def build_response(db: AsyncSession, group: Group, *, now: datetime) -> AchievementOut:
    """T5 completo: roster de T2 (mismo orden) + logro de cada estudiante."""
    roster = await panel_service.roster(db, group)
    por_estudiante = await intentos_del_grupo(db, group, [s.profile_id for s in roster])

    students = [
        StudentAchievementOut(
            profile_id=s.profile_id, full_name=s.full_name,
            **compute_achievement_for_student(por_estudiante.get(s.profile_id, []), now),
        )
        for s in roster
    ]
    return AchievementOut(method=METHOD, students=students)


__all__ = [
    "normalize_skill", "skill_to_axis", "AttemptRow", "primeros_en_ventana",
    "intentos_del_grupo", "compute_achievement_for_student", "build_response", "METHOD",
    "WINDOW_DAYS", "MIN_ITEMS", "MIN_CHALLENGES",
    "THRESHOLD_LOGRADO", "THRESHOLD_EN_DESARROLLO", "AXIS_ORDER", "EXCLUDED_TYPES",
]
