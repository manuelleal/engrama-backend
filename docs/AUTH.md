# Guía de Autenticación — Engrama 2.0

> **Para quién es esto:** para ti (Christiam) o cualquiera que nunca haya programado.
> Explica **qué hicimos hoy**, cómo funciona el login en Engrama, y cómo
> arreglarlo si algo falla. Está en español y evita jerga.

> **Doc técnica para devs:** ver `docs/AUTH_DEV.md` (ese sí es para programadores).

---

## 1. ¿Qué problema resolvimos hoy?

Antes de hoy, el backend tenía:
- ✅ La base de datos (26 tablas con RLS activado).
- ❌ Pero **cualquiera podía llamar a la API sin decir quién era**.

Hoy resolvimos dos cosas:

1. **Políticas RLS (candados por fila):** dijimos *quién puede ver qué* en la base de datos.
2. **Módulo de autenticación:** el backend ahora **sabe quién es el usuario** en cada request y rechaza a los impostores.

---

## 2. Glosario mínimo (con analogías)

| Palabra | Qué es (en humano) |
|---|---|
| **Autenticación** | Verificar que sos quien decís ser. Como mostrar la cédula en un banco. |
| **JWT (JSON Web Token)** | Una pulsera firmada que te dan al entrar al concierto. Cada vez que querés volver, mostrás la pulsera. El backend la mira y confirma que es real. |
| **Supabase Auth** | El portero que emite la pulsera. Nosotros solo la verificamos, no la emitimos. |
| **`Authorization: Bearer <token>`** | La forma estándar de mandar la pulsera en cada request. `Bearer` significa "el portador" (quien la tenga). |
| **RLS (Row Level Security)** | Candados por fila en la base de datos. Aunque dos escuelas compartan tabla, cada una solo ve sus propios alumnos. |
| **Tenant** | Una institución (colegio, universidad). Cada tenant es un cliente del SaaS. |
| **Rol** | Qué podés hacer: `student`, `teacher`, `admin`, `super_admin`. |
| **Endpoint** | Una dirección web del backend (ej. `/auth/me`). Cada endpoint hace una cosa. |

---

## 3. Cómo funciona el login (flujo completo)

```
   Frontend (Next.js)                    Backend (FastAPI)
   ─────────────────                     ──────────────────

1. Usuario escribe email+password
        ↓
2. Supabase Auth verifica
   ← pulsera (JWT) ─────────┐
                            │
3. Frontend guarda la pulsera
                            │
4. Usuario pide su perfil   │
   ─── GET /auth/me ────────▶
   Header: Authorization:       5. Backend lee la pulsera
       Bearer eyJhbGciOi...     6. Verifica firma con el secreto
                                7. Extrae el ID del usuario
                                8. Busca el perfil en la DB
                                9. Arma AuthContext
                                    (profile_id, tenant_id, role)
   ← ProfileOut (JSON) ─────────┘
10. Frontend muestra el perfil
```

**Importante:**
- El backend **NO emite** pulseras — solo las verifica. Las emite Supabase Auth.
- La pulsera tiene fecha de vencimiento (**expira**). Cuando expira, hay que volver a loguearse.
- Si alguien intenta falsificar la pulsera, la firma no cuadra y el backend rechaza.

---

## 4. Qué archivos creamos hoy

```
engrama-backend/
├── SPECS/
│   ├── 00b-rls-policies.md  ✅ (diseño de las 51 políticas RLS)
│   └── 01-auth.md           ✅ (diseño del módulo auth — leído hoy)
│
├── alembic/versions/
│   └── 029_rls_policies.py  ✅ (aplica las 51 políticas a la DB)
│
├── src/
│   ├── shared/
│   │   ├── config.py        ✅ (lee el .env con todas las claves)
│   │   ├── db.py            ✅ (conexión a la DB)
│   │   └── deps.py          ✅ (las 3 "dependencias" de auth)
│   │
│   ├── auth/
│   │   ├── schemas.py       ✅ (qué forma tienen los datos)
│   │   ├── service.py       ✅ (la lógica: validar JWT, buscar perfil)
│   │   └── router.py        ✅ (los endpoints: /me, /session, /logout)
│   │
│   └── main.py              ✅ (ahora incluye las rutas de auth)
│
└── tests/
    ├── conftest.py          ✅ (setup común de tests)
    └── auth/
        ├── conftest.py      ✅ (helpers para fabricar JWTs de prueba)
        ├── test_validate_jwt.py      ✅ (5 tests)
        └── test_auth_endpoints.py    ✅ (8 tests)
```

**Total:** 3 endpoints, 13 tests, 51 políticas RLS, todo verde.

---

## 5. Los 3 endpoints que creamos

### 5.1 `GET /auth/me` — "¿quién soy?"

El frontend lo llama para refrescar los datos del usuario (puntos, streak, nivel).

**Sin pulsera:**
```bash
curl http://localhost:8000/auth/me
# Respuesta: HTTP 401 {"detail":"Missing Authorization header"}
```

**Con pulsera válida:**
```bash
curl -H "Authorization: Bearer eyJhbGci..." http://localhost:8000/auth/me
# Respuesta: HTTP 200 con JSON del perfil + memberships
```

### 5.2 `POST /auth/session` — "acabo de loguearme"

Igual que `/auth/me` pero método POST. El frontend lo llama **una sola vez**,
justo después del login, para cachear el perfil.

### 5.3 `POST /auth/logout` — "me voy"

Registra el cierre de sesión en `audit_logs` (tabla de auditoría). El
"logout real" lo hace el frontend borrando la pulsera.

---

## 6. Los 3 roles y qué pueden hacer

El sistema tiene 4 roles (definidos en la columna `memberships.role`):

| Rol | Qué puede hacer | Ejemplo |
|---|---|---|
| `student` | Ver su propio perfil, responder retos, comprar en la tienda. | Un alumno normal. |
| `teacher` | Todo lo del student + crear retos + ver alumnos de su grupo. | Un profe. |
| `admin` | Todo lo del teacher + ver todo el tenant + gestionar usuarios. | Coordinador de la institución. |
| `super_admin` | Todo + cambiar configuración de tenants. | Soporte Engrama. |

En el código, cuando queremos restringir un endpoint a ciertos roles,
usamos "dependencias":

- `get_current_user` — solo exige que esté logueado (cualquier rol).
- `require_teacher` — exige teacher, admin o super_admin.
- `require_admin` — exige admin o super_admin.

---

## 7. Cómo probar (sin abrir Supabase)

### Opción A: `pytest` (ya corre en local)

```bash
cd ~/projects/engrama/engrama-backend
poetry run pytest tests/auth/ -v
```

Debería mostrar **13 tests verdes** en menos de 1 segundo. Si alguno falla,
algo rompió: revisá el último cambio que hiciste.

### Opción B: curl contra un servidor local

```bash
# Terminal 1: levantar el backend
cd ~/projects/engrama/engrama-backend
poetry run uvicorn src.main:app --reload

# Terminal 2: probar
curl http://localhost:8000/health                  # → 200 OK
curl http://localhost:8000/auth/me                 # → 401 sin pulsera
curl -H "Authorization: Bearer basura" \
     http://localhost:8000/auth/me                 # → 401 pulsera inválida
```

Para probar con pulsera válida necesitás un JWT real de Supabase — eso
lo genera el frontend cuando lo construyamos.

---

## 8. Los errores más comunes y cómo arreglarlos

### ❌ `401 Missing Authorization header`

**Qué significa:** no mandaste pulsera. **Arreglo:** agregá el header
`Authorization: Bearer <token>`.

### ❌ `401 Invalid or expired JWT`

**Qué significa:** la pulsera es fake, vencida, o firmada con otra llave.
**Arreglo:**
- Si venció, volvé a loguearte.
- Si la firma no cuadra, verifica que `SUPABASE_JWT_SECRET` en `.env` sea
  el mismo que usa tu proyecto Supabase (dashboard → Project Settings →
  API → JWT Secret).

### ❌ `403 User has no active tenant memberships`

**Qué significa:** el usuario se autenticó OK, pero no está matriculado
en ningún tenant. **Arreglo:** crear un registro en `memberships` para
ese usuario con `is_active = TRUE`.

### ❌ `403 User is not a member of the requested tenant`

**Qué significa:** mandaste el header `X-Tenant-ID` con un UUID al que
el usuario no pertenece. **Arreglo:** quitá el header o usá el tenant
correcto.

### ❌ `pydantic.ValidationError: supabase_jwt_secret field required`

**Qué significa:** `.env` no tiene la variable `SUPABASE_JWT_SECRET`.
**Arreglo:** agregala copiándola del dashboard de Supabase.

### ❌ Tests pasan en local pero el servidor no arranca

Causa típica: `.env` tiene `DATABASE_URL` mal formado (los corchetes
típicos del placeholder `[YOUR-PASSWORD]`). Mirá `docs/DATABASE.md` §6
para el arreglo.

---

## 9. Resumen del día en 5 líneas

1. Aplicamos la migración `029_rls_policies` → 51 candados RLS activos en la DB.
2. Creamos la infraestructura base: `shared/config.py`, `shared/db.py`, `shared/deps.py`.
3. Implementamos el módulo `auth`: `schemas.py`, `service.py`, `router.py`.
4. Conectamos los 3 endpoints (`/auth/me`, `/auth/session`, `/auth/logout`) en `main.py`.
5. Escribimos 13 tests → todos verdes → commit `7207500`.

---

## 10. ¿Qué falta para tener login real?

El backend está listo. Falta:

1. **Frontend:** código en Next.js que llame a `supabase.auth.signInWithPassword()`
   y que luego mande la pulsera al backend.
2. **Crear usuarios en Supabase Auth:** desde el dashboard o por script
   (tema de onboarding).
3. **Poblar `profiles` y `memberships`:** para cada usuario de Supabase Auth,
   crear la fila espejo en `profiles` y al menos un `memberships`.

Eso lo cubre la próxima spec: **`SPECS/02-engrama-core.md`** (coins + attendance)
y más adelante la spec de onboarding.

---

*Última actualización: 2026-04-20. Corresponde al commit `7207500 feat(auth)`.*
