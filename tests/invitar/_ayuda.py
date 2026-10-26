"""Ayudas y el doble de GoTrue de las pruebas de invitar profes — `docs/ESPEC_invitar_profe.md` §4.

No empieza por `test_`: pytest no lo recolecta.

`GoTrueFalso` imita lo MEDIDO en el banco (§1.1):
  - `crear_invitado` con un correo que ya es de otra cuenta → `correo_en_uso` (P8, sin
    distinguir mayúsculas);
  - `invitar` a una cuenta sin confirmar → `enviada` (P2, P3: también enseguida); a una
    confirmada → `ya_confirmada` (P7); a un correo SIN cuenta → la CREA con un id
    propio (P9), para que un tramposo que se salte la regla se vea;
  - `recuperar` → `enviada`;
  - `fallar = True` → toda llamada lanza `ErrorCuenta`, como un GoTrue caído.
Guarda cada llamada en `llamadas`, en orden. Todo es sintético.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.auth.cuentas import get_cambio_de_clave
from src.main import app
from src.onboarding.cuentas import CORREO_EN_USO, CREADA, ENVIADA, YA_CONFIRMADA, ErrorCuenta
from src.registro.cuentas import get_cuentas_de_invitacion
from src.shared.models import TeacherGroup

client = TestClient(app, raise_server_exceptions=False)
RUTA = "/admin/invitaciones"


class GoTrueFalso:
    def __init__(self) -> None:
        self.cuentas: dict[UUID, dict[str, Any]] = {}
        self.llamadas: list[tuple[str, ...]] = []
        self.fallar = False

    def _quizas_falla(self) -> None:
        if self.fallar:
            raise ErrorCuenta("fallo sintético de GoTrue")

    def _id_de(self, correo: str) -> UUID | None:
        for cid, c in self.cuentas.items():
            if c["correo"] == correo.lower():
                return cid
        return None

    def sembrar(self, correo: str, *, confirmada: bool = True) -> UUID:
        """Una cuenta que ya existe (p. ej. de otra institución)."""
        cid = uuid4()
        self.cuentas[cid] = {"correo": correo.lower(), "confirmada": confirmada}
        return cid

    async def estado_de_cuenta(self, id: UUID) -> tuple[str, bool] | None:
        self.llamadas.append(("estado_de_cuenta", str(id)))
        self._quizas_falla()
        c = self.cuentas.get(id)
        return None if c is None else (c["correo"], c["confirmada"])

    async def crear_invitado(self, id: UUID, correo: str) -> str:
        self.llamadas.append(("crear_invitado", str(id), correo))
        self._quizas_falla()
        if self._id_de(correo) is not None:
            return CORREO_EN_USO
        self.cuentas[id] = {"correo": correo.lower(), "confirmada": False}
        return CREADA

    async def invitar(self, correo: str) -> str:
        self.llamadas.append(("invitar", correo))
        self._quizas_falla()
        cid = self._id_de(correo)
        if cid is None:  # P9: GoTrue crea la cuenta con un id que elige él
            self.cuentas[uuid4()] = {"correo": correo.lower(), "confirmada": False}
            return ENVIADA
        return YA_CONFIRMADA if self.cuentas[cid]["confirmada"] else ENVIADA

    async def recuperar(self, correo: str) -> str:
        self.llamadas.append(("recuperar", correo))
        self._quizas_falla()
        return ENVIADA

    def de_correo(self, nombre: str) -> list[tuple[str, ...]]:
        """Las llamadas de correo (`invitar`/`recuperar`), para contar envíos."""
        return [c for c in self.llamadas if c[0] == nombre]


class CambioFalso:
    """El doble de `PUT /user` de GoTrue para `POST /auth/contrasena`: siempre acepta."""

    async def cambiar(self, token: str, nueva: str) -> None:
        return None


def preparar() -> GoTrueFalso:
    falso = GoTrueFalso()
    app.dependency_overrides[get_cuentas_de_invitacion] = lambda: falso
    app.dependency_overrides[get_cambio_de_clave] = lambda: CambioFalso()
    return falso


def soltar() -> None:
    """El dict de overrides es global: `test_h3_sin_overrides_de_dependencias_filtrados`."""
    app.dependency_overrides.pop(get_cuentas_de_invitacion, None)
    app.dependency_overrides.pop(get_cambio_de_clave, None)


@dataclass(frozen=True)
class Colegio:
    tenant: UUID
    admin: UUID
    grupo: UUID
    codigo: str


def colegio(integ: Any, codigo: str = "G1") -> Colegio:
    tenant = integ.crear_tenant()
    admin = integ.crear_perfil(tenant, rol="admin")
    grupo = integ.crear_grupo(tenant, codigo)
    return Colegio(tenant, admin, grupo, codigo)


def profe_de(integ: Any, c: Colegio) -> UUID:
    profe = integ.crear_perfil(c.tenant, rol="teacher")
    integ._insertar(TeacherGroup(tenant_id=c.tenant, teacher_id=profe, group_id=c.grupo))
    return profe


def cuerpo(c: Colegio, n: int = 1, **cambios: Any) -> dict[str, Any]:
    datos: dict[str, Any] = {"nombre": f"Profe Sintética {n}",
                             "correo": f"profe{n}@sintetico.test", "group_id": str(c.grupo)}
    datos.update(cambios)
    return {k: v for k, v in datos.items() if v is not ...}


def invitar(integ: Any, c: Colegio, datos: dict[str, Any],
            quien: UUID | None = None) -> httpx.Response:
    return client.post(RUTA, json=datos, headers=integ.headers(quien or c.admin))


def listar(integ: Any, quien: UUID) -> httpx.Response:
    return client.get(RUTA, headers=integ.headers(quien))


def reenviar(integ: Any, quien: UUID, inv: Any) -> httpx.Response:
    return client.post(f"{RUTA}/{inv}/reenviar", headers=integ.headers(quien))


def json_de(r: httpx.Response) -> Any:
    try:
        return r.json()
    except ValueError:
        return None


def ejecutar(integ: Any, sql: str, **params: Any) -> None:
    """Un UPDATE o DELETE commiteado (las fábricas de `Integ` solo leen o insertan)."""
    async def _e() -> None:
        async with integ.Session() as db:
            await db.execute(text(sql), params)
            await db.commit()
    integ.run(_e())


def perfil_de(integ: Any, inv_id: int) -> UUID:
    return UUID(str(integ.valor(
        "select profile_id from invitaciones_docente where id = :i", i=inv_id)))


def sin_variables(cuerpo_json: dict[str, Any]) -> dict[str, Any]:
    """El cuerpo sin lo que cambia de una invitación a otra (id, nombre, correo, fecha)."""
    return {k: v for k, v in cuerpo_json.items()
            if k not in ("id", "nombre", "correo", "enviada_en")}


def filas_de(integ: Any, profile_id: UUID) -> dict[str, Any]:
    """Qué filas tiene ese perfil: perfil, membresía, grupo, invitación (para comparar casos)."""
    return {
        "perfil": integ.fila("select role, force_password_reset, full_name, pin_hash, "
                             "left(documento_id, 4) as prefijo from profiles where id = :p",
                             p=profile_id),
        "membresias": integ.valor("select count(*) from memberships where profile_id = :p "
                                  "and role = 'teacher' and is_active", p=profile_id),
        "grupos": integ.valor("select count(*) from teacher_groups where teacher_id = :p",
                              p=profile_id),
        "invitaciones": integ.valor("select count(*) from invitaciones_docente "
                                    "where profile_id = :p", p=profile_id),
    }
