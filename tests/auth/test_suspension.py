"""Suspender una cuenta — `docs/ESPEC_endurecimiento_piloto.md`, H-8.

  AH8   `profiles.is_active = false` -> 403 `account_suspended` en toda ruta, al instante.
  OH8   las órdenes `suspender` y `reactivar` de la CLI del operador.
  ZH8a  `get_current_user` no mira `is_active`            -> AH8 rojo.
  ZH8b  `suspender` no desactiva la membresía            -> OH8 rojo.

Reglas: el cliente con `raise_server_exceptions=False`, lo observado en un
dict comparado entero, y el estado sembrado en la base (ERR-9).
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.onboarding import suspension as suspension_mod
from src.onboarding.__main__ import main
from src.shared import deps as deps_mod
from tests.seguridad.veredictos import sembrar

pytestmark = pytest.mark.integ
client = TestClient(app, raise_server_exceptions=False)


def _tres(integ: Any, perfil: UUID) -> list[tuple[int, Any]]:
    h = integ.headers(perfil)
    respuestas = (client.get("/auth/me", headers=h), client.post("/auth/session", headers=h),
                  client.get("/challenges/", headers=h))
    return [(r.status_code, r.json().get("detail") if r.status_code != 200 else None)
            for r in respuestas]


def test_ah8_la_cuenta_suspendida_no_entra_a_nada(integ) -> None:
    """AH8 (H-8): 403 `account_suspended` en las tres; el otro usuario y el reactivado, 200."""
    tenant = integ.crear_tenant()
    ana, otro = integ.crear_perfil(tenant), integ.crear_perfil(tenant)
    antes = _tres(integ, ana)
    sembrar(integ, "update profiles set is_active = false where id = :p", p=ana)
    suspendida = _tres(integ, ana)
    del_otro = _tres(integ, otro)
    sembrar(integ, "update profiles set is_active = true where id = :p", p=ana)
    observado = {"antes": antes, "suspendida": suspendida, "el_otro": del_otro,
                 "reactivada": _tres(integ, ana)}
    ok = [(200, None)] * 3
    assert observado == {"antes": ok, "suspendida": [(403, "account_suspended")] * 3,
                         "el_otro": ok, "reactivada": ok}, f"AH8: {observado}"


def _cli(capsys: Any, integ: Any, *argv: str) -> tuple[int, dict[str, Any]]:
    """Corre la CLI SIN doble de GoTrue: estas órdenes no lo necesitan."""
    capsys.readouterr()
    codigo = main(list(argv), sesiones=integ.Session)
    salida = capsys.readouterr().out.strip()
    return codigo, (json.loads(salida) if salida else {})


def _estado(integ: Any, perfil: UUID, tenant: UUID) -> tuple[Any, Any]:
    """(perfil activo, membresía activa en esa institución)."""
    return (integ.valor("select is_active from profiles where id = :p", p=perfil),
            integ.valor("select is_active from memberships where profile_id = :p "
                        "and tenant_id = :t", p=perfil, t=tenant))


def test_oh8_suspender_y_reactivar_por_la_cli(integ, capsys, monkeypatch) -> None:
    """OH8 (H-8): `suspender` corta perfil y membresía sin GoTrue; `reactivar` lo deshace."""
    monkeypatch.delenv("GOTRUE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    a, b = integ.crear_tenant(), integ.crear_tenant()
    sembrar(integ, "update tenants set slug = 'inst-a' where id = :t", t=a)
    sembrar(integ, "update tenants set slug = 'inst-b' where id = :t", t=b)
    ana, beto = integ.crear_perfil(a), integ.crear_perfil(a)
    doc = {p: str(integ.valor("select documento_id from profiles where id = :p", p=p))
           for p in (ana, beto)}

    de_otra = _cli(capsys, integ, "suspender", "--slug", "inst-b", "--documento", doc[ana])
    sin_cambios = _estado(integ, ana, a)
    suspender = _cli(capsys, integ, "suspender", "--slug", "inst-a", "--documento", doc[ana])
    tras_suspender = (_estado(integ, ana, a), _tres(integ, ana)[0])
    otra_vez = _cli(capsys, integ, "suspender", "--slug", "inst-a", "--documento", doc[ana])[0]
    solo = _cli(capsys, integ, "suspender", "--slug", "inst-a", "--documento", doc[beto],
                "--solo-institucion")
    reactivar = _cli(capsys, integ, "reactivar", "--slug", "inst-a", "--documento", doc[ana])
    observado = {
        "documento_de_otra_institucion": (de_otra[0], de_otra[1].get("suspendidas"),
                                          "error" in de_otra[1], sin_cambios),
        "suspender": (suspender, tras_suspender), "repetir": otra_vez,
        "solo_institucion": (solo[0], _estado(integ, beto, a)),
        "reactivar": (reactivar, _estado(integ, ana, a), _tres(integ, ana)[0]),
        "auditorias": [int(integ.valor("select count(*) from audit_logs where action_type = :a",
                                       a=accion))
                       for accion in ("cuenta_suspendida", "cuenta_reactivada")],
    }
    assert observado == {
        "documento_de_otra_institucion": (1, 0, True, (True, True)),
        "suspender": ((0, {"institucion": "inst-a", "suspendidas": 1}),
                      ((False, False), (403, "account_suspended"))),
        "repetir": 0, "solo_institucion": (0, (True, False)),
        "reactivar": ((0, {"institucion": "inst-a", "reactivadas": 1}), (True, True),
                      (200, None)),
        "auditorias": [3, 1],
    }, f"OH8: {observado}"


# =============================================================================
# Tramposos
# =============================================================================
def test_zh8a_tramposo_sin_mirar_is_active(integ, monkeypatch) -> None:
    """ZH8a: si `get_current_user` no mira `is_active`, la suspendida entra y AH8 cae."""
    monkeypatch.setattr(deps_mod, "exigir_cuenta_activa", lambda profile: None)
    with pytest.raises(AssertionError, match=r"'suspendida': \[\(200, None\), \(200, None\)"):
        test_ah8_la_cuenta_suspendida_no_entra_a_nada(integ)


async def _solo_el_perfil(db: Any, membresia: Any, *, activo: bool, tocar_perfil: bool) -> None:
    """ZH8b: toca el perfil y deja la membresía como estaba."""
    from sqlalchemy import update

    from src.shared.models import Profile

    await db.execute(update(Profile).where(Profile.id == membresia.profile_id)
                     .values(is_active=activo))


def test_zh8b_tramposo_suspender_sin_la_membresia(integ, capsys, monkeypatch) -> None:
    """ZH8b: si `suspender` no desactiva la membresía, OH8 cae."""
    monkeypatch.setattr(suspension_mod, "_aplicar", _solo_el_perfil)
    with pytest.raises(AssertionError, match=r"\(\(False, True\), \(403, 'account_suspended'\)\)"):
        test_oh8_suspender_y_reactivar_por_la_cli(integ, capsys, monkeypatch)
