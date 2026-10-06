"""Arnés compartido por el humo HP1 y la réplica RP1 — `docs/ESPEC_login_piloto.md` §4.

No empieza por `test_`: pytest no lo recolecta.

Aquí el token de cada persona lleva como `sub` el `id` de SU CUENTA en el doble
de GoTrue (`CuentasFalsas.id_de(correo)`), no `profiles.id`: es lo que pasa en
el piloto (se entra con correo y contraseña, y GoTrue pone su `id` en el JWT).
Si la cuenta no naciera con el `id` del perfil, aquí nadie entraría.

Todo es sintético: nombres, correos (`@engrama.test`) y documentos al azar.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
from fastapi.testclient import TestClient

from src.main import app
from tests.cuentas_falsas import CuentasFalsas
from tests.onboarding._ayuda import Fila

client = TestClient(app, raise_server_exceptions=False)

CLAVE_NUEVA = "Sintetica-2026-ok"
LETRAS = ("A", "B", "C")


def slug_de(letra: str) -> str:
    return f"inst-{letra.lower()}"


def correo_de(quien: str, letra: str) -> str:
    return f"{quien}.{letra.lower()}@engrama.test"


def filas_de(letra: str, docs: list[str], *, compartido: str | None = None,
             con_codigo: int | None = None) -> list[Fila]:
    """1 admin, 1 profe y 4 estudiantes en el grupo `G<letra>`; `docs` trae 6 documentos.

    `compartido`: el documento de D, el profe que también está en otra
    institución. `con_codigo`: cuál estudiante (0-3) usa `CODIGO` en vez de CC.
    """
    grupo = f"G{letra}"
    filas: list[Fila] = [
        (f"Admin {letra}", correo_de("admin", letra), docs[0], "CC", "", "admin"),
        (f"Profe {letra}", correo_de("profe", letra), docs[1], "CC", grupo, "profe"),
    ]
    for i in range(4):
        tipo = "CODIGO" if con_codigo == i else "CC"
        filas.append((f"Estudiante {letra}{i + 1}", correo_de(f"est{i + 1}", letra),
                      docs[2 + i], tipo, grupo, "estudiante"))
    if compartido is not None:
        filas.append((f"Profe D en {letra}", correo_de("d", letra), compartido, "CC", grupo,
                      "profe"))
    return filas


def _json(r: httpx.Response) -> dict[str, Any]:
    try:
        datos = r.json()
    except ValueError:
        return {}
    return datos if isinstance(datos, dict) else {}


def cabeceras(integ: Any, doble: CuentasFalsas, correo: str,
              tenant: Any = None) -> dict[str, str]:
    """El Bearer de quien entra con `correo`: `sub` = el `id` de su cuenta en GoTrue."""
    h: dict[str, str] = integ.headers(doble.id_de(correo))
    if tenant is not None:
        h["X-Tenant-ID"] = str(tenant)
    return h


def me(integ: Any, doble: CuentasFalsas, correo: str, tenant: Any = None,
       ) -> tuple[int, dict[str, Any]]:
    r = client.get("/auth/me", headers=cabeceras(integ, doble, correo, tenant))
    return r.status_code, _json(r)


def retos(integ: Any, doble: CuentasFalsas, correo: str, tenant: Any = None) -> int:
    return client.get("/challenges/", headers=cabeceras(integ, doble, correo, tenant)).status_code


def cambiar_clave(integ: Any, doble: CuentasFalsas, correo: str) -> int:
    return client.post("/auth/contrasena", headers=cabeceras(integ, doble, correo),
                       json={"nueva": CLAVE_NUEVA}).status_code


def tenants(integ: Any) -> dict[str, UUID]:
    """`A`, `B`, `C` -> el id del tenant (los que existan)."""
    encontrados: dict[str, UUID] = {}
    for letra in LETRAS:
        valor = integ.valor("select id from tenants where slug = :s", s=slug_de(letra))
        if valor is not None:
            encontrados[letra] = UUID(str(valor))
    return encontrados


def letra_de(ids: dict[str, UUID], tenant_id: Any) -> str | None:
    """El id de un tenant -> su letra (para escribir etiquetas, nunca ids)."""
    for letra, tid in ids.items():
        if str(tid) == str(tenant_id):
            return letra
    return None


def cuenta_igual_perfil(integ: Any, doble: CuentasFalsas) -> int:
    """Cuántas cuentas del doble tienen como `id` un `profiles.id` (el vínculo)."""
    return sum(1 for cuenta_id in doble.cuentas
               if integ.valor("select count(*) from profiles where id = :p", p=cuenta_id) == 1)
