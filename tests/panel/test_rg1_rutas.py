"""RG1 — regresión = identidad del inventario de rutas (docs/ESPEC_panel_super_admin.md §2).

Se congeló en `d275074` (rama `juego/sprint-backend`), ANTES de agregar el panel. Después del
cambio, la app debe tener EXACTAMENTE estas rutas más las que declara la espec (`NUEVAS`): ni una
ruta vieja menos, ni una nueva sin declarar.
"""
from __future__ import annotations

from fastapi.routing import APIRoute

from src.main import app

# 84 (método, ruta) medidos en d275074.
CONGELADAS: frozenset[tuple[str, str]] = frozenset({
    ("DELETE", "/teachers/groups/{gid}/codigo-inscripcion"),
    ("DELETE", "/teachers/groups/{gid}/foco/{desde}"),
    ("GET", "/admin/presupuestos"),
    ("GET", "/admin/solicitudes-datos"),
    ("GET", "/auth/me"),
    ("GET", "/auth/solicitudes-datos"),
    ("GET", "/challenges/"),
    ("GET", "/challenges/all"),
    ("GET", "/challenges/attempts/history"),
    ("GET", "/challenges/attempts/{attempt_id}/answers"),
    ("GET", "/challenges/camino"),
    ("GET", "/challenges/foco"),
    ("GET", "/challenges/refuerzo"),
    ("GET", "/challenges/tanda"),
    ("GET", "/challenges/{challenge_id}"),
    ("GET", "/core/attendance/history"),
    ("GET", "/core/attendance/history/{student_id}"),
    ("GET", "/core/attendance/sessions/active"),
    ("GET", "/core/coins/balance"),
    ("GET", "/core/coins/history"),
    ("GET", "/core/racha"),
    ("GET", "/economia/grupo/{gid}/mochila"),
    ("GET", "/economia/grupo/{gid}/saldos"),
    ("GET", "/economia/mochila"),
    ("GET", "/economia/presupuesto"),
    ("GET", "/economia/tienda"),
    ("GET", "/grader/grupos/{group_code}/lista"),
    ("GET", "/health"),
    ("GET", "/subastas/activa"),
    ("GET", "/teachers/challenges/{cid}/nodos"),
    ("GET", "/teachers/curriculo/nodos"),
    ("GET", "/teachers/groups"),
    ("GET", "/teachers/groups/{gid}/achievement"),
    ("GET", "/teachers/groups/{gid}/codigo-inscripcion"),
    ("GET", "/teachers/groups/{gid}/foco"),
    ("GET", "/teachers/groups/{gid}/foco/logro"),
    ("GET", "/teachers/groups/{gid}/item-errors"),
    ("GET", "/teachers/groups/{gid}/refuerzo"),
    ("GET", "/teachers/groups/{gid}/solicitudes"),
    ("GET", "/teachers/groups/{gid}/students"),
    ("PATCH", "/challenges/{challenge_id}/status"),
    ("PATCH", "/economia/tienda/{item_id}"),
    ("POST", "/admin/groups"),
    ("POST", "/admin/groups/{gid}/students"),
    ("POST", "/admin/groups/{gid}/students/import"),
    ("POST", "/admin/groups/{gid}/teachers"),
    ("POST", "/admin/presupuestos/{teacher_id}/devolver"),
    ("POST", "/admin/presupuestos/{teacher_id}/recargar"),
    ("POST", "/auth/consentimiento"),
    ("POST", "/auth/contrasena"),
    ("POST", "/auth/logout"),
    ("POST", "/auth/registro"),
    ("POST", "/auth/session"),
    ("POST", "/auth/solicitudes-datos"),
    ("POST", "/challenges/"),
    ("POST", "/challenges/attempts/{attempt_id}/answers"),
    ("POST", "/challenges/attempts/{attempt_id}/finish"),
    ("POST", "/challenges/attempts/{attempt_id}/submit"),
    ("POST", "/challenges/generate"),
    ("POST", "/challenges/refuerzo/{entrada_id}/respuestas"),
    ("POST", "/challenges/tanda"),
    ("POST", "/challenges/{challenge_id}/attempt"),
    ("POST", "/core/attendance/check-in"),
    ("POST", "/core/attendance/sessions"),
    ("POST", "/economia/corregir"),
    ("POST", "/economia/dar"),
    ("POST", "/economia/mochila/{inventory_id}/entregar"),
    ("POST", "/economia/tienda"),
    ("POST", "/economia/tienda/{item_id}/comprar"),
    ("POST", "/events/batch"),
    ("POST", "/grader/resultados"),
    ("POST", "/subastas"),
    ("POST", "/subastas/{aid}/cerrar"),
    ("POST", "/subastas/{aid}/pujar"),
    ("POST", "/teachers/attendance-sessions/{sid}/close"),
    ("POST", "/teachers/groups/{gid}/attendance-sessions"),
    ("POST", "/teachers/groups/{gid}/codigo-inscripcion"),
    ("POST", "/teachers/groups/{gid}/solicitudes/{sid}/aprobar"),
    ("POST", "/teachers/groups/{gid}/solicitudes/{sid}/rechazar"),
    ("PUT", "/admin/solicitudes-datos/{sid}"),
    ("PUT", "/grader/examenes/{codigo}"),
    ("PUT", "/teachers/challenges/{cid}/nodos"),
    ("PUT", "/teachers/groups/{gid}/challenges/{cid}"),
    ("PUT", "/teachers/groups/{gid}/foco"),
})

# Lo que la espec declara (§1.4): las tres rutas GET del panel.
NUEVAS: frozenset[tuple[str, str]] = frozenset({
    ("GET", "/super/clientes"),
    ("GET", "/super/clientes/{tenant_id}"),
    ("GET", "/admin/metricas"),
})


# Lo que trae la base nueva fase0/backend @ 71e26a1 (lo que corre el servidor), unida a esta rama:
# el pase acotado hacia EVA y SET (docs/ESPEC_pase_acotado.md). No es del panel; se declara aquí.
DE_FASE0: frozenset[tuple[str, str]] = frozenset({
    ("POST", "/anillo/pases"),
    ("POST", "/anillo/canje"),
})


def _rutas() -> set[tuple[str, str]]:
    return {(m, r.path) for r in app.routes if isinstance(r, APIRoute) for m in r.methods}


def test_rg1_inventario_de_rutas_es_el_congelado_mas_las_nuevas() -> None:
    actuales = _rutas()
    faltan = CONGELADAS - actuales
    sobran = actuales - CONGELADAS - NUEVAS - DE_FASE0
    assert not faltan and not sobran, f"RG1: faltan {sorted(faltan)}, sobran {sorted(sobran)}"
    assert len(CONGELADAS) == 84
