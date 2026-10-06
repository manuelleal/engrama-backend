"""UR-reloj y su tramposo — `docs/ESPEC_endurecimiento_piloto.md`, el intermitente del reloj.

El colegio por defecto de quien tiene dos membresías es la MÁS ANTIGUA
(`ESPEC_login_piloto.md` §1.3). El reloj del contenedor de pruebas retrocede
hasta 1,95 s, así que dos membresías creadas seguidas podían quedar en el orden
inverso, y varios tests caían de vez en cuando (`test_f4_…`, HP1, RP1, Y1, X21).

Desde esta espec, los actores de prueba con dos membresías fijan `created_at`
explícito. Este test lo comprueba donde nace: en `_actores.armar`.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.main import app
from tests.integ_ayudante import Integ
from tests.teachers._actores import armar

pytestmark = pytest.mark.integ
client = TestClient(app, raise_server_exceptions=False)


def test_ur_reloj_los_actores_no_dependen_del_reloj(integ) -> None:
    """La membresía de D en A es al menos 1 hora más antigua que la de B; por defecto, A."""
    esc = armar(integ)
    diferencia = integ.valor(
        "select (select created_at from memberships where profile_id = :d and tenant_id = :b)"
        " - (select created_at from memberships where profile_id = :d and tenant_id = :a)",
        d=esc.d, a=esc.tenant_a, b=esc.tenant_b)
    activos = {client.get("/auth/me", headers=integ.headers(esc.d)).json().get("active_tenant_id")
               for _ in range(5)}
    observado = {"a_es_al_menos_una_hora_mas_antigua": diferencia >= timedelta(hours=1),
                 "por_defecto": activos == {str(esc.tenant_a)}}
    assert observado == {"a_es_al_menos_una_hora_mas_antigua": True, "por_defecto": True}, (
        f"UR-reloj: {observado}, diferencia = {diferencia}")


def _fecha_de_la_base(creada_hace: Any) -> dict[str, Any]:
    """El tramposo: como antes, la fecha la pone `now()` de la base."""
    return {}


def test_zh_reloj_tramposo_sin_fecha_explicita(integ, monkeypatch) -> None:
    """Sin la fecha explícita, las dos membresías quedan a milisegundos (y a merced del reloj)."""
    monkeypatch.setattr(Integ, "_fecha", staticmethod(_fecha_de_la_base))
    with pytest.raises(AssertionError, match=r"'a_es_al_menos_una_hora_mas_antigua': False"):
        test_ur_reloj_los_actores_no_dependen_del_reloj(integ)
