# SPEC 04 — Leaderboard

> **Módulo:** `src/leaderboard/`
> **Estado:** ✅ implementado (rama `feat/leaderboard`)
> **Depende de:** `engrama_core` (coins) y `auth` (AuthContext). NO importa sus
> services — solo lee tablas compartidas de `shared/models.py`.

---

## 1. Objetivo

Ranking gamificado de estudiantes para el dashboard. Reemplaza el leaderboard
del MVP Lingo Coins. Es **solo-lectura**: no crea tablas ni migraciones, no
mueve dinero. Arma el ranking sobre tablas existentes:

- `profiles` — nombre, xp, level, current_streak.
- `memberships` — quién es estudiante y a qué grupo/tenant pertenece.
- `coin_wallets` — balance de coins (métrica principal de orden).

---

## 2. Schemas (`schemas.py`)

Pydantic v2 strict (`extra="forbid"`). Solo salida.

| Schema | Campos |
|---|---|
| `LeaderboardEntry` | `rank`, `profile_id`, `full_name`, `coins`, `xp`, `level`, `current_streak`, `is_me` |
| `LeaderboardOut` | `scope` ('group'\|'tenant'), `group_code`, `entries[]`, `me?`, `total` |

`me` trae la fila del propio usuario con su **rank real** aunque caiga fuera del
top-N de `entries`. Así el front muestra "estás en el puesto 47" sin otra query.

---

## 3. Lógica (`service.py`)

### Métrica de orden (determinista)
1. `coins` DESC — balance de la wallet COIN del estudiante.
2. `xp` DESC — desempate por experiencia.
3. `full_name` ASC — desempate final estable.

### `build_leaderboard(rows, *, me_profile_id, limit)` — función pura
Recibe filas **ya ordenadas** (`RankRow`) y devuelve `(entries, me, total)`.
El rank es la posición 1-based sobre la lista completa. Separada de la DB para
ser unit-testable.

### `get_leaderboard(db, *, tenant_id, group_code, me_profile_id, limit)`
Query con `JOIN memberships` + `LEFT JOIN coin_wallets` (estudiantes sin wallet
cuentan 0 coins, no desaparecen). Filtros: `memberships.role = 'student'`,
`is_active`, `tenant_id` explícito (WINDSURF §3), y `group_code` si se pidió.

---

## 4. Resolución de scope (permisos)

| Caso | Resultado |
|---|---|
| Sin `group_code` | grupo activo del usuario (`auth.group_code`); si es `None` → todo el tenant |
| Con `group_code`, teacher/admin | cualquier grupo de **su** tenant |
| Con `group_code`, estudiante pidiendo OTRO grupo | **403** |

El aislamiento entre tenants lo garantiza el filtro `tenant_id` del service; el
router solo controla el cruce entre grupos.

---

## 5. Endpoints (`router.py`) — prefijo `/leaderboard`

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/leaderboard?group_code=&limit=` | `get_current_user` | Ranking + posición propia |

`limit`: default 20, `ge=1`, `le=100`.

---

## 6. Tests (`tests/leaderboard/`)

- **Contract HTTP** (sin DB): `/leaderboard` sin auth → 401.
- **Unit** (sin DB): `build_leaderboard` — ranks secuenciales, `is_me`, `me`
  fuera del top-N con rank real, truncado a `limit`, lista vacía, `me=None`
  cuando el caller no está rankeado (teacher).
- **Integration** (skip hasta fixture testcontainers): orden por coins,
  filtro de grupo, aislamiento por tenant.

---

## 7. Pendiente / futuro

- Desbloquear los integration tests con el fixture de Postgres (tarea común a
  todos los módulos DB-bound).
- Posible caché (Redis) del top-N por grupo cuando haya volumen (Fase 3+).
- Snapshots semanales para "movimiento de puestos" (backlog).
