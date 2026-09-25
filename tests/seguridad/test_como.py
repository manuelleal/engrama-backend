"""`como` rechaza una identidad que Supabase nunca produce (espec CI y deudas, C3).

`rol="anon"` con un `perfil` distinto de None simularía un `auth.uid()` en una
sesión anónima: Supabase nunca manda `sub` sin JWT, así que esa combinación no
existe en producción y ninguna llamada real la usa. `validar_identidad`
rechaza antes de que `como` toque la base (`ComoMixin.como` la llama a través
del módulo); no hace falta Docker para probarlo. Se llama aquí como
`como_modulo.validar_identidad`, no con `from ... import`, para que el
tramposo pueda sustituirla con `monkeypatch.setattr`.
Tramposo: tests/tramposos/test_tramposos_como.py.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

import tests.seguridad.como as como_modulo


def test_como_rechaza_anon_con_perfil() -> None:
    with pytest.raises(ValueError, match="anon"):
        como_modulo.validar_identidad("anon", uuid4())
