"""MG47: la migración 047 (la economía de la ola 1) sube, baja y vuelve a subir idéntica.

`docs/ESPEC_ola1_economia.md` §7. Usa las funciones de `test_migracion_035.py`
(ERR-24): una transacción que se deshace, el mismo SQL que corre Alembic, y se
comparan columnas, restricciones, índices y RLS de las cinco tablas tocadas.
No crea tablas: al bajar, cada tabla pierde solo lo que la 047 le puso.
"""
from __future__ import annotations

from typing import Any

import pytest

from tests.integ.test_migracion_035 import cargar, sube_baja_sube

pytestmark = pytest.mark.integ

TABLAS = ("coin_wallets", "shop_items", "inventory", "coin_ledger", "auctions")
COLUMNAS = {"shop_items": {"created_by"}, "inventory": {"price_paid", "purchase_ledger_id"},
            "auctions": {"ends_at", "extensions", "item_id", "created_by"}}
INDICES = {"coin_ledger": "idx_ledger_tenant_action_actor", "inventory": "idx_inventory_pendientes",
           "auctions": "uq_auctions_grupo_activa"}
M047 = cargar("047_economia_ola1.py")


def _nombres(esquema: dict[str, Any], que: str) -> list[str]:
    return [fila[0] for fila in esquema.get(que, [])]


def _definicion(esquema: dict[str, Any], restriccion: str) -> str | None:
    return dict(esquema.get("restricciones", [])).get(restriccion)


def _columnas(esquema: dict[str, Any]) -> dict[str, tuple[Any, ...]]:
    return {fila[0]: tuple(fila[1:4]) for fila in esquema.get("columnas", [])}


def test_mg47_sube_baja_y_vuelve_a_subir_identica(integ) -> None:
    """MG47: up/down/up con el mismo esquema, y subir dos veces no falla."""
    visto = sube_baja_sube(integ, M047, TABLAS)
    primera, bajada = visto["primera"], visto["tras_bajar"]
    observado = {
        "el_check_del_dueno": _definicion(primera["coin_wallets"],
                                          "coin_wallets_owner_type_check"),
        "las_columnas": {t: {c: _columnas(primera[t]).get(c) for c in sorted(cs)}
                         for t, cs in COLUMNAS.items()},
        "el_check_de_lo_pagado": _definicion(primera["inventory"], "inventory_price_paid_check"),
        "los_indices": {t: i in _nombres(primera[t], "indices") for t, i in INDICES.items()},
        "rls_igual": {t: (primera[t]["rls"], primera[t]["politicas"]) == (
            bajada[t]["rls"], bajada[t]["politicas"]) for t in TABLAS},
        "tras_bajar": {
            "el_check_viejo": _definicion(bajada["coin_wallets"],
                                          "coin_wallets_owner_type_check"),
            "pierden_solo_eso": {
                t: sorted(_columnas(bajada[t])) == sorted(
                    x for x in _columnas(primera[t]) if x not in cs)
                for t, cs in COLUMNAS.items()},
            "sin_los_indices": {t: i not in _nombres(bajada[t], "indices")
                                for t, i in INDICES.items()},
            "sin_el_check_de_lo_pagado": _definicion(bajada["inventory"],
                                                     "inventory_price_paid_check") is None,
        },
        "segunda_igual_a_la_primera": visto["segunda"] == primera,
        "repetida_igual_a_la_primera": visto["repetida"] == primera,
    }
    assert observado == {
        "el_check_del_dueno": "CHECK ((owner_type = ANY (ARRAY['system'::text, 'tenant'::text, "
                              "'profile'::text, 'membership'::text, 'auction'::text])))",
        "las_columnas": {
            "shop_items": {"created_by": ("uuid", "YES", None)},
            "inventory": {"price_paid": ("integer", "YES", None),
                          "purchase_ledger_id": ("uuid", "YES", None)},
            "auctions": {"created_by": ("uuid", "YES", None),
                         "ends_at": ("timestamp with time zone", "YES", None),
                         "extensions": ("integer", "NO", "0"), "item_id": ("uuid", "YES", None)},
        },
        "el_check_de_lo_pagado": "CHECK (((price_paid IS NULL) OR (price_paid > 0)))",
        "los_indices": dict.fromkeys(INDICES, True),
        "rls_igual": dict.fromkeys(TABLAS, True),
        "tras_bajar": {
            "el_check_viejo": "CHECK ((owner_type = ANY (ARRAY['system'::text, 'tenant'::text, "
                              "'profile'::text])))",
            "pierden_solo_eso": dict.fromkeys(COLUMNAS, True),
            "sin_los_indices": dict.fromkeys(INDICES, True),
            "sin_el_check_de_lo_pagado": True,
        },
        "segunda_igual_a_la_primera": True, "repetida_igual_a_la_primera": True,
    }, f"MG47: {observado}"
