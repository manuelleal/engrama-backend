"""Datos del ataque D11: tablas de módulos que existen en la base sin código aún.

(docs/ESPEC_aceptacion_seguridad.md §4: shop_items, inventory, bets,
auction_bids, badge_unlocks, announcements, teacher_groups y groups.)
Cada INSERT es lo que haría un alumno con la clave pública: regalarse un
premio, apostar a su favor, pujar, darse una insignia, anunciar, hacerse
docente de un grupo o crear un grupo. Pytest no recolecta este módulo.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from tests.integ_ayudante import Integ
from tests.seguridad.veredictos import sembrar

INSERTS_MODULOS: dict[str, str] = {
    "shop_items": "insert into shop_items (tenant_id, name, price_coins) values (:t, 'Trampa', 0)",
    "inventory": "insert into inventory (tenant_id, student_id, item_id, source) "
                 "values (:t, :yo, :item, 'reward')",
    "bets": "insert into bets (tenant_id, challenger_id, opponent_id, stake_coins, status, "
            "winner_id) values (:t, :yo, :otro, 500, 'completed', :yo)",
    "auction_bids": "insert into auction_bids (tenant_id, auction_id, bidder_id, bid_amount) "
                    "values (:t, :subasta, :yo, 1)",
    "badge_unlocks": "insert into badge_unlocks (tenant_id, student_id, badge_id) "
                     "values (:t, :yo, :insignia)",
    "announcements": "insert into announcements (tenant_id, message, expiry_date) "
                     "values (:t, 'Trampa', current_date + 1)",
    "teacher_groups": "insert into teacher_groups (tenant_id, teacher_id, group_id) "
                      "values (:t, :yo, :grupo)",
    "groups": "insert into groups (tenant_id, group_code) values (:t, 'TRAMPA')",
}


def sembrar_modulos(integ: Integ, tenant: UUID, alumno: UUID, otro: UUID) -> dict[str, Any]:
    """Filas previas que exigen las FK; devuelve todos los parámetros posibles."""
    ids = {"item": uuid4(), "subasta": uuid4(), "insignia": uuid4()}
    sembrar(integ, "insert into shop_items (id, tenant_id, name, price_coins) "
                   "values (:i, :t, 'Premio', 10)", i=ids["item"], t=tenant)
    sembrar(integ, "insert into auctions (id, tenant_id, item_name, base_price) "
                   "values (:i, :t, 'Subasta', 10)", i=ids["subasta"], t=tenant)
    sembrar(integ, "insert into badges (id, tenant_id, code, name, description) "
                   "values (:i, :t, :c, 'Insignia', 'x')",
            i=ids["insignia"], t=tenant, c=f"b-{ids['insignia'].hex[:8]}")
    return {**ids, "t": tenant, "yo": alumno, "otro": otro,
            "grupo": integ.crear_grupo(tenant, "G1")}


def parametros(sql: str, todos: dict[str, Any]) -> dict[str, Any]:
    """Solo los parámetros que la sentencia nombra (`:clave` seguido de un no-letra)."""
    import re

    usados = set(re.findall(r":([a-z_]+)\b", sql))
    return {k: v for k, v in todos.items() if k in usados}
