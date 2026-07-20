# SPEC 06 — Teachers (economía multinivel + dashboard)

> **Módulo:** `src/teachers/`
> **Estado:** 📝 spec listo — pendiente de implementación
> **Depende de:** `shared/models.py` (CoinWallet, CoinLedger, AuditLog, TeacherGroup, Membership, Group, Tenant), `shared/services.py` (award_coins expuesto desde `engrama_core`). NO importa `engrama_core` directamente.

---

## 1. Objetivo

Implementar la capa de gestión del profesor en la economía multinivel de Engrama:

```
Tenant (coin_pool en CoinWallet owner_type='tenant')
    └── Profesor (coin_budget en CoinWallet owner_type='profile', currency='COIN_BUDGET')
            └── Estudiante (CoinWallet owner_type='profile', currency='COIN')
```

El profesor puede **dar o quitar coins** a estudiantes de sus grupos, siempre que tenga saldo en su presupuesto. El admin puede **asignar presupuesto** al profesor desde el pool del tenant. Ninguna operación puede producir saldos negativos.

---

## 2. Schemas (`schemas.py`)

Pydantic v2 strict (`model_config = ConfigDict(strict=True, extra="forbid")`).

### Entrada

| Schema | Campos |
|---|---|
| `AwardCoinsIn` | `student_id: UUID`, `amount: int (ge=1)`, `reason: str (min_length=3, max_length=255)` |
| `DeductCoinsIn` | `student_id: UUID`, `amount: int (ge=1)`, `reason: str (min_length=3, max_length=255)` |
| `AllocateBudgetIn` | `teacher_id: UUID`, `amount: int (ge=1)`, `note: str \| None = None` |

### Salida

| Schema | Campos |
|---|---|
| `TeacherBudgetOut` | `teacher_id: UUID`, `budget_balance: int`, `updated_at: datetime` |
| `CoinOpResultOut` | `ledger_id: UUID`, `action: str`, `amount: int`, `student_id: UUID`, `teacher_budget_remaining: int`, `created_at: datetime` |
| `StudentSummaryOut` | `profile_id: UUID`, `full_name: str`, `coins: int`, `xp: int`, `level: int`, `current_streak: int`, `group_code: str` |
| `TeacherGroupOut` | `group_id: UUID`, `group_code: str`, `student_count: int`, `assigned_at: datetime` |
| `TeacherDashboardOut` | `budget: TeacherBudgetOut`, `groups: list[TeacherGroupOut]`, `students: list[StudentSummaryOut]` |

---

## 3. Lógica (`service.py`)

### 3.1 Presupuesto del profesor — wallet secundaria

El profesor tiene **dos wallets**:
- `CoinWallet(owner_type='profile', owner_id=teacher_id, currency='COIN')` — sus propias monedas como jugador (si aplica).
- `CoinWallet(owner_type='profile', owner_id=teacher_id, currency='COIN_BUDGET')` — su presupuesto para dar a estudiantes.

La wallet `COIN_BUDGET` se crea con saldo 0 en el primer `allocate_budget`. Se usa `SELECT ... FOR UPDATE` al operar sobre ella.

> **Migración requerida:** la tabla `coin_wallets` ya soporta `currency TEXT` — no hace falta nueva columna. Solo hay que añadir el valor `'COIN_BUDGET'` al `CheckConstraint` de `currency` (actualmente solo existe `'COIN'`). Ver §9.

### 3.2 `allocate_budget(db, *, admin_id, teacher_id, tenant_id, amount, note)` → `CoinOpResultOut`

```
# Validaciones:
# - admin_id tiene role 'admin' o 'super_admin' en tenant_id
# - teacher_id tiene role 'teacher' en tenant_id
# - tenant coin_pool (CoinWallet owner_type='tenant', currency='COIN') >= amount → 402 si no

# Lógica (dentro de la transacción del caller):
# 1. SELECT ... FOR UPDATE wallet tenant (currency='COIN')
# 2. SELECT ... FOR UPDATE wallet profesor (currency='COIN_BUDGET', lazy-create si no existe)
# 3. tenant_wallet.balance -= amount
# 4. teacher_budget_wallet.balance += amount
# 5. INSERT CoinLedger(action='budget_allocation', from=tenant_wallet, to=teacher_budget_wallet,
#       amount, tenant_id, created_by_profile_id=admin_id,
#       metadata={'note': note, 'admin_id': str(admin_id)})
# 6. INSERT AuditLog(tenant_id, user_id=admin_id, action_type='budget_allocation',
#       result='success', metadata={'teacher_id': str(teacher_id), 'amount': amount})
# Retorna: CoinOpResultOut
```

### 3.3 `award_coins_to_student(db, *, teacher_id, student_id, tenant_id, amount, reason)` → `CoinOpResultOut`

**Regla de oro del MVP:** el profesor NO puede dar coins que no tiene en su presupuesto.

```
# Validaciones:
# - teacher_id tiene role 'teacher' o 'admin' en tenant_id
# - student_id tiene role 'student' en tenant_id
# - student_id pertenece a un grupo asignado al teacher_id (TeacherGroup) → 403 si no
# - teacher_budget_wallet.balance >= amount → 402 "Presupuesto insuficiente"

# Lógica (dentro de la transacción del caller):
# 1. SELECT ... FOR UPDATE wallet profesor (currency='COIN_BUDGET')
# 2. SELECT ... FOR UPDATE wallet estudiante (currency='COIN', lazy-create si no existe)
# 3. teacher_budget_wallet.balance -= amount
# 4. student_wallet.balance += amount
# 5. INSERT CoinLedger(action='teacher_award', from=teacher_budget_wallet, to=student_wallet,
#       amount, tenant_id, created_by_profile_id=teacher_id,
#       metadata={'reason': reason, 'teacher_id': str(teacher_id)})
# 6. INSERT AuditLog(tenant_id, user_id=teacher_id, action_type='teacher_award_coins',
#       result='success', metadata={'student_id': str(student_id), 'amount': amount, 'reason': reason})
# Retorna: CoinOpResultOut
```

### 3.4 `deduct_coins_from_student(db, *, teacher_id, student_id, tenant_id, amount, reason)` → `CoinOpResultOut`

```
# Validaciones:
# - Mismas de 3.3 (scope de grupo y tenant)
# - student_wallet.balance >= amount → 402 "Saldo insuficiente del estudiante"
#   (el CheckConstraint balance >= 0 de la DB es la segunda línea de defensa)

# Lógica:
# 1. SELECT ... FOR UPDATE wallet estudiante (currency='COIN')
# 2. student_wallet.balance -= amount
# 3. teacher_budget_wallet.balance += amount  ← los coins regresan al presupuesto del profesor
# 4. INSERT CoinLedger(action='teacher_deduct', from=student_wallet, to=teacher_budget_wallet,
#       amount, tenant_id, created_by_profile_id=teacher_id,
#       metadata={'reason': reason, 'teacher_id': str(teacher_id)})
# 5. INSERT AuditLog(tenant_id, user_id=teacher_id, action_type='teacher_deduct_coins',
#       result='success', metadata={'student_id': str(student_id), 'amount': amount, 'reason': reason})
# Retorna: CoinOpResultOut
```

### 3.5 `get_teacher_budget(db, teacher_id, tenant_id)` → `TeacherBudgetOut`

```
# SELECT CoinWallet WHERE owner_type='profile', owner_id=teacher_id,
#         currency='COIN_BUDGET', tenant_id=tenant_id
# Si no existe → balance = 0 (sin crear fila)
# Retorna: TeacherBudgetOut
```

### 3.6 `get_teacher_groups(db, teacher_id, tenant_id)` → `list[TeacherGroupOut]`

```
# SELECT TeacherGroup JOIN Group
#   WHERE TeacherGroup.teacher_id = teacher_id
#     AND TeacherGroup.tenant_id = tenant_id
# Para cada grupo: COUNT memberships WHERE group_code=X AND role='student' AND is_active=True
# Retorna: list[TeacherGroupOut]
```

### 3.7 `get_teacher_dashboard(db, teacher_id, tenant_id)` → `TeacherDashboardOut`

```
# 1. get_teacher_budget(...)
# 2. get_teacher_groups(...)
# 3. Recopilar group_codes de los grupos del profesor
# 4. SELECT Profile JOIN Membership JOIN CoinWallet(currency='COIN')
#      WHERE membership.role='student', membership.group_code IN (group_codes),
#            membership.tenant_id=tenant_id, membership.is_active=True
#    LEFT JOIN CoinWallet — estudiante sin wallet cuenta 0 coins
# Retorna: TeacherDashboardOut con todos sus estudiantes
```

---

## 4. Permisos (RBAC)

| Operación | Roles permitidos | Restricción adicional |
|---|---|---|
| `allocate_budget` | `admin`, `super_admin` | Solo sobre teachers de SU tenant |
| `award_coins_to_student` | `teacher`, `admin` | Teacher solo sobre estudiantes de SUS grupos (TeacherGroup) |
| `deduct_coins_from_student` | `teacher`, `admin` | Ídem |
| `get_teacher_budget` | `teacher` propio, `admin` | Teacher solo puede ver su propio presupuesto |
| `get_teacher_groups` | `teacher` propio, `admin` | Idem |
| `get_teacher_dashboard` | `teacher` propio, `admin` | Idem |
| `list_teachers` (admin) | `admin`, `super_admin` | Solo teachers de SU tenant |

Verificación de scope de grupo: antes de cualquier operación sobre un estudiante, el service valida que exista una fila en `TeacherGroup(teacher_id=X, group_id=Y, tenant_id=Z)` donde el grupo del estudiante sea Y. Un admin saltea esta validación pero NUNCA el filtro de `tenant_id`.

---

## 5. Endpoints (`router.py`) — prefijo `/v1/teachers`

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/v1/teachers/me/budget` | `require_teacher` | Presupuesto propio |
| GET | `/v1/teachers/me/groups` | `require_teacher` | Grupos asignados |
| GET | `/v1/teachers/me/dashboard` | `require_teacher` | Budget + grupos + estudiantes |
| POST | `/v1/teachers/me/award` | `require_teacher` | Dar coins a estudiante |
| POST | `/v1/teachers/me/deduct` | `require_teacher` | Quitar coins a estudiante |
| POST | `/v1/admin/teachers/{teacher_id}/budget` | `require_admin` | Admin asigna presupuesto |
| GET | `/v1/admin/teachers` | `require_admin` | Listar teachers del tenant |
| GET | `/v1/admin/teachers/{teacher_id}/budget` | `require_admin` | Ver presupuesto de un teacher |

Todos los endpoints **leen `tenant_id` del `AuthContext`** inyectado por la dependencia `get_current_user`; nunca del body.

---

## 6. Tests (`tests/teachers/`)

### Unitarios (sin DB)

- `test_award_coins_insufficient_budget` — verifica que `award_coins_to_student` lanza 402 cuando `teacher_budget < amount`.
- `test_deduct_coins_restores_budget` — verifica que el presupuesto del profesor aumenta al quitar coins.
- `test_award_wrong_group_raises_403` — teacher intenta dar coins a estudiante fuera de sus grupos.

### Contractuales HTTP (sin DB)

- `GET /v1/teachers/me/budget` sin auth → 401.
- `POST /v1/teachers/me/award` con JWT de estudiante → 403.
- `POST /v1/admin/teachers/{id}/budget` con JWT de teacher → 403.
- `POST /v1/teachers/me/award` sin campo `reason` → 422.

### Integración (skip hasta fixture testcontainers)

- Flujo completo: admin asigna presupuesto → teacher da coins → verificar ledger double-entry (2 filas: allocate + award) → verificar balances de wallet profesor y estudiante.
- Intento de dar más coins que el presupuesto → 402, balances sin cambiar.
- Aislamiento: teacher de tenant A no puede operar sobre estudiante de tenant B → 403.

---

## 7. Estructura de archivos

```
src/teachers/
├── __init__.py
├── router.py
├── service.py
└── schemas.py
```

`service.py` importa de `src/shared/models.py` (CoinWallet, CoinLedger, AuditLog, TeacherGroup, Membership, Group). NO importa de `src/engrama_core/`.

---

## 8. Registro en `main.py`

```python
from src.teachers.router import router as teachers_router
app.include_router(teachers_router, tags=["teachers"])
```

---

## 9. Migración requerida

Las siguientes modificaciones de schema son necesarias. Deben generarse como migraciones Alembic separadas con la política RLS estándar.

| Campo / Constraint | Tabla | Cambio | Justificación |
|---|---|---|---|
| `currency` CHECK constraint | `coin_wallets` | Agregar `'COIN_BUDGET'` a la lista permitida | Wallet de presupuesto del profesor usa moneda separada |
| `action` CHECK constraint | `coin_ledger` | Agregar `'budget_allocation'`, `'teacher_award'`, `'teacher_deduct'` | Nuevas acciones del módulo |
| `action_type` CHECK (si existe) | `audit_logs` | Agregar `'budget_allocation'`, `'teacher_award_coins'`, `'teacher_deduct_coins'` | `AuditLog.action_type` es `TEXT` libre, no tiene constraint actualmente — sin cambio |

> **Nota de diseño:** `Tenant.coin_pool` (Integer) ya existe en el modelo como campo escalar, pero el **saldo operativo** del pool se lleva en `CoinWallet(owner_type='tenant', currency='COIN')`. Ambos deben mantenerse sincronizados; `coin_pool` en la tabla `tenants` sirve como referencia de configuración (cuántos coins se acuñaron al crear el tenant), mientras que la wallet refleja el saldo real disponible. La función `allocate_budget` solo opera sobre la wallet, no sobre `Tenant.coin_pool`.

---

## 10. Pendiente / futuro

- **Recompensas de engagement del profesor** (MVP §5): `+2 créditos` por ≥10 retos creados, `+3 créditos` por completion rate ≥80% con ≥20 intentos. Requiere tabla `teacher_rewards` (inexistente en el schema actual) o acumulación sobre `CoinWallet(currency='COIN_BUDGET')`. No es MVP — definir en SPEC 07.
- **God Mode del super_admin**: override de asignación sin validar pool. Definir explícitamente qué bypasea y qué no.
- **Vista de historial de transacciones del profesor**: últimas N entradas de `coin_ledger` donde `created_by_profile_id = teacher_id`.
