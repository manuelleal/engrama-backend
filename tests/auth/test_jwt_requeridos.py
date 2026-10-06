"""UJ1 y su tramposo ZH10 — `docs/ESPEC_endurecimiento_piloto.md`, H-10.

No-integ: `validate_jwt` es pura. Un token BIEN FIRMADO al que le falte `exp`,
`aud` o `sub` da 401. Antes, python-jose aceptaba uno sin `exp` (no vencía
nunca) y uno sin `aud` (medido en la auditoría 02).

La función se llama por el módulo (`auth_service.validate_jwt`) para que el
tramposo la alcance.
"""
from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi import HTTPException
from jose import jwt

from src.auth import service as auth_service
from tests.conftest import TEST_JWT_SECRET

SUB = "11111111-1111-4111-8111-111111111111"


def _token(**sin: bool) -> str:
    """Un token completo, menos los claims que se pidan quitar (`sin_exp=True`…)."""
    ahora = int(time.time())
    claims: dict[str, Any] = {"sub": SUB, "aud": "authenticated", "iat": ahora,
                              "exp": ahora + 3600, "role": "authenticated"}
    for clave in ("exp", "aud", "sub"):
        if sin.get(f"sin_{clave}"):
            del claims[clave]
    return jwt.encode(claims, TEST_JWT_SECRET, algorithm="HS256")


def _estado(token: str) -> int:
    try:
        auth_service.validate_jwt(token)
    except HTTPException as exc:
        return exc.status_code
    return 200


def test_uj1_el_jwt_debe_traer_exp_aud_y_sub() -> None:
    """UJ1 (H-10): completo pasa; sin `exp`, sin `aud` o sin `sub`, 401."""
    observado = {
        "completo": _estado(_token()),
        "sin_exp": _estado(_token(sin_exp=True)),
        "sin_aud": _estado(_token(sin_aud=True)),
        "sin_sub": _estado(_token(sin_sub=True)),
    }
    assert observado == {"completo": 200, "sin_exp": 401, "sin_aud": 401, "sin_sub": 401}, (
        f"UJ1: {observado}")


def _validate_jwt_de_antes(token: str) -> dict[str, Any]:
    """ZH10: el `jwt.decode` anterior, sin `options` (no exige ningún claim)."""
    payload: dict[str, Any] = jwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"],
                                         audience="authenticated")
    if not payload.get("sub"):
        raise HTTPException(status_code=401, detail="JWT payload missing 'sub' claim")
    return payload


def test_zh10_tramposo_sin_exigir_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    """ZH10: con el decode de antes, un token sin `exp` (eterno) entra, y UJ1 se pone rojo."""
    monkeypatch.setattr(auth_service, "validate_jwt", _validate_jwt_de_antes)
    with pytest.raises(AssertionError, match=r"UJ1: \{'completo': 200, 'sin_exp': 200"):
        test_uj1_el_jwt_debe_traer_exp_aud_y_sub()
