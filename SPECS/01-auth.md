# SPECS/01-auth.md — Engrama 2.0 Auth Module
# Estado: APROBADO | Fecha: 2026-04-19
# Para: Windsurf — implementa src/auth/
# Prerequisito: 029_rls_policies aplicado

## 0. Contexto

Supabase Auth emite JWTs. El frontend los obtiene y los manda
en cada request al backend FastAPI via header:
  Authorization: Bearer <jwt>

El backend NO emite tokens — solo los valida.
El backend NO usa el cliente de Supabase JS — usa python-jose para validar JWT.

Flujo completo:
  1. Usuario hace login en frontend (Supabase Auth)
  2. Supabase devuelve JWT al frontend
  3. Frontend manda requests a FastAPI con JWT en header
  4. FastAPI valida JWT con SUPABASE_JWT_SECRET
  5. FastAPI extrae profile_id (= auth.uid()) del JWT
  6. FastAPI busca profile + memberships en DB
  7. FastAPI inyecta contexto en el request (tenant_id, role, etc.)

---

## 1. Estructura de archivos a crear

```
src/auth/
├── __init__.py
├── router.py       ← endpoints HTTP
├── service.py      ← lógica de negocio
├── schemas.py      ← Pydantic models (request/response)
└── models.py       ← (vacío — usa shared/models.py)
```

---

## 2. Schemas Pydantic — src/auth/schemas.py

```python
# Request
class SessionRequest(BaseModel):
    # No body — el JWT viene en el header Authorization

# Response de /auth/me
class MembershipOut(BaseModel):
    tenant_id: UUID
    tenant_name: str
    tenant_slug: str
    role: str          # 'student' | 'teacher' | 'admin' | 'super_admin'
    group_code: str | None
    is_active: bool

class ProfileOut(BaseModel):
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

# Contexto interno inyectado en cada request autenticado
class AuthContext(BaseModel):
    profile_id: UUID
    role: str
    tenant_id: UUID        # tenant activo (del JWT o del primer membership)
    group_code: str | None
    is_teacher: bool
    is_admin: bool
```

---

## 3. Service — src/auth/service.py

### 3.1 validate_jwt(token: str) -> dict

```python
# Usa python-jose para verificar el JWT
# Secret: settings.SUPABASE_JWT_SECRET
# Algoritmo: HS256
# Verifica: exp, iss ("supabase"), rol claim
# Retorna: payload dict con sub (= profile_id UUID)
# Lanza: HTTPException 401 si inválido o expirado
```

### 3.2 get_or_create_profile(db, profile_id: UUID, jwt_payload: dict) -> Profile

```python
# Busca profiles.id = profile_id
# Si no existe → crea perfil mínimo con datos del JWT
#   (email del JWT como full_name temporal, documento_id = sub[:8])
# Retorna: Profile SQLAlchemy model
# NOTA: en producción el perfil se crea en onboarding, no aquí
#       este fallback es solo para desarrollo
```

### 3.3 get_memberships(db, profile_id: UUID) -> list[Membership]

```python
# SELECT memberships + JOIN tenants
# WHERE profile_id = profile_id AND is_active = TRUE
# Retorna: lista de memberships con tenant info
```

### 3.4 build_auth_context(profile, memberships, tenant_id_header=None) -> AuthContext

```python
# Si hay X-Tenant-ID header → usa ese tenant
# Si no → usa el primer membership activo
# Valida que el tenant existe en los memberships del usuario
# Lanza: HTTPException 403 si el usuario no pertenece al tenant
```

---

## 4. Dependency — src/shared/deps.py

Agregar estas dos dependencias FastAPI (pueden ya existir como stubs):

### 4.1 get_current_user

```python
async def get_current_user(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db)
) -> AuthContext:
    # 1. Extrae token del header "Bearer <token>"
    # 2. Llama validate_jwt(token)
    # 3. Llama get_or_create_profile(db, profile_id, payload)
    # 4. Llama get_memberships(db, profile_id)
    # 5. Llama build_auth_context(profile, memberships)
    # 6. Retorna AuthContext
    # Lanza: HTTPException 401 si no hay header o token inválido
```

### 4.2 require_teacher

```python
async def require_teacher(
    auth: AuthContext = Depends(get_current_user)
) -> AuthContext:
    if not auth.is_teacher and not auth.is_admin:
        raise HTTPException(403, "Teacher role required")
    return auth
```

### 4.3 require_admin

```python
async def require_admin(
    auth: AuthContext = Depends(get_current_user)
) -> AuthContext:
    if not auth.is_admin:
        raise HTTPException(403, "Admin role required")
    return auth
```

---

## 5. Router — src/auth/router.py

### POST /auth/session
```
- Body: vacío (JWT en header)
- Llama: get_current_user dependency
- Retorna: ProfileOut con memberships
- Status: 200
- Uso: el frontend llama esto al iniciar sesión para obtener el perfil completo
```

### GET /auth/me
```
- Igual que POST /auth/session pero método GET
- Uso: el frontend llama esto para refrescar el perfil
- Retorna: ProfileOut con memberships
- Status: 200
```

### POST /auth/logout
```
- Body: vacío
- Solo retorna 200 (el logout real lo maneja Supabase Auth en el frontend)
- Uso: para audit log del lado del servidor
- Registra en audit_logs: action_type='logout'
```

---

## 6. Registro en main.py

```python
# Agregar en src/main.py
from src.auth.router import router as auth_router
app.include_router(auth_router, prefix="/auth", tags=["auth"])
```

---

## 7. Tests — tests/auth/

### test_validate_jwt.py
```python
# test_valid_jwt → retorna payload correcto
# test_expired_jwt → lanza 401
# test_invalid_signature → lanza 401
# test_missing_header → lanza 401
```

### test_auth_endpoints.py
```python
# test_me_authenticated → 200 con ProfileOut
# test_me_unauthenticated → 401
# test_me_wrong_tenant → 403
```

---

## 8. Variables de entorno requeridas

Ya en .env:
- SUPABASE_JWT_SECRET ✅
- DATABASE_URL ✅

Agregar si no están:
- SUPABASE_URL (para referencia, no para validación)

---

## 9. Notas importantes para Windsurf

1. **NO usar supabase-py para validar JWT** — usar python-jose directamente
2. **El JWT de Supabase usa HS256** — no RS256
3. **El claim `sub` del JWT = profiles.id** (UUID como string)
4. **El claim `role` del JWT** puede ser 'authenticated' — el role real está en profiles.role
5. **X-Tenant-ID header** — opcional, para cuando un usuario pertenece a múltiples tenants
6. **service_role bypass** — el backend no necesita RLS porque usa service_role en la DB connection

---

## 10. Checklist para Windsurf

- [ ] src/auth/schemas.py
- [ ] src/auth/service.py (4 funciones)
- [ ] src/shared/deps.py (3 dependencias)
- [ ] src/auth/router.py (3 endpoints)
- [ ] Registrar router en main.py
- [ ] tests/auth/test_validate_jwt.py
- [ ] tests/auth/test_auth_endpoints.py
- [ ] Verificar: `curl -X GET http://localhost:8000/auth/me` sin token → 401
- [ ] Verificar: `curl -X GET http://localhost:8000/auth/me` con token válido → 200
- [ ] Commit: `feat(auth): implement JWT validation and /auth/me endpoint`

---

**Próxima spec:** SPECS/02-engrama-core.md (coins + attendance)
**Generada por:** Claude Sonnet 4.6
**Implementación:** Windsurf (src/auth/)
