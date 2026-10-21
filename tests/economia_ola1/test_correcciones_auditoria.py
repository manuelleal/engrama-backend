"""Correcciones de la auditoría independiente de la ola 1 (H-1 a H-4), sin base de datos.

Cada una tiene su prueba que falla sin la corrección: el select bloqueado debe pedir
`populate_existing` (si no, el ORM devuelve el objeto viejo de la sesión y el
`stock + 1` o el saldo se calculan sobre un valor rancio), el monto enorme debe morir
en el esquema (422) y no en la base (500), y cerrar una subasta sin objeto no revienta.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.bolsillo.schemas import MovimientoIn
from src.engrama_core.service import libro
from src.shop import entregas, subastas
from src.shop.schemas import PujaIn


class _Resultado:
    def __init__(self, valor: Any) -> None:
        self._valor = valor

    def scalar_one(self) -> Any:
        return self._valor

    def scalar_one_or_none(self) -> Any:
        return self._valor


class _DbFalsa:
    """Registra cada sentencia que recibe; responde con un valor fijo."""

    def __init__(self, valor: Any = None) -> None:
        self.sentencias: list[Any] = []
        self._valor = valor

    async def execute(self, stmt: Any) -> _Resultado:
        self.sentencias.append(stmt)
        return _Resultado(self._valor)

    async def flush(self) -> None:
        return None


def _bloqueado_y_fresco(stmt: Any) -> tuple[bool, bool]:
    return (stmt._for_update_arg is not None,
            bool(stmt.get_execution_options().get("populate_existing")))


def test_h2_billetera_bloqueada_relee_el_saldo() -> None:
    db = _DbFalsa(valor=SimpleNamespace(balance=5))
    asyncio.run(libro.billetera(db, "tenant", uuid4(), uuid4(), bloquear=True))  # type: ignore[arg-type]
    asyncio.run(libro.billetera_por_id(db, uuid4(), bloquear=True))  # type: ignore[arg-type]
    observado = [_bloqueado_y_fresco(s) for s in db.sentencias]
    assert observado == [(True, True), (True, True)], f"H-2: (FOR UPDATE, populate_existing) {observado}"


def test_h2_billetera_sin_bloqueo_no_cambia() -> None:
    db = _DbFalsa(valor=SimpleNamespace(balance=5))
    asyncio.run(libro.billetera(db, "tenant", uuid4(), uuid4()))  # type: ignore[arg-type]
    assert _bloqueado_y_fresco(db.sentencias[0]) == (False, False)


def test_h1_devolucion_relee_el_objeto_bloqueado(monkeypatch: pytest.MonkeyPatch) -> None:
    objeto = SimpleNamespace(stock=3)
    db = _DbFalsa(valor=objeto)
    billetera = SimpleNamespace(balance=1000)

    async def _billetera(*_a: Any, **_k: Any) -> Any:
        return billetera

    async def _transferir(*_a: Any, **_k: Any) -> Any:
        return None

    monkeypatch.setattr(entregas.libro, "billetera", _billetera)
    monkeypatch.setattr(entregas.libro, "transferir", _transferir)
    fila = SimpleNamespace(price_paid=10, tenant_id=uuid4(), student_id=uuid4(), id=uuid4(),
                           item_id=uuid4(), status="pending_delivery", resolved_at=None)
    assert asyncio.run(entregas._devolver_una(db, fila)) is True  # type: ignore[arg-type]
    assert objeto.stock == 4
    assert [_bloqueado_y_fresco(s) for s in db.sentencias] == [(True, True)], \
        "H-1: el objeto del stock + 1 debe venir bloqueado y releído"


@pytest.mark.parametrize("modelo", [PujaIn, MovimientoIn])
def test_h4_monto_enorme_es_422_no_500(modelo: Any) -> None:
    modelo(monto=1_000_000)  # el tope mismo sí
    for enorme in (1_000_001, 10**12, 2**63):
        with pytest.raises(ValidationError):
            modelo(monto=enorme)


def test_h3_cerrar_subasta_sin_objeto_no_revienta(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _billetera(*_a: Any, **_k: Any) -> Any:
        return SimpleNamespace(balance=0)

    monkeypatch.setattr(subastas.libro, "billetera", _billetera)
    db = _DbFalsa()
    a = SimpleNamespace(status="active", ends_at=None, tenant_id=uuid4(), id=uuid4(),
                        item_id=None, highest_bidder_id=None)
    asyncio.run(subastas.cerrar(db, a))  # type: ignore[arg-type]
    assert a.status == "ended" and db.sentencias == []
