"""PA1: la forma del pase y su huella (no-integ) — `docs/ESPEC_pase_acotado.md` §1.1.

Sin base ni HTTP. `pase_service.generar_pase` y `pase_service.huella` se llaman
por el módulo para que el tramposo ZA1 (`BYTES_AL_AZAR = 16`) los alcance.
"""
from __future__ import annotations

import hashlib
import re

from src.anillo import service as pase_service

FORMA = re.compile(r"pa1_[A-Za-z0-9_-]{43}")
CUANTOS = 2000


def test_pa1_forma_del_pase_y_su_huella() -> None:
    pases = [pase_service.generar_pase() for _ in range(CUANTOS)]
    huellas = [pase_service.huella(p) for p in pases[:50]]
    observado = {
        "con_la_forma": sum(FORMA.fullmatch(p) is not None for p in pases),
        "distintos": len(set(pases)),
        "huella_es_sha256_hex": all(
            h == hashlib.sha256(p.encode("utf-8")).hexdigest()
            for p, h in zip(pases, huellas, strict=False)),
        "la_huella_no_contiene_el_pase": all(
            p not in h and p[4:] not in h for p, h in zip(pases, huellas, strict=False)),
    }
    assert observado == {"con_la_forma": CUANTOS, "distintos": CUANTOS,
                         "huella_es_sha256_hex": True,
                         "la_huella_no_contiene_el_pase": True}, f"PA1: {observado}"
