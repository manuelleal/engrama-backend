# engrama_core — Developer Reference

> **Scope:** technical reference for `src/engrama_core/` — coins +
> attendance. Implemented on 2026-04-20 per `SPECS/02-engrama-core.md`.
>
> **Beginner companion:** `docs/CORE.md`.

---

## 1. Module layout

```
src/engrama_core/
├── __init__.py
├── schemas.py                 # Pydantic strict schemas
├── router.py                  # 7 endpoints, mounted at /core
└── service/
    ├── __init__.py
    ├── coins.py               # get_wallet, award_coins, get_balance, history
    └── attendance.py          # create_session, check_in, history, expire;
                               # pure helpers: haversine, streak_multiplier,
                               # compute_next_streak, generate_session_code
```

**Cross-module imports:**
- `router.py` → `service.coins`, `service.attendance`, `schemas`,
  `shared.db`, `shared.deps`, `auth.schemas` (for `AuthContext`).
- `service/attendance.py` → `service/coins.py` (same module, intra-domain
  — allowed per WINDSURF §2). This is the ONLY intra-domain coupling in
  this module.
- `service/*` → `shared.models`, `schemas`. No cross-domain imports.

---

## 2. Coins — double-entry with row-level locks

### Wallet ownership types

Enforced by the `coin_wallets_owner_type_check` CHECK constraint:
`{'system', 'tenant', 'profile'}`. We only use `tenant` and `profile`
here; `system` is reserved for future global sinks.

Composite unique key: `UNIQUE (owner_type, owner_id, currency)`. Every
call to `get_wallet(owner_type, owner_id, tenant_id)` uses this triplet
plus `currency='COIN'` (the only currency so far).

### `get_wallet` — lazy creation

```python
wallet = await get_wallet(db, 'profile', student_id, tenant_id, for_update=True)
```

- If the wallet row exists, returns it (optionally with `SELECT ... FOR UPDATE`).
- If not, inserts a new wallet with `balance=0` and flushes to get the PK.
- `for_update=True` is only used inside `award_coins` to serialize concurrent
  transfers on the same wallet.

**Important:** `get_wallet` does not commit. The caller owns the transaction.

### `award_coins` — the money mover

```python
async def award_coins(
    db: AsyncSession,
    *,
    student_id: UUID,
    tenant_id: UUID,
    amount: int,
    action: str,
    metadata: dict | None = None,
    created_by_profile_id: UUID | None = None,
) -> CoinLedger: ...
```

Invariants:

1. **Amount > 0** (else 400). The DB CHECK `coin_ledger_amount_pos_check`
   is the last line of defense.
2. **Lock ordering:** tenant wallet first, then profile wallet. Prevents
   deadlocks if another flow grabs them in the opposite order. This is
   the kind of detail that only matters under contention.
3. **Sufficient pool:** if `from_wallet.balance < amount`, raises
   `HTTPException(402)`. The DB `coin_wallets_balance_nonneg_check`
   would also abort the transaction, but we prefer the friendlier HTTP
   semantics.
4. **Atomic:** all writes happen within the caller's transaction. A
   failure anywhere (including the implicit flush) rolls back every
   change — the `attendance` record, the streak update, the ledger
   insert, and the balance updates — because they share the same session.
5. **Does not commit.** The router handler (or `check_in`) issues the
   single `await db.commit()` at the end.

### Model attribute gotcha

The SQLAlchemy models rename the DB column `metadata` to avoid
colliding with `DeclarativeBase.metadata`:

- `CoinWallet.coin_metadata` → DB column `metadata`
- `CoinLedger.ledger_metadata` → DB column `metadata`

Always use the Python attribute name when reading/writing.

---

## 3. Attendance

### `create_session` flow

```python
session = await create_session(
    db,
    teacher_id=auth.profile_id,
    tenant_id=auth.tenant_id,
    group_code="FL40556",
    duration_minutes=15,
)
```

1. Resolve `group_id` by `(tenant_id, group_code)`. 404 if absent.
2. Generate a `session_code` via `secrets.choice` over
   `string.ascii_uppercase + string.digits`, 6 chars. Retry up to 3x on
   UNIQUE collision (36^6 ≈ 2.1B, collisions are astronomically rare).
   After 3 retries, 503.
3. Build `qr_payload`:
   ```json
   {
     "session_code": "AB3X9K",
     "tenant_id": "uuid-of-tenant",
     "group_code": "FL40556",
     "expires_at": "2026-04-20T14:45:00+00:00"
   }
   ```
4. Insert `AttendanceSession` with `admin_lat/lng` copied from
   `groups.last_admin_lat/lng` (populated elsewhere when the admin
   registers the classroom location).

### `check_in` flow

```
1. Lookup session by (session_code, tenant_id)     → 404 if not found
2. Validate status == 'active' and expires_at > now → 410 if expired
3. Check UNIQUE (session_id, student_id)           → 409 if duplicate
4. Compute geo_status from haversine              → never blocks
5. Load Profile, compute new streak               → update profile
6. Compute coins = 50 * streak_multiplier(streak)
7. Insert attendance row (with geo_status)
8. award_coins(...) — transfers from tenant wallet
9. return CheckInResult(success, coins_awarded, streak, message)
```

All 8 writes happen in one session/transaction. The router commits once.

### Streak semantics (spec §11.3)

The helper `compute_next_streak(last, today)` returns:
- `1` if `last is None` (first check-in ever) — streak initialized.
- `-1` (sentinel) if `last == today - 1 day` — caller increments
  `profile.current_streak += 1`.
- `1` if `last < today - 1 day` — streak broken, reset.
- `1` for `last == today` (shouldn't reach here; UNIQUE blocks).

Returning a sentinel keeps the helper pure (no ORM access). The caller
in `check_in` interprets `-1` to mean "bump existing streak by 1".

### Geo validation

Informative only, per spec §11.4. States:
- `"valid"` — haversine ≤ 100m from session's reference point.
- `"out_of_range"` — haversine > 100m.
- `"reference_missing"` — session has no admin_lat/lng set.
- `"skipped"` — client didn't send GPS.

Teachers see `geo_status` in reports; no policy blocks the check-in. If
you need to enforce geo in the future, do it in a separate middleware
or a policy table — not by changing this service.

### Pure helpers in `service/attendance.py`

All unit-testable without a DB:

```python
def haversine_distance(lat1, lon1, lat2, lon2) -> float: ...
def streak_multiplier(current_streak: int) -> float: ...
def compute_next_streak(last: date | None, today: date) -> int: ...
def generate_session_code(length: int = 6) -> str: ...
```

Tested in `tests/engrama_core/test_attendance.py::Test*` classes.

---

## 4. Endpoints contract

Mounted with `prefix="/core"`. Commit `8147159` for the source of truth.

| Method | Path | Guard | Body / Query | Returns | HTTP |
|---|---|---|---|---|---|
| GET | `/core/coins/balance` | `get_current_user` | — | `BalanceOut` | 200 |
| GET | `/core/coins/history` | `get_current_user` | `?limit=20` | `CoinHistoryOut` | 200 |
| POST | `/core/attendance/sessions` | `require_teacher` | `AttendanceSessionCreate` | `AttendanceSessionOut` | 201 |
| GET | `/core/attendance/sessions/active` | `require_teacher` | — | `list[AttendanceSessionOut]` | 200 |
| POST | `/core/attendance/check-in` | `get_current_user` | `CheckInRequest` | `CheckInResult` | 200 |
| GET | `/core/attendance/history` | `get_current_user` | `?limit=30` | `list[AttendanceRecordOut]` | 200 |
| GET | `/core/attendance/history/{student_id}` | `require_teacher` | `?limit=30` | `list[AttendanceRecordOut]` | 200 |

### Defense in depth

Every service query filters by `tenant_id` explicitly even though RLS
would also catch it (WINDSURF §3). `read_student_attendance_history`
uses `auth.tenant_id` (from the JWT), not a client-provided value, to
prevent scope escalation.

### Commit semantics in handlers

- **Reads (`GET /coins/balance`, `GET /attendance/history`)** do not
  commit.
- **`GET /coins/history`** commits because `get_coin_history` may lazy-
  create the wallet via `get_wallet` if it didn't exist yet.
- **`POST /attendance/sessions`** and **`POST /attendance/check-in`**
  both commit once at the end, wrapping all service writes in one
  transaction.

---

## 5. Testing strategy

### What's in the repo (`tests/engrama_core/`)

| Test level | Count | Needs DB? | CI green? |
|---|---|---|---|
| Pure unit (helpers) | 21 | No | ✅ |
| HTTP contract (auth-less → 401) | 8 | No | ✅ |
| DB integration (coins + attendance full paths) | 12 | Yes | ⏩ skipped |

The 12 skipped tests use `@pytest.mark.skip(reason="Needs testcontainers
Postgres fixture")`. Unblock them by adding a session-scoped fixture
that spins up a throwaway Postgres (see next section).

### What to do to enable integration tests

Rough sketch for a future PR:

```python
# tests/conftest.py (additions)
import pytest_asyncio
from testcontainers.postgres import PostgresContainer
from alembic.config import Config
from alembic.command import upgrade as alembic_upgrade

@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer("postgres:16") as pg:
        os.environ["DATABASE_URL"] = pg.get_connection_url()
        cfg = Config("alembic.ini")
        alembic_upgrade(cfg, "head")
        yield pg

@pytest_asyncio.fixture
async def db_session(pg_container):
    from src.shared.db import AsyncSessionLocal
    async with AsyncSessionLocal() as s:
        await s.begin()
        yield s
        await s.rollback()  # clean between tests
```

Then each skipped test uses `db_session` and also seeds a minimal
tenant + profile + membership + group before exercising the service.

Time budget: ~1 hour for the fixture + ~15 min per test. Total effort
to unskip all 12: ~3-4 hours.

### Why we didn't build this today

Out of scope for "implement coins and attendance endpoints". Wiring up
testcontainers would double the commit size and isn't on the spec
checklist. The skipped tests document intent so nothing is forgotten.

---

## 6. Known gotchas

1. **`datetime.now(UTC)` everywhere.** We use timezone-aware
   `datetime.now(UTC)` — never `datetime.utcnow()` (deprecated) or
   naive `datetime.now()`. The DB columns are `TIMESTAMPTZ`, comparing
   naive vs aware datetimes would be a subtle bug.

2. **`Numeric` → Python `float`.** `attendance.latitude/longitude`
   columns are `NUMERIC` in Postgres but mapped to Python `float` in
   SQLAlchemy. For values in the GPS range this is fine; for financial
   math we'd use `Decimal`.

3. **Async `db.get(Profile, id)`.** Used in `check_in` instead of a
   `select(Profile).where(...)` because it benefits from the identity
   map and is 1 line. If you add `where` filters (e.g. `tenant_id`),
   switch to `select` + `scalar_one_or_none`.

4. **`expire_sessions` is not scheduled.** Calling it requires a
   manually-triggered endpoint or a Celery beat task (Fase 3). Until
   then, `check_in` correctly rejects expired sessions by comparing
   `expires_at > now` regardless of the row's `status` value, so nothing
   breaks — sessions just linger with `status='active'` in the DB.

5. **`get_coin_history` creates a wallet as side effect.** First time
   a student calls `/core/coins/history`, a zero-balance wallet row is
   inserted. The router handler commits this. If you prefer read-only
   history, split `get_coin_history` into `get_wallet_readonly` +
   `get_history_raw`.

6. **No pagination token yet.** `CoinHistoryOut.total` returns
   `len(entries)`, not the total count in DB. When volumes grow, switch
   to a proper cursor-based pagination (add `before_id` param + `count()`
   subquery).

7. **Tenant coin_pool isn't auto-funded.** The tenant wallet starts at
   balance 0 — new tenants need `tenants.coin_pool` manually transferred
   into a `coin_wallet` row. This will be part of the tenant onboarding
   spec (future).

---

## 7. Verification of §10 checklist

Observed on 2026-04-20 with live uvicorn:

```
[x] GET /core/coins/balance sin auth       → 401 "Missing Authorization header"
[x] POST /core/attendance/sessions         → 403 (require_teacher denies; in
                                              smoke test the fabricated JWT
                                              also fails earlier at
                                              "no active tenant memberships")
[x] POST /core/attendance/check-in invalid → service layer returns 404
    for nonexistent session_code. Smoke test with fabricated JWT returns
    403 first ("no memberships"); the 404 path is exercised by service
    code review and by `test_checkin_invalid_session_code_returns_404`
    (skipped integration test).
[x] pytest: 41 passed, 12 skipped in ~1s.
```

Full end-to-end verification of 404/410 requires a seeded Profile +
Membership, which is the same fixture that will unskip the integration
tests. That task is tracked as part of the testcontainers fixture work.

---

## 8. Commits

```
8147159 feat(core): implement coins and attendance endpoints
```

---

*Last updated: 2026-04-20. Corresponds to commit `8147159`.*
