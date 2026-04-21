# SPECS/02-engrama-core.md — Engrama 2.0 Core Module
# Estado: APROBADO | Fecha: 2026-04-19
# Para: Windsurf — implementa src/engrama_core/
# Prerequisito: src/auth/ funcionando, migración 029 aplicada

## 0. Contexto

Este módulo cubre las dos mecánicas core de Engrama:
1. **Coins** — sistema de monedas virtuales (double-entry via coin_ledger)
2. **Attendance** — check-in de asistencia con QR + geolocalización

Son independientes entre sí pero se conectan:
cuando un estudiante hace check-in → recibe coins automáticamente.

---

## 1. Estructura de archivos a crear

```
src/engrama_core/
├── __init__.py
├── router.py
├── service/
│   ├── __init__.py
│   ├── coins.py        ← lógica de monedas
│   └── attendance.py   ← lógica de asistencia
└── schemas.py
```

---

## 2. Schemas Pydantic — src/engrama_core/schemas.py

```python
# --- COINS ---

class WalletOut(BaseModel):
    id: UUID
    owner_type: str
    balance: int
    currency: str
    updated_at: datetime

class LedgerEntryOut(BaseModel):
    id: UUID
    amount: int
    action: str
    from_wallet_id: UUID | None
    to_wallet_id: UUID | None
    metadata: dict
    created_at: datetime

class CoinHistoryOut(BaseModel):
    wallet: WalletOut
    entries: list[LedgerEntryOut]
    total: int  # total entries (para paginación futura)

# --- ATTENDANCE ---

class AttendanceSessionCreate(BaseModel):
    group_code: str
    duration_minutes: int = 15  # cuánto dura la sesión QR

class AttendanceSessionOut(BaseModel):
    id: UUID
    session_code: str
    qr_payload: dict
    starts_at: datetime
    expires_at: datetime
    status: str

class CheckInRequest(BaseModel):
    session_code: str
    latitude: float | None = None
    longitude: float | None = None

class CheckInResult(BaseModel):
    success: bool
    coins_awarded: int
    streak: int
    message: str   # "Check-in exitoso! +50 coins" etc.

class AttendanceRecordOut(BaseModel):
    id: UUID
    student_id: UUID
    attendance_date: date
    coins_awarded: int
    geo_status: str | None
    created_at: datetime
```

---

## 3. Coins Service — src/engrama_core/service/coins.py

### 3.1 get_wallet(db, owner_type, owner_id, tenant_id) -> CoinWallet

```python
# SELECT coin_wallets WHERE owner_type=X AND owner_id=Y
# Si no existe → crea wallet con balance=0
# Retorna: CoinWallet model
```

### 3.2 award_coins(db, student_id, tenant_id, amount, action, metadata) -> LedgerEntry

```python
# Flujo double-entry:
# 1. get_wallet(owner_type='tenant', owner_id=tenant_id) → from_wallet
# 2. get_wallet(owner_type='profile', owner_id=student_id) → to_wallet
# 3. Verifica from_wallet.balance >= amount (si no → HTTPException 402)
# 4. INSERT coin_ledger (from, to, amount, action, metadata)
# 5. UPDATE coin_wallets SET balance = balance - amount WHERE id = from_wallet.id
# 6. UPDATE coin_wallets SET balance = balance + amount WHERE id = to_wallet.id
# 7. Todo en una sola transacción DB
# Retorna: LedgerEntry creado
# NOTA: usar SELECT FOR UPDATE en los wallets para evitar race conditions
```

### 3.3 get_balance(db, student_id, tenant_id) -> int

```python
# SELECT balance FROM coin_wallets
# WHERE owner_type='profile' AND owner_id=student_id
# Retorna: balance como int (0 si no existe wallet)
```

### 3.4 get_coin_history(db, student_id, tenant_id, limit=20) -> CoinHistoryOut

```python
# SELECT coin_ledger WHERE to_wallet_id = student_wallet.id
# ORDER BY created_at DESC LIMIT limit
# Retorna: CoinHistoryOut con wallet + entries
```

---

## 4. Attendance Service — src/engrama_core/service/attendance.py

### 4.1 create_session(db, teacher_id, tenant_id, group_code, duration_minutes) -> AttendanceSession

```python
# Validaciones:
# - teacher_id tiene role teacher/admin en tenant_id
# - group_code existe en tenant_id
# Lógica:
# 1. Genera session_code: 6 chars alfanumérico uppercase (ej: "AB3X9K")
# 2. Genera qr_payload: {session_code, tenant_id, group_code, expires_at}
# 3. expires_at = now() + duration_minutes
# 4. INSERT attendance_sessions
# Retorna: AttendanceSession model
```

### 4.2 check_in(db, student_id, tenant_id, session_code, lat, lng) -> CheckInResult

```python
# Validaciones:
# 1. Busca attendance_sessions WHERE session_code=X AND status='active'
# 2. Verifica expires_at > now() → si no: HTTPException 410 "Sesión expirada"
# 3. Verifica student NO hizo check-in ya en esta sesión
#    (UNIQUE constraint en attendance(session_id, student_id))
#    → si ya hizo: HTTPException 409 "Ya registraste asistencia"
# 4. Verifica geolocalización si lat/lng presentes:
#    - Calcula distancia entre (lat, lng) y (session.admin_lat, session.admin_lng)
#    - Si distancia > 100 metros: geo_status = 'out_of_range'
#    - Si distancia <= 100 metros: geo_status = 'valid'
#    - Si no hay lat/lng: geo_status = 'skipped'

# Lógica de coins:
# coins_base = 50
# streak_multiplier:
#   - streak 1-6: x1.0
#   - streak 7-13: x1.5
#   - streak 14+: x2.0
# coins_awarded = int(coins_base * streak_multiplier)

# Acciones:
# 1. INSERT attendance (session_id, student_id, date, lat, lng, geo_status, coins_awarded)
# 2. UPDATE profiles SET
#      current_streak = current_streak + 1,
#      longest_streak = GREATEST(longest_streak, current_streak + 1),
#      last_attendance_date = today
#    WHERE id = student_id
# 3. award_coins(db, student_id, tenant_id, coins_awarded, 'attendance',
#      {session_id, streak, geo_status})

# Retorna: CheckInResult
```

### 4.3 get_attendance_history(db, student_id, tenant_id, limit=30) -> list[AttendanceRecordOut]

```python
# SELECT attendance WHERE student_id=X AND tenant_id=Y
# ORDER BY attendance_date DESC LIMIT limit
```

### 4.4 expire_sessions(db) → int

```python
# UPDATE attendance_sessions SET status='expired'
# WHERE expires_at < now() AND status='active'
# Retorna: número de sesiones expiradas
# NOTA: Este método lo llamará Celery en Fase 3
# Por ahora se puede llamar manualmente o en un background task de FastAPI
```

---

## 5. Router — src/engrama_core/router.py

### Coins endpoints

```
GET  /coins/balance
     - Auth: get_current_user
     - Retorna: {balance: int, currency: str}

GET  /coins/history
     - Auth: get_current_user
     - Query params: limit=20
     - Retorna: CoinHistoryOut
```

### Attendance endpoints

```
POST /attendance/sessions
     - Auth: require_teacher
     - Body: AttendanceSessionCreate
     - Retorna: AttendanceSessionOut
     - Descripción: profesor crea sesión QR

GET  /attendance/sessions/active
     - Auth: require_teacher
     - Retorna: list[AttendanceSessionOut] con status='active' del grupo

POST /attendance/check-in
     - Auth: get_current_user
     - Body: CheckInRequest
     - Retorna: CheckInResult
     - Descripción: estudiante hace check-in con session_code

GET  /attendance/history
     - Auth: get_current_user
     - Query params: limit=30
     - Retorna: list[AttendanceRecordOut]

GET  /attendance/history/{student_id}
     - Auth: require_teacher
     - Retorna: list[AttendanceRecordOut] de un estudiante específico
```

---

## 6. Registro en main.py

```python
from src.engrama_core.router import router as core_router
app.include_router(core_router, prefix="/core", tags=["engrama-core"])
```

---

## 7. Constantes de negocio

Definir en `src/shared/config.py` o como constantes en el service:

```python
ATTENDANCE_COINS_BASE = 50
ATTENDANCE_STREAK_THRESHOLDS = {
    7: 1.5,   # streak >= 7 → x1.5
    14: 2.0,  # streak >= 14 → x2.0
}
GEO_MAX_DISTANCE_METERS = 100
SESSION_CODE_LENGTH = 6
```

---

## 8. Fórmula de distancia geográfica

Usar fórmula de Haversine para calcular distancia entre dos puntos GPS:

```python
import math

def haversine_distance(lat1, lon1, lat2, lon2) -> float:
    """Retorna distancia en metros entre dos coordenadas GPS."""
    R = 6371000  # radio de la tierra en metros
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2*R*math.asin(math.sqrt(a))
```

---

## 9. Tests — tests/engrama_core/

### test_coins.py
```python
# test_award_coins_basic → balance aumenta correctamente
# test_award_coins_double_entry → from_wallet disminuye, to_wallet aumenta
# test_award_coins_insufficient_balance → HTTPException 402
# test_get_balance_no_wallet → retorna 0
```

### test_attendance.py
```python
# test_checkin_valid → 200, coins_awarded=50, streak=1
# test_checkin_expired_session → 410
# test_checkin_duplicate → 409
# test_checkin_streak_multiplier_7 → coins_awarded=75 (50*1.5)
# test_checkin_streak_multiplier_14 → coins_awarded=100 (50*2.0)
# test_checkin_geo_out_of_range → success=True, geo_status='out_of_range'
```

---

## 10. Checklist para Windsurf

- [ ] src/engrama_core/schemas.py
- [ ] src/engrama_core/service/coins.py (4 funciones)
- [ ] src/engrama_core/service/attendance.py (4 funciones + haversine)
- [ ] src/engrama_core/router.py (7 endpoints)
- [ ] Registrar router en main.py
- [ ] tests/engrama_core/test_coins.py
- [ ] tests/engrama_core/test_attendance.py
- [ ] Verificar:
  - `GET /core/coins/balance` sin auth → 401
  - `POST /core/attendance/sessions` con auth student → 403
  - `POST /core/attendance/check-in` con session_code inválido → 404 o 410
- [ ] Commit: `feat(core): implement coins and attendance endpoints`

---

## 11. Notas importantes para Windsurf

1. **SELECT FOR UPDATE** en award_coins — crítico para evitar race conditions si dos requests llegan al mismo tiempo
2. **Todo en una transacción** en award_coins — si falla el UPDATE de balance, hacer rollback del INSERT en ledger
3. **streak logic** — si last_attendance_date = ayer → streak + 1. Si last_attendance_date < ayer → streak = 1 (se rompe el streak). Si last_attendance_date = hoy → ya hizo check-in (no debería llegar aquí por el UNIQUE constraint)
4. **geo_status** — nunca bloquear el check-in por geolocalización. Solo registrar el estado. El profesor decide qué hacer con esa info.
5. **session_code** — generar con `secrets.choice(string.ascii_uppercase + string.digits)` — NO usar random.choice (no es criptográficamente seguro)

---

**Próxima spec:** SPECS/03-challenges.md
**Generada por:** Claude Sonnet 4.6
**Implementación:** Windsurf (src/engrama_core/)
