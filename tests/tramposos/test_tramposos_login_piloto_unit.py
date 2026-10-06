"""Tramposos (no-integ) del login piloto — `docs/ESPEC_login_piloto.md` §3.

Mismo patrón que `test_tramposos_login_piloto.py`, sin base: se reemplaza lo
que usa el código (en su módulo), se corre el cuerpo del test real y se exige
`AssertionError` con el mensaje.

  ZP7   `puede_con_contrasena_temporal` siempre verdadera          -> UP3
  ZP20  la lista indexada solo por path, sin el método (H-4)       -> UP3
  ZP10  `StudentEnrollIn.model_fields["documento_id"]` con un
        `pattern` que admite `:`                                  -> UP1
  ZP16  `leer_csv` no antepone el prefijo de la institución a
        un `CODIGO`                                               -> UP2
"""
from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic.fields import FieldInfo

from src.auth import service as auth_service
from src.onboarding import csv_personas as csv_mod
from src.teachers.schemas import StudentEnrollIn
from tests.auth import test_permitidas_unit as up
from tests.onboarding import test_csv_personas as csvp
from tests.teachers import test_m3_documento as m3d

Aplicar = Callable[[pytest.MonkeyPatch], None]

_PATHS_PERMITIDOS = frozenset(p for p, _m in auth_service.RUTAS_CON_CONTRASENA_TEMPORAL)
_PATRON_CON_DOS_PUNTOS = r"^[A-Za-z0-9_:-]{3,32}$"


def _solo_por_path(path: str, _metodo: str) -> bool:
    """ZP20: cualquier método de un path permitido pasa (p. ej. `POST /auth/me`)."""
    return path in _PATHS_PERMITIDOS


def _permitidas(roto: Callable[..., bool]) -> Aplicar:
    return lambda mp: mp.setattr(auth_service, "puede_con_contrasena_temporal", roto)


def _campo_con_dos_puntos(mp: pytest.MonkeyPatch) -> None:
    """ZP10: el campo de M3 declara otro patrón (la validación compilada no cambia)."""
    mp.setitem(StudentEnrollIn.model_fields, "documento_id",
               FieldInfo(annotation=str, pattern=_PATRON_CON_DOS_PUNTOS))


def _codigo_sin_prefijo(mp: pytest.MonkeyPatch) -> None:
    """ZP16: el código interno queda tal cual, sin `<slug>_` (el `001` de todas es el mismo)."""
    mp.setattr(csv_mod, "con_prefijo", lambda _slug, codigo: codigo)


TRAMPOSOS: dict[str, tuple[Aplicar, Callable[[], None], str]] = {
    "ZP7": (_permitidas(lambda *_: True), up.test_up3_permitidas_por_path_y_metodo,
            r"\('/auth/me', 'POST'\): True"),
    "ZP20": (_permitidas(_solo_por_path), up.test_up3_permitidas_por_path_y_metodo,
             r"\('/auth/me', 'POST'\): True"),
    "ZP10": (_campo_con_dos_puntos, m3d.test_up1_una_sola_fuente_de_la_regex,
             r"'m3': '\^\[A-Za-z0-9_:-\]"),
    "ZP16": (_codigo_sin_prefijo, csvp.test_up2_csv_del_alta,
             r"'codigo_con_prefijo': \{'filas': \[\], 'errores': \[1\]\}"),
}


@pytest.mark.parametrize("clave", list(TRAMPOSOS))
def test_tramposo_pone_rojo_su_test(monkeypatch, clave: str) -> None:
    aplicar, test_real, motivo = TRAMPOSOS[clave]
    aplicar(monkeypatch)
    with pytest.raises(AssertionError, match=motivo):
        test_real()
