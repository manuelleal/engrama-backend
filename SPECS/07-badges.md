# SPEC 07 — Badges

> **Módulo:** `src/badges/`
> **Estado:** 📝 spec listo — pendiente de implementación
> **Depende de:** `shared/models.py` (Badge, BadgeUnlock, Attendance, ChallengeAttempt, Profile). NO importa otros dominios directamente.

---

## 1. Objetivo

Persistir server-side los 4 badges del MVP (antes calculados al vuelo en `student.html`). La
persistencia aporta tres ventajas concretas sobre el enfoque client-side:

1. **Consistencia**: el cliente no puede falsificar un unlock ni perder el historial al limpiar caché.
2. **Historial**: `unlocked_at` permite ordenar logros y mostrar "desbloqueaste esto el lunes".
3. **Notificaciones futuras**: un evento de unlock (Fase 3) puede disparar push/WebSocket; sin fila en DB no hay fuente de verdad.

---

## 2. Catálogo de badges del MVP (datos semilla)

| slug | name | Criterio |
|---|---|---|
| `streak_5` | Racha de fuego | `profiles.current_streak >= 5` |
| `top_3` | Top 3 del grupo | posición en leaderboard del grupo `<= 3` |
| `challenges_10` | Maestro de retos | `COUNT(challenge_attempts WHERE is_correct AND tenant_id) >= 10` |
| `perfect_week` | Semana perfecta | asistencia registrada en los 5 días lun–vie de la semana ISO actual |

Los slugs se almacenan en `badges.code` (columna ya existente). `tenant_id = NULL` indica badge global
(disponible para todos los tenants). Sin migración extra de columnas: el modelo `Badge` existente cubre
`id`, `code`, `name`, `description`, `icon_url`, `tenant_id`, `created_at`.

---

## 3. Schemas (`schemas.py`)

Pydantic v2 strict (`extra="forbid"`). Solo salida.

| Schema | Campos |
|---|---|
| `BadgeOut` | `id`, `slug` (alias de `code`), `name`, `description`, `icon_url`, `unlocked`, `unlocked_at \| None` |
| `BadgeCatalogOut` | `badges: list[BadgeOut]`, `total_unlocked: int` |

---

## 4. Lógica pura (`service.py`)

### 4.1 Snapshot de evaluación

```python
@dataclass
class BadgeSnapshot:
    current_streak: int
    leaderboard_rank: int | None    # None si no está en el grupo
    correct_challenges: int
    attendance_this_week: set[int]  # {0=lun, 1=mar, ..., 4=vie}
```

### 4.2 Función pura testeable

```python
def evaluate_badges(snapshot: BadgeSnapshot) -> list[str]:
    """Devuelve lista de slugs que el snapshot merece. Sin DB, sin efectos."""
    earned: list[str] = []
    if snapshot.current_streak >= 5:
        earned.append("streak_5")
    if snapshot.leaderboard_rank is not None and snapshot.leaderboard_rank <= 3:
        earned.append("top_3")
    if snapshot.correct_challenges >= 10:
        earned.append("challenges_10")
    week_days = {0, 1, 2, 3, 4}
    if week_days.issubset(snapshot.attendance_this_week):
        earned.append("perfect_week")
    return earned
```

### 4.3 `unlock_earned_badges(db, student_id, tenant_id, slugs) -> list[BadgeUnlock]`

Persiste en `badge_unlocks` solo los slugs no desbloqueados aún. El `UniqueConstraint("student_id",
"badge_id")` ya existente garantiza idempotencia a nivel DB — el service también filtra primero para
evitar excepciones innecesarias.

### 4.4 Evaluación por EVENTOS

| Evento | Badges evaluados |
|---|---|
| Post check-in (engrama_core → shared) | `streak_5`, `perfect_week` |
| Post submit de challenge correcto | `challenges_10` |

Mecanismo cross-dominio: función `evaluate_and_unlock_badges(db, student_id, tenant_id, trigger)`
expuesta en **`src/shared/services.py`**. Los módulos `engrama_core` y `challenge_engine` la importan
desde `shared/` — no hay import cross-dominio (WINDSURF §2).

### 4.5 Badge `top_3` — evaluación lazy on-read

El ranking no es un evento discreto: fluctúa con cada asistencia o reto de cualquier compañero. Dos
opciones:

- **Job periódico (Celery)**: evaluación correcta pero requiere infraestructura que aún no existe.
- **Lazy on-read**: `GET /badges` ejecuta la query de ranking en el momento. Si el estudiante está en
  top 3, se desbloquea `top_3` (idempotente). **Opción elegida para el MVP**: sin dependencias de
  Celery, sin estado desincronizado, costo de una query por llamada al endpoint.

---

## 5. Permisos

| Caso | Resultado |
|---|---|
| Sin JWT | 401 |
| Estudiante pidiendo sus propios badges | ✅ |
| Estudiante pidiendo badges de otro | 403 (no aplica — el endpoint solo devuelve los del caller) |
| Teacher/admin | ✅ (ven el catálogo; pueden consultar el de un estudiante en Fase 2) |

`tenant_id` siempre filtrado en toda query (WINDSURF §3).

---

## 6. Endpoints (`router.py`) — prefijo `/badges`

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/badges` | `get_current_user` | Catálogo completo + estado desbloqueado/bloqueado del caller |

El endpoint:
1. Lee catálogo de badges para el tenant (global + tenant-específicos).
2. Lee `badge_unlocks` del estudiante.
3. Para `top_3`: ejecuta query de ranking lazy (igual que leaderboard, sin job externo).
4. Llama `unlock_earned_badges` con los slugs nuevos.
5. Devuelve `BadgeCatalogOut` con `unlocked=True/False` y `unlocked_at` si aplica.

Hook interno (`src/shared/services.py`): no expone endpoint propio — es llamado directamente desde los
módulos productores de eventos.

---

## 7. Tests (`tests/badges/`)

### Unit (sin DB) — `test_evaluate_badges.py`

| Caso | Input | Esperado |
|---|---|---|
| Racha exactamente 5 | `streak=5` | `["streak_5"]` |
| Racha 4 | `streak=4` | `[]` |
| Top 3 exacto | `rank=3` | `["top_3"]` |
| Top 4 | `rank=4` | `[]` |
| 10 retos correctos | `correct=10` | `["challenges_10"]` |
| 9 retos | `correct=9` | `[]` |
| Semana perfecta lun–vie | `attendance={0,1,2,3,4}` | `["perfect_week"]` |
| Semana con festivo (falta jue) | `attendance={0,1,2,4}` | `[]` (el sistema no distingue festivo — **decisión pendiente §8**) |
| Racha rota en miércoles | `streak=0, attendance={0,1}` | `[]` |
| Todos a la vez | snapshot completo | `["streak_5","top_3","challenges_10","perfect_week"]` |

### Contract HTTP (sin DB) — `test_badges_contract.py`

- `GET /badges` sin auth → 401.

### Integration (skip hasta testcontainers)

- Badge ya desbloqueado no duplica fila.
- Estudiante de otro tenant no ve badges del primero.

---

## 8. Pendiente / futuro

- **Recompensa en coins por badge**: mecánica natural para celebrar el unlock, pero introduce riesgo
  de inflación (un estudiante que entra con 10 retos previos los desbloquea todos de golpe). Decidir
  monto en sesión de game-design antes de implementar. Anotar en `coin_ledger` con `action="badge_reward"`.
- **Festivos y semana perfecta**: la condición actual no considera festivos ni ausencias justificadas.
  Para la Fase 2, recibir el set de días hábiles del tenant (configurable por institución).
- **Notificaciones de unlock**: evento `badge_unlocked` en `shared/events.py` → WebSocket/push (Fase 3).
- **Badges de tenant**: el campo `badges.tenant_id` permite badges privados por institución (Fase 2+).
- **Desbloquear integration tests** con fixture de Postgres común a todos los módulos.
- Commit esperado: `feat(badges): implement badge evaluation and unlock endpoint`

---

**Generada por:** Claude Sonnet 4.6
**Implementación:** Windsurf (`src/badges/`)
