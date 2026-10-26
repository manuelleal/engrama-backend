"""Unitarias del panel, sin base (docs/ESPEC_panel_super_admin.md §2): ventanas y código neutro."""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.panel import ventanas as v


def test_codigo_de_es_neutro_y_de_dos_digitos() -> None:
    assert [v.codigo_de(n) for n in (1, 9, 10, 123)] == [
        "Cliente 01", "Cliente 09", "Cliente 10", "Cliente 123"]


def test_ventana_de_30_dias_termina_hoy() -> None:
    dias = v.dias_de_la_ventana(date(2026, 10, 26))
    assert (len(dias), dias[0], dias[-1]) == (30, date(2026, 9, 27), date(2026, 10, 26))
    assert all((b - a).days == 1 for a, b in zip(dias, dias[1:], strict=False))


def test_hoy_local_en_bogota_cruza_la_medianoche_utc() -> None:
    # 03:00 UTC del 27 = 22:00 del 26 en Bogotá (−5).
    assert v.hoy_local(datetime(2026, 10, 27, 3, 0, tzinfo=UTC), -5) == date(2026, 10, 26)
    assert v.inicio_utc(date(2026, 10, 26), -5) == datetime(2026, 10, 26, 5, 0, tzinfo=UTC)


def test_ocho_semanas_terminan_en_el_lunes_actual() -> None:
    semanas = v.semanas_de_la_ventana(date(2026, 10, 29))  # jueves
    assert (len(semanas), semanas[-1], semanas[0]) == (8, date(2026, 10, 26), date(2026, 9, 7))
    assert all(s.weekday() == 0 for s in semanas)


def _ventana_que_no_incluye_hoy(hoy: date, n: int = 30) -> list[date]:
    """Tramposo de fecha: la ventana termina AYER."""
    from datetime import timedelta

    return [hoy - timedelta(days=n - i) for i in range(n)]


def test_tramposo_ventana_sin_hoy_pone_rojo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(v, "dias_de_la_ventana", _ventana_que_no_incluye_hoy)
    with pytest.raises(AssertionError):
        test_ventana_de_30_dias_termina_hoy()
