# Guía del Módulo Challenges

> **Para quién es esto:** para ti (Christiam) o cualquiera sin background técnico.
> Explica qué hace el módulo `challenge_engine`: retos de inglés,
> intentos, calificación y generación con IA.
>
> **Doc técnica para devs:** `docs/CHALLENGES_DEV.md`.

---

## 1. ¿Qué resolvimos hoy?

Hasta hoy el backend ya tenía:
- Login (auth) ✅
- Coins y asistencia (engrama_core) ✅

Hoy agregamos **el corazón educativo de Engrama**: los retos (challenges).

Un **challenge** es un ejercicio de inglés que el profesor crea (manual
o con IA) y asigna a un grupo. Los estudiantes lo resuelven, el sistema
los califica, y quienes ganan reciben coins + XP automáticamente.

---

## 2. Glosario

| Palabra | Qué es (en humano) |
|---|---|
| **Challenge** | Un reto/ejercicio con una o varias preguntas. Ej: "Past Simple — 3 preguntas A2". |
| **Challenge Question** | Una pregunta dentro del challenge. Ej: "What did you ___ yesterday? (a) do (b) did" |
| **Attempt** | Un intento del estudiante. Se guarda con sus respuestas y el puntaje. |
| **CEFR level** | Nivel europeo de inglés (A1, A2, B1, B2, C1...). Cada challenge tiene el suyo. |
| **Skill** | Habilidad: grammar, vocabulary, reading, listening, writing. |
| **Max attempts** | Cuántos intentos puede hacer cada estudiante del mismo challenge (ej: 2). |
| **Max winners** | Cuántos estudiantes pueden ganar coins por el reto (ej: 10). El 11º que acierte ya no recibe premio. |
| **XP** | Puntos de experiencia. A diferencia de las coins, suben el *nivel* del perfil. |
| **Drako** | El asistente de feedback personalizado con IA (queda stubbed en Fase 1, se activa en Fase 2). |

---

## 3. Flujo completo: del profe al alumno

```
PROFESOR                                 ALUMNO
─────────                                ──────

1a. Crea challenge manual
    (POST /challenges/)
                 ↓
    O BIEN:

1b. Pide a la IA que lo genere
    (POST /challenges/generate)
    - cefr_level: B1
    - skill: grammar
    - topic: past simple
    - num_questions: 3
                 ↓
2. Sistema llama a Claude,
   parsea JSON, persiste challenge
   con N preguntas
                 ↓
3. Challenge queda "active"  ──────────▶ 4. Alumno ve el challenge
                                           en su feed
                                           (GET /challenges/)
                                                ↓
                                         5. Abre el detalle
                                           (GET /challenges/{id})
                                                ↓
                                         6. Inicia intento
                                           (POST /challenges/{id}/attempt)
                                           → attempt_id
                                                ↓
                                         7. Responde preguntas, envía todo
                                           (POST /challenges/attempts/
                                            {attempt_id}/submit)
                                                ↓
                                         8. Sistema califica:
                                            - multiple_choice: 100% = pasa
                                            - open/fill_blank: 70% = pasa
                                                ↓
                                         9. Si pasa:
                                            → coins_reward + xp_reward
                                            → current_winners += 1
                                            → profile.xp actualiza
                                                ↓
                                        10. Respuesta:
                                            - is_correct
                                            - coins_earned
                                            - correct_answers (reveladas)
                                            - intentos restantes
```

**Regla sagrada:** el `correct_answer` de una pregunta **NUNCA** viaja
al estudiante antes de enviar el intento. Solo se revela en la respuesta
del `submit` para que pueda aprender del error. Esto impide trampas.

---

## 4. Reglas de puntaje

Cuando el alumno envía sus respuestas, el sistema compara cada respuesta
con la correcta:
- **Ignora mayúsculas/minúsculas** y **espacios al inicio/fin**. Ej:
  "`  PARIS `" cuenta como "paris".
- Si la pregunta no tiene respuesta enviada, cuenta como incorrecta.

El puntaje (`score_percent`) es el % de preguntas correctas. El
challenge se considera "ganado" según el tipo:

| Tipo | Requisito para ganar |
|---|---|
| `multiple_choice` | 100% (todas bien) |
| `listening` | 100% |
| `open` | 70% o más |
| `fill_blank` | 70% o más |

Si el estudiante gana **y** aún hay cupo (`current_winners < max_winners`),
recibe `coins_reward` y `xp_reward` del challenge. Si llegó tarde y el
cupo ya se llenó, ve sus respuestas correctas pero sin premio (situación
rara porque el feed filtra challenges llenos).

---

## 5. Los 9 endpoints que creamos

Todos bajo el prefijo `/challenges` y requieren JWT.

### Para profesores (4 endpoints)

| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/challenges/` | Crear challenge manual con preguntas provistas. |
| POST | `/challenges/generate` | Generar challenge con IA (Anthropic Claude). |
| GET | `/challenges/all` | Listar TODOS los challenges del tenant (dashboard). |
| PATCH | `/challenges/{id}/status` | Activar/desactivar/archivar. |

### Para estudiantes (5 endpoints)

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/challenges/` | Mi feed de challenges disponibles. |
| GET | `/challenges/{id}` | Detalle de un challenge (sin correct_answer). |
| POST | `/challenges/{id}/attempt` | Iniciar un intento. |
| POST | `/challenges/attempts/{attempt_id}/submit` | Enviar respuestas y recibir calificación. |
| GET | `/challenges/attempts/history` | Mi historial de últimos 20 intentos. |

---

## 6. La generación con IA (paso a paso)

Cuando un profesor llama a `POST /challenges/generate`:

1. El backend arma un **prompt** que le dice a Claude:
   - "Eres experto en enseñanza de inglés nivel B1"
   - "Genera 3 preguntas multiple choice sobre 'past simple'"
   - "Formato respuesta: JSON estricto"
2. Llama a la **Anthropic Messages API** (modelo `claude-sonnet-4`).
3. Parsea la respuesta JSON del modelo (tolerante a markdown wrapping).
4. Valida que tenga la forma de un `ChallengeCreate` (usando Pydantic).
5. Inserta el challenge + preguntas en la DB.
6. Registra el uso en `ai_usage_logs` (tokens consumidos).

**Si falla**:
- Sin `ANTHROPIC_API_KEY` configurada → `503 Service Unavailable`.
- Error de red o HTTP 4xx/5xx del API → `503`.
- JSON malformado del modelo → `502 Bad Gateway`.

El API key se lee de `.env` y nunca se loguea en errores (prevención
para que no aparezca en logs por accidente).

---

## 7. Cómo probar

### `pytest` (sin DB)

```bash
cd ~/projects/engrama/engrama-backend
poetry run pytest tests/ -v
```

Deberías ver **71 tests pasando** (auth + core + challenges) y **24
skipped** (integration tests pendientes de fixture Postgres).

### `curl` contra servidor vivo

```bash
poetry run uvicorn src.main:app --reload
# en otra terminal:
curl http://localhost:8000/challenges/                        # → 401
curl http://localhost:8000/challenges/attempts/history        # → 401
```

---

## 8. Errores comunes y cómo arreglarlos

### ❌ `401 Missing Authorization header`
No mandaste JWT. Agregá `Authorization: Bearer <token>`.

### ❌ `403 Teacher role required`
Intentaste crear/editar un challenge con un rol `student`. **Arreglo:**
usar un JWT con `memberships.role` en `{teacher, admin, super_admin}`.

### ❌ `404 Challenge not found`
El `challenge_id` de la URL no existe en tu tenant.

### ❌ `429 No attempts remaining for this challenge`
El alumno ya agotó `max_attempts` completados. **Arreglo:** el profesor
puede aumentar `max_attempts` o crear otra variante del challenge.

### ❌ `409 Challenge is not active`
El profe desactivó el challenge. Se ve en `/challenges/all` con
`status != 'active'`. Reactivar con `PATCH /challenges/{id}/status`.

### ❌ `409 Attempt already completed or abandoned`
El alumno intentó enviar dos veces el mismo attempt. **Arreglo:**
iniciar un nuevo attempt (`POST /challenges/{id}/attempt`) si le
quedan intentos disponibles.

### ❌ `503 Anthropic API key not configured`
El `.env` no tiene `ANTHROPIC_API_KEY`. **Arreglo:** copiar la key del
dashboard de Anthropic y pegarla en `.env`.

### ❌ `502 AI response JSON is malformed`
El modelo devolvió algo que no pudimos parsear. Ocurre rara vez.
**Arreglo:** reintentar el `POST /challenges/generate`.

---

## 9. Estado actual (fin del día 2026-04-20)

✅ **Hecho:**
- 9 endpoints funcionando bajo `/challenges`.
- Integración con Claude Sonnet para generar retos.
- Regla `correct_answer` oculto al estudiante verificada a nivel schema.
- 71 tests pasan (unit + contract), 24 integration tests stubs.
- Commits `8967997`.

⏳ **Pendiente:**
- Fixture de Postgres para desbloquear integration tests.
- Feedback "Drako" con IA para cada intento (reservado Fase 2).
- Streak bonus en coins (reservado Fase 3).
- Frontend que consuma todo esto.

**Siguiente spec:** `SPECS/04-leaderboard.md`.

---

*Última actualización: 2026-04-20. Commit `8967997 feat(challenges)`.*
