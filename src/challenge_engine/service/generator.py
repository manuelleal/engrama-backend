"""Generación de challenges con Anthropic API — SPECS/03-challenges.md §5.

`generate_challenge` llama al modelo Claude Sonnet y parsea un JSON
estructurado que convertimos a `ChallengeCreate`. El caller
(`router.generate_challenge`) usa ese output para persistir el challenge
vía `challenges_service.create_challenge`.

Diseño:
  - Llamada HTTP async con `httpx.AsyncClient` — no bloqueamos el loop.
  - Si la API key no está configurada → 503 sin tocar red.
  - Si la API falla (red, 4xx, 5xx) → 503 con detalle sanitizado.
  - Si el modelo devuelve JSON malformado → 502 (Bad Gateway).
  - Cada invocación se loguea en `ai_usage_logs` (best-effort; si el
    INSERT falla no tumba el request — los logs son informativos).

NOTA sobre la AI key: este módulo jamás loguea el secret ni lo devuelve
en errores. Si algún día se captura el exception body, sanitizarlo
antes de loguear.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.challenge_engine.schemas import (
    ChallengeCreate,
    ChallengeQuestionIn,
)
from src.shared.config import settings

logger = logging.getLogger(__name__)

# Modelo y endpoint — constantes locales del módulo. Si se necesitan
# configurables por tenant en el futuro, migrar a `tenants.active_ai_provider`.
ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
MAX_TOKENS = 2000
REQUEST_TIMEOUT_SECONDS = 45.0


# =============================================================================
# Prompt builder — separado para testeabilidad
# =============================================================================
def build_prompt(
    *,
    cefr_level: str,
    skill: str,
    topic: str,
    num_questions: int,
    specific_instructions: str | None,
) -> str:
    """Construye el user-prompt que se envía al modelo.

    El system prompt se maneja por separado en `_build_messages` para
    dar al modelo el rol y el formato de salida estrictos.
    """
    extra = f"\n\nAdditional instructions: {specific_instructions}" if specific_instructions else ""
    return (
        f"Generate {num_questions} multiple-choice questions in English at "
        f"CEFR level {cefr_level} on the topic: \"{topic}\". "
        f"Skill focus: {skill}."
        f"{extra}\n\n"
        "Return ONLY a JSON object matching this schema exactly (no markdown, "
        "no commentary, no trailing text):\n"
        "{\n"
        '  "title": "<short title>",\n'
        '  "description": "<one-sentence description>",\n'
        '  "questions": [\n'
        "    {\n"
        '      "question_text": "<the question>",\n'
        '      "options_json": [\n'
        '        {"label": "A", "value": "<option A>"},\n'
        '        {"label": "B", "value": "<option B>"},\n'
        '        {"label": "C", "value": "<option C>"},\n'
        '        {"label": "D", "value": "<option D>"}\n'
        "      ],\n"
        '      "correct_answer": "<exact value of the correct option>"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )


def _build_messages(prompt: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": prompt}]


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_model_output(raw_text: str) -> dict[str, Any]:
    """Extrae el primer objeto JSON del texto devuelto por el modelo.

    Aunque pedimos JSON puro, los modelos a veces envuelven en ```json...```
    o añaden texto. Con un regex tolerante nos aseguramos.
    """
    # Intento directo primero (feliz camino).
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass
    m = _JSON_OBJECT_RE.search(raw_text)
    if not m:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI response did not contain valid JSON",
        )
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI response JSON is malformed",
        ) from exc


# =============================================================================
# Main: generate_challenge
# =============================================================================
async def generate_challenge(
    *,
    cefr_level: str,
    skill: str,
    topic: str,
    num_questions: int = 3,
    specific_instructions: str | None = None,
    group_id: UUID | None = None,
) -> ChallengeCreate:
    """Invoca al modelo y devuelve un `ChallengeCreate` listo para persistir.

    No escribe en DB; el log a `ai_usage_logs` lo hace `log_ai_usage`
    aparte (el caller decide si loguearlo con tenant/user context).
    """
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Anthropic API key not configured",
        )

    prompt = build_prompt(
        cefr_level=cefr_level,
        skill=skill,
        topic=topic,
        num_questions=num_questions,
        specific_instructions=specific_instructions,
    )
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": _build_messages(prompt),
    }
    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.post(ANTHROPIC_ENDPOINT, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("Anthropic API network error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service unavailable",
        ) from exc

    if resp.status_code >= 400:
        # No reinyectamos el cuerpo de Anthropic para evitar filtrar detalles
        # o la API key en errores de proxy.
        logger.warning("Anthropic API HTTP %s", resp.status_code)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI service returned HTTP {resp.status_code}",
        )

    body = resp.json()
    # Claude Messages API: content es lista de bloques {type, text}.
    text_blocks = [b.get("text", "") for b in body.get("content", []) if b.get("type") == "text"]
    raw = "".join(text_blocks).strip()
    data = parse_model_output(raw)

    # Armado defensivo de ChallengeCreate. Validación estricta de Pydantic
    # atrapa cualquier campo faltante.
    try:
        questions_in = [
            ChallengeQuestionIn(
                question_type="multiple_choice",
                question_text=str(q["question_text"]),
                options_json=list(q.get("options_json") or []),
                correct_answer=str(q["correct_answer"]),
                order_index=i,
            )
            for i, q in enumerate(data.get("questions", []), start=1)
        ]
        challenge_in = ChallengeCreate(
            title=str(data.get("title") or f"{topic} — {cefr_level}"),
            description=str(data.get("description") or f"Generated challenge for {topic}"),
            challenge_type="multiple_choice",
            cefr_level=cefr_level,
            skill=skill,
            topic=topic,
            specific_instructions=specific_instructions,
            group_id=group_id,
            questions=questions_in,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI response missing required challenge fields",
        ) from exc

    # Exponer también tokens consumidos para el logger.
    usage = body.get("usage") or {}
    total_tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
    challenge_in.__dict__["_ai_tokens_used"] = total_tokens  # side-channel para log
    return challenge_in


# =============================================================================
# Logging de uso IA (best-effort)
# =============================================================================
async def log_ai_usage(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    tokens_used: int,
    cefr_level: str,
    skill: str,
    topic: str,
) -> None:
    """Inserta una fila en `ai_usage_logs`. Silencia errores (best-effort)."""
    try:
        await db.execute(
            text(
                """
                INSERT INTO ai_usage_logs
                    (tenant_id, user_id, provider, model, tokens_used,
                     credits_charged, cefr_level, skill, topic)
                VALUES
                    (:tenant_id, :user_id, :provider, :model, :tokens_used,
                     :credits_charged, :cefr_level, :skill, :topic)
                """
            ),
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "provider": "anthropic",
                "model": ANTHROPIC_MODEL,
                "tokens_used": tokens_used,
                "credits_charged": 1,
                "cefr_level": cefr_level,
                "skill": skill,
                "topic": topic,
            },
        )
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("Failed to write ai_usage_logs: %s", exc)
