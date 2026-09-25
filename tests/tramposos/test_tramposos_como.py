"""Tramposo de C3 (docs/ESPEC_ci_y_deudas.md).

Mismo patrón que test_tramposos_bug2.py: se sustituye `validar_identidad` por
una que no rechaza nada, se corre el test real y se exige que falle, no que
pase. Como ya no hay `ValueError` que atrapar, `pytest.raises` del test real
falla con su propio "DID NOT RAISE": eso es lo que este tramposo exige.
No necesita Docker (el test real tampoco).
"""
from __future__ import annotations

import pytest

import tests.seguridad.como as como_modulo
import tests.seguridad.test_como as prueba_real


def test_tramposo_como_pone_rojo_su_test(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(como_modulo, "validar_identidad", lambda rol, perfil: None)
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        prueba_real.test_como_rechaza_anon_con_perfil()
