"""Los 7 actores de la matriz rol×ruta — ESPEC §3. Fábrica compartida por
`tests/teachers/test_t*.py` y `test_m*.py`.

No empieza por `test_`: pytest no lo recolecta (mismo patrón que
`tests/seguridad/veredictos.py`).

  D  : docente dueño de GA (colegio A).
  E  : estudiante de GA.
  DO : docente de A SIN GA (sin fila en teacher_groups).
  DT : docente de B (otro colegio, sin relación con A).
  DM : D con membresía TAMBIÉN en B; llama con X-Tenant-ID: B.
  AA : admin de A.
  AB : admin de B.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from src.shared.models import TeacherGroup
from tests.integ_ayudante import Integ


@dataclass(frozen=True)
class Escuela:
    """Dos colegios con un grupo cada uno (GA en A, GB en B) y los 7 actores."""

    tenant_a: UUID
    tenant_b: UUID
    grupo_a: UUID
    grupo_b: UUID
    codigo_a: str
    codigo_b: str
    d: UUID
    e: UUID
    do: UUID
    dt: UUID
    dm: UUID
    aa: UUID
    ab: UUID

    def h(self, integ: Integ, quien: UUID, *, tenant: UUID | None = None) -> dict[str, str]:
        """Headers de `quien`; con `tenant` agrega X-Tenant-ID (para DM)."""
        headers = integ.headers(quien)
        if tenant is not None:
            headers["X-Tenant-ID"] = str(tenant)
        return headers


def armar(integ: Integ, *, codigo_a: str = "GA", codigo_b: str = "GB") -> Escuela:
    """Crea los dos colegios, sus grupos y los 7 actores. `D` ya está en `teacher_groups`.

    `DM` NO es un perfil nuevo: es el MISMO `D` (§3, "D con membresía también
    en B"), con una segunda `Membership` en `tenant_b` vía `afiliar`. Llama
    con `X-Tenant-ID: B` (ver `Escuela.h(..., tenant=esc.tenant_b)`).
    """
    tenant_a = integ.crear_tenant()
    tenant_b = integ.crear_tenant()
    grupo_a = integ.crear_grupo(tenant_a, codigo_a)
    grupo_b = integ.crear_grupo(tenant_b, codigo_b)

    # La membresía de D en A, un día antes que la de B: el colegio por defecto
    # de D (el más antiguo) no depende del reloj del contenedor.
    d = integ.crear_perfil(tenant_a, rol="teacher", creada_hace=timedelta(days=1))
    e = integ.crear_perfil(tenant_a, group_code=codigo_a)
    do = integ.crear_perfil(tenant_a, rol="teacher")
    dt = integ.crear_perfil(tenant_b, rol="teacher")
    integ.afiliar(d, tenant_b, rol="teacher")  # D también es DM en B
    aa = integ.crear_perfil(tenant_a, rol="admin")
    ab = integ.crear_perfil(tenant_b, rol="admin")

    integ._insertar(TeacherGroup(tenant_id=tenant_a, teacher_id=d, group_id=grupo_a))

    return Escuela(
        tenant_a=tenant_a, tenant_b=tenant_b, grupo_a=grupo_a, grupo_b=grupo_b,
        codigo_a=codigo_a, codigo_b=codigo_b,
        d=d, e=e, do=do, dt=dt, dm=d, aa=aa, ab=ab,
    )


def prohibidos_t(esc: Escuela, integ: Integ) -> list[tuple[str, dict[str, str], int]]:
    """[(actor, headers, status) ...] para T2-T6: 'E 403 · DO, DT, DM, AB 404'."""
    return [
        ("E", esc.h(integ, esc.e), 403),
        ("DO", esc.h(integ, esc.do), 404),
        ("DT", esc.h(integ, esc.dt), 404),
        ("DM", esc.h(integ, esc.dm, tenant=esc.tenant_b), 404),
        ("AB", esc.h(integ, esc.ab), 404),
    ]


def prohibidos_m(esc: Escuela, integ: Integ) -> list[tuple[str, dict[str, str], int]]:
    """[(actor, headers, status) ...] para M2-M4: 'E 403 · D 403 · AB 404'."""
    return [
        ("E", esc.h(integ, esc.e), 403),
        ("D", esc.h(integ, esc.d), 403),
        ("AB", esc.h(integ, esc.ab), 404),
    ]
