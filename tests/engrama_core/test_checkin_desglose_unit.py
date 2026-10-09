"""Lo puro del desglose del check-in (sin base) — `docs/ESPEC_economia_oleada0.md` §13.

  UK1  C30  `cobro_de_asistencia`: la tabla y el invariante (suma; ya cobrada = ceros)
  UK2  C31  `CheckInResult` sin los campos nuevos sigue construyéndose (cliente viejo)

La función se llama por el módulo (`economia.f(...)`) para que sus tramposos
(ZK1-ZK3, `tests/tramposos/test_tramposos_economia_unit.py`) puedan reemplazarla.
"""
from __future__ import annotations

from itertools import product

from src.engrama_core.schemas import CheckInResult
from src.engrama_core.service import economia


def _pago(puntual: bool, base: int, bono: int) -> economia.DesgloseAsistencia:
    """Lo que la regla HABRÍA pagado: (base, bono si llegó puntual)."""
    return economia.DesgloseAsistencia(base=base, puntualidad=bono if puntual else 0,
                                       puntual=puntual)


def _cobro(puntual: bool, ya_cobrada: bool, base: int = 5,
           bono: int = 5) -> tuple[int, int, bool, bool]:
    c = economia.cobro_de_asistencia(_pago(puntual, base, bono), ya_cobrada=ya_cobrada)
    return (c.base, c.puntualidad, c.puntual, c.ya_cobrada_hoy)


def test_uk1_el_cobro_de_la_asistencia_suma_y_distingue_ya_cobrada() -> None:
    """C30: la tabla de casos, y para toda combinación: suma y, si ya cobrada, ceros."""
    tabla = {
        "puntual": _cobro(True, False),
        "tarde": _cobro(False, False),
        # La configuración en cero NO es "ya cobrada": puntual dice la verdad.
        "config en cero y puntual": _cobro(True, False, base=0, bono=0),
        "ya cobrada, puntual": _cobro(True, True),
        "ya cobrada, tarde": _cobro(False, True),
    }
    esperado = {
        "puntual": (5, 5, True, False),
        "tarde": (5, 0, False, False),
        "config en cero y puntual": (0, 0, True, False),
        "ya cobrada, puntual": (0, 0, False, True),
        "ya cobrada, tarde": (0, 0, False, True),
    }
    assert tabla == esperado, f"UK1: {tabla}, esperado {esperado}"

    malas: list[str] = []
    for puntual, ya, (base, bono) in product((True, False), (True, False),
                                             ((5, 5), (4, 3), (0, 0), (7, 0))):
        pago = _pago(puntual, base, bono)
        c = economia.cobro_de_asistencia(pago, ya_cobrada=ya)
        caso = f"puntual={puntual} ya={ya} cfg={(base, bono)}"
        esperado_total = 0 if ya else pago.total
        if c.base + c.puntualidad != esperado_total or c.total != esperado_total:
            malas.append(f"suma {caso}: {(c.base, c.puntualidad)} no suma {esperado_total}")
        if c.ya_cobrada_hoy != ya:
            malas.append(f"bandera {caso}: {c.ya_cobrada_hoy}")
        if ya and (c.base, c.puntualidad, c.puntual) != (0, 0, False):
            malas.append(f"ceros {caso}: {tuple(c)}")
        if not ya and c.puntual != puntual:
            malas.append(f"puntual {caso}: {c.puntual}")
    assert malas == [], f"UK1: {malas}"


def test_uk2_el_resultado_del_checkin_sin_los_campos_nuevos_sigue_valiendo() -> None:
    """C31: quien arme un `CheckInResult` como antes (un doble, un cliente viejo) lo consigue."""
    viejo = CheckInResult(success=True, coins_awarded=10, streak=2, message="ok")
    visto = (viejo.base, viejo.puntualidad, viejo.puntual, viejo.ya_cobrada_hoy)
    assert visto == (0, 0, False, False), f"UK2: los defectos son {visto}"
    assert set(viejo.model_dump()) == {"success", "coins_awarded", "streak", "message", "base",
                                       "puntualidad", "puntual", "ya_cobrada_hoy"}, \
        f"UK2: los campos de la respuesta son {sorted(viejo.model_dump())}"
