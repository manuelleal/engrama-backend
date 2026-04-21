# Guía del Módulo Core — Coins + Attendance

> **Para quién es esto:** para ti (Christiam) o cualquiera sin background de programación.
> Explica qué hace el módulo `engrama_core`: cómo funcionan las monedas y la asistencia.
>
> **Doc técnica para devs:** `docs/CORE_DEV.md`.

---

## 1. ¿Qué resolvimos hoy?

Antes de hoy, el backend sabía **quién es el usuario** (módulo auth). Hoy
agregamos **qué puede hacer el usuario** en la mecánica principal de la app:

1. **Coins (monedas virtuales):** cada estudiante tiene una billetera (wallet).
   Puede ver su saldo, su historial, y recibir coins automáticamente cuando
   hace check-in de asistencia.
2. **Attendance (asistencia):** el profesor crea una sesión QR → los alumnos
   la escanean → cada uno marca asistencia y recibe coins. Se lleva cuenta
   de la **racha** (días seguidos asistiendo) para multiplicar premios.

---

## 2. Glosario

| Palabra | Qué es (en humano) |
|---|---|
| **Wallet** | Billetera digital. Cada estudiante tiene una. El colegio (tenant) tiene la suya, que es el "banco". |
| **Double-entry (doble partida)** | Contabilidad clásica: cada moneda que cambia de manos se registra **dos veces** — salió de una wallet, entró a otra. Igual que en un banco real. |
| **Ledger** | Libro contable. En Engrama es la tabla `coin_ledger` donde se apuntan todas las transferencias. |
| **Check-in** | Marcar que estás presente en clase. Se hace escaneando un QR que proyecta el profesor. |
| **Session code** | Un código de 6 letras/números (ej. `AB3X9K`) que aparece en el QR. El alumno lo manda al backend para registrar asistencia. |
| **Racha (streak)** | Cuántos días seguidos ha asistido el alumno. Se rompe si falta un día. |
| **Multiplicador** | A más racha, más coins por asistir. Incentiva constancia. |
| **Haversine** | Una fórmula matemática para calcular distancia entre dos puntos GPS. La usamos para ver si el alumno está cerca del aula. |

---

## 3. Cómo funcionan las monedas (coins)

### El colegio es el banco

Cuando se crea un colegio (tenant) en el sistema, se le asigna un "pool" de
coins (`tenant.coin_pool`). Piénsalo como la emisión del Banco Central: el
colegio es quien "imprime" las monedas.

### Cada estudiante tiene su billetera

La primera vez que un alumno recibe coins, el sistema le crea su wallet en
cero. A partir de ahí suma conforme haga actividades.

### Double-entry: cada movimiento se registra dos veces

Cuando un alumno gana 50 coins por asistencia:

```
Antes:  Wallet del colegio: 10,000  │  Wallet de Juan: 0
                          ↓ -50     │      ↓ +50
Después: Wallet del colegio: 9,950  │  Wallet de Juan: 50
```

En el libro contable (`coin_ledger`) queda una línea que dice:

```
- Salió de: wallet_colegio
- Entró a:  wallet_juan
- Monto:    50
- Acción:   "attendance"
- Cuándo:   2026-04-20 14:30
```

### ¿Por qué double-entry?

Porque nos permite **auditar**: si alguien pregunta "¿de dónde salieron
los coins de Juan?", podemos rastrear cada moneda desde su origen. En un
sistema mal diseñado, uno podría "aparecer" coins de la nada → caos y fraude.

---

## 4. Cómo funciona la asistencia

### Flujo visual

```
PROFESOR                                    ALUMNO
─────────                                   ──────

1. Entra a la app, selecciona su grupo
        ↓
2. Crea sesión (POST /attendance/sessions)
   Duración: 15 minutos
        ↓
3. El backend genera:
   - session_code: "AB3X9K"
   - QR con ese código
        ↓
4. Proyecta el QR en clase ────────────────▶ 5. Alumno escanea el QR
                                                con su celular
                                                    ↓
                                             6. Manda al backend:
                                                session_code + GPS
                                                    ↓
                                             7. Backend valida:
                                                - ¿Sesión activa?
                                                - ¿Ya hizo check-in?
                                                - ¿GPS cerca del aula?
                                                    ↓
                                             8. Actualiza racha (+1)
                                             9. Calcula coins
                                                (50 × multiplicador)
                                            10. Transfiere coins
                                                colegio → alumno
                                                    ↓
                                            11. Alumno ve:
                                                "¡+75 coins! Racha: 8"
```

### La racha (streak) y los multiplicadores

| Racha (días seguidos) | Multiplicador | Coins por asistencia |
|---|---|---|
| 1 a 6 días | ×1.0 | 50 |
| 7 a 13 días | ×1.5 | 75 |
| 14 días o más | ×2.0 | 100 |

**Cómo se actualiza la racha:**
- **Primer día:** racha = 1.
- **Ayer asistió, hoy asiste:** racha + 1.
- **Falta un día o más:** racha vuelve a 1 (se rompió).

### El GPS

Cuando el alumno escanea el QR, su celular manda latitud/longitud. El
backend calcula la distancia al aula con la fórmula de Haversine:

- **≤ 100 metros:** `geo_status = "valid"` (está en clase ✓).
- **> 100 metros:** `geo_status = "out_of_range"` (sospechoso).
- **No mandó GPS:** `geo_status = "skipped"`.

**Importante:** aunque el GPS esté lejos, el check-in **igual se registra
y el alumno igual recibe coins**. Solo se marca el estado para que el
profesor vea el reporte y decida. Se siguió esta regla del spec para
no bloquear a estudiantes con GPS fallando.

---

## 5. Los 7 endpoints que creamos

Todos están bajo el prefijo `/core` y requieren JWT (pulsera de Supabase).

### Coins (2 endpoints, para cualquier usuario autenticado)

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/core/coins/balance` | Mi saldo actual. Responde `{balance: 1350, currency: "COIN"}`. |
| GET | `/core/coins/history` | Últimas 20 transacciones. Con `?limit=N` se cambia. |

### Attendance — profesor (2 endpoints, requieren role teacher/admin)

| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/core/attendance/sessions` | Crear nueva sesión QR. Body: `{group_code, duration_minutes}`. |
| GET | `/core/attendance/sessions/active` | Listar sesiones activas del tenant. |

### Attendance — alumno (3 endpoints)

| Método | Ruta | Quién | Qué hace |
|---|---|---|---|
| POST | `/core/attendance/check-in` | Cualquier autenticado | Marcar asistencia con session_code + GPS. |
| GET | `/core/attendance/history` | Cualquier autenticado | Mi historial (últimas 30 asistencias). |
| GET | `/core/attendance/history/{student_id}` | Solo teacher/admin | Historial de un alumno específico. |

---

## 6. Cómo probar

### `pytest` (sin DB, corre siempre)

```bash
cd ~/projects/engrama/engrama-backend
poetry run pytest tests/ -v
```

Debés ver:
- **41 tests pasando** (helpers matemáticos + contratos HTTP sin auth).
- **12 tests saltados** (marcados "skip"): necesitan una DB de prueba con
  datos semilla. Los habilitaremos cuando montemos fixtures de Postgres
  para tests (próxima iteración).

### `curl` contra servidor vivo

```bash
poetry run uvicorn src.main:app --reload
# en otra terminal:
curl http://localhost:8000/core/coins/balance   # → 401 sin JWT
curl http://localhost:8000/health               # → 200
```

### Probar flujos reales

Para probar el flujo completo (crear sesión, check-in, ver balance
actualizado) hace falta:
1. Un usuario real en Supabase Auth con su JWT.
2. Su fila espejo en `profiles`.
3. Una `membership` activa con el tenant.
4. Un `group` en ese tenant con el `group_code` correcto.

Cuando el frontend esté listo (próxima fase), todo esto se probará con
alumnos reales.

---

## 7. Errores comunes y cómo arreglarlos

### ❌ `401 Missing Authorization header`

No mandaste JWT. Agregá `Authorization: Bearer <tu-token>`.

### ❌ `403 User has no active tenant memberships`

El usuario está autenticado pero no tiene `memberships` activos en ningún
tenant. **Arreglo:** crear fila en `memberships` con `is_active = TRUE`.

### ❌ `403 Teacher role required`

Estás llamando un endpoint de profesor (ej. crear sesión) con un usuario
student. **Arreglo:** usar un JWT de un usuario cuya `memberships.role`
sea `teacher`, `admin` o `super_admin`.

### ❌ `404 Group 'XYZ' not found in tenant`

El `group_code` que mandó el profesor no existe. **Arreglo:** crear el
grupo en la tabla `groups` o verificar que escribiste bien el código.

### ❌ `404 Session code not found`

El alumno mandó un `session_code` que no existe. **Arreglo:** que el
profesor genere una sesión nueva y pase el código correcto.

### ❌ `410 Session expired or no longer active`

La sesión duró 15 minutos y se venció. **Arreglo:** el profesor genera
una sesión nueva.

### ❌ `409 Student already checked in to this session`

El alumno está intentando marcar asistencia dos veces en la misma sesión.
Es la seguridad contra trampas. **Arreglo:** ninguno necesario — no puede
marcar dos veces.

### ❌ `402 Tenant coin pool insufficient`

El tenant se quedó sin coins. **Arreglo:** recargar `tenants.coin_pool`
(tarea admin) o ajustar cuánto premia cada acción.

---

## 8. Estado actual (fin del día 2026-04-20)

✅ **Hecho:**
- 7 endpoints funcionando bajo `/core`.
- Contabilidad double-entry implementada con lock anti-race-condition.
- Lógica de racha con multiplicadores (×1, ×1.5, ×2).
- GPS no bloqueante (solo informativo).
- 41 tests pasan, 12 tests de integración pendientes.
- Commit `8147159`.

⏳ **Pendiente:**
- Fixture de Postgres de prueba para desbloquear los 12 tests saltados.
- Frontend que consuma estos endpoints.
- Celery task para `expire_sessions` automático (Fase 3).
- Onboarding real que cree Profile + Membership + Wallet del tenant con coin_pool inicial.

**Siguiente spec:** `SPECS/03-challenges.md`.

---

*Última actualización: 2026-04-20. Commit `8147159 feat(core): implement coins and attendance endpoints`.*
