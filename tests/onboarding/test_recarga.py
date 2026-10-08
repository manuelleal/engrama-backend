"""Recargar la bolsa de la institución — `docs/ESPEC_economia_oleada0.md` §1.6.

  UE7  C16  (no-integ) sin `--operador`, sin `--motivo` o sin `--referencia`; con
            `--monedas` 0, negativo o sobre el máximo -> salida 2 y la base ni se abre
  EP1  C17  recarga: salida 0; billetera +n; `coin_pool` +n; UNA fila `pool_topup`
            con origen NULL, operador, motivo, saldos y fecha; ninguna otra billetera
            cambia. Repetirla -> `repetida: true`. La misma referencia con otro
            monto, o una institución que no existe -> salida 1 y nada cambia
  EP2  C18  todo o nada: un fallo provocado después de mover el saldo deja saldo,
            `coin_pool` y libro idénticos a antes

La CLI se corre SIEMPRE por su `main(argv, sesiones=)`: los mismos argumentos que
escribe el operador. Los tramposos ZE7 y ZT14 a ZT17 están en
`tests/tramposos/test_tramposos_economia*.py`; cada pieza se llama por el módulo
(`recarga.f`, `economia.f`) para que se pueda reemplazar.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest

from src.onboarding import recarga as recarga_mod
from src.onboarding.__main__ import main
from src.shared.config import Settings
from tests.onboarding._ayuda import sembrar_institucion

OPERADOR, MOTIVO = "Operador Sintético", "prueba sintética de recarga"


def orden(*, slug: str = "inst-a", monedas: int | None = 500, operador: str | None = OPERADOR,
          motivo: str | None = MOTIVO, referencia: str | None = "REC-001") -> list[str]:
    """Los argumentos de `recargar`; con None ese argumento NO se escribe."""
    argv = ["recargar", "--slug", slug]
    for nombre, valor in (("--monedas", monedas), ("--operador", operador),
                          ("--motivo", motivo), ("--referencia", referencia)):
        if valor is not None:
            argv.append(f"{nombre}={valor}")
    return argv


# =============================================================================
# UE7 — C16: lo que se rechaza ANTES de abrir la base
# =============================================================================
class _AbrioLaBase(RuntimeError):
    """La CLI llegó a pedir una sesión de base de datos."""


def _sesiones_trampa() -> Any:
    raise _AbrioLaBase


def _salida_sin_base(argv: list[str]) -> Any:
    """El código de salida de la CLI, o 'abrió la base' si llegó a pedir una sesión."""
    try:
        return main(argv, sesiones=_sesiones_trampa)  # type: ignore[arg-type]
    except _AbrioLaBase:
        return "abrió la base"


def test_ue7_la_recarga_mal_pedida_no_abre_la_base(monkeypatch) -> None:
    monkeypatch.delenv("BOLSA_RECARGA_MAXIMA", raising=False)
    tabla = {
        "sin --operador": _salida_sin_base(orden(operador=None)),
        "sin --motivo": _salida_sin_base(orden(motivo=None)),
        "sin --referencia": _salida_sin_base(orden(referencia=None)),
        "--operador en blanco": _salida_sin_base(orden(operador="  ")),
        "sin --monedas": _salida_sin_base(orden(monedas=None)),
        "--monedas 0": _salida_sin_base(orden(monedas=0)),
        "--monedas negativo": _salida_sin_base(orden(monedas=-5)),
        "--monedas sobre el máximo": _salida_sin_base(orden(monedas=1_000_001)),
        # Los controles: una orden bien pedida SÍ llega a la base (el test puede fallar
        # hacia el otro lado), y el máximo exacto todavía pasa.
        "bien pedida": _salida_sin_base(orden()),
        "--monedas en el máximo": _salida_sin_base(orden(monedas=1_000_000)),
    }
    rechazadas = dict.fromkeys(
        ("sin --operador", "sin --motivo", "sin --referencia", "--operador en blanco",
         "sin --monedas", "--monedas 0", "--monedas negativo", "--monedas sobre el máximo"), 2)
    assert tabla == {**rechazadas, "bien pedida": "abrió la base",
                     "--monedas en el máximo": "abrió la base"}, f"UE7: {tabla}"

    # El máximo es configuración (BOLSA_RECARGA_MAXIMA): se lee del entorno en cada orden.
    monkeypatch.setenv("BOLSA_RECARGA_MAXIMA", "400")
    con_400 = (_salida_sin_base(orden(monedas=500)), _salida_sin_base(orden(monedas=400)))
    assert con_400 == (2, "abrió la base"), f"UE7: con el máximo en 400: {con_400}"
    monkeypatch.setenv("BOLSA_RECARGA_MAXIMA", "muchas")
    assert _salida_sin_base(orden()) == 2, "UE7: un máximo que no es número no dio salida 2"

    # La CLI no carga `Settings`: su defecto y su rango deben ser los mismos de la clase.
    campo = Settings.model_fields["bolsa_recarga_maxima"]
    rango = tuple(m.ge if hasattr(m, "ge") else m.le for m in campo.metadata)
    de_la_cli = (recarga_mod.RECARGA_MAXIMA_POR_DEFECTO, recarga_mod.RECARGA_MAXIMA_RANGO)
    assert de_la_cli == (campo.default, rango) == (1_000_000, (1, 100_000_000)), \
        f"UE7: la CLI usa {de_la_cli} y Settings {(campo.default, rango)}"


# =============================================================================
# Lecturas de la base
# =============================================================================
def cli(capsys: Any, integ: Any, argv: list[str]) -> tuple[int, dict[str, Any]]:
    """Corre la CLI contra la base de prueba: (código de salida, resumen JSON)."""
    capsys.readouterr()
    codigo = main(argv, sesiones=integ.Session)
    salida = capsys.readouterr().out.strip()
    return codigo, (json.loads(salida) if salida else {})


def recargas(integ: Any, tenant: UUID) -> list[dict[str, Any]]:
    """Las filas `pool_topup` del libro de esa institución, en orden."""
    async def _q() -> list[dict[str, Any]]:
        from sqlalchemy import text
        async with integ.Session() as db:
            filas = (await db.execute(text(
                "select amount, from_wallet_id, to_wallet_id, idempotency_key, metadata, "
                "created_by_profile_id, created_at from coin_ledger "
                "where tenant_id = :t and action = 'pool_topup' order by created_at, id"),
                {"t": tenant})).mappings().all()
            return [dict(f) for f in filas]
    return integ.run(_q())  # type: ignore[no-any-return]


def bolsa(integ: Any, tenant: UUID) -> dict[str, int]:
    """Lo que la recarga puede mover: saldo de la billetera, lo emitido y las filas del libro."""
    return {"saldo": int(integ.saldo("tenant", tenant) or 0),
            "coin_pool": int(integ.valor("select coin_pool from tenants where id = :t", t=tenant)),
            "filas": int(integ.valor("select count(*) from coin_ledger where tenant_id = :t",
                                     t=tenant))}


# =============================================================================
# EP1 — C17: la recarga, su repetición y sus rechazos
# =============================================================================
@pytest.mark.integ
def test_ep1_la_recarga_suma_una_vez_y_deja_quien_y_cuando(integ, capsys) -> None:
    a = sembrar_institucion(integ, "inst-a", pool=1000)
    b = sembrar_institucion(integ, "inst-b", pool=700)  # control: otra institución
    alumno = integ.crear_perfil(a, saldo=30)
    billetera = integ.valor("select id from coin_wallets where owner_type = 'tenant' "
                            "and owner_id = :t", t=a)

    codigo, resumen = cli(capsys, integ, orden(monedas=500, referencia="REC-001"))
    assert codigo == 0, f"EP1: la recarga salió con {codigo}: {resumen}"
    estado = bolsa(integ, a)
    assert estado["saldo"] == 1500, f"EP1: la billetera quedó en {estado['saldo']}, no 1500"
    assert estado["coin_pool"] == 1500, f"EP1: coin_pool quedó en {estado['coin_pool']}, no 1500"
    filas = recargas(integ, a)
    assert len(filas) == 1, f"EP1: {len(filas)} filas pool_topup, esperada 1"
    fila = filas[0]
    asiento = {k: fila[k] for k in ("amount", "from_wallet_id", "to_wallet_id",
                                    "idempotency_key", "metadata", "created_by_profile_id")}
    assert asiento == {
        "amount": 500, "from_wallet_id": None, "to_wallet_id": billetera,
        "idempotency_key": "topup:REC-001", "created_by_profile_id": None,
        "metadata": {"operador": OPERADOR, "motivo": MOTIVO, "saldo_antes": 1000,
                     "saldo_despues": 1500}}, f"EP1: el asiento es {asiento}"
    assert fila["created_at"] is not None, "EP1: el asiento no dice cuándo"
    assert resumen == {"institucion": "inst-a", "recargado": 500, "saldo": 1500,
                       "emitido": 1500, "repetida": False}, f"EP1: el resumen es {resumen}"
    # Nadie más se movió: ni un estudiante de la institución, ni la otra institución.
    ajenos = (integ.saldo("profile", alumno), bolsa(integ, b))
    assert ajenos == (30, {"saldo": 700, "coin_pool": 700, "filas": 0}), f"EP1: ajenos {ajenos}"

    # La misma orden otra vez (el operador reintenta): no suma dos veces.
    repetida = cli(capsys, integ, orden(monedas=500, referencia="REC-001"))
    tras_repetir = bolsa(integ, a)
    assert tras_repetir == estado, \
        f"EP1: la misma referencia volvió a sumar: {tras_repetir}, antes {estado}"
    assert repetida == (0, {"institucion": "inst-a", "recargado": 0, "saldo": 1500,
                            "emitido": 1500, "repetida": True}), f"EP1: repetida {repetida}"

    # Los rechazos: salida 1 y nada cambia.
    otro_monto = cli(capsys, integ, orden(monedas=501, referencia="REC-001"))
    no_existe = cli(capsys, integ, orden(slug="inst-fantasma", referencia="REC-002"))
    sembrar_institucion(integ, "inst-llena", pool=1_999_999_900)
    desborda = cli(capsys, integ, orden(slug="inst-llena", monedas=500, referencia="REC-003"))
    codigos = {"otro monto": otro_monto[0], "no existe": no_existe[0], "desborda": desborda[0]}
    con_error = all("error" in r and r["recargado"] == 0
                    for _, r in (otro_monto, no_existe, desborda))
    assert codigos == {"otro monto": 1, "no existe": 1, "desborda": 1} and con_error, \
        f"EP1: los rechazos: {(otro_monto, no_existe, desborda)}"
    assert bolsa(integ, a) == estado, f"EP1: un rechazo cambió algo: {bolsa(integ, a)}"

    # Y otra referencia SÍ suma: lo que deduplica es la referencia, no la institución.
    segunda = cli(capsys, integ, orden(monedas=200, referencia="REC-004"))
    assert segunda == (0, {"institucion": "inst-a", "recargado": 200, "saldo": 1700,
                           "emitido": 1700, "repetida": False}), f"EP1: la segunda {segunda}"
    assert bolsa(integ, a) == {"saldo": 1700, "coin_pool": 1700, "filas": 2}, "EP1: el final"


# =============================================================================
# EP2 — C18: todo o nada
# =============================================================================
@pytest.mark.integ
def test_ep2_un_fallo_a_mitad_no_deja_nada(integ, capsys) -> None:
    a = sembrar_institucion(integ, "inst-a", pool=1000)
    antes = bolsa(integ, a)
    visto: list[int] = []

    async def _falla_al_subir_lo_emitido(db: Any, tenant: Any, monedas: int) -> None:
        """El último paso revienta; antes anota el saldo que la transacción ya había movido."""
        from sqlalchemy import text
        visto.append(int((await db.execute(text(
            "select balance from coin_wallets where owner_type = 'tenant' and owner_id = :t"),
            {"t": tenant.id})).scalar_one()))
        raise RuntimeError("fallo provocado")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(recarga_mod, "_subir_emitido", _falla_al_subir_lo_emitido)
        with pytest.raises(RuntimeError, match="fallo provocado"):
            cli(capsys, integ, orden(monedas=500, referencia="REC-001"))
    # El control: el fallo ocurrió DESPUÉS de mover el saldo (si no, no prueba nada).
    assert visto == [1500], f"EP2: el fallo no ocurrió después de mover el saldo: {visto}"
    despues = bolsa(integ, a)
    assert despues == antes, f"EP2: tras el fallo quedó {despues}, antes {antes}"

    # La referencia tampoco quedó tomada: la misma orden, ya sin el fallo, recarga.
    codigo, resumen = cli(capsys, integ, orden(monedas=500, referencia="REC-001"))
    assert (codigo, resumen.get("repetida"), bolsa(integ, a)) == (
        0, False, {"saldo": 1500, "coin_pool": 1500, "filas": 1}), \
        f"EP2: después del fallo, la misma orden: {codigo} {resumen} {bolsa(integ, a)}"
