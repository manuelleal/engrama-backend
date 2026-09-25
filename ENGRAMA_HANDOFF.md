# ENGRAMA 2.0 — Handoff Document

## 🆕 Estado al 2026-09-25

> Fuente única del estado del ecosistema: `..\..\TABLERO.md` (sección "🧭 Dónde
> está el trabajo"). Esto es el resumen de lo que toca a `engrama-backend`; el
> resto del documento (abajo) es el handoff histórico de abril, desactualizado
> salvo donde el código y esta sección lo confirman.

**Rama activa:** `test/fixture-integ`. **163 passed / 0 xfail / 0 fallan** (última medición limpia, `d0bcf12`..`8a1f075`); ruff 0; mypy 0. Ahora mismo hay trabajo sin commitear encima de esa base (grupos y panel del docente, ver más abajo) — **no lo toques desde otro chat**.

### Commits clave de la sesión F4 (por hito, ver `REGISTRO.md` para números completos)
| Hito | Commits |
|---|---|
| Fixture de integración (Docker + 24 tests con cuerpo) | `9d3b2f7`, `46687c5`, `4a570a8` — 94 passed / 5 xfail |
| BUG-1 (UUID en texto, 3 esquemas) | `d86574c`, `16de639` — 102 passed / 0 xfail |
| BUG-2 (recursión RLS en `memberships`, migración **030**) | `4b3a1fb`, `5deeec0`, `5a13428`, `f1fef55` — 128 passed / 14 xfail |
| CI y deudas (lint/tipos a 0, `integ_db.py` partido, workflow) | `80b7abb`, `e39fdb2`, `89c1fe8`, `e57d970`, `b474cca` — 130 passed / 14 xfail |
| BUG-3..9 (sin acceso directo de clientes, migración **031**) | `d0bcf12`, `fbc9081`, `8a1f075`, `d77dcb4` — **163 passed / 0 xfail**. El backend no tiene huecos de seguridad conocidos abiertos en local |

### Specs pendientes / en curso
- **Grupos y panel del docente** (`docs/ESPEC_grupos_y_panel_docente.md`, corregida por ERR-16 en `8318ca7`, con respuestas del pedagogo P1-P5 en `4a0ae72`): **en implementación ahora**, sin commitear (`src/teachers/admin_router.py`, `src/teachers/service/`, `tests/teachers/`, `tests/tramposos/test_tramposos_grupos.py` nuevos; `src/main.py`, `src/teachers/router.py`, `src/teachers/schemas.py`, `tests/integ_ayudante.py` modificados). Meta: 269 passed / 96 no-integ. Pendiente: BUG-10 (docente sin asignación abre asistencia de un grupo ajeno) y el candidato a BUG-11 (M3 reutiliza perfiles entre colegios por `documento_id`).
- **Login vendible** (decisión 008, `36c1ea8`): correo+contraseña, enlace mágico, Google, Microsoft y cuenta gestionada por el colegio (código de clase + PIN argon2id para menores sin correo); `/auth/me`, onboarding, licencias, migración 032. Meta N+45. **Se implementa después de cerrar grupos y panel.** Decisiones de Christiam pendientes: proveedor SMTP, riesgo residual del PIN de 6 dígitos, límites de la licencia gratis.

### Entorno oficial (ERR-11)
- El entorno oficial es `.venv` reconstruido con `poetry install --with dev` **desde `poetry.lock`** (Python 3.12, mismas versiones que usará el CI).
- **Nunca `poetry env use` con una ruta dentro de este repo**: con un `.venv` ya presente, Poetry lo recrea vacío y se pierde el entorno medido. Un entorno alternativo se crea con `py -3.x -m venv` + `pip install` **fuera** de la carpeta del proyecto.

### Cómo correr la suite
```bash
cd engrama-backend
docker rm -f engrama-test-pg   # solo ese nombre exacto, si quedó uno de una corrida anterior
poetry run pytest -q           # 163 passed / 0 xfail / 0 fallan (levanta y tumba engrama-test-pg solo)
poetry run ruff check .        # 0
poetry run mypy .              # 0
```
La fixture de integración (`tests/integ_db.py`, registrada en `tests/conftest.py`) levanta un contenedor Docker `engrama-test-pg` (`public.ecr.aws/supabase/postgres:17.6.1.167`, con `auth.uid()` y los roles `anon`/`authenticated`/`service_role`) y lo tumba al terminar. Al final no debe quedar ningún `engrama-test-pg` en `docker ps -a`.

### No verificado / a confirmar
- El README.md de este repo todavía anuncia "79 passed, 27 skipped": desactualizado frente a los 163 medidos arriba (no se tocó README.md en esta pasada, fuera del alcance del encargo de documentación).

---

> **Propósito:** Este documento empaca TODO el contexto de construcción de Engrama 2.0 para que cualquier agente de Claude (Chat, Code, Cowork) pueda continuar sin preguntar lo básico.
>
> **Fecha de handoff:** 2026-04-19  
> **Generado por:** Claude Sonnet 4.6 (Chat) con Christiam Manuel Puentes Leal  
> **Orden de lectura:** este archivo → `ARQUITECTURA.md` → `WINDSURF.md` → `.windsurfrules` del repo actual

---

## 1. Quién es el usuario

- **Nombre:** Christiam Manuel Puentes Leal
- **Ubicación:** Bucaramanga, Santander, Colombia
- **Background:** profesor de inglés en UIS (Universidad Industrial de Santander)
- **Experiencia técnica:** flujos n8n, Git/GitHub básico, Docker básico, HTML/CSS/JS vanilla
- **No ha usado antes de este proyecto:** Python/FastAPI, TypeScript, Celery/Redis, Stripe, RLS, pgvector
- **Sistema operativo:** Windows 11 con WSL2 + Ubuntu 24.04
- **Editor:** Windsurf conectado a WSL (usa Opus 4.7)
- **Ambición:** construir Engrama 2.0 como producto comerciable escalable

**Estilo de trabajo:**
- Pide respuestas concretas, no rodeos
- Odia que se le "quemen tokens" en prosa innecesaria
- Quiere entender QUÉ hace cada pieza (no solo pegar comandos)
- Valora cuando el agente empuja decisiones que él tomó mal
- Responde bien a la franqueza, no al adulado

---

## 2. Qué es Engrama 2.0

**Ecosistema EdTech B2B/B2C** con 3 productos interconectados:

### 2.1 Engrama (SaaS core)
Plataforma institucional gamificada para aprender inglés. Estudiantes ven app móvil con:
- Sistema de monedas virtuales (Lingo-Coins)
- Challenges diarios con IA
- Attendance con QR + geolocalización
- Leaderboard por grupo
- Apuestas entre estudiantes (Bet Mode)
- Tienda de recompensas
- Subastas en tiempo real
- Sistema de badges/logros

Los profesores tienen dashboard con analytics y generación de contenido.  
Las instituciones pagan licencia B2B.

**Modelo de negocio:** suscripción mensual por institución (tier por cantidad de estudiantes).

### 2.2 Grader (satélite)
Servicio independiente de visión artificial. Profesor fotografía exámenes físicos → Grader los califica → envía resultados a Engrama vía **webhook** → Engrama convierte errores en challenges personalizados.

**Estado:** ya existe versión funcional separada. Se integra vía webhook. **No tocar en Fase 1-2.**

### 2.3 Question Bank API (DaaS)
Base de datos vectorial (pgvector) con preguntas extraídas de fuentes auténticas vía agentes LLM. API pública REST con usage-based billing vía Stripe.

**Estado:** Fase 4. No construir antes.

---

## 3. Relación con Lingo Coins

**Lingo Coins** = MVP actual en producción:
- URL: `https://manuelleal.github.io/coins-mvp`
- Stack: HTML/CSS/JS vanilla + Supabase (cliente directo)
- **97 estudiantes reales** en UIS, grupo "Foreign Language 40556"

**Reglas de convivencia (innegociables):**
1. Lingo Coins NO se toca hasta que Engrama 2.0 tenga paridad funcional
2. Los 97 estudiantes siguen en Lingo Coins durante toda la construcción
3. Migración 1-vez al final (scripts one-shot)
4. Se reutiliza: diseño visual, decisiones de gamificación, schema de DB (con limpieza)
5. NO se copia: código fuente frontend

---

## 4. Stack decidido (inmutable sin discusión)

### Frontend (`engrama-web` repo)
- Next.js 14 (App Router)
- TypeScript strict mode
- Tailwind CSS + shadcn/ui
- Zustand (estado global)
- TanStack Query (data fetching)
- Supabase JS client (SOLO para auth)
- Lucide icons
- Vitest + Playwright (tests)

### Backend (`engrama-backend` repo)
- Python 3.12.3
- FastAPI + Pydantic v2 strict
- SQLAlchemy 2.x async + asyncpg
- Alembic (migraciones)
- python-jose (validación JWT)
- httpx (cliente HTTP)
- Celery + Redis (tareas async)
- pytest + pytest-asyncio
- ruff + mypy

### Base de datos
- Supabase PostgreSQL (proyecto: `engrama-2.0`, ref: `gvzwutaclvcaqfqmzzwx`)
- Supabase Auth (solo emisión JWT)
- Supabase Storage (archivos)
- pgvector (Fase 4)
- Row Level Security (multi-tenant)

### Infra
- Docker + Docker Compose (dev local)
- WSL2 + Ubuntu 24.04
- Vercel (hosting frontend)
- Railway o Fly.io (hosting backend)
- GitHub Actions (CI/CD)

### Servicios externos
- Anthropic API — generación de preguntas, NLP
- Stripe — suscripciones B2B
- Resend — emails
- Sentry — error tracking

---

## 5. Estado actual del proyecto (2026-04-19)

### ✅ Completado — Fase 0 + Schema

**Entorno:**
- WSL2 + Ubuntu 24.04 funcionando
- Docker Desktop integrado
- Node.js v20.20.2, Python 3.12.3, Poetry 2.3.4, Docker 28.3.0
- Git 2.43.0, GitHub CLI autenticado como `manuelleal`
- Windsurf conectado a WSL, corriendo en `~/projects/engrama/`

**Repos GitHub (privados):**
- `manuelleal/engrama-backend` — commit HEAD: `93c102c`
- `manuelleal/engrama-web`

**Supabase:**
- Proyecto: `engrama-2.0`
- URL: `https://gvzwutaclvcaqfqmzzwx.supabase.co`
- Región: East US (Ohio) — us-east-2
- Plan: Free tier
- Conexión: Session Pooler IPv4 (`aws-0-us-east-2.pooler.supabase.com:5432`)

**Database — 26 tablas en producción:**
```
tenants, profiles, memberships, groups, teacher_groups,
coin_wallets, coin_ledger, attendance_sessions, attendance,
challenges, challenge_questions, challenge_attempts,
question_bank, student_progress, student_analytics,
improvement_plans, shop_items, inventory, auctions,
auction_bids, badges, badge_unlocks, bets, announcements,
ai_usage_logs, audit_logs
```

**Migraciones Alembic aplicadas:**
- 000_extensions → 028_enable_rls (29 migraciones)
- 029_rls_policies ✅ aplicada — 51 políticas activas

**Archivos clave en engrama-backend:**
```
SPECS/
├── 00-database-schema.md   ✅ completo (471 líneas)
├── 00b-rls-policies.md     ✅ completo
├── 01-auth.md              ✅ completo
├── 02-engrama-core.md      ✅ completo
├── 03-challenges.md        ✅ completo
└── 04-leaderboard.md       ❌ pendiente (próximo paso)
alembic/versions/           30 archivos (000–029)
src/
├── main.py                 ✅ /health + /auth + /core + /challenges
├── shared/                 ✅ config.py, db.py, deps.py, models.py
├── auth/                   ✅ feat(auth) — JWT + /auth/me
├── engrama_core/           ✅ feat(core) — coins + attendance
└── challenge_engine/       ✅ feat(challenges) — AI generation
docker-compose.yml          ✅ api + redis corriendo
.env                        ✅ configurado con Session Pooler
```

### ❌ Pendiente inmediato
- ✅ Migración 029_rls_policies completada
- ✅ feat(auth) — módulo auth con JWT validation y /auth/me
- ✅ feat(core) — coins (double-entry) + attendance (QR + streak)
- ✅ feat(challenges) — challenge engine con generación IA (Anthropic)
- Generar `SPECS/04-leaderboard.md` (próximo paso)
- Implementar módulo `leaderboard/` en backend
- Fixture de testcontainers Postgres para desbloquear 24 integration tests skipped
- Walking Skeleton frontend

---

## 6. Decisiones arquitectónicas (CERRADAS)

| ADR | Decisión |
|---|---|
| ADR-001 | Monolito modular (no microservicios) |
| ADR-002 | FastAPI propio + Supabase como DB/Auth/Storage |
| ADR-003 | RLS híbrido: JWT usuario por defecto, service_role solo admin |
| ADR-004 | Shared DB + tenant_id + RLS (multi-tenant) |
| ADR-005 | Grader se comunica vía webhooks |
| ADR-006 | Toda lógica de negocio en backend services |
| ADR-007 | TypeScript strict + Pydantic strict obligatorio |
| ADR-008 | Tipos TS auto-generados desde OpenAPI del backend |
| DB-001 | ✅ Opción B — DB nueva Supabase, schema limpio, migración 1-vez al final |
| DB-002 | ✅ Free tier Supabase (monitorear al llegar a 300MB) |
| AGENT-001 | ✅ Claude Chat = arquitecto, Windsurf Opus 4.7 = implementador |

**Plan de fases:**
- **Fase 0** — Fundaciones ✅ COMPLETA
- **Fase 1** — Walking Skeleton: login + coins + attendance end-to-end ← ACTUAL
- **Fase 2** — Paridad con Lingo Coins
- **Fase 3** — Celery + Agentes + Grader webhook
- **Fase 4** — Question Bank API + Stripe
- **Fase 5** — Expansión multi-universidad

---

## 7. Schema Engrama 2.0 — resumen de cambios vs Lingo Coins

| Cambio | Detalle |
|---|---|
| 6 tablas descartadas | coin_backfill_runs, feedback_messages, system_configs, credit_transactions, institution_credit_history, student_coin_transactions |
| 3→1 tablas de challenges | completed_challenges + challenge_submissions + challenge_sessions → challenge_attempts |
| Sistema de monedas unificado | profiles.monedas eliminado → solo coin_wallets + coin_ledger |
| Todo en inglés | monedas→coins, rol→role, nombre_completo→full_name |
| tenant_id en todo | Multi-tenancy real desde día 1 |
| FKs a UUID | documento_id solo como campo de búsqueda |

---

## 8. Personalidad y reglas del agente

- **Idioma:** español siempre
- **Código, variables, commits:** inglés
- **Tono:** directo, franco, sin adulado
- **Formato:** tablas, listas, bloques de código — evitar prosa larga
- **Preguntas:** una a la vez con opciones

### División de roles
- **Claude Chat (arquitecto):** piensa, planea, escribe SPECS/docs. NO escribe código grande.
- **Windsurf / Claude Code (obrero):** escribe código real, ejecuta specs.
- **Christiam (fundador):** decide, revisa, pregunta cuando no entiende.

### Claude NO debe:
- ❌ Escribir implementación grande — eso es trabajo de Windsurf
- ❌ Asumir decisiones de negocio sin preguntar
- ❌ Dar 20 bloques de código cuando basta una spec
- ❌ Prosa larga, justificaciones, disclaimers
- ❌ Cambiar decisiones de ARQUITECTURA.md sin discusión

### Claude SÍ debe:
- ✅ Desafiar decisiones técnicamente riesgosas
- ✅ Generar specs por módulo en SPECS/*.md
- ✅ Actualizar este HANDOFF cuando se toma decisión nueva
- ✅ Una pregunta a la vez cuando hay ambigüedad
- ✅ Checkpoints antes de pasar al siguiente módulo

---

## 9. Siguiente paso inmediato

Al retomar el proyecto el orden es:

1. Confirmar migración 029_rls_policies OK:
   ```bash
   cd ~/projects/engrama/engrama-backend && poetry run alembic current
   ```
   Debe mostrar `029_rls_policies (head)`

2. Verificar políticas en Supabase SQL Editor:
   ```sql
   SELECT tablename, policyname FROM pg_policies
   WHERE schemaname = 'public'
   ORDER BY tablename;
   ```
   Debe devolver 40+ filas.

3. Generar `SPECS/01-auth.md` (Claude Chat lo genera)

4. Windsurf implementa módulo `auth/`:
   - `POST /auth/session` — valida JWT de Supabase
   - `GET /auth/me` — retorna perfil + memberships
   - Multi-tenant: valida que el usuario pertenece al tenant

5. Generar `SPECS/02-engrama-core.md` (coins + attendance)

6. Walking Skeleton frontend: login → home con wallet → check-in

---

**Última actualización:** 2026-04-19 por Claude Sonnet 4.6  
**Próxima revisión:** al completar módulo auth
