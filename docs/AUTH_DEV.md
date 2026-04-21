# Auth Module — Developer Reference

> **Scope:** technical reference for the `src/auth/` module plus the RLS
> policies migration `029_rls_policies`. Both were implemented on
> 2026-04-20.
>
> **Audience:** developers who will read, extend, or debug this code.
>
> **Beginner-friendly companion:** `docs/AUTH.md`.

---

## 1. Module layout

```
src/auth/
├── __init__.py       # empty
├── schemas.py        # Pydantic v2 strict: MembershipOut, ProfileOut, AuthContext
├── service.py        # Pure-ish business logic (HTTPException allowed)
├── router.py         # FastAPI router: POST /session, GET /me, POST /logout
└── models.py         # empty by design — ORM models live in shared/models.py

src/shared/
├── config.py         # pydantic-settings; loads .env; normalizes DB DSN
├── db.py             # AsyncEngine + get_db dep
└── deps.py           # get_current_user, require_teacher, require_admin

alembic/versions/
└── 029_rls_policies.py   # 51 RLS policies (38 tenant_isolation + 13 specials)

tests/
├── conftest.py            # Sets env vars before src.shared.config import
└── auth/
    ├── conftest.py        # make_jwt() helper + 3 token fixtures
    ├── test_validate_jwt.py
    └── test_auth_endpoints.py
```

All cross-module imports respect **WINDSURF §2 dependency rule**:
- `router.py` → `service.py`, `schemas.py`, `shared.deps`, `shared.db`.
- `service.py` → `shared.models`, `shared.config`, `schemas`.
- `shared/deps.py` → imports from `src.auth` — **deliberately allowed**
  because `shared/deps.py` is the project-wide infrastructure layer
  (same rationale as `shared/events.py` per ADR-003).

---

## 2. JWT validation (`service.validate_jwt`)

### Algorithm and claims

- **Algorithm:** HS256 (Supabase default). Not RS256.
- **Secret:** `settings.supabase_jwt_secret`, loaded from `.env`.
- **Verified claims:**
  - `exp` (automatic via `jose.jwt.decode`)
  - `aud == "authenticated"` (passed as `audience=...`)
  - `sub` must be present and non-empty (explicit check after decode;
    `jose` does not enforce it).
- **Not verified:**
  - `iss` varies per Supabase project (sometimes `"supabase"`, sometimes
    the project URL). Trusting the HS256 signature is sufficient.
  - `role` claim of the JWT is always `"authenticated"`; the actual app
    role lives in `profiles.role` / `memberships.role`.

### Error model

All validation failures raise `HTTPException(401)` with
`WWW-Authenticate: Bearer` header (RFC 7235 compliant). FastAPI never
returns 422 for missing auth in this module because `get_current_user`
uses `Header(default=None)` and raises manually.

```python
# src/auth/service.py
def validate_jwt(token: str) -> dict[str, Any]:
    payload = jwt.decode(
        token,
        settings.supabase_jwt_secret,
        algorithms=["HS256"],
        audience="authenticated",
    )
    if not payload.get("sub"):
        raise HTTPException(401, "JWT payload missing 'sub' claim", ...)
    return payload
```

---

## 3. Dependency injection chain

```
HTTP request
    │
    ▼
┌─────────────────────────────────────────────────────┐
│ get_db (shared/db.py)                                │
│   → AsyncSession (service_role connection)           │
└─────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────┐
│ get_current_user (shared/deps.py)                    │
│   1. _extract_bearer_token(authorization header)     │
│   2. validate_jwt(token)            → payload dict   │
│   3. UUID(payload["sub"])           → profile_id     │
│   4. get_or_create_profile(db, ...) → Profile ORM    │
│   5. get_memberships(db, ...)       → [(M, T), ...]  │
│   6. build_auth_context(...)        → AuthContext    │
└─────────────────────────────────────────────────────┘
    │
    ▼
  router handler receives `auth: AuthContext`
```

Role-restricted endpoints wrap `get_current_user`:

```python
# For teacher-only endpoints
async def require_teacher(auth: AuthContext = Depends(get_current_user)) -> AuthContext:
    if not auth.is_teacher and not auth.is_admin:
        raise HTTPException(403, "Teacher role required")
    return auth
```

`is_teacher` is `True` for `{teacher, admin, super_admin}`.
`is_admin` is `True` for `{admin, super_admin}`.

---

## 4. AuthContext and tenant resolution

`AuthContext` is the per-request identity object passed to every
downstream service. It carries the **active tenant**, resolved in
`build_auth_context`:

1. If header `X-Tenant-ID: <uuid>` is present:
   - Must parse as UUID (else `400`).
   - Must match one of the user's active memberships (else `403`).
2. If absent: the first active membership wins (arbitrary but stable).
3. If the user has no active memberships: `403`.

This is the hook for multi-tenant users (e.g. a teacher affiliated to
two universities). The frontend sets `X-Tenant-ID` after the user picks
a tenant in a switcher UI.

---

## 5. The `get_or_create_profile` fallback

**This is a development convenience, not production logic.** If a JWT
arrives for a Supabase Auth user that has no mirror row in
`public.profiles`, the backend creates a stub:

- `id` = JWT `sub`
- `documento_id` = first 8 hex chars of sub (unique because derived from UUID)
- `full_name` = JWT `email` or `"User <sub[:8]>"`
- `pin_hash` = `""` (user must set it in onboarding flow)

Production onboarding will create the Profile deliberately with real
`documento_id`, hashed PIN, and assign at least one `Membership`. The
fallback prevents dev friction while that spec is pending.

**Implication:** a user with a valid JWT but no `memberships` row will
authenticate (step 4 succeeds) but fail at step 6 with
`403 User has no active tenant memberships`. This is the correct
behaviour.

---

## 6. Endpoints contract

| Method | Path | Dep | Body | Returns | Notes |
|---|---|---|---|---|---|
| POST | `/auth/session` | `get_current_user` | empty | `ProfileOut` | Called once post-login by frontend. |
| GET  | `/auth/me`      | `get_current_user` | —     | `ProfileOut` | Idempotent refresh. |
| POST | `/auth/logout`  | `get_current_user` | empty | `{"status":"ok"}` | Writes audit_logs row; real logout is frontend-side. |

`ProfileOut` fields (all strict, `extra="forbid"`):

```python
id: UUID
documento_id: str
full_name: str
role: str
current_streak: int
longest_streak: int
xp: int
level: int
is_active: bool
last_attendance_date: date | None
memberships: list[MembershipOut]
```

The `logout` handler writes directly to `audit_logs` via parameterized
`text()` SQL to avoid coupling `auth/` to an audit ORM model (the audit
domain is not yet carved out). The SQL is parameter-bound, not
concatenated (WINDSURF §9).

---

## 7. Configuration

`src/shared/config.py` uses `pydantic-settings` with `env_file=".env"`
and `extra="ignore"`. Required fields (no default, will fail-fast at
boot if missing):

- `SUPABASE_JWT_SECRET`
- `DATABASE_URL`

Optional fields have safe defaults (empty string or reasonable value).

`DATABASE_URL` is normalized in a `field_validator` to always use the
`postgresql+asyncpg://` scheme. This means either of these work in
`.env`:

```
DATABASE_URL=postgresql://user:pass@host/db            # gets +asyncpg injected
DATABASE_URL=postgresql+asyncpg://user:pass@host/db    # untouched
DATABASE_URL=postgres://user:pass@host/db              # legacy; normalized
```

Same normalization happens in `alembic/env.py` — intentional duplication
to keep alembic independent of the app import graph.

---

## 8. Database session (`shared/db.py`)

Fase 1 (Walking Skeleton per ARQUITECTURA §10) uses a single connection
pool with `service_role` credentials:

```python
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)
```

`service_role` bypasses RLS. Tenant isolation is enforced in-code via
explicit `WHERE tenant_id = ...` filters in every service (defense in
depth, WINDSURF §3). RLS remains active in the DB as the second layer.

Future work (ADR-003): add `get_user_session` that opens a connection
with the end-user's JWT so RLS applies. Not needed for Fase 1.

---

## 9. RLS migration `029_rls_policies`

Applied on 2026-04-20. Total: **51 policies** (spec minimum: 40+).

### Base pattern (38 policies on 19 tables)

For each table in section 1 of `SPECS/00b-rls-policies.md`:

```sql
CREATE POLICY "tenant_isolation_select" ON <table>
  FOR SELECT TO authenticated
  USING (tenant_id IN (SELECT tenant_id FROM memberships
                       WHERE profile_id = auth.uid() AND is_active = TRUE));

CREATE POLICY "tenant_isolation_insert" ON <table>
  FOR INSERT TO authenticated
  WITH CHECK (... same subquery ...);
```

Exception: `challenge_questions` has no `tenant_id` column (inherits via
FK to `challenges`). The migration uses a JOIN-based variant for that
table. Semantically identical.

### Special policies (13)

Covered tables:
- `profiles` (4): select_own, select_teacher, select_admin, update_own
- `tenants` (1): select_admin
- `coin_wallets` (1): select_own
- `coin_ledger` (1): select_own
- `challenges` (3): select_student, select_teacher, insert_teacher
- `audit_logs` (1): select_staff
- `badges` (1): select_all (allows `tenant_id IS NULL`)
- `question_bank` (1): select (allows `tenant_id IS NULL`)

`question_bank` ends up with **3 policies** (2 base + 1 special) by design.
PG policies of the same command combine with OR, producing the net semantics
"tenant matches OR tenant_id IS NULL" required by spec 2.8.

### Verification query

```sql
SELECT tablename, policyname, cmd
FROM pg_policies WHERE schemaname = 'public'
ORDER BY tablename, policyname;
-- Expect 51 rows.
```

### Downgrade

`029.downgrade()` drops all 51 policies in reverse order. Safe to re-run
`upgrade head` afterwards.

---

## 10. Testing strategy

### Unit tests — `test_validate_jwt.py` (5 tests)

Direct calls to `validate_jwt()` with JWTs forged by
`tests/auth/conftest.py::make_jwt`. No FastAPI, no DB.

Cases:
- Valid token returns decoded payload.
- Expired token (`expires_in=-10`) → 401.
- Wrong signature (secret mismatch) → 401.
- Malformed string → 401.
- Missing `sub` claim (forced `sub=""`) → 401.

### Integration tests — `test_auth_endpoints.py` (8 tests)

Uses `fastapi.testclient.TestClient(app)`. Covers the HTTP surface
**without hitting the real DB** because all cases intentionally fail
before the DB query:

- No `Authorization` header → 401.
- Malformed header (`NotBearer abc`) → 401.
- Empty bearer (`Bearer `) → 401.
- Invalid signature → 401.
- Expired → 401.
- Missing header on `/auth/session` → 401.
- Missing header on `/auth/logout` → 401.
- `/health` still public → 200.

### Not covered yet

- 200 happy path (`/auth/me` with valid token + seeded DB). Needs a
  test-containers Postgres fixture. Deferred to Fase 1 integration test
  suite.

### Running

```bash
poetry run pytest tests/auth/ -v
# 13 passed in ~0.7s
```

### Test JWT secret

Set once in `tests/conftest.py` at import time (before
`src.shared.config` loads):

```python
os.environ.setdefault("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
```

The DB URL is a throwaway because tests never open a real connection.

---

## 11. Extension points

### Adding a new role-restricted endpoint

```python
# src/somewhere/router.py
from fastapi import APIRouter, Depends
from src.auth.schemas import AuthContext
from src.shared.deps import require_teacher

router = APIRouter()

@router.post("/challenges")
async def create_challenge(
    payload: ChallengeCreate,
    auth: AuthContext = Depends(require_teacher),
):
    # auth.tenant_id is guaranteed set
    # auth.is_teacher is True
    ...
```

### Adding a new config field

1. Add `Field(...)` to `Settings` in `src/shared/config.py`.
2. Add to `.env.example` (NEVER `.env`).
3. Use via `settings.my_field`.

### Moving audit_logs write to its own module

The `POST /auth/logout` handler currently writes directly to `audit_logs`
via raw SQL. When the audit domain gets carved out:

1. Create `src/audit/service.py` with `async def log_action(...)`.
2. Expose it through `src/shared/events.py::publish_audit` (per
   ARQUITECTURA §6 ADR-001 + WINDSURF §2).
3. Replace the raw SQL in `auth/router.py::logout` with a call to that
   event/service.

---

## 12. Known gotchas

1. **FastAPI `Header(...)` returns 422**, not 401, when the header is
   missing. We use `Header(default=None)` and raise 401 manually to
   match the spec contract.

2. **asyncpg requires `audience` validation explicitly.** If you drop
   `audience="authenticated"` from `jwt.decode`, `python-jose` will
   still accept tokens with that claim, but you lose defense against
   tokens from other Supabase audiences (e.g. service_role JWTs).

3. **`Profile` PK is not auto-generated.** Unlike other tables,
   `profiles.id` has no `DEFAULT gen_random_uuid()` — it must equal
   `auth.users.id` from Supabase Auth. `get_or_create_profile`
   therefore passes the UUID explicitly.

4. **`pin_hash` NOT NULL.** The stub uses `""`. If you later enforce
   hash validity (non-empty, bcrypt-formatted), you'll trip the
   fallback — add a migration that makes `pin_hash` nullable or provide
   a dev-only placeholder hash.

5. **`.env` in tests.** `tests/conftest.py` sets env vars via
   `os.environ.setdefault`. If your shell has real Supabase credentials
   exported, they'll win over the test defaults. Use a subshell or
   unset them before running tests in CI.

---

## 13. Commits of the day (2026-04-20)

```
7207500 feat(auth): implement JWT validation and /auth/me endpoint
e9a8fc5 docs: update handoff post 029_rls_policies
5643f7f chore(db): add RLS policies migration 029
```

---

*Last updated: 2026-04-20. Corresponds to commit `7207500`.*
