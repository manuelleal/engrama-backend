# ENGRAMA 2.0 — Arquitectura del Sistema

> **Versión:** 2.0  
> **Estado del documento:** Vivo (se actualiza conforme evoluciona el proyecto)  
> **Fundador:** Christiam Manuel Puentes Leal  
> **Arquitecto / Planificador:** Claude (Anthropic)  
> **Stack decidido:** Next.js 14 + FastAPI + Supabase + Celery + Docker
> **Filosofía:** Ambicioso estructuralmente, disciplinado en la ejecución.

---

## 📑 ÍNDICE

1. [Qué es este documento y cómo se usa](#1-qué-es-este-documento-y-cómo-se-usa)
2. [Relación con Lingo Coins (MVP)](#2-relación-con-lingo-coins-mvp)
3. [Los 3 productos del ecosistema](#3-los-3-productos-del-ecosistema)
4. [Stack tecnológico (decidido)](#4-stack-tecnológico-decidido)
5. [Arquitectura macro (diagrama de capas)](#5-arquitectura-macro-diagrama-de-capas)
6. [Decisiones arquitectónicas resueltas](#6-decisiones-arquitectónicas-resueltas)
7. [Estructura de repositorios](#7-estructura-de-repositorios)
8. [Reglas de modularidad (dependency rule)](#8-reglas-de-modularidad-dependency-rule)
9. [Multi-tenancy y seguridad de datos](#9-multi-tenancy-y-seguridad-de-datos)
10. [Estrategia de activación por fases](#10-estrategia-de-activación-por-fases)
11. [Glosario rápido](#11-glosario-rápido)

---

## 1. Qué es este documento y cómo se usa

Este es el **documento maestro de Engrama 2.0**. No es un README, no es un roadmap, no es documentación de API. Es la **constitución del proyecto**: las reglas que no cambian sin una discusión explícita.

### Cómo se usa:

- **Al empezar cualquier chat nuevo con Claude:** pega este archivo o menciona "lee ARQUITECTURA.md".
- **Al configurar Windsurf:** este archivo va en la raíz del repo y se referencia desde `WINDSURF.md` / `.windsurfrules`.
- **Al tomar una decisión técnica:** si contradice este documento, primero se actualiza este documento y se justifica el cambio en la sección "Historial de cambios".
- **Al onboardear a alguien (dev, profesor, inversionista):** este es el primer archivo que leen.

### Cómo NO se usa:

- ❌ No es para documentación operativa (eso va en `README.md` y `RUNBOOK.md`).
- ❌ No es para explicar cada endpoint (eso va en OpenAPI auto-generado por FastAPI).
- ❌ No es para tracking de tareas (eso va en `ENGRAMA_ROADMAP.md`).

---

## 2. Relación con Lingo Coins (MVP)

**Lingo Coins** es el MVP actual (`coins-mvp` en GitHub Pages, vanilla JS, Supabase directo desde el cliente, 97 estudiantes en UIS grupo Foreign Language 40556).

**Engrama 2.0** es un proyecto **completamente nuevo**, en repositorio separado, con arquitectura distinta. No es una refactorización.

### Reglas de convivencia:

1. **Lingo Coins NO se toca** hasta que Engrama 2.0 tenga paridad funcional (Fase 2 completa).
2. **Los 97 estudiantes siguen en Lingo Coins** durante toda la construcción de Engrama 2.0.
3. **Migración de datos:** cuando Engrama 2.0 esté listo, se migran usuarios + transacciones + attendance desde la DB de Lingo Coins mediante scripts one-shot (no hay sincronización continua).
4. **Aprendizaje, no código:** lo que se reutiliza de Lingo Coins es el *diseño visual*, las *decisiones de gamificación*, y el *contenido*. El código fuente no se copia.

---

## 3. Los 3 productos del ecosistema

Engrama 2.0 es un **ecosistema**, no una app. Tres productos interconectados:

### 3.1 Engrama (core SaaS)
Plataforma institucional gamificada. Los estudiantes ven una app móvil-first con coins, challenges, leaderboards y tienda. Los profesores tienen dashboard de analytics y generación de contenido. Las instituciones pagan licencia B2B.

**Modelo de negocio:** suscripción mensual por institución (tier por número de estudiantes).

### 3.2 Grader (satélite)
Servicio independiente de visión artificial. Profesor fotografía exámenes físicos → Grader los califica → envía resultados a Engrama vía webhook → Engrama convierte errores en challenges personalizados.

**Estado:** ya tiene una versión funcional (separado de Lingo Coins). Se integra vía webhook, no se fusiona.

**Modelo de negocio:** puede venderse independiente a instituciones que no usan Engrama core.

### 3.3 Question Bank API (DaaS)
Base de datos vectorial (pgvector) con preguntas de "inglés real" extraídas de fuentes auténticas (YouTube, podcasts, etc.) vía agentes LLM. Se expone como API REST pública.

**Modelo de negocio:** usage-based billing vía Stripe — cobro por consumo (ej: $0.01 por pregunta generada).

**Clientes potenciales:** otras EdTech, profesores independientes, plataformas de idiomas.

---

## 4. Stack tecnológico (decidido)

Estas decisiones están **cerradas**. Cambiarlas requiere reescribir este documento.

### 4.1 Frontend — Web (estudiantes + profesores + admins)

| Tecnología | Propósito |
|---|---|
| **Next.js 14** (App Router) | Framework React con server components y server actions |
| **TypeScript** (strict) | Tipado obligatorio, nada de `any` salvo justificación |
| **Tailwind CSS** | Utility-first para estilos |
| **shadcn/ui** | Librería de componentes accesibles (copy-paste, no dependencia) |
| **Zustand** | State management para estado cliente complejo |
| **TanStack Query** (React Query) | Data fetching, caché, revalidación |
| **Supabase JS client** | Solo para auth (login/logout/session), NO para queries de datos |
| **Lucide icons** | Iconografía (consistente con Lingo Coins) |

### 4.2 Backend — API principal

| Tecnología | Propósito |
|---|---|
| **Python 3.11+** | Lenguaje |
| **FastAPI** | Framework ASGI (async, tipado) |
| **Pydantic v2** | Validación y serialización |
| **SQLAlchemy 2.x** (async) + **asyncpg** | ORM y driver de PostgreSQL |
| **Alembic** | Migraciones de schema |
| **python-jose** | Validación de JWT emitidos por Supabase Auth |
| **httpx** | Cliente HTTP (llamadas a Anthropic API, webhooks) |

### 4.3 Base de datos

| Tecnología | Propósito |
|---|---|
| **Supabase PostgreSQL** | DB principal (managed) |
| **Supabase Auth** | Solo emisión de JWT, nada más |
| **Supabase Storage** | Archivos (fotos de exámenes, avatares) |
| **pgvector** (extensión) | Búsqueda semántica para Question Bank |
| **Row Level Security (RLS)** | Aislamiento multi-tenant a nivel motor |

### 4.4 Trabajos asíncronos

| Tecnología | Propósito |
|---|---|
| **Celery** | Broker de tareas |
| **Redis** | Broker + backend de resultados + caché |
| **Flower** (dev) | UI para monitorear workers |

### 4.5 Servicios externos

| Servicio | Propósito |
|---|---|
| **Anthropic API (Claude)** | Generación de preguntas, NLP cleanup, análisis |
| **Stripe** | Suscripciones B2B + usage-based billing |
| **Resend** | Emails transaccionales |
| **Sentry** | Error tracking (frontend + backend) |

### 4.6 Infraestructura y dev tools

| Tecnología | Propósito |
|---|---|
| **Docker + Docker Compose** | Entorno de desarrollo reproducible |
| **WSL2** (obligatorio en Windows) | Linux dentro de Windows para Docker + Redis |
| **GitHub Actions** | CI/CD |
| **Vercel** | Hosting frontend (Next.js) |
| **Railway o Fly.io** | Hosting backend + Celery + Redis |
| **pytest** | Tests backend |
| **Vitest + Playwright** | Tests frontend (unit + e2e) |

---

## 5. Arquitectura macro (diagrama de capas)

```
╔══════════════════════════════════════════════════════════════════╗
║                    USUARIOS Y CLIENTES                           ║
║  📱 Estudiantes (mobile web)                                     ║
║  💻 Profesores (desktop web)                                     ║
║  🏫 Admins institucionales                                       ║
║  🤖 Clientes API (Question Bank)                                 ║
╚══════════════════════════════════════════════════════════════════╝
                            ↓↑ HTTPS
╔══════════════════════════════════════════════════════════════════╗
║            FRONTEND — Next.js 14 (Vercel)                        ║
║  ┌────────────────────────────────────────────────────────────┐  ║
║  │ app/          (rutas App Router)                           │  ║
║  │ features/     (dominios: coins, challenges, bets, shop...) │  ║
║  │ components/ui (shadcn primitives)                          │  ║
║  │ lib/          (supabase client, api client, utils)         │  ║
║  │ stores/       (zustand)                                    │  ║
║  └────────────────────────────────────────────────────────────┘  ║
║                                                                  ║
║  Responsabilidades:                                              ║
║  - UI y UX                                                       ║
║  - Login (via Supabase Auth JS)                                  ║
║  - Llamadas al backend con JWT en headers                        ║
║  - NO contiene lógica de negocio crítica                         ║
║  - NO habla directo con la DB (salvo Supabase Auth)              ║
╚══════════════════════════════════════════════════════════════════╝
                            ↓↑ REST + JWT
╔══════════════════════════════════════════════════════════════════╗
║          BACKEND — FastAPI (Railway/Fly.io)                      ║
║  ┌────────────────────────────────────────────────────────────┐  ║
║  │ src/                                                       │  ║
║  │  ├── auth/            (valida JWT, inyecta tenant_id)     │  ║
║  │  ├── engrama_core/    (coins, streaks, attendance)        │  ║
║  │  ├── challenge_engine/(generación y resolución)           │  ║
║  │  ├── bets/            (apuestas entre estudiantes)        │  ║
║  │  ├── shop/            (tienda y recompensas)              │  ║
║  │  ├── badges/          (logros)                            │  ║
║  │  ├── teachers/        (dashboard profesor)                │  ║
║  │  ├── question_bank/   (API pública, pgvector)             │  ║
║  │  ├── agents/          (youtube scraper, nlp cleaner)      │  ║
║  │  ├── billing/         (stripe, metering)                  │  ║
║  │  ├── webhooks/        (grader integration)                │  ║
║  │  └── shared/          (models, db, deps, config)          │  ║
║  └────────────────────────────────────────────────────────────┘  ║
║                                                                  ║
║  Responsabilidades:                                              ║
║  - TODA la lógica de negocio                                     ║
║  - Validación de permisos (además de RLS)                        ║
║  - Comunicación con servicios externos (Claude, Stripe)          ║
║  - Encolar tareas a Celery                                       ║
╚══════════════════════════════════════════════════════════════════╝
          ↓↑ PostgreSQL         ↓ enqueue              ↑ webhook
╔═══════════════════════╗  ╔══════════════════════╗  ╔═══════════════╗
║  SUPABASE PostgreSQL  ║  ║ CELERY WORKERS       ║  ║ GRADER        ║
║  - Tablas con RLS     ║  ║ - youtube_scraper    ║  ║ (satélite,    ║
║  - tenant_id en todas ║  ║ - nlp_cleaner        ║  ║  separado)    ║
║  - pgvector           ║  ║ - daily_challenge_gen║  ║               ║
║  - Storage            ║  ║ - analytics          ║  ║               ║
╚═══════════════════════╝  ╚══════════════════════╝  ╚═══════════════╝
                                   ↓↑
                           ┌───────────────┐
                           │    REDIS      │
                           │ (broker+cache)│
                           └───────────────┘
```

---

## 6. Decisiones arquitectónicas resueltas

Cada decisión aquí tiene: **contexto**, **opciones consideradas**, **decisión**, **consecuencias**. Esto es un mini-ADR (Architecture Decision Record).

### 6.1 ADR-001: Monolito Modular vs Microservicios

- **Contexto:** Engrama tendrá 3 productos interconectados. ¿Separarlos en servicios independientes desde día 1?
- **Opciones:**
  - (A) Monolito clásico (todo junto, todo importa todo)
  - (B) Microservicios (cada producto su propio servicio + DB)
  - (C) **Monolito modular** (un solo deploy, pero dominios aislados internamente)
- **Decisión:** **(C) Monolito modular**. Velocidad de monolito, disciplina de microservicios. Question Bank y Grader pueden separarse en el futuro sin reescribir.
- **Consecuencias:** Requiere enforzar la [regla de dependencias](#8-reglas-de-modularidad-dependency-rule). Si se viola, se degrada a monolito clásico.

### 6.2 ADR-002: FastAPI propio vs Supabase Edge Functions puras

- **Contexto:** ¿Para qué backend propio si Supabase tiene Edge Functions?
- **Opciones:**
  - (A) Solo Supabase (Edge Functions + RLS + RPC)
  - (B) **FastAPI como backend principal + Supabase como DB/Auth/Storage**
- **Decisión:** **(B)**. Edge Functions no soportan Celery, son limitadas para agentes LLM largos, y el tipado TypeScript no se comparte con Python. FastAPI da control total.
- **Consecuencias:** Perdemos "gratis" el RLS cuando usamos `service_role`. Se compensa con [ADR-003](#63-adr-003-cómo-usamos-rls-con-fastapi).

### 6.3 ADR-003: Cómo usamos RLS con FastAPI

- **Contexto:** FastAPI puede conectarse con `service_role` (bypassa RLS) o con el JWT del usuario (respeta RLS). ¿Cuál elegimos?
- **Opciones:**
  - (A) Siempre `service_role` + lógica de tenant en Python
  - (B) Siempre JWT del usuario + depender 100% de RLS
  - (C) **Híbrido: JWT del usuario por defecto, `service_role` solo para tareas administrativas explícitas**
- **Decisión:** **(C)**. El 95% de las queries usa el JWT del usuario (defensa en profundidad: código Python + RLS). El 5% administrativo (migraciones, agentes LLM, webhooks de Stripe, Celery tasks) usa `service_role` con un wrapper que loguea cada uso.
- **Consecuencias:** Requiere dos tipos de "session" en SQLAlchemy: `user_session` y `admin_session`. Están en `shared/db.py`.

### 6.4 ADR-004: Shared Database, Shared Schema (multi-tenant)

- **Contexto:** ¿Cómo aislar datos de múltiples instituciones (UIS, UDES, UPB...)?
- **Opciones:**
  - (A) Una DB por tenant (máximo aislamiento, máximo costo)
  - (B) Un schema por tenant (medio y medio)
  - (C) **Shared DB + tenant_id en cada tabla + RLS** (eficiente, escalable)
- **Decisión:** **(C)**. Estándar de la industria. Soporta miles de tenants.
- **Consecuencias:** `tenant_id` es **obligatorio** en toda tabla transaccional. Las políticas RLS se generan con un patrón estándar (ver `shared/rls.py`).

### 6.5 ADR-005: Comunicación Grader → Engrama

- **Contexto:** Grader es un servicio ya existente, separado.
- **Opciones:**
  - (A) Fusionar Grader en Engrama
  - (B) REST API (Engrama pregunta a Grader)
  - (C) **Webhooks (Grader avisa a Engrama)**
- **Decisión:** **(C)**. Desacoplamiento máximo, Grader no necesita saber si Engrama está arriba o no (eventos eventualmente consistentes).
- **Consecuencias:** Endpoint `POST /webhooks/grader-result` con HMAC signature obligatoria. Idempotencia por `event_id`.

### 6.6 ADR-006: Dónde vive el dominio de negocio

- **Contexto:** La lógica de "dar coins" puede vivir en (1) frontend, (2) backend, (3) procedures SQL, (4) RLS.
- **Decisión:** **Toda la lógica de negocio vive en el backend (capa de servicios por dominio).** El frontend solo muestra. La DB solo guarda. RLS solo protege.
- **Consecuencias:** Frontend no calcula coins. SQL no tiene procedures complejos. RLS solo filtra, no computa.

### 6.7 ADR-007: TypeScript estricto + Pydantic estricto

- **Contexto:** Los tipos pueden ser laxos (`any`, `dict`) o estrictos.
- **Decisión:** **Strict mode obligatorio en ambos lados.** `tsconfig.json` con `strict: true`. Pydantic con `model_config = ConfigDict(strict=True, extra="forbid")`.
- **Consecuencias:** Curva inicial más dura, pero errores atrapados en tiempo de compilación, no en producción.

### 6.8 ADR-008: Contratos de API compartidos

- **Contexto:** ¿Cómo mantener sincronizados los tipos de TS con los de Python?
- **Opciones:**
  - (A) Duplicar manualmente (inevitablemente desincronizado)
  - (B) **Generar tipos TS desde el OpenAPI de FastAPI**
- **Decisión:** **(B)**. FastAPI genera `/openapi.json` automáticamente. Una herramienta (`openapi-typescript`) genera los tipos TS en `frontend/lib/api-types.ts`.
- **Consecuencias:** Un comando en CI regenera los tipos. Si el backend cambia un contrato, el frontend deja de compilar hasta actualizar.

---

## 7. Estructura de repositorios

### 7.1 Estrategia: monorepo vs multi-repo

**Decisión: multi-repo.** Tres repositorios separados:

```
engrama-web/        → Frontend Next.js (Vercel)
engrama-backend/    → Backend FastAPI + Celery (Railway)
engrama-grader/     → Satélite ya existente (NO se toca por ahora)
```

**Razones:**
- Deploy independiente (frontend a Vercel, backend a Railway)
- Permisos distintos (eventualmente devs solo-frontend)
- CI/CD más simple por repo
- Grader ya está separado y funcionando

**En el futuro (solo si duele):** considerar monorepo con Turborepo si la sincronización de tipos se vuelve fricción alta.

### 7.2 `engrama-backend/` (estructura detallada)

```
engrama-backend/
├── alembic/
│   ├── versions/              # Migraciones generadas
│   └── env.py
│
├── src/
│   ├── main.py                # Punto de entrada FastAPI
│   │
│   ├── shared/                # 🔧 Infraestructura compartida
│   │   ├── config.py          # Settings con pydantic-settings
│   │   ├── db.py              # Sessions: user_session, admin_session
│   │   ├── deps.py            # Dependencies: get_current_user, get_tenant
│   │   ├── exceptions.py      # Excepciones custom
│   │   ├── logging.py         # Structured logging
│   │   ├── rls.py             # Helpers para aplicar RLS policies
│   │   └── celery_app.py      # Configuración Celery
│   │
│   ├── auth/                  # 🔐 Autenticación y tenants
│   │   ├── router.py          # /auth/session, /auth/me
│   │   ├── service.py         # Validación JWT, lookup de tenant
│   │   ├── schemas.py         # Pydantic: CurrentUser, Tenant
│   │   └── models.py          # SQLAlchemy: profiles, tenants, memberships
│   │
│   ├── engrama_core/          # 💰 Motor de gamificación
│   │   ├── router.py          # /coins, /attendance, /streaks
│   │   ├── service.py         # grant_coins, check_in, compute_streak
│   │   ├── schemas.py
│   │   └── models.py          # transactions, attendance, streaks
│   │
│   ├── challenge_engine/      # 🎯 Retos
│   │   ├── router.py
│   │   ├── service.py
│   │   ├── generator.py       # Genera con Anthropic API
│   │   ├── webhooks.py        # Recibe weak_areas de Grader
│   │   ├── schemas.py
│   │   └── models.py          # challenges, attempts
│   │
│   ├── bets/                  # 🎲 Apuestas
│   ├── shop/                  # 🛍️ Tienda
│   ├── badges/                # 🏆 Logros
│   ├── teachers/              # 👩‍🏫 Vista profesor
│   ├── question_bank/         # 📚 API pública + pgvector
│   ├── agents/                # 🤖 Workers LLM (tareas Celery)
│   ├── billing/               # 💳 Stripe
│   └── webhooks/              # 📡 Receptores externos
│
├── tests/                     # Espeja src/
│   ├── auth/
│   ├── engrama_core/
│   └── ...
│
├── docker/
│   ├── Dockerfile.api
│   ├── Dockerfile.worker
│   └── Dockerfile.dev
│
├── docker-compose.yml         # Dev: api + worker + redis + flower
├── pyproject.toml             # Poetry o uv
├── .env.example
├── .pre-commit-config.yaml    # ruff, mypy, black
├── alembic.ini
└── README.md
```

### 7.3 `engrama-web/` (estructura detallada)

```
engrama-web/
├── app/                       # Next.js App Router
│   ├── (auth)/                # Layout group: login/signup
│   │   ├── login/page.tsx
│   │   └── layout.tsx
│   │
│   ├── (student)/             # Layout group: app del estudiante
│   │   ├── home/page.tsx
│   │   ├── challenges/page.tsx
│   │   ├── leaderboard/page.tsx
│   │   ├── shop/page.tsx
│   │   ├── profile/page.tsx
│   │   └── layout.tsx         # Bottom nav
│   │
│   ├── (teacher)/             # Layout group: dashboard profesor
│   │   ├── dashboard/page.tsx
│   │   ├── students/page.tsx
│   │   ├── challenges/page.tsx
│   │   └── layout.tsx         # Sidebar
│   │
│   ├── (admin)/               # Layout group: admin institucional
│   ├── api/                   # Solo si Next.js actúa como BFF
│   ├── layout.tsx             # Root layout
│   └── globals.css
│
├── features/                  # 🎯 Lógica por dominio (espejea backend)
│   ├── auth/
│   │   ├── components/
│   │   ├── hooks/             # useCurrentUser, useLogin
│   │   └── api.ts             # Cliente para /auth/*
│   │
│   ├── engrama_core/          # Coins, streaks, attendance
│   │   ├── components/        # WalletCard, StreakRing
│   │   ├── hooks/             # useCoins, useCheckIn
│   │   └── api.ts
│   │
│   ├── challenges/
│   ├── bets/
│   ├── shop/
│   ├── leaderboard/
│   └── teacher_dashboard/
│
├── components/
│   ├── ui/                    # shadcn primitives (Button, Card, Dialog...)
│   └── shared/                # Navbar, BottomNav, ErrorBoundary
│
├── lib/
│   ├── supabase.ts            # Cliente Supabase (solo auth)
│   ├── api-client.ts          # fetch wrapper con JWT
│   ├── api-types.ts           # Auto-generado desde OpenAPI
│   └── utils.ts               # cn(), formatters
│
├── stores/                    # Zustand
│   ├── user-store.ts
│   └── ui-store.ts
│
├── public/
│   └── sounds/                # success.mp3, error.mp3, coin.mp3...
│
├── tests/
│   ├── e2e/                   # Playwright
│   └── unit/                  # Vitest
│
├── next.config.js
├── tailwind.config.ts
├── tsconfig.json              # strict: true
├── package.json
├── .env.local.example
└── README.md
```

---

## 8. Reglas de modularidad (dependency rule)

**Esta es la sección más importante del documento.** Sin estas reglas, el monolito modular se degrada en 3 meses.

### 8.1 La regla sagrada

> **Un módulo de dominio NUNCA importa otro módulo de dominio directamente.**  
> Si necesita algo de otro dominio, lo hace vía:  
> (a) Servicio expuesto en `shared/` o  
> (b) Evento (publicado a Celery / Redis pub-sub)

### 8.2 Capas permitidas

```
┌─────────────────────────────────────────────┐
│  Capa 4: ROUTERS (router.py)                │
│  - HTTP, Pydantic schemas, deps             │
│  - Puede importar: service, schemas, shared │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│  Capa 3: SERVICES (service.py)              │
│  - Lógica de negocio                        │
│  - Puede importar: models del mismo dominio,│
│    shared, servicios expuestos en shared/   │
│  - NO puede importar: otros dominios,       │
│    routers, schemas de otros dominios       │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│  Capa 2: MODELS (models.py)                 │
│  - SQLAlchemy models                        │
│  - Puede importar: shared/db, shared/models │
│  - NO puede importar: nada de dominios      │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│  Capa 1: SHARED                             │
│  - Infraestructura, config, DB, logging     │
│  - No importa NADA de dominios              │
└─────────────────────────────────────────────┘
```

### 8.3 Ejemplo concreto (bueno y malo)

**❌ MAL:**
```python
# src/bets/service.py
from src.engrama_core.service import grant_coins  # ← VIOLACIÓN

def resolve_bet(winner_id, amount):
    grant_coins(winner_id, amount)  # dependencia directa
```

**✅ BIEN:**
```python
# src/shared/events.py
def publish_coins_granted(user_id: UUID, amount: int, reason: str):
    """Evento público que cualquier dominio puede disparar."""
    ...

# src/bets/service.py
from src.shared.events import publish_coins_granted

def resolve_bet(winner_id, amount):
    publish_coins_granted(winner_id, amount, reason="bet_won")
    # engrama_core escucha este evento y da las coins
```

### 8.4 Enforcement

- **`import-linter`** (Python): configurado en CI. Si alguien importa cross-domain, el build falla.
- **ESLint rule** (TS): `no-restricted-imports` configurado para prohibir imports entre `features/`.
- **Code review:** cualquier PR que introduzca un import cross-domain se rechaza automáticamente.

---

## 9. Multi-tenancy y seguridad de datos

### 9.1 Concepto de "tenant"

Un **tenant** = una institución (universidad, colegio). Ejemplos:
- Tenant 1: UIS (Universidad Industrial de Santander)
- Tenant 2: UDES
- Tenant 3: Colegio San José

Un usuario pertenece a **uno o varios tenants** (un profesor puede trabajar en dos universidades).

### 9.2 Schema base

```sql
-- Tabla de instituciones
CREATE TABLE tenants (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug        TEXT UNIQUE NOT NULL,      -- 'uis', 'udes'
  name        TEXT NOT NULL,
  plan        TEXT NOT NULL,              -- 'free', 'pro', 'enterprise'
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- Perfiles de usuario (1 fila por usuario de Supabase Auth)
CREATE TABLE profiles (
  id          UUID PRIMARY KEY REFERENCES auth.users(id),
  email       TEXT NOT NULL,
  full_name   TEXT,
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- Membresías: un usuario puede estar en varios tenants con roles distintos
CREATE TABLE memberships (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id  UUID NOT NULL REFERENCES profiles(id),
  tenant_id   UUID NOT NULL REFERENCES tenants(id),
  role        TEXT NOT NULL CHECK (role IN ('student','teacher','admin')),
  UNIQUE (profile_id, tenant_id)
);

-- TODA tabla transaccional lleva tenant_id OBLIGATORIO
CREATE TABLE transactions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   UUID NOT NULL REFERENCES tenants(id),
  profile_id  UUID NOT NULL REFERENCES profiles(id),
  amount      INT NOT NULL,
  reason      TEXT NOT NULL,
  created_at  TIMESTAMPTZ DEFAULT now()
);
```

### 9.3 Política RLS estándar

Cada tabla con `tenant_id` recibe **la misma política**:

```sql
-- 1. Activar RLS
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;

-- 2. Policy: solo ves filas de tenants donde eres miembro
CREATE POLICY "tenant_isolation" ON transactions
  FOR ALL
  USING (
    tenant_id IN (
      SELECT tenant_id FROM memberships
      WHERE profile_id = auth.uid()
    )
  );
```

### 9.4 Flujo de una request autenticada

```
1. Usuario hace login en frontend (Supabase Auth)
   → recibe JWT con auth.uid() = profile_id

2. Frontend llama al backend con header:
   Authorization: Bearer <JWT>

3. Backend (shared/deps.py):
   a. Valida JWT (firma, expiración)
   b. Extrae profile_id del JWT
   c. Lee header X-Tenant-Slug: 'uis'
   d. Verifica que el usuario tenga membership en ese tenant
   e. Crea un user_session de SQLAlchemy con el JWT
   f. Inyecta: current_user, current_tenant, db_session

4. Router llama a service con (current_user, current_tenant, ...)

5. Service hace queries con db_session
   → PostgreSQL aplica RLS automáticamente con auth.uid()
   → Si una query intenta ver otro tenant, devuelve vacío (NO error)

6. Defensa en profundidad: el service ADEMÁS filtra
   por tenant_id en WHERE. Si RLS falla, el filtro explícito salva.
```

### 9.5 Prohibiciones

- ❌ **NUNCA** una query sin `tenant_id` en el WHERE (aunque RLS lo cubra).
- ❌ **NUNCA** exponer el `service_role` key en el frontend.
- ❌ **NUNCA** crear una tabla transaccional sin `tenant_id NOT NULL`.
- ❌ **NUNCA** pasar el JWT de un usuario a un worker Celery (los workers usan `admin_session` con scope explícito).

---

## 10. Estrategia de activación por fases

**Construimos el esqueleto completo desde día 1. Activamos un módulo a la vez.**

### Fase 0 — Fundaciones (Semanas 1-2)
**Objetivo:** entorno funcional. Nada de features.

- WSL2 + Docker Desktop instalados
- Repos creados (`engrama-web`, `engrama-backend`) con estructura vacía
- `docker-compose.yml` corriendo: FastAPI + Redis + Celery (worker vacío) + Flower
- Supabase project creado, schema vacío
- Health-check `/health` respondiendo en FastAPI
- Next.js 14 "hello world" haciendo fetch al `/health`
- CI en GitHub Actions: lint + typecheck (sin tests aún)

**Entregable:** una página que dice "API: OK" consultando al backend vía JWT.

### Fase 1 — Walking Skeleton (Semanas 3-6)
**Objetivo:** ciclo completo end-to-end con UNA feature: login + ver coins + check-in de asistencia.

Módulos activados:
- ✅ `auth/` (completo)
- ✅ `engrama_core/` (solo coins + attendance, NO streaks aún)
- ❌ Resto declarado pero no implementado

Infraestructura:
- ✅ Multi-tenant con RLS desde día 1
- ✅ TypeScript strict
- ✅ Tests de auth + coins (los críticos)
- ❌ Celery aún no ejecuta tasks reales
- ❌ Stripe no cobra

**Entregable:** un estudiante se loguea, ve sus coins, marca asistencia, las coins suman. Con RLS real: dos estudiantes de tenants distintos no se ven entre sí.

### Fase 2 — Paridad con Lingo Coins (Semanas 7-14)
**Objetivo:** Engrama 2.0 hace todo lo que hace Lingo Coins hoy.

Módulos activados:
- ✅ `challenge_engine/` (sin Grader webhook aún, solo manual)
- ✅ `bets/`
- ✅ `shop/`
- ✅ `badges/`
- ✅ `teachers/` (dashboard básico)
- ✅ Streaks en `engrama_core/`

**Entregable:** podemos migrar los 97 estudiantes.

### Fase 3 — Celery + Agentes + Grader (Semanas 15-20)
- Celery worker procesando tasks reales
- Agentes: youtube_scraper + nlp_cleaner
- Webhook Grader → challenge_engine
- Primer approach de Question Bank (sin pgvector aún)

### Fase 4 — Question Bank API + Stripe (Semanas 21-26)
- pgvector activo, embeddings generados
- API pública `/v1/questions`
- Stripe: suscripciones B2B + usage billing
- Primer cliente externo de pagos

### Fase 5 — Expansión (Semanas 27+)
- Más tenants (UDES, UPB, UNAB)
- Analytics avanzados
- Mobile nativa (React Native, reusando `features/`)

---

## 11. Glosario rápido

| Término | Significado |
|---|---|
| **Tenant** | Una institución (universidad, colegio). Unidad de aislamiento de datos. |
| **Membership** | Relación usuario ↔ tenant con un rol (student/teacher/admin). |
| **RLS** | Row Level Security. Filtrado de filas a nivel motor PostgreSQL. |
| **JWT** | Token firmado que porta identidad. Lo emite Supabase Auth. |
| **service_role** | Key de Supabase que bypassa RLS. Solo para backend, nunca cliente. |
| **ADR** | Architecture Decision Record. Decisión arquitectónica documentada. |
| **Walking Skeleton** | Versión mínima end-to-end: esqueleto que camina. |
| **Dependency Rule** | Regla de qué capa/módulo puede importar qué. |
| **Monolito Modular** | Un solo deploy, pero módulos internos aislados como si fueran servicios. |
| **DaaS** | Data-as-a-Service. Modelo de negocio donde vendes acceso a datos/API. |

---

## 📝 Historial de cambios

| Fecha | Versión | Cambio | Autor |
|---|---|---|---|
| 2026-04-18 | 2.0 | Creación del documento maestro | Claude + Christiam |

---

**Última actualización:** 2026-04-18  
**Próxima revisión obligatoria:** al terminar Fase 0
