# Engrama — Backend

> **Status:** 🟡 Early-stage · work in progress — end of Phase 1 (walking skeleton).
> **4 of 12** planned domain modules are implemented and mounted. This is an
> actively developed project, **not** a finished or production-hardened product.

Engrama is an early-stage **EdTech platform for gamified English learning**,
built for multi-tenant institutions. It is the ground-up evolution of
**Lingo-Coins**, a vanilla-JavaScript MVP that ran in a real university
classroom (~97 students at Universidad Industrial de Santander, Colombia).

This repository is the **backend**: a modular monolith in FastAPI that owns all
business logic — the coin economy, attendance, AI-generated challenges and
ranking — behind a typed HTTP API.

📖 The full story of how this project grew out of the MVP:
[**From Lingo-Coins MVP to Engrama**](https://github.com/manuelleal) *(portfolio narrative)*.

---

## Why this exists

Lingo-Coins proved that a coin economy motivates English students, but it was a
single-file vanilla-JS app talking straight to the database from the browser:
no multi-tenancy, coin balances updated with optimistic locks that broke under
classroom concurrency, and all business rules scattered across a 4,700-line
`app.js`. Engrama rebuilds the same game on a foundation that can serve more than
one institution safely. Every hard rule below is a lesson learned from operating
the MVP with real students.

---

## What's implemented (and what isn't)

| Module | Capability | Status |
|---|---|---|
| `auth` | Supabase JWT validation, `/session`, `/me`, `/logout`, tenant membership resolution | ✅ Implemented |
| `engrama_core` — coins | **Double-entry** coin ledger with `SELECT … FOR UPDATE` locking | ✅ Implemented |
| `engrama_core` — attendance | QR check-in sessions, per-student streaks, history | ✅ Implemented |
| `challenge_engine` | Challenge CRUD, **AI question generation (Anthropic)**, attempts & scoring | ✅ Implemented |
| `leaderboard` | Per-group ranking by coins, with the caller's own rank even outside the top-N | ✅ Implemented |
| `shop` · `teachers` · `badges` · `bets` · `billing` · `question_bank` · `agents` · `webhooks` | Store & auctions, teacher dashboard, badges, betting, subscriptions, vector question bank, LLM agents, Grader webhook | 🔴 Scaffolding only (empty stubs) — **specs written, not built** |

The database schema is already ahead of the code: **26 SQLAlchemy models** and
**30 Alembic migrations** describe the whole target platform, so most pending
modules need *services and endpoints*, not new tables. Each pending module has a
written contract in [`SPECS/`](./SPECS).

**Tests:** `79 passed, 27 skipped` (the skipped ones are integration tests
waiting on a Postgres testcontainers fixture).

---

## Architecture at a glance

- **Modular monolith.** One deployable, domain folders under `src/` (`auth`,
  `engrama_core`, `challenge_engine`, …). Domains never import each other;
  anything shared lives in `src/shared/`.
- **Multi-tenant from day one.** Every row carries a `tenant_id` and **every
  query filters by it explicitly** — the single defense that keeps institutions'
  data isolated.
- **Money is double-entry.** Coins never appear from nowhere: every award is a
  transfer from the tenant's "central-bank" wallet to the student's wallet,
  written as one row in `coin_ledger` inside a single transaction, with row locks
  to survive concurrent classroom traffic. *(This directly replaces the MVP's
  optimistic-locking approach, which failed under load.)*
- **Pure logic separated from I/O.** Reward math, bid validation and badge
  criteria are pure, unit-testable functions; services only orchestrate the DB.
- **Spec-driven.** No module is written before its `SPECS/*.md` contract exists.
- **Didactic comments.** Comments explain the *business why*, because the founder
  learns the platform by reading its code.

### Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.11 |
| API | FastAPI + Pydantic v2 (strict, `extra="forbid"`) |
| Data | SQLAlchemy 2.x async + asyncpg · Alembic migrations |
| Database / Auth | Supabase (PostgreSQL + Auth for JWT issuance) |
| AI | Anthropic API (challenge generation) |
| Async (planned) | Celery + Redis |
| Tests | pytest + pytest-asyncio |
| Tooling | ruff · mypy · import-linter |

---

## API surface (live modules)

```
GET  /health

POST /auth/session            # exchange Supabase JWT → profile + memberships
GET  /auth/me
POST /auth/logout

GET  /core/coins/balance
GET  /core/coins/history
POST /core/attendance/sessions            # teacher opens a QR session
GET  /core/attendance/sessions/active
POST /core/attendance/check-in            # student checks in
GET  /core/attendance/history[/{student_id}]

POST /challenges/                         # create a challenge
POST /challenges/generate                 # AI-generate questions (Anthropic)
GET  /challenges/ · /challenges/all · GET /challenges/{id}
PATCH /challenges/{id}/status
POST /challenges/{id}/attempt · POST /challenges/attempts/{id}/submit
GET  /challenges/attempts/history

GET  /leaderboard?group_code=&limit=      # top-N + your own rank
```

Interactive docs are available at `/docs` when the API is running.

---

## Getting started

```bash
# 1. Install dependencies (Poetry)
poetry install

# 2. Configure environment
cp .env.example .env        # fill DATABASE_URL + Supabase keys

# 3. Run migrations
poetry run alembic upgrade head

# 4. Start the API
poetry run uvicorn src.main:app --reload
# → http://localhost:8000/docs
```

### Tests

Tests don't need a database or `.env`:

```bash
python -m pytest -q            # 79 passed, 27 skipped
python -m pytest tests/engrama_core -q
```

---

## Project structure

```
src/
├── main.py                # app factory + router wiring
├── shared/                # models, db, config, deps, exceptions (single source of truth)
├── auth/                  # ✅ JWT + membership
├── engrama_core/          # ✅ coins (double-entry) + attendance (QR + streaks)
│   └── service/           #    pure logic split from I/O
├── challenge_engine/      # ✅ challenges + AI generation + attempts
├── leaderboard/           # ✅ per-group ranking
└── shop · teachers · badges · bets · billing · question_bank · agents · webhooks   # 🔴 stubs
SPECS/                     # per-module contracts (00–09)
alembic/versions/          # 30 migrations
tests/                     # unit + contract (401) + skipped integration
```

---

## My role in this project

This backend is built with an **AI-assisted, spec-driven workflow**: I act as
product owner, learning designer and architect, and drive implementation through
Claude Code against written specifications. My contribution is the *design and the
rules* — the multi-tenant model, the double-entry economy, the pedagogical reward
logic, and the engineering constraints that keep it honest — plus reviewing and
integrating every module. See the portfolio narrative for the full breakdown of
learning design, product thinking, educational UX and AI-assisted development.

---

## Roadmap (short)

1. **Unblock** — Postgres testcontainers fixture (unlocks 27 integration tests) + CI.
2. **Parity with the MVP** — implement `shop`/auctions, `teachers`, `badges`,
   announcements and challenge-economy v2 (reward mastery, not speed).
3. **Frontend walking skeleton** ([`engrama-web`](https://github.com/manuelleal)).
4. **Prove it teaches** — pre/post CEFR measurement with real students.

---

*Engrama is a work in progress and is not affiliated with any commercial release.
Built in Bucaramanga, Colombia.*
