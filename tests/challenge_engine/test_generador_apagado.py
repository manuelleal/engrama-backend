"""GA1: el generador viejo con IA nace apagado — `docs/ESPEC_generador_apagado.md`.

No-integ: `get_current_user` se reemplaza por un docente y el generador por un
doble que CUENTA sus llamadas y corta con un 418 propio (así nunca hay red ni
base). Un solo test afirma C1 (el valor por defecto), C2 (apagado: 503 y 0
llamadas) y C3 (encendido: llega al generador).
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.auth.schemas import AuthContext
from src.challenge_engine import router as retos_router
from src.main import app
from src.shared.config import Settings
from src.shared.deps import get_current_user

client = TestClient(app, raise_server_exceptions=False)
CUERPO = {"cefr_level": "B1", "skill": "grammar", "topic": "sintético"}


def _por_defecto(monkeypatch: pytest.MonkeyPatch) -> bool:
    """El valor con la variable AUSENTE del entorno y sin leer ningún `.env`."""
    monkeypatch.delenv("CHALLENGES_GENERATE_ENABLED", raising=False)
    limpio = Settings(_env_file=None, supabase_jwt_secret="x" * 32,  # type: ignore[call-arg]
                      database_url="postgresql://u:p@127.0.0.1:1/x")
    return limpio.challenges_generate_enabled


def _llamar(monkeypatch: pytest.MonkeyPatch, *, encendido: bool) -> tuple[int, Any, int]:
    """(estado, detalle, llamadas al generador) de un profe con cuerpo válido."""
    llamadas: list[dict[str, Any]] = []

    async def doble(**datos: Any) -> Any:
        llamadas.append(datos)
        raise HTTPException(status_code=418, detail="llegó al generador")

    monkeypatch.setattr(retos_router.generator_service, "generate_challenge", doble)
    monkeypatch.setattr(retos_router.settings, "challenges_generate_enabled", encendido)
    r = client.post("/challenges/generate", json=CUERPO)
    return r.status_code, r.json().get("detail"), len(llamadas)


def test_ga1_el_generador_nace_apagado(monkeypatch) -> None:
    """GA1 (C1-C3): apagado por defecto, 503 sin llamar a la IA; encendido, llega."""
    docente = AuthContext(profile_id=uuid4(), role="teacher", tenant_id=uuid4(),
                          group_code=None, is_teacher=True, is_admin=False)
    app.dependency_overrides[get_current_user] = lambda: docente
    try:
        observado = {
            "por_defecto": _por_defecto(monkeypatch),
            "apagado": _llamar(monkeypatch, encendido=False),
            "encendido": _llamar(monkeypatch, encendido=True),
        }
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert observado == {
        "por_defecto": False,
        "apagado": (503, "generador_apagado", 0),
        "encendido": (418, "llegó al generador", 1),
    }, f"GA1: {observado}"
