"""Tramposos ZA1 a ZA10 del pase acotado — `docs/ESPEC_pase_acotado.md` §3.

Una versión ROTA a propósito, inyectada con monkeypatch en el módulo donde se
USA; se corre el cuerpo del test real y se exige `AssertionError` con el
mensaje del mecanismo (la diagonal: cada tramposo, su test). ZA1 es no-integ.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.anillo import service as pase_service
from src.shared import deps
from src.shared.config import settings
from tests.anillo import test_pase as tp
from tests.anillo import test_pase_unit as tu

Aplicar = Callable[[pytest.MonkeyPatch], None]

_VALIDATE_JWT = deps.validate_jwt


def _parche(objeto: Any, nombre: str, valor: Any) -> Aplicar:
    return lambda mp: mp.setattr(objeto, nombre, valor)


def _huella_reversible(pase: str) -> str:
    """ZA2: guarda el pase "codificado" (hex de sus bytes), no su sha256."""
    return pase.encode("utf-8").hex()[:64]


def _todas_las_membresias(filas: list[Any], tenant_id: Any) -> list[Any]:
    """ZA3: el carné lleva todas las instituciones de la persona."""
    return list(filas)


# ZA4: gastar sin exigir que siga sin usar (el pase sirve muchas veces).
_GASTAR_SIN_SOLO_USO = pase_service.SQL_GASTAR.replace(" AND usado_en IS NULL", "")


def _sin_mirar_la_audiencia(fila: Any, audiencia: str) -> bool:
    """ZA5: cualquier audiencia canjea cualquier pase."""
    return bool(fila["vigente"])


def _sin_mirar_el_vencimiento(fila: Any, audiencia: str) -> bool:
    """ZA6: un pase vencido sigue sirviendo."""
    return bool(fila["audiencia"] == audiencia)


async def _gastar_sin_commit_previo(db: AsyncSession, pase: str, audiencia: str) -> Any:
    """ZA7: gasta, pero el commit queda para después de las revisiones (un 403 lo deshace)."""
    fila = (await db.execute(text(pase_service.SQL_GASTAR),
                             {"h": pase_service.huella(pase)})).mappings().first()
    if fila is None or not pase_service.es_canjeable(fila, audiencia):
        await db.commit()
        raise HTTPException(status_code=401, detail=pase_service.PASE_INVALIDO)
    return pase_service.PaseGastado(profile_id=fila["profile_id"], tenant_id=fila["tenant_id"],
                                    audiencia=fila["audiencia"])


def _leer_y_luego_escribir() -> Callable[..., Any]:
    """ZA10: «leer y luego escribir». La barrera fuerza que las dos lecturas pasen
    antes de cualquier escritura: así la carrera ocurre siempre, no por suerte."""
    barrera = asyncio.Barrier(2)

    async def gastar(db: AsyncSession, pase: str, audiencia: str) -> Any:
        h = pase_service.huella(pase)
        fila = (await db.execute(text(
            "SELECT profile_id, tenant_id, audiencia, (expira_en > now()) AS vigente "
            "FROM anillo_pases WHERE hash = :h AND usado_en IS NULL"),
            {"h": h})).mappings().first()
        await barrera.wait()
        await db.execute(text("UPDATE anillo_pases SET usado_en = now() WHERE hash = :h"),
                         {"h": h})
        await db.commit()
        if fila is None or not pase_service.es_canjeable(fila, audiencia):
            raise HTTPException(status_code=401, detail=pase_service.PASE_INVALIDO)
        return pase_service.PaseGastado(profile_id=fila["profile_id"],
                                        tenant_id=fila["tenant_id"], audiencia=fila["audiencia"])

    return gastar


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[..., None], str]] = {
    "ZA1": (_parche(pase_service, "BYTES_AL_AZAR", 16), tu.test_pa1_forma_del_pase_y_su_huella,
            r"PA1: \{'con_la_forma': 0"),
    "ZA2": (_parche(pase_service, "huella", _huella_reversible), tp.test_pa2_emitir,
            r"'hash_es_sha256_del_pase': False"),
    "ZA3": (_parche(pase_service, "solo_la_institucion", _todas_las_membresias),
            tp.test_pa3_canjear_da_el_carne_minimo,
            r"'membresias': \[\(False, 'student', 'G-A'\), \(True, 'student', 'G-B'\)\]"),
    "ZA4": (_parche(pase_service, "SQL_GASTAR", _GASTAR_SIN_SOLO_USO), tp.test_pa4_un_solo_uso,
            r"PA4: \{'primero': 200, 'segundo': \(200, None\)"),
    "ZA5": (_parche(pase_service, "es_canjeable", _sin_mirar_la_audiencia),
            tp.test_pa5_audiencia, r"PA5: \{'cruzado': \(200, None\)"),
    "ZA6": (_parche(pase_service, "es_canjeable", _sin_mirar_el_vencimiento),
            tp.test_pa6_vencido, r"PA6: \{'vencido': \(200, None\)"),
    "ZA7": (_parche(pase_service, "gastar", _gastar_sin_commit_previo),
            tp.test_pa7_revisiones_de_la_cuenta_y_el_gasto,
            r"'suspendida': \{'primero': \(403, 'account_suspended'\), "
            r"'reparada_el_mismo_pase': \(200, None\)"),
    "ZA9": (_parche(settings, "anillo_pases_vivos_max", 1000), tp.test_pa9_tope_de_pases_vivos,
            r"'el_11': \(201, None\)"),
}
SIN_BASE = ("ZA1",)


def correr(test_real: Callable[..., None], disponibles: dict[str, Any]) -> None:
    pedidas = inspect.signature(test_real).parameters
    test_real(**{nombre: disponibles[nombre] for nombre in pedidas})


@pytest.mark.integ
@pytest.mark.parametrize("clave", [c for c in TRAMPOSOS if c not in SIN_BASE])
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        correr(test_real, {"integ": integ, "monkeypatch": monkeypatch})


@pytest.mark.parametrize("clave", SIN_BASE)
def test_tramposo_puro_pone_rojo_su_test(monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        correr(test_real, {"monkeypatch": monkeypatch})


@pytest.mark.integ
def test_za8_tramposo_el_pase_como_sesion(integ, monkeypatch) -> None:
    """ZA8: `validate_jwt` acepta un pase vivo como si fuera la sesión de su dueño.

    La búsqueda corre en otro hilo: `validate_jwt` es síncrona y la app la llama
    dentro de su propio bucle de eventos (no se puede anidar `asyncio.run`).
    """
    def como_sesion(token: str) -> dict[str, Any]:
        if token.startswith(pase_service.PREFIJO):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as hilo:
                dueno = hilo.submit(
                    integ.valor, "select profile_id::text from anillo_pases where hash = :h "
                    "and usado_en is null and expira_en > now()", h=pase_service.huella(token),
                ).result()
            if dueno:
                return {"sub": dueno, "aud": "authenticated"}
        return dict(_VALIDATE_JWT(token))

    monkeypatch.setattr(deps, "validate_jwt", como_sesion)
    with pytest.raises(AssertionError, match=r"'no_dieron_401': \{'(GET|POST|PUT|PATCH|DELETE) /"):
        tp.test_pa8_el_pase_no_sirve_para_nada_mas(integ)


@pytest.mark.integ
def test_za10_tramposo_leer_y_luego_escribir(integ, monkeypatch) -> None:
    """ZA10: con «leer y luego escribir», los dos canjes simultáneos ganan."""
    monkeypatch.setattr(pase_service, "gastar", _leer_y_luego_escribir())
    with pytest.raises(AssertionError,
                       match=r"PA10: \{'resultados': \['gastado', 'gastado'\]"):
        tp.test_pa10_dos_canjes_a_la_vez(integ)
