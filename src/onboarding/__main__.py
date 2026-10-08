"""CLI del operador — `docs/ESPEC_login_piloto.md` §1.7.

    python -m src.onboarding alta --nombre "<institución>" --slug <slug> \\
        --monedas <n> --csv <ruta> --salida <ruta>
    python -m src.onboarding restablecer --slug <slug> --documento <doc> --salida <ruta>
    python -m src.onboarding suspender --slug <slug> --documento <doc> [--solo-institucion]
    python -m src.onboarding reactivar --slug <slug> --documento <doc>
    python -m src.onboarding recargar --slug <slug> --monedas <n> \\
        --operador "<quién>" --motivo "<por qué>" --referencia <id único>

`recargar` (ESPEC_economia_oleada0 §1.6) EMITE monedas a la bolsa de la
institución: todo o nada, idempotente por `--referencia`, y deja en el libro
quién y cuándo. Solo toca la base, como `suspender`.

Credenciales, SOLO por variable de entorno: `DATABASE_URL`, `GOTRUE_URL` y
`SUPABASE_SERVICE_ROLE_KEY`. La clave de servicio la usa únicamente esta CLI.

Salida del proceso:
  0  todo se hizo (o ya estaba hecho: es idempotente).
  1  algo no se hizo; el resumen JSON dice qué, con su fila.
  2  argumentos inválidos, falta configuración, o `--salida` cae dentro del
     repo del backend (no se escribe NADA: ni base, ni cuentas, ni archivo).
     En `recargar`: falta `--operador`, `--motivo` o `--referencia`, o
     `--monedas` es <= 0 o pasa de `BOLSA_RECARGA_MAXIMA` (la base ni se abre).

Imprime en stdout un resumen JSON, sin contraseñas. Las contraseñas temporales
solo van al archivo `--salida`.

ES PRODUCCIÓN cuando se corre con datos reales: necesita el sí de Christiam
(`docs/PRODUCCION_030.md`, "Antes del piloto con estudiantes reales").
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.onboarding.alta import Sesiones, correr_alta
from src.onboarding import recarga
from src.onboarding.cuentas import CuentasAdmin, ErrorDeConfiguracion, gotrue_admin_del_entorno
from src.onboarding.restablecer import correr_restablecer
from src.onboarding.salida import dentro_del_repo
from src.onboarding.suspension import correr_suspension

SALIDA_OK, SALIDA_CON_ERRORES, SALIDA_NO_CORRIO = 0, 1, 2
# Órdenes que solo tocan la base: no usan GoTrue ni escriben credenciales.
SOLO_BASE = ("suspender", "reactivar", "recargar")


def _monedas(texto: str) -> int:
    valor = int(texto)
    if valor < 0:
        raise argparse.ArgumentTypeError("--monedas no puede ser negativo")
    return valor


def argumentos(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m src.onboarding",
                                description="Alta de instituciones y personas (operador).")
    sub = p.add_subparsers(dest="orden", required=True)
    alta = sub.add_parser("alta", help="crea la institución, las personas y sus cuentas")
    alta.add_argument("--nombre", required=True, help="nombre visible de la institución")
    alta.add_argument("--slug", required=True, help="identificador corto, p. ej. sena")
    # Sin valor por defecto a propósito: es la emisión de monedas (la decide Christiam).
    alta.add_argument("--monedas", required=True, type=_monedas,
                      help="saldo inicial de la billetera; solo se usa si la institución nace")
    alta.add_argument("--csv", required=True, type=Path,
                      help="nombre,correo,documento,tipo_documento,grupo,rol")
    alta.add_argument("--salida", required=True, type=Path,
                      help="archivo de credenciales (fuera del repo); se agrega al final")
    rest = sub.add_parser("restablecer", help="contraseña temporal nueva para una persona")
    rest.add_argument("--slug", required=True)
    rest.add_argument("--documento", required=True, help="el documento_id tal como está en la base")
    rest.add_argument("--salida", required=True, type=Path)
    susp = sub.add_parser("suspender", help="corta el acceso de una persona (403 en todo)")
    susp.add_argument("--solo-institucion", action="store_true",
                      help="desactiva solo la membresía; el perfil (global) no se toca")
    react = sub.add_parser("reactivar", help="deshace una suspensión")
    for orden in (susp, react):
        orden.add_argument("--slug", required=True)
        orden.add_argument("--documento", required=True,
                           help="el documento_id tal como está en la base")
    rec = sub.add_parser("recargar", help="emite monedas a la bolsa de la institución")
    # Ninguno es `required` para argparse: los valida `recarga.motivo_de_rechazo`
    # (una función pura, con su test y su tramposo) y `main` responde 2.
    rec.add_argument("--slug")
    rec.add_argument("--monedas", type=int, help="cuántas monedas se emiten (mayor que 0)")
    rec.add_argument("--operador", help="quién hace la recarga (queda en el libro)")
    rec.add_argument("--motivo", help="por qué (queda en el libro)")
    rec.add_argument("--referencia",
                     help="id único de esta recarga: repetirla con la misma no suma dos veces")
    return p.parse_args(argv)


def sesiones_del_entorno() -> Sesiones:
    """Sesiones contra `DATABASE_URL`, sin pasar por `src.shared.config`.

    La CLI no necesita el secreto JWT ni el resto de la configuración web. La
    URL se normaliza igual que `Settings._normalize_async_scheme`.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise ErrorDeConfiguracion("falta la variable de entorno DATABASE_URL")
    for viejo in ("postgresql://", "postgres://"):
        if url.startswith(viejo):
            url = url.replace(viejo, "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, poolclass=NullPool)
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False,
                              autoflush=False)


async def _correr(a: argparse.Namespace, cuentas: CuentasAdmin | None,
                  sesiones: Sesiones) -> tuple[dict[str, Any], bool]:
    """(resumen, ¿hubo errores?)."""
    if a.orden == "recargar":
        datos = await recarga.correr_recarga(
            slug=a.slug, monedas=a.monedas, operador=a.operador, motivo=a.motivo,
            referencia=a.referencia, sesiones=sesiones)
        return datos, "error" in datos
    if a.orden in SOLO_BASE:
        datos = await correr_suspension(
            slug=a.slug, documento_id=a.documento, activo=a.orden == "reactivar",
            solo_institucion=getattr(a, "solo_institucion", False), sesiones=sesiones)
        return datos, "error" in datos
    assert cuentas is not None  # `main` ya lo exigió para estas órdenes
    if a.orden == "alta":
        resumen = await correr_alta(nombre=a.nombre, slug=a.slug, monedas=a.monedas,
                                    contenido=a.csv.read_bytes(), salida=a.salida,
                                    cuentas=cuentas, sesiones=sesiones)
        return resumen.como_dict(), bool(resumen.errores)
    datos = await correr_restablecer(slug=a.slug, documento_id=a.documento, salida=a.salida,
                                     cuentas=cuentas, sesiones=sesiones)
    return datos, "error" in datos


def main(argv: Sequence[str] | None = None, *, cuentas: CuentasAdmin | None = None,
         sesiones: Sesiones | None = None) -> int:
    """Punto de entrada. `cuentas` y `sesiones` se inyectan en los tests."""
    a = argumentos(sys.argv[1:] if argv is None else argv)
    # Antes de TODO lo demás: una contraseña nunca debe poder caer en el repo.
    con_credenciales = a.orden not in SOLO_BASE
    if con_credenciales and dentro_del_repo(a.salida):
        print("--salida no puede quedar dentro de un repositorio git: no se escribió nada",
              file=sys.stderr)
        return SALIDA_NO_CORRIO
    if a.orden == "alta" and not a.csv.is_file():
        print(f"no existe el CSV {a.csv}", file=sys.stderr)
        return SALIDA_NO_CORRIO
    try:
        if a.orden == "recargar":
            rechazo = recarga.motivo_de_rechazo(
                slug=a.slug, monedas=a.monedas, operador=a.operador, motivo=a.motivo,
                referencia=a.referencia, maximo=recarga.recarga_maxima())
            if rechazo is not None:
                # Antes de abrir la base: una emisión mal pedida no toca nada.
                print(f"recargar: {rechazo}", file=sys.stderr)
                return SALIDA_NO_CORRIO
        if con_credenciales and cuentas is None:
            cuentas = gotrue_admin_del_entorno()
        sesiones = sesiones if sesiones is not None else sesiones_del_entorno()
    except ErrorDeConfiguracion as exc:
        print(str(exc), file=sys.stderr)
        return SALIDA_NO_CORRIO
    resumen, con_errores = asyncio.run(_correr(a, cuentas, sesiones))
    print(json.dumps(resumen, ensure_ascii=False))
    return SALIDA_CON_ERRORES if con_errores else SALIDA_OK


if __name__ == "__main__":
    raise SystemExit(main())
