"""Ayudas de los tests del autorregistro — `docs/ESPEC_autorregistro.md` §3.

No empieza por `test_`: pytest no lo recolecta.

Reglas (las del login piloto): el cliente con `raise_server_exceptions=False`
(un 500 es una respuesta, y por tanto un `AssertionError`), las claves con
`.get()`, y lo observado en un dict que se compara ENTERO y va en el mensaje.
Todo es sintético: ningún correo, nombre ni contraseña de aquí existe.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from fastapi.testclient import TestClient

from src.main import app
from src.registro import limite
from src.registro.cuentas import get_cuentas_de_registro
from src.shared.models import TeacherGroup
from tests.cuentas_falsas import CuentasFalsas

client = TestClient(app, raise_server_exceptions=False)

CLAVE = "clave-sintetica-de-prueba"
AVISO = "2026-10-v1"
PENDIENTE = {"estado": "pendiente"}
NO_VALIDO = (403, {"detail": "codigo_no_valido"})
RUTA = "/auth/registro"


def cuerpo_json(r: httpx.Response) -> Any:
    try:
        return r.json()
    except ValueError:
        return None


def campo(r: httpx.Response, clave: str) -> Any:
    datos = cuerpo_json(r)
    return datos.get(clave) if isinstance(datos, dict) else None


def preparar(integ: Any) -> CuentasFalsas:
    """El doble de GoTrue en la dependencia de la ruta, y el límite en cero."""
    falsas = CuentasFalsas(sesiones=integ.Session)
    app.dependency_overrides[get_cuentas_de_registro] = lambda: falsas
    limite.reiniciar()
    return falsas


def soltar() -> None:
    """Quita el doble de la dependencia (el dict de overrides es global) y limpia el límite."""
    app.dependency_overrides.pop(get_cuentas_de_registro, None)
    limite.reiniciar()


@dataclass(frozen=True)
class Aula:
    """Una institución con un grupo, su profe y (si se pidió) el código en claro."""

    tenant: UUID
    slug: str
    grupo: UUID
    codigo_de_grupo: str
    profe: UUID
    codigo: str

    def doc(self, n: int) -> str:
        """El `documento_id` que el registro arma para la persona `n`."""
        return f"{self.slug}_{codigo_estudiantil(n)}"


def codigo_estudiantil(n: int) -> str:
    return f"22{n:05d}"


def crear_codigo(integ: Any, profe: UUID, grupo: UUID, **cuerpo: Any) -> httpx.Response:
    return client.post(f"/teachers/groups/{grupo}/codigo-inscripcion", json=cuerpo,
                       headers=integ.headers(profe))


def grupo_con_profe(integ: Any, tenant: UUID, nombre: str) -> tuple[UUID, UUID]:
    grupo = integ.crear_grupo(tenant, nombre)
    profe = integ.crear_perfil(tenant, rol="teacher")
    integ._insertar(TeacherGroup(tenant_id=tenant, teacher_id=profe, group_id=grupo))
    return grupo, profe


def aula(integ: Any, *, grupo: str = "G1", tenant: UUID | None = None,
         con_codigo: bool = True, **del_codigo: Any) -> Aula:
    """Siembra institución, grupo y profe; el código se crea por SU RUTA.

    El código en claro solo existe en la respuesta de crearlo (por eso no se
    siembra por SQL). `del_codigo`: `cupo` y `horas`.
    """
    tenant = tenant or integ.crear_tenant()
    slug = str(integ.valor("select slug from tenants where id = :t", t=tenant))
    gid, profe = grupo_con_profe(integ, tenant, grupo)
    codigo = ""
    if con_codigo:
        codigo = str(campo(crear_codigo(integ, profe, gid, **del_codigo), "codigo") or "")
    return Aula(tenant, slug, gid, grupo, profe, codigo)


def cuerpo(codigo: str, n: int = 1, /, **cambios: Any) -> dict[str, Any]:
    """El cuerpo válido de la persona sintética `n`; `cambios` pisa o quita (`...`)."""
    datos: dict[str, Any] = {
        "codigo": codigo, "nombre": f"Persona Sintética {n}",
        "correo": f"persona{n}@sintetico.test", "codigo_estudiantil": codigo_estudiantil(n),
        "contrasena": CLAVE, "mayor_de_edad": True, "aviso_version": AVISO,
    }
    datos.update(cambios)
    return {k: v for k, v in datos.items() if v is not ...}


def registrar(datos: dict[str, Any], **headers: str) -> httpx.Response:
    return client.post(RUTA, json=datos, headers=headers)


def estado_y_cuerpo(r: httpx.Response) -> tuple[int, Any]:
    return r.status_code, cuerpo_json(r)


def perfil_de(integ: Any, documento: str) -> UUID | None:
    valor = integ.valor("select id from profiles where documento_id = :d", d=documento)
    return None if valor is None else UUID(str(valor))


def contar(integ: Any, sql: str, **params: Any) -> int:
    return int(integ.valor(sql, **params) or 0)


def usos(integ: Any, grupo: UUID) -> int | None:
    """Los usos del código ACTIVO del grupo."""
    valor = integ.valor("select usos from codigos_inscripcion where group_id = :g and activo",
                        g=grupo)
    return None if valor is None else int(valor)


def solicitudes(integ: Any, **filtro: Any) -> list[tuple[int, str]]:
    """[(id, estado)] en orden de id; `filtro`: `group_id` o `profile_id`."""
    from sqlalchemy import text

    donde = " and ".join(f"{k} = :{k}" for k in filtro) or "true"

    async def _q() -> list[tuple[int, str]]:
        async with integ.Session() as db:
            r = await db.execute(text("select id, estado from solicitudes_inscripcion "
                                      f"where {donde} order by id"), filtro)
            return [(int(i), str(e)) for i, e in r.all()]

    return list(integ.run(_q()))


def estudiantes(integ: Any) -> int:
    """Perfiles con rol `student` (los que crea el registro o la matrícula)."""
    return contar(integ, "select count(*) from profiles where role = 'student'")


def membresia(integ: Any, perfil: UUID | None, tenant: UUID) -> tuple[Any, ...] | None:
    fila = integ.fila("select role, is_active, group_code, full_name from memberships "
                      "where profile_id = :p and tenant_id = :t", p=perfil, t=tenant)
    return None if fila is None else tuple(fila.values())


def decidir(integ: Any, quien: UUID, grupo: UUID, solicitud: int, accion: str,
            **headers: str) -> httpx.Response:
    return client.post(f"/teachers/groups/{grupo}/solicitudes/{solicitud}/{accion}",
                       headers={**integ.headers(quien), **headers})


def lista(integ: Any, quien: UUID, grupo: UUID) -> Any:
    return cuerpo_json(client.get(f"/teachers/groups/{grupo}/solicitudes",
                                  headers=integ.headers(quien)))
