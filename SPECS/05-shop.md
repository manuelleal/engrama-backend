# SPEC 05 — Shop (Tienda + Subastas + Inventario)

> **Módulo:** `src/shop/`
> **Estado:** 📝 spec listo — pendiente de implementación
> **Depende de:** `shared/models.py` (ShopItem, Inventory, Auction, AuctionBid, CoinWallet, CoinLedger). NUNCA importa de `engrama_core` — usa `src/shared/services.py` para mover coins (ver §3).

---

## 1. Objetivo

Implementar dos mecanismos de sink de coins: **tienda buy-now** (precio fijo, stock finito)
y **subastas** (puja incremental con refund automático). Ambos producen filas en `inventory`
como "propiedad" del estudiante. Todo bajo multi-tenancy estricto (WINDSURF §3).

---

## 2. Schemas (`schemas.py`)

Pydantic v2 strict (`extra="forbid"`).

| Schema | Campos clave |
|---|---|
| `ShopItemCreate` | `name`, `description?`, `item_type`, `price_coins`, `stock?` (None = ilimitado), `group_id?` |
| `ShopItemOut` | todos los anteriores + `id`, `is_active`, `remaining_quantity`, `created_at` |
| `PurchaseOut` | `inventory_id`, `item_id`, `item_name`, `coins_spent`, `new_balance` |
| `AuctionCreate` | `item_name`, `description?`, `item_type`, `base_price`, `group_id?`, `duration_days` (default 7) |
| `AuctionOut` | `id`, `item_name`, `base_price`, `current_bid`, `highest_bidder_name?`, `status`, `expires_at`, `group_id?` |
| `BidIn` | `amount` (`gt=0`) |
| `BidOut` | `auction_id`, `bid_amount`, `new_balance`, `is_highest_bidder` |
| `InventoryItemOut` | `id`, `item_id`, `item_name`, `source`, `status`, `obtained_via`, `purchased_at`, `expires_at?` |
| `ClaimOut` | `inventory_id`, `auction_id`, `item_name` |

`obtained_via` es campo calculado del join (alias de `source` renombrado para el front).

---

## 3. Movimiento de coins — patrón double-entry

El shop NO importa `src.engrama_core.service.coins` directamente (violación de dependency rule).
La función `debit_coins` se expone en **`src/shared/services.py`** como servicio compartido:

```python
# src/shared/services.py (ampliar el existente o crear)
async def debit_coins(
    db: AsyncSession,
    *,
    student_id: UUID,
    tenant_id: UUID,
    amount: int,
    action: str,                 # 'shop_purchase' | 'auction_bid' | 'auction_refund'
    metadata: dict | None = None,
) -> CoinLedger:
    """Transfiere `amount` coins del wallet del estudiante al del tenant.
    SELECT FOR UPDATE en ambos wallets. Lanza 402 si saldo insuficiente.
    Mismo patrón que award_coins pero dirección invertida."""
```

**Flujo de compra:** `student_wallet → tenant_wallet` (debit) + fila en `coin_ledger` +
fila en `inventory`. Todo en una sola transacción; el router NO hace commit intermedio.

**Flujo de puja:** debit al nuevo postor + INSERT en `auction_bids` + UPDATE `auctions`
+ refund (award_coins invertido) al postor anterior si existía. Todo atómico.

---

## 4. Lógica (`service/`)

```
src/shop/service/
├── items.py      ← CRUD ShopItem + compra buy-now
├── auctions.py   ← CRUD Auction + puja + cierre + claim
└── inventory.py  ← lectura y gestión del inventario del estudiante
```

### 4.1 `items.py`

**`create_item(db, teacher_id, tenant_id, data)`**
- Valida `group_id` pertenece al `tenant_id` si se pasa.
- INSERT `shop_items`. `stock` NULL = sin límite.

**`list_items(db, tenant_id, group_id=None)`**
- SELECT `shop_items` WHERE `tenant_id=X AND is_active=TRUE`.
- Si `group_id`: filtrar por `group_id IS NULL OR group_id=Y`.
- Devuelve `remaining_quantity` = `stock` (el campo se llama `stock` en el modelo — ver §6 Migración).

**`purchase_item(db, student_id, tenant_id, item_id)`** — operación atómica
1. `SELECT shop_items FOR UPDATE WHERE id=X AND tenant_id=Y AND is_active=TRUE`.
2. Si `stock IS NOT NULL AND stock <= 0` → 409 "Sin stock".
3. `debit_coins(db, student_id, tenant_id, item.price_coins, 'shop_purchase', {item_id})`.
4. Si `stock IS NOT NULL`: `item.stock -= 1`; si llega a 0: `item.is_active = False`.
5. INSERT `inventory(tenant_id, student_id, item_id, source='shop', status='available')`.
6. `flush()` — el caller (router) commitea.

> **Lección de concurrencia del MVP:** el MVP usaba optimistic locking con hasta 3 reintentos;
> bajo carga de aula (30 estudiantes simultáneos) sufría race conditions. Engrama 2.0 usa
> `SELECT ... FOR UPDATE` (pessimistic lock) en el item y en ambas wallets. No hay reintentos
> en el service: si el lock tarda, es el SGBD quien serializa. Timeout de transacción en el
> pool de conexiones (30 s) actúa como guardián de último recurso.

### 4.2 `auctions.py`

**`create_auction(db, teacher_id, tenant_id, data)`**
- `expires_at = now() + timedelta(days=data.duration_days)`.
- INSERT `auctions(status='active', current_bid=0)`.

**`list_auctions(db, tenant_id, group_id=None)`**
- Retorna activas + cerradas recientes (últimas 24 h) para mostrar ganador en UI.

**`place_bid(db, bidder_id, tenant_id, auction_id, amount)`** — atómica
1. `SELECT auctions FOR UPDATE WHERE id=X AND tenant_id=Y AND status='active'`.
2. Si `expires_at < now()` → cerrar subasta (lazy close) → 409.
3. Si `amount <= auction.current_bid` → 422 "Puja mínima: current_bid + 1".
4. Refund al postor anterior si existe:
   `award_coins(db, highest_bidder_id, tenant_id, current_bid, 'auction_refund', {auction_id})`.
5. `debit_coins(db, bidder_id, tenant_id, amount, 'auction_bid', {auction_id})`.
6. INSERT `auction_bids`. UPDATE `auctions(current_bid, highest_bidder_id, highest_bidder_name)`.
7. `flush()`.

**`close_auction(db, auction_id, tenant_id)`** (teacher/admin o tarea futura)
- UPDATE `auctions SET status='ended', winner_id=highest_bidder_id`.
- No refund aquí: el bid ganador ya fue debitado y no se devuelve.

**`claim_auction_win(db, student_id, tenant_id, auction_id)`**
1. Verifica `status='ended' AND winner_id=student_id`.
2. INSERT `inventory(source='auction', status='available')`.
3. Retorna `ClaimOut`.

### 4.3 `inventory.py`

**`list_inventory(db, student_id, tenant_id)`**
- SELECT `inventory JOIN shop_items` WHERE `student_id=X AND tenant_id=Y`.
- Orden: `purchased_at DESC`.

**`mark_used(db, student_id, tenant_id, inventory_id)`**
- UPDATE `inventory SET status='delivered', activated_at=now()`.
- Verifica ownership (`student_id` + `tenant_id`).

---

## 5. Permisos

| Rol | Puede |
|---|---|
| teacher / admin | crear/desactivar ShopItem, crear/cerrar Auction (solo de su tenant) |
| student | listar ítems, comprar, pujar, listar su inventario, claim, marcar usado |
| student otro tenant | 403 (filtro tenant_id lo garantiza) |
| student otro grupo | 403 si ítem/subasta tiene `group_id` distinto al suyo |

---

## 6. Endpoints (`router.py`) — prefijo `/shop`

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/shop/items` | `get_current_user` | Listar ítems activos del tenant/grupo |
| POST | `/shop/items` | `require_teacher` | Crear ítem |
| PATCH | `/shop/items/{id}/deactivate` | `require_teacher` | Desactivar ítem |
| POST | `/shop/items/{id}/buy` | `get_current_user` | Comprar ítem (buy-now) |
| GET | `/shop/auctions` | `get_current_user` | Listar subastas activas |
| POST | `/shop/auctions` | `require_teacher` | Crear subasta |
| POST | `/shop/auctions/{id}/bid` | `get_current_user` | Pujar |
| POST | `/shop/auctions/{id}/close` | `require_teacher` | Cerrar subasta manualmente |
| POST | `/shop/auctions/{id}/claim` | `get_current_user` | Reclamar premio ganado |
| GET | `/shop/inventory` | `get_current_user` | Mi inventario |
| PATCH | `/shop/inventory/{id}/use` | `get_current_user` | Marcar ítem como usado |

---

## 7. Tests (`tests/shop/`)

**Unit (sin DB):**
- `test_bid_minimum_enforced` — puja = current_bid lanza 422; puja = current_bid + 1 pasa.
- `test_bid_refund_amount` — refund es exactamente el bid anterior (función pura).
- `test_purchase_closes_item_at_zero` — stock 1 → compra → is_active=False.

**Contract HTTP (sin DB, cliente de test):**
- `GET /shop/items` sin auth → 401.
- `POST /shop/items` con JWT estudiante → 403.
- `POST /shop/auctions/{id}/bid` sin auth → 401.

**Integration (skip con `pytest.mark.integration` hasta fixture testcontainers):**
- Compra concurrente: dos estudiantes compran el último ítem en paralelo — solo uno logra, el otro recibe 409.
- Puja: A puja 10, B puja 15 → A recibe refund 10, B es el nuevo highest_bidder.
- Aislamiento de tenant: estudiante de tenant_A no ve ítems de tenant_B.

---

## 8. Migración — campos faltantes en modelos existentes

Los modelos viven en `src/shared/models.py` (stubs en `src/shop/models.py`). Se detectaron
las siguientes discrepancias respecto al GDD:

| Modelo | Campo del GDD | Estado en shared/models.py | Acción |
|---|---|---|---|
| `ShopItem` | `remaining_quantity` (GDD §1.4) | Ausente; el modelo tiene `stock` | Crear alias en schema (`remaining_quantity = stock`) o añadir columna calculada. Preferir alias en Pydantic validator. |
| `ShopItem` | `group_id` (scope de grupo) | Ausente | Agregar `group_id UUID NULLABLE FK(groups.id)` en migración Alembic. |
| `Auction` | `expires_at` (GDD: default 7 días) | Ausente; hay `start_at` + `duration_seconds` | Añadir `expires_at TIMESTAMPTZ NOT NULL` en migración. Calcular al crear: `start_at + duration_days * interval '1 day'`. |
| `Auction` | `status` CHECK | Tiene `'active','ended','cancelled'`; spec dice `'closed'` | Usar `'ended'` (el modelo manda). Documentar alias en schema: `closed = ended`. |
| `Inventory` | `obtained_via` (GDD §1.4) | Campo se llama `source` con valores `'shop','auction','reward'` | Exponer `obtained_via` en `InventoryItemOut` como alias de `source`. |
| `Inventory` | `used` (bool simple, GDD) | Tiene `status` enum richer (`available/pending_delivery/delivered/expired/archived`) | Usar `status='delivered'` para "usado". Documentar en schema. |

Nueva migración Alembic: `add_shop_group_id_and_auction_expires_at`.

---

## 9. Pendiente / Fase D

- **Realtime "outbid":** cuando el postor anterior es superado, emitir evento WebSocket/SSE
  para que el front muestre el toast "You've been outbid!" (GAME-DESIGN-MVP §1.4). Diseño:
  publicar en `shared/events.py` post-refund; consumer en módulo `notifications` (Fase D).
- **Cierre automático de subastas expiradas:** tarea Celery/APScheduler que llame
  `close_auction()` a las `expires_at`. Por ahora el close es lazy (en `place_bid`) o manual.
- **Polling/realtime de marketplace:** el MVP hace polling cada 2500 ms. Engrama 2.0 usará
  SSE o WebSocket; diseño pendiente (Fase D).
- **God Mode admin:** override de coins sin validar pool (GAME-DESIGN-MVP §2) — fuera del MVP de Engrama.
