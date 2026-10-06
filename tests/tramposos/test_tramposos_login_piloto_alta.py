"""Tramposos (integ) del ALTA del login piloto — `docs/ESPEC_login_piloto.md` §3.

Mismo patrón que `test_tramposos_login_piloto.py` (ZP2-ZP9, ZP14, ZP15): una
versión ROTA a propósito, inyectada con monkeypatch en el módulo donde se USA;
se corre el cuerpo del test real y se exige `AssertionError` con el mensaje
del mecanismo. Aquí se automatiza la DIAGONAL (la negrita de §3); la matriz
completa se mide aparte (ERR-15, 19 y 23).

  ZP1   el alta llama a `crear` SIN `id` (GoTrue elige el `sub`)       -> OP2
  ZP11  `asegurar_institucion` recarga la billetera en cada corrida    -> OP1
  ZP12  commit por fila, sin validar antes todo el CSV                 -> OP5
  ZP13  el alta no llama a `buscar` y siempre crea                     -> OP3 y OP4
  ZP17  `restablecer` no pone la bandera                               -> OP7
  ZP18  el alta pone la bandera también a las cuentas que ya existían  -> OP3
  ZP19  orden invertido: `crear` primero y la bandera después (H-3)    -> OP8

ZP16 (no-integ) vive en `test_tramposos_login_piloto_unit.py`.

Viven aparte de `test_tramposos_login_piloto.py` porque los tests del alta
piden `tmp_path` y `capsys`, y para que ningún archivo pase de 400 líneas.

ZP1, ZP13, ZP18 y ZP19 rompen `alta.asegurar_cuenta`, la única función que
decide qué se le pide a GoTrue y en qué orden. ZP1 y ZP13 la llaman con un
puerto que miente (sin `id`, o sin `buscar`): así el resto de la función es el
código real y el tramposo no se desactualiza si ella cambia.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.onboarding import alta as alta_mod
from src.onboarding import restablecer as restablecer_mod
from src.onboarding.csv_personas import FilaPersona
from src.shared.models import CoinWallet
from tests.onboarding import test_alta as op

pytestmark = pytest.mark.integ

Aplicar = Callable[[pytest.MonkeyPatch], None]

_CUENTA_BUENA = alta_mod.asegurar_cuenta
_INSTITUCION_BUENA = alta_mod.asegurar_institucion
_LEER_BUENO = alta_mod.leer_csv


# =============================================================================
# ZP1, ZP13 — el puerto que miente
# =============================================================================
class _Puerto:
    """Delega en el puerto real todo lo que la subclase no rompe."""

    def __init__(self, real: Any) -> None:
        self._real = real

    def __getattr__(self, nombre: str) -> Any:
        return getattr(self._real, nombre)


class _SinId(_Puerto):
    """ZP1: `crear` no manda el `id`: la cuenta nace con el `sub` que elija GoTrue."""

    async def crear(self, _id: UUID | None, correo: str, clave: str) -> str:
        resultado: str = await self._real.crear(None, correo, clave)
        return resultado


class _SinBuscar(_Puerto):
    """ZP13: nunca hay cuenta previa, así que siempre se intenta crear."""

    async def buscar(self, _id: UUID) -> str | None:
        return None


async def _crea_sin_id(sesiones: Any, cuentas: Any, perfil_id: UUID, correo: str,
                       clave: str) -> str:
    return await _CUENTA_BUENA(sesiones, _SinId(cuentas), perfil_id, correo, clave)


async def _siempre_crea(sesiones: Any, cuentas: Any, perfil_id: UUID, correo: str,
                        clave: str) -> str:
    return await _CUENTA_BUENA(sesiones, _SinBuscar(cuentas), perfil_id, correo, clave)


# =============================================================================
# ZP18, ZP19 — la bandera donde no va, o cuando no va
# =============================================================================
async def _marca_tambien_a_las_existentes(sesiones: Any, cuentas: Any, perfil_id: UUID,
                                          correo: str, clave: str) -> str:
    """ZP18: la bandera a TODOS, también a quien ya cambió su contraseña."""
    await alta_mod.marcar_clave_temporal(sesiones, perfil_id)
    return await _CUENTA_BUENA(sesiones, cuentas, perfil_id, correo, clave)


async def _cuenta_antes_que_bandera(sesiones: Any, cuentas: Any, perfil_id: UUID,
                                    correo: str, clave: str) -> str:
    """ZP19: `crear` primero y la bandera después (el orden que falla abierto)."""
    if await cuentas.buscar(perfil_id) is not None:
        return await _CUENTA_BUENA(sesiones, cuentas, perfil_id, correo, clave)
    resultado: str = await cuentas.crear(perfil_id, correo, clave)
    await alta_mod.marcar_clave_temporal(sesiones, perfil_id)
    return resultado


# =============================================================================
# ZP11 — la billetera se recarga
# =============================================================================
async def _institucion_recarga(db: AsyncSession, nombre: str, slug: str,
                               monedas: int) -> tuple[Any, bool]:
    tenant, creada = await _INSTITUCION_BUENA(db, nombre, slug, monedas)
    if not creada:
        tenant.coin_pool = tenant.coin_pool + monedas
        await db.execute(
            update(CoinWallet)
            .where(CoinWallet.owner_type == "tenant", CoinWallet.owner_id == tenant.id)
            .values(balance=CoinWallet.balance + monedas))
    return tenant, creada


# =============================================================================
# ZP12 — commit por fila, sin validar antes todo el CSV
# =============================================================================
def _leer_sin_frenar(contenido: bytes, slug: str) -> tuple[list[FilaPersona], list[Any]]:
    """Las filas buenas siguen adelante aunque haya filas malas."""
    return _LEER_BUENO(contenido, slug)[0], []


async def _commit_por_fila(db: AsyncSession, nombre: str, slug: str, monedas: int,
                           filas: list[FilaPersona], resumen: Any) -> dict[str, UUID]:
    tenant, resumen.institucion_creada = await alta_mod.asegurar_institucion(
        db, nombre, slug, monedas)
    await db.commit()
    perfiles: dict[str, UUID] = {}
    for f in filas:
        try:
            perfiles[f.documento_id] = await alta_mod.sembrar_fila(db, tenant, f, resumen)
        except HTTPException as exc:
            raise alta_mod.ErrorDeAlta(f.fila, str(exc.detail)) from exc
        await db.commit()
    return perfiles


def _sin_todo_o_nada(mp: pytest.MonkeyPatch) -> None:
    mp.setattr(alta_mod, "leer_csv", _leer_sin_frenar)
    mp.setattr(alta_mod, "escribir_en_base", _commit_por_fila)


# =============================================================================
# ZP17 — restablecer sin la bandera
# =============================================================================
async def _no_marca(_sesiones: Any, _perfil_id: UUID) -> None:
    """La clave se cambia, pero nadie obliga a cambiarla después."""


def _parche(objetivo: Any, nombre: str, valor: Any) -> Aplicar:
    return lambda mp: mp.setattr(objetivo, nombre, valor)


# =============================================================================
# Registro: id -> (cómo romper, [(test real, mensaje con el que debe caer)])
# =============================================================================
TRAMPOSOS: dict[str, tuple[Aplicar, list[tuple[Callable[..., None], str]]]] = {
    "ZP1": (_parche(alta_mod, "asegurar_cuenta", _crea_sin_id), [
        (op.test_op2_alta_completa_la_cuenta_nace_con_el_id_del_perfil,
         r"'cuentas_con_id_de_perfil': 0"),
    ]),
    "ZP11": (_parche(alta_mod, "asegurar_institucion", _institucion_recarga), [
        (op.test_op1_institucion_nace_con_billetera_y_no_se_recarga, r"'billetera': 6000"),
    ]),
    "ZP12": (_sin_todo_o_nada, [
        (op.test_op5_todo_o_nada, r"'fila_mala': \{'codigo': 0"),
    ]),
    "ZP13": (_parche(alta_mod, "asegurar_cuenta", _siempre_crea), [
        # El doble rechaza el `id` repetido (`id_en_uso`), la CLI lo atrapa y sale con 1.
        (op.test_op3_segunda_corrida_no_crea_nada_ni_toca_la_bandera,
         r"OP3: \{'codigo': 1, 'nuevos': \(0, 0, 0\)"),
        (op.test_op4_profe_en_dos_instituciones_una_sola_cuenta,
         r"OP4: \{'codigo': 1, 'perfiles': 1, 'cuentas': \['d\.en\.a@engrama\.test'\]"),
    ]),
    "ZP17": (_parche(restablecer_mod, "marcar_clave_temporal", _no_marca), [
        (op.test_op7_restablecer, r"'bandera': False"),
    ]),
    "ZP18": (_parche(alta_mod, "asegurar_cuenta", _marca_tambien_a_las_existentes), [
        (op.test_op3_segunda_corrida_no_crea_nada_ni_toca_la_bandera,
         r"'bandera_de_quien_ya_cambio': True"),
    ]),
    "ZP19": (_parche(alta_mod, "asegurar_cuenta", _cuenta_antes_que_bandera), [
        (op.test_op8_la_bandera_antes_que_la_cuenta,
         r"'visto_al_crear': \[False, False, False\]"),
    ]),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, tmp_path: Path, capsys,
                                    clave: str) -> None:
    aplicar, diagonal = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    for i, (test_real, motivo) in enumerate(diagonal):
        if i:
            integ.truncar_todo()  # cada test real arranca con la base vacía, como en pytest
        carpeta = tmp_path / f"real-{i}"
        carpeta.mkdir()
        with pytest.raises(AssertionError, match=motivo):
            test_real(integ, carpeta, capsys)
