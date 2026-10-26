"""Tramposo no-integ del límite compartido — `docs/ESPEC_limites_registro.md` §3.

  ZR37  la llave se guarda en claro (`"<contador>|<llave>"`)   -> UL4
"""
from __future__ import annotations

import pytest

from src.registro import limite as limite_mod
from tests.registro import test_limite_compartido as tlc


def _en_claro(contador: str, llave: str) -> str:
    """ZR37: la IP (o la red) va tal cual a la tabla y al respaldo."""
    return f"{contador}|{llave}"


def test_tramposo_zr37_pone_rojo_ul4(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(limite_mod, "_llave_guardada", _en_claro)
    with pytest.raises(AssertionError, match=r"'hex_de_64': \[False, False\], "
                                             r"'sin_la_ip_adentro': \[False, False, False, False\]"):
        tlc.test_ul4_la_llave_guardada_no_lleva_la_ip()
