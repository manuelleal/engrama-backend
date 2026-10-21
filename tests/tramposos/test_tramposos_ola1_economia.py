"""Tramposos de las reglas de plata de la ola 1 — `docs/ESPEC_ola1_economia.md` §A.6.

Mismo patrón que `test_tramposos_bug15.py`: cada tramposo rompe UNA pieza a
propósito, se corre el cuerpo del test real y se exige `AssertionError` con el
mensaje de su test. Si un tramposo no pone rojo su test, ese test no prueba nada.
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import AuthContext
from src.bolsillo import consultas, entregas, presupuesto, reglas
from src.engrama_core.service import libro
from src.shared.models import CoinLedger, CoinWallet, ShopItem
from src.shop import compras, subastas
from src.shop import entregas as tienda_entregas
from src.teachers.service import access
from tests.economia_ola1 import test_bolsillo as tb
from tests.economia_ola1 import test_subastas as ts
from tests.economia_ola1 import test_tienda as tt
from tests.tramposos.test_tramposos_bug13 import correr

pytestmark = pytest.mark.integ

Aplicar = Callable[[Any, pytest.MonkeyPatch], AbstractContextManager[Any]]


def _parche(objetivo: Any, nombre: str, valor: Any) -> Aplicar:
    def aplicar(_integ: Any, mp: pytest.MonkeyPatch) -> AbstractContextManager[Any]:
        mp.setattr(objetivo, nombre, valor)
        return nullcontext()
    return aplicar


async def _cupo_por_profe(db: AsyncSession, auth: AuthContext, alumno_wallet: UUID) -> int:
    """OT2: cuenta solo lo que dio ESTE profe (dos profes llenan al mismo estudiante)."""
    stmt = select(CoinLedger.amount).where(
        CoinLedger.tenant_id == auth.tenant_id, CoinLedger.action == consultas.ENTREGA,
        CoinLedger.to_wallet_id == alumno_wallet,
        CoinLedger.created_by_profile_id == auth.profile_id,
        CoinLedger.created_at >= consultas.lunes_actual())
    return sum(int(x) for x in (await db.execute(stmt)).scalars().all())


async def _transferir_sin_mirar(db: AsyncSession, *, tenant_id: UUID, desde: CoinWallet,
                                hacia: CoinWallet, monto: int, accion: str,
                                creado_por: UUID | None, metadata: dict[str, Any] | None = None,
                                llave: str | None = None) -> tuple[CoinLedger, bool]:
    """OT3: el traslado sin mirar el saldo del origen (como si el CHECK fuera la única barrera)."""
    asiento = CoinLedger(tenant_id=tenant_id, from_wallet_id=desde.id, to_wallet_id=hacia.id,
                         amount=monto, action=accion, created_by_profile_id=creado_por,
                         ledger_metadata=metadata or {}, idempotency_key=llave)
    db.add(asiento)
    desde.balance = desde.balance - monto
    hacia.balance = hacia.balance + monto
    await db.flush()
    return asiento, True


async def _cobrar_destruye(db: AsyncSession, *, tenant_id: UUID, alumno: CoinWallet,
                           bolsa: CoinWallet, monto: int, llave: str, creado_por: UUID,
                           item_id: UUID) -> CoinLedger:
    """OT13: la compra le quita al estudiante y no le pone a nadie (Lingo, app.js:2289)."""
    del bolsa, item_id
    asiento = CoinLedger(tenant_id=tenant_id, from_wallet_id=alumno.id, to_wallet_id=None,
                         amount=monto, action=compras.COMPRA, created_by_profile_id=creado_por,
                         idempotency_key=llave)
    db.add(asiento)
    alumno.balance = alumno.balance - monto
    await db.flush()
    return asiento


async def _objeto_sin_institucion(db: AsyncSession, tenant_id: UUID,
                                  item_id: UUID) -> ShopItem | None:
    """OT15: busca el objeto solo por id, sin mirar la institución."""
    del tenant_id
    return (await db.execute(select(ShopItem).where(ShopItem.id == item_id)
                             .with_for_update())).scalar_one_or_none()


async def _cero(*_a: Any, **_k: Any) -> int:
    return 0


async def _nada(*_a: Any, **_k: Any) -> None:
    return None


TRAMPOSOS: dict[str, tuple[Aplicar, list[tuple[Callable[..., None], str]]]] = {
    "OT1": (_parche(reglas, "validar_monto_entrega", lambda *_: None), [
        (tb.test_oe1_tope_por_entrega, r"OE1: \{'21': 201"),
    ]),
    "OT2": (_parche(entregas, "_cupo_semanal", _cupo_por_profe), [
        (tb.test_oe2_tope_semanal_entre_dos_profes, r"OE2: .*'tercero': 201"),
    ]),
    "OT3": (_parche(libro, "transferir", _transferir_sin_mirar), [
        (tb.test_oe3_presupuesto_insuficiente, r"OE3: \{'16': 500"),
        (tb.test_oe5_corregir_lo_ya_gastado_no_deja_negativo, r"OE5: .*'corregir': 500"),
        (tt.test_oe11_12_sin_saldo_y_sin_existencias, r"OE11-12: \{'sin_saldo': 500"),
    ]),
    "OT4": (_parche(access, "_requiere_asignacion", lambda *_a, **_k: False), [
        (tb.test_oe4_profe_sin_el_grupo_del_estudiante, r"OE4: \{'p2_al_10A': 201"),
    ]),
    "OT6": (_parche(reglas, "dentro_del_plazo", lambda *_: True), [
        (tb.test_oe6_corregir_solo_14_dias, r"OE6: \{'15_dias': 201"),
    ]),
    "OT10": (_parche(presupuesto, "_recargado_semana", _cero), [
        (tb.test_oe10_recarga_semanal_con_tope, r"OE10: .*'1_mas': 201"),
    ]),
    "OT12": (_parche(compras, "_verificar_stock", lambda *_: None), [
        (tt.test_oe11_12_sin_saldo_y_sin_existencias, r"OE11-12: .*'agotado': 201"),
    ]),
    "OT13": (_parche(compras, "_cobrar", _cobrar_destruye), [
        (tt.test_oe13_la_compra_vuelve_a_la_bolsa, r"OE13: .*'bolsa_sube': 0"),
    ]),
    "OT14": (_parche(tienda_entregas, "_marcar_devuelta", lambda *_: None), [
        (tt.test_oe14_devolucion_a_los_14_dias_una_sola_vez, r"OE14: \{'vieja': \['por_entregar'"),
    ]),
    "OT15": (_parche(compras, "_objeto_de", _objeto_sin_institucion), [
        (tt.test_oe15b_aislamiento_de_la_tienda, r"OE15b: \{'compra_ajena': 201"),
    ]),
    "OT20": (_parche(subastas, "_devolver_al_superado", _nada), [
        (ts.test_sb1_retencion_y_devolucion_al_superado, r"SB1: .*\(200, 90, 85, 25\)"),
    ]),
    "OT21": (_parche(subastas, "MAX_EXTENSIONES", 99), [
        (ts.test_sb3_extension_de_10_s_maximo_3, r"SB3: .*\(200, 4, True\)"),
    ]),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(integ, monkeypatch, clave: str) -> None:
    aplicar, diagonal = TRAMPOSOS[clave]
    with aplicar(integ, monkeypatch):
        for test_real, motivo in diagonal:
            with pytest.raises(AssertionError, match=motivo):
                correr(test_real, integ, monkeypatch)
            integ.truncar_todo()  # cada test real arranca con la base limpia
