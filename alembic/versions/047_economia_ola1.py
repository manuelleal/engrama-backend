"""la economía de la ola 1: bolsillo del profe, quién creó el objeto y lo pagado en la mochila

Revision ID: 047_economia_ola1
Revises: 045_correccion_por_pregunta
Create Date: 2026-10-21

Espec: docs/ESPEC_ola1_economia.md §7.

OJO con el número (ERR-45): las ramas `seg/limites-registro` y `seg/pase-acotado`
ya traen cada una una migración 046 sin integrar. Esta salta a 047 y cuelga de
la 045; al integrar se renumera y cambia su `down_revision`.

Qué hace (`SQL_SUBIR`, idempotente y ADITIVA; no crea tablas ni políticas):
  1. `coin_wallets`: el CHECK de `owner_type` admite también `'membership'`. El
     bolsillo del profe es una billetera de su MEMBRESÍA (única por institución y
     perfil), no de su perfil: un profe con dos colegios tiene dos bolsillos y no
     puede gastar en uno lo que le recargó el otro.
  2. `shop_items.created_by`: quién publicó el objeto (decide quién lo entrega y
     quién lo edita). NULL en lo que ya existía.
  3. `inventory.price_paid` y `inventory.purchase_ledger_id`: lo que costó de
     verdad (el precio del objeto puede cambiar después) y el asiento de la
     compra. Con eso la devolución de los 14 días devuelve exactamente lo pagado.
  4. Dos índices: uno del libro para los topes (por institución, acción, quién y
     cuándo) y uno parcial de la mochila para el barrido de las pendientes.
  5. La subasta (ADENDA 1, decisión 017): `owner_type = 'auction'` es la billetera
     donde quedan RETENIDAS las monedas del líder; `auctions` gana `ends_at`,
     `extensions`, `item_id` (el objeto de la tienda) y `created_by`; y un índice
     único parcial: una sola subasta activa por grupo.

NO pone CHECK de escalones ni de tipo en `shop_items`: el ataque D11
(`tests/seguridad/modulos.py`) inserta precios 0 y 10 con el tipo por defecto, y
esas reglas viven en la API.

Downgrade (`SQL_BAJAR`): lo deshace en orden inverso. Si ya existen bolsillos,
volver al CHECK viejo FALLA a propósito: bajar no borra dinero. En producción no
se baja.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "047_economia_ola1"
down_revision: Union[str, None] = "045_correccion_por_pregunta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_SUBIR: tuple[str, ...] = (
    "ALTER TABLE coin_wallets DROP CONSTRAINT IF EXISTS coin_wallets_owner_type_check;",
    """
    ALTER TABLE coin_wallets ADD CONSTRAINT coin_wallets_owner_type_check
      CHECK (owner_type IN ('system','tenant','profile','membership','auction'));
    """,
    "ALTER TABLE shop_items ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES profiles(id);",
    "ALTER TABLE inventory ADD COLUMN IF NOT EXISTS price_paid INTEGER;",
    "ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_price_paid_check;",
    """
    ALTER TABLE inventory ADD CONSTRAINT inventory_price_paid_check
      CHECK (price_paid IS NULL OR price_paid > 0);
    """,
    "ALTER TABLE inventory ADD COLUMN IF NOT EXISTS purchase_ledger_id UUID "
    "REFERENCES coin_ledger(id);",
    """
    CREATE INDEX IF NOT EXISTS idx_ledger_tenant_action_actor
      ON coin_ledger (tenant_id, action, created_by_profile_id, created_at);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_inventory_pendientes
      ON inventory (tenant_id, purchased_at) WHERE status = 'pending_delivery';
    """,
    "ALTER TABLE auctions ADD COLUMN IF NOT EXISTS ends_at TIMESTAMPTZ;",
    "ALTER TABLE auctions ADD COLUMN IF NOT EXISTS extensions INTEGER NOT NULL DEFAULT 0;",
    "ALTER TABLE auctions ADD COLUMN IF NOT EXISTS item_id UUID REFERENCES shop_items(id);",
    "ALTER TABLE auctions ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES profiles(id);",
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_auctions_grupo_activa
      ON auctions (group_id) WHERE status = 'active';
    """,
)

SQL_BAJAR: tuple[str, ...] = (
    "DROP INDEX IF EXISTS uq_auctions_grupo_activa;",
    "ALTER TABLE auctions DROP COLUMN IF EXISTS created_by;",
    "ALTER TABLE auctions DROP COLUMN IF EXISTS item_id;",
    "ALTER TABLE auctions DROP COLUMN IF EXISTS extensions;",
    "ALTER TABLE auctions DROP COLUMN IF EXISTS ends_at;",
    "DROP INDEX IF EXISTS idx_inventory_pendientes;",
    "DROP INDEX IF EXISTS idx_ledger_tenant_action_actor;",
    "ALTER TABLE inventory DROP COLUMN IF EXISTS purchase_ledger_id;",
    "ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_price_paid_check;",
    "ALTER TABLE inventory DROP COLUMN IF EXISTS price_paid;",
    "ALTER TABLE shop_items DROP COLUMN IF EXISTS created_by;",
    "ALTER TABLE coin_wallets DROP CONSTRAINT IF EXISTS coin_wallets_owner_type_check;",
    """
    ALTER TABLE coin_wallets ADD CONSTRAINT coin_wallets_owner_type_check
      CHECK (owner_type IN ('system','tenant','profile'));
    """,
)


def upgrade() -> None:
    for sql in SQL_SUBIR:
        op.execute(sql)


def downgrade() -> None:
    for sql in SQL_BAJAR:
        op.execute(sql)
