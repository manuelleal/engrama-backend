# WINDSURF.md — Reglas para la IA que escribe código en Engrama 2.0

> **Propósito:** este archivo lo lee Windsurf (o cualquier IA asistente) ANTES de escribir una sola línea de código. Define qué puede hacer, qué no, cómo nombrar cosas, y cómo no romper la arquitectura.
>
> **Si una regla de este documento entra en conflicto con una petición del usuario, el documento gana.** La IA debe pausar y pedir confirmación explícita antes de violar cualquier regla.

---

## 📑 ÍNDICE

1. [Cómo debe leer la IA este repositorio](#1-cómo-debe-leer-la-ia-este-repositorio)
2. [Regla sagrada: dependency rule](#2-regla-sagrada-dependency-rule)
3. [Multi-tenancy: lo innegociable](#3-multi-tenancy-lo-innegociable)
4. [Tipado estricto](#4-tipado-estricto)
5. [Estructura de un módulo de dominio](#5-estructura-de-un-módulo-de-dominio)
6. [Convenciones de nombres](#6-convenciones-de-nombres)
7. [Cómo hacer commits](#7-cómo-hacer-commits)
8. [Tests: qué exigir y qué no](#8-tests-qué-exigir-y-qué-no)
9. [Seguridad: prohibiciones absolutas](#9-seguridad-prohibiciones-absolutas)
10. [Cómo responder a ambigüedad del usuario](#10-cómo-responder-a-ambigüedad-del-usuario)
11. [Checklist antes de entregar código](#11-checklist-antes-de-entregar-código)

---

## 1. Cómo debe leer la IA este repositorio

**Al recibir cualquier tarea, la IA debe leer en este orden:**

1. `ARQUITECTURA.md` — contexto arquitectónico completo (obligatorio)
2. Este archivo (`WINDSURF.md`) — reglas operativas
3. El `SPECS/*.md` correspondiente al módulo que se va a tocar
4. El código existente del módulo (si ya hay algo implementado)

**Si cualquiera de estos tres archivos no existe o está vacío, la IA debe detenerse y avisar al usuario.** No se implementa nada sin spec.

**Si la tarea abarca múltiples módulos**, la IA lee los specs de todos, y ANTES de escribir código debe listar (en formato texto breve) qué archivos va a crear o modificar en cada módulo. Solo procede si el usuario confirma.

---

## 2. Regla sagrada: dependency rule

**Un módulo de dominio NUNCA importa otro módulo de dominio directamente.**

Módulos de dominio en backend (`src/`):
`auth`, `engrama_core`, `challenge_engine`, `bets`, `shop`, `badges`, `teachers`, `question_bank`, `agents`, `billing`, `webhooks`.

Módulos de dominio en frontend (`features/`):
`auth`, `engrama_core`, `challenges`, `bets`, `shop`, `leaderboard`, `teacher_dashboard`.

### ❌ Prohibido

```python
# src/bets/service.py
from src.engrama_core.service import grant_coins   # ← VIOLACIÓN
```

```typescript
// features/bets/hooks/useBets.ts
import { useCoins } from '@/features/engrama_core/hooks/useCoins'  // ← VIOLACIÓN
```

### ✅ Permitido

Comunicación cross-dominio solo a través de:

- **`src/shared/events.py`** (backend) — publicación de eventos que otros módulos escuchan.
- **`src/shared/services.py`** (backend) — servicios "públicos" expuestos intencionalmente.
- **API HTTP** (frontend) — un feature llama al backend, nunca importa otro feature.
- **Estado global (Zustand)** (frontend) — stores en `stores/` son la única vía de estado compartido.

### ✅ Siempre permitido importar

Todos los módulos pueden importar de:
- `src/shared/` (backend) o `lib/`, `components/ui/`, `stores/` (frontend)
- Librerías externas (fastapi, pydantic, react, etc.)

### Si la IA detecta que necesita hacer un import cross-dominio

**Se detiene y avisa al usuario.** Propone dos caminos:
- (A) Crear un servicio expuesto en `shared/`
- (B) Disparar un evento

La IA NO decide sola; el usuario elige.

---

## 3. Multi-tenancy: lo innegociable

### Backend

**Toda tabla transaccional nueva DEBE tener `tenant_id UUID NOT NULL REFERENCES tenants(id)`.**

**Toda query DEBE filtrar por tenant_id en el WHERE**, incluso si RLS ya lo cubre. Es defensa en profundidad.

```python
# ❌ PROHIBIDO
result = await session.execute(select(Transaction).where(Transaction.user_id == user_id))

# ✅ OBLIGATORIO
result = await session.execute(
    select(Transaction).where(
        Transaction.user_id == user_id,
        Transaction.tenant_id == current_tenant.id,  # ← siempre
    )
)
```

**Toda nueva migración Alembic que cree una tabla transaccional DEBE incluir la política RLS estándar.** La IA debe generar la policy junto con la tabla. No hay excepciones.

### Frontend

- **Nunca** se hardcodea un `tenant_id` en el código.
- El tenant activo se lee del store (`useUserStore().currentTenant`) y se manda en el header `X-Tenant-Slug` a cada request al backend.
- Si el usuario pertenece a múltiples tenants, la UI debe ofrecer un switcher (lo construimos cuando aplique).

### Prohibiciones

- ❌ Usar `service_role` key desde el frontend (jamás).
- ❌ Crear una query que bypassé el filtro de tenant "porque es admin".
- ❌ Exponer endpoints sin autenticación que devuelvan datos de cualquier tenant.

---

## 4. Tipado estricto

### Python (backend)

- **Pydantic v2 en modo estricto** para todos los schemas:
  ```python
  from pydantic import BaseModel, ConfigDict
  
  class MySchema(BaseModel):
      model_config = ConfigDict(strict=True, extra="forbid")
      ...
  ```
- **Type hints obligatorios** en toda función pública (router, service).
- **Nada de `Any`, `dict`, `list` sin parametrizar** salvo justificación escrita.
- **mypy debe pasar en CI** (strict mode).

### TypeScript (frontend)

- **`tsconfig.json` con `strict: true`** — no se negocia.
- **Nada de `any`** salvo justificación en comentario.
- **Tipos de API se importan de `lib/api-types.ts`** (auto-generado desde OpenAPI del backend). No se reescriben manualmente.
- **Props de componentes con interfaces explícitas**, nunca inline con `any`.

### Cuando la IA no sabe el tipo

Pregunta. No inventa `Any` ni `unknown` como escape.

---

## 5. Estructura de un módulo de dominio

Todo módulo en `src/` del backend tiene exactamente estos archivos:

```
src/<dominio>/
├── __init__.py       # vacío o exporta el router
├── router.py         # endpoints FastAPI, Pydantic I/O, deps
├── service.py        # lógica de negocio pura
├── schemas.py        # Pydantic: request/response
├── models.py         # SQLAlchemy: tablas
└── (opcional) ...    # helpers específicos del dominio
```

Regla de qué va en cada capa:

| Archivo | Puede importar de | No puede importar de |
|---|---|---|
| `router.py` | `service.py`, `schemas.py`, `shared/deps.py`, FastAPI | `models.py` directamente, otros dominios |
| `service.py` | `models.py` (mismo dominio), `shared/`, `schemas.py` | otros dominios, `router.py` |
| `schemas.py` | Pydantic, `shared/types` | `models.py`, `service.py` |
| `models.py` | SQLAlchemy, `shared/db`, `shared/models` | cualquier cosa de dominio |

**Si la IA crea un archivo nuevo en un módulo, DEBE respetar esta jerarquía.** Si necesita otro archivo (ej: `generator.py`, `webhooks.py`), se añade al mismo nivel y respeta las mismas reglas de imports.

### Frontend equivalente (`features/<dominio>/`)

```
features/<dominio>/
├── components/    # componentes React específicos del dominio
├── hooks/         # React Query hooks, useState wrappers
├── api.ts         # funciones que llaman al backend (fetch/axios)
└── types.ts       # tipos locales (si los necesita)
```

---

## 6. Convenciones de nombres

### Archivos

- **Python:** `snake_case.py` (ej: `grant_coins.py`, `webhook_handler.py`).
- **TypeScript:** `kebab-case.ts` o `PascalCase.tsx` para componentes (ej: `wallet-card.tsx`, `WalletCard.tsx` aceptado también pero consistente dentro del módulo).
- **Tests:** `test_<lo_que_testea>.py` / `<archivo>.test.ts`.

### Funciones y variables

- **Python:** `snake_case` siempre. Funciones async con prefijo verbal claro (`grant_coins`, `fetch_user_wallet`).
- **TypeScript:** `camelCase` para funciones y variables, `PascalCase` para componentes y tipos/interfaces.

### Tablas y columnas de DB

- **Tablas:** `snake_case` plural (`transactions`, `user_profiles`).
- **Columnas:** `snake_case` singular (`user_id`, `created_at`).
- **Foreign keys:** `<tabla_singular>_id` (`user_id`, `tenant_id`).
- **Timestamps:** siempre `created_at`, `updated_at` con `TIMESTAMPTZ DEFAULT now()`.

### Endpoints API

- **REST resources:** plural y kebab-case (`/api/v1/transactions`, `/api/v1/question-bank`).
- **Versionado en URL:** todo endpoint público empieza con `/v1/`.
- **Verbos HTTP estándar:** GET (leer), POST (crear), PATCH (actualizar parcial), DELETE.

---

## 7. Cómo hacer commits

### Conventional Commits obligatorio

Formato: `<tipo>(<scope>): <mensaje corto>`

Tipos permitidos:
- `feat` — nueva feature
- `fix` — bug fix
- `chore` — mantenimiento (deps, config)
- `docs` — documentación
- `refactor` — cambio de código sin cambiar comportamiento
- `test` — agregar/modificar tests
- `perf` — mejora de rendimiento

Ejemplos:
- `feat(auth): add JWT validation middleware`
- `fix(engrama_core): prevent negative coin balance`
- `docs(architecture): add ADR for multi-tenancy`

### Granularidad

- **Un commit = un cambio lógico.** Si agregas una feature que toca 3 módulos, pueden ser 3 commits.
- **Nunca** un commit con "fix varias cosas". Si son varias, se separan.

### Antes de commitear

La IA debe asegurarse de que:
1. Los tests del módulo tocado pasen.
2. El linter (ruff/eslint) esté limpio.
3. El typechecker (mypy/tsc) no reporte errores.

Si algo falla, la IA NO commitea. Avisa al usuario.

---

## 8. Tests: qué exigir y qué no

### Obligatorio (Fase 1-2)

- **Test de auth:** validación de JWT, aislamiento de tenants.
- **Test de `engrama_core`:** no se puede dar coins negativas, no se ven coins de otro tenant, atomicidad de transacciones.
- **Test de cada endpoint que mueve dinero/puntos** (coins, bets, shop).

### No obligatorio en Fase 0-1

- Tests de UI complejos (Playwright) — se añaden en Fase 2.
- Tests de integración end-to-end — se añaden en Fase 2.
- Tests de agentes LLM — se añaden en Fase 3 (con mocks).

### Regla

**Si la IA implementa lógica que toca `tenant_id` o dinero/coins, DEBE escribir tests junto con la implementación.** No es opcional.

---

## 9. Seguridad: prohibiciones absolutas

La IA **nunca** debe:

1. Poner `SUPABASE_SERVICE_ROLE_KEY`, `STRIPE_SECRET_KEY`, `ANTHROPIC_API_KEY` o cualquier secreto en código cliente (frontend).
2. Commitear archivos `.env` (solo `.env.example` con claves vacías).
3. Usar `eval`, `exec`, o construir SQL concatenando strings.
4. Exponer endpoints sin autenticación que devuelvan datos sensibles.
5. Ignorar validación de input en un endpoint público (toda request pasa por Pydantic).
6. Confiar en datos del frontend para autorización (los roles se chequean en backend).
7. Deshabilitar RLS en una tabla transaccional "temporalmente".
8. Aceptar un webhook externo sin validar firma HMAC.
9. Loguear información sensible (tokens, passwords, PII sin necesidad).
10. Hacer `git push --force` sobre la rama `main`.

Si el usuario pide alguna de estas cosas, la IA pausa y pide confirmación explícita con advertencia de riesgo.

---

## 10. Cómo responder a ambigüedad del usuario

### Regla general

**Cuando el usuario da una instrucción ambigua, la IA hace UNA pregunta concreta y espera respuesta.** No asume, no adivina, no elige la opción "más probable".

### Ejemplos

**Usuario:** "Hazme el endpoint de coins."
**IA (mal):** [escribe un endpoint genérico asumiendo lo que quiso decir]
**IA (bien):** "¿Te refieres a (a) leer el balance de coins del usuario, (b) agregar coins manualmente como admin, o (c) transferir coins entre usuarios? Hay spec para el primero en `SPECS/02-engrama-core.md`."

**Usuario:** "Agrega validación."
**IA (mal):** [agrega cualquier validación]
**IA (bien):** "¿Qué campos querés validar y con qué reglas? Si hay un caso específico que falló, pásame el input."

### Excepción

Si la ambigüedad es trivial (ej: nombre de variable), la IA decide y deja el nombre marcado con un comentario `# TODO: confirmar naming` para revisión.

---

## 11. Checklist antes de entregar código

Antes de cerrar una tarea, la IA verifica TODO lo siguiente:

- [ ] Leí `ARQUITECTURA.md` y el `SPECS/*.md` correspondiente.
- [ ] No importé cross-dominio (o lo hice vía `shared/` con justificación).
- [ ] Agregué `tenant_id` en toda tabla y query nueva.
- [ ] Los tipos son estrictos (no hay `Any`/`any` sin justificar).
- [ ] Hay tests para la lógica crítica tocada.
- [ ] El linter pasa (ruff / eslint).
- [ ] El typechecker pasa (mypy / tsc).
- [ ] No hay secretos en el código.
- [ ] El commit sigue Conventional Commits.
- [ ] Si la tarea abarcó múltiples módulos, listé los cambios antes de empezar.

Si alguno falla, la IA NO entrega la tarea; avisa al usuario qué falta y por qué.

---

## 📝 Historial de cambios

| Fecha | Versión | Cambio |
|---|---|---|
| 2026-04-18 | 1.0 | Creación |

---

**Última actualización:** 2026-04-18
