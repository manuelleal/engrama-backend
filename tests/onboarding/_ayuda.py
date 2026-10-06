"""Arnés de los tests del alta — `docs/ESPEC_login_piloto.md` §3 (OP1-OP8, HP1, RP1-RP2).

No empieza por `test_`: pytest no lo recolecta.

La CLI se corre SIEMPRE por su `main(argv, cuentas=, sesiones=)`: los mismos
argumentos que escribe el operador, con el doble de GoTrue y las sesiones del
fixture. Lo que imprime se lee con `capsys` (el resumen JSON es su contrato).
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from src.onboarding.__main__ import main
from src.shared.models import CoinWallet, Tenant
from tests.cuentas_falsas import CuentasFalsas

CABECERA = ("nombre", "correo", "documento", "tipo_documento", "grupo", "rol")
# (nombre, correo, documento, tipo_documento, grupo, rol)
Fila = tuple[str, str, str, str, str, str]


@dataclass(frozen=True)
class Corrida:
    codigo: int
    resumen: dict[str, Any]
    stdout: str


def escribir_csv(carpeta: Path, nombre: str, filas: list[Fila], *, sep: str = ",",
                 encoding: str = "utf-8") -> Path:
    ruta = carpeta / nombre
    lineas = [sep.join(CABECERA), *(sep.join(f) for f in filas)]
    ruta.write_bytes(("\n".join(lineas) + "\n").encode(encoding))
    return ruta


def _corrida(capsys: Any, argv: list[str], integ: Any, doble: CuentasFalsas) -> Corrida:
    capsys.readouterr()  # lo anterior no cuenta
    codigo = main(argv, cuentas=doble, sesiones=integ.Session)
    stdout = capsys.readouterr().out
    try:
        resumen = json.loads(stdout.strip().splitlines()[-1]) if stdout.strip() else {}
    except ValueError:
        resumen = {}
    return Corrida(codigo, resumen if isinstance(resumen, dict) else {}, stdout)


def envejecer_membresias(integ: Any) -> None:
    """Todas las membresías que ya existen pasan a ser 1 hora más viejas.

    Se llama ANTES de cada `alta`: lo que cree esa corrida queda al menos una
    hora después de lo anterior, así que "la membresía más antigua" (el
    colegio por defecto) no depende de que dos `now()` seguidos salgan en
    orden. El reloj del contenedor de pruebas retrocede hasta 1,95 s.
    """
    from sqlalchemy import text

    async def _envejecer() -> None:
        async with integ.engine.begin() as conn:
            await conn.execute(text(
                "update memberships set created_at = created_at - interval '1 hour'"))

    integ.run(_envejecer())


def alta(integ: Any, doble: CuentasFalsas, capsys: Any, *, slug: str, csv_: Path,
         salida: Path, monedas: int = 1000, nombre: str | None = None) -> Corrida:
    envejecer_membresias(integ)
    return _corrida(capsys, [
        "alta", "--nombre", nombre or f"Institución Sintética {slug}", "--slug", slug,
        "--monedas", str(monedas), "--csv", str(csv_), "--salida", str(salida),
    ], integ, doble)


def restablecer(integ: Any, doble: CuentasFalsas, capsys: Any, *, slug: str, documento: str,
                salida: Path) -> Corrida:
    return _corrida(capsys, ["restablecer", "--slug", slug, "--documento", documento,
                             "--salida", str(salida)], integ, doble)


def leer_salida(ruta: Path) -> list[dict[str, str]]:
    """Las filas del archivo de credenciales ([] si no existe)."""
    if not ruta.exists():
        return []
    with ruta.open(encoding="utf-8", newline="") as archivo:
        return list(csv.DictReader(archivo))


def cabecera_de(ruta: Path) -> list[str]:
    if not ruta.exists():
        return []
    with ruta.open(encoding="utf-8", newline="") as archivo:
        return next(csv.reader(archivo), [])


def contar(integ: Any, tabla_y_filtro: str, **params: Any) -> int:
    return int(integ.valor(f"select count(*) from {tabla_y_filtro}", **params))


def perfil_de(integ: Any, documento: str) -> UUID | None:
    valor = integ.valor("select id from profiles where documento_id = :d", d=documento)
    return None if valor is None else UUID(str(valor))


def bandera(integ: Any, documento: str) -> Any:
    return integ.valor("select force_password_reset from profiles where documento_id = :d",
                       d=documento)


def poner_bandera(integ: Any, documento: str, valor: bool) -> None:
    from tests.seguridad.veredictos import sembrar

    sembrar(integ, "update profiles set force_password_reset = :v where documento_id = :d",
            v=valor, d=documento)


def sembrar_institucion(integ: Any, slug: str, *, pool: int = 1000) -> UUID:
    """Un tenant con `slug` conocido y su billetera, por la base (ERR-9)."""
    from uuid import uuid4

    tid = uuid4()
    integ._insertar(
        Tenant(id=tid, name=f"Institución Sintética {slug}", slug=slug, coin_pool=pool),
        CoinWallet(tenant_id=tid, owner_type="tenant", owner_id=tid, currency="COIN",
                   balance=pool),
    )
    return tid
