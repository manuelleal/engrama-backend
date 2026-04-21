# challenge_engine — Developer Reference

> **Scope:** referencia técnica del módulo `src/challenge_engine/`.
> Implementado 2026-04-20 per `SPECS/03-challenges.md`.
>
> **Companion no-dev:** `docs/CHALLENGES.md`.

---

## 1. Module layout

```
src/challenge_engine/
├── __init__.py
├── schemas.py                         # Pydantic strict
├── router.py                          # 9 endpoints under /challenges
└── service/
    ├── __init__.py
    ├── challenges.py                  # CRUD + serializers (hides correct_answer)
    ├── attempts.py                    # grading + coin/XP award + winners cap
    └── generator.py                   # Anthropic Messages API wrapper
```

Cross-module imports:
- `service/attempts.py` → `service/challenges.py` + `engrama_core.service.coins`.
  Cross-domain import vía `engrama_core.coins` se justifica porque
  `coins_service.award_coins` es el *único* camino válido para mover
  coins (centraliza el double-entry). Alternativa idiomática sería pasar
  por `shared.events.publish_coins_granted` (ADR-001), pero por ahora
  mantenemos la llamada directa para simplicidad. Si crecen más casos,
  migrar a eventos.
- `router.py` → los 3 services + `auth.schemas.AuthContext` + `shared.{db,deps}`.

---

## 2. Route ordering (subtle)

El router monta rutas en este orden **intencional**:

```python
@router.get("/")                                 # list_challenges_for_student
@router.get("/attempts/history")                 # read_attempts_history  ← debe ir ANTES de {challenge_id}
@router.post("/attempts/{attempt_id}/submit")    # submit_attempt
@router.get("/{challenge_id}")                   # get_challenge (catch-all)
@router.post("/{challenge_id}/attempt")          # start_attempt
```

Si declaras `/{challenge_id}` antes que `/attempts/history`, FastAPI
matchea `attempts` como valor de `challenge_id` y devuelve 422
(UUID parsing error). Ver `router.py` — las rutas literales siempre
van antes de las paramétricas.

Tipo `PATCH /{challenge_id}/status` se declara con el `@router.patch`
al inicio de la sección teacher; funciona porque el método HTTP es
distinto al `GET /{challenge_id}` student.

---

## 3. Schemas: el contrato de no-leak de `correct_answer`

El spec §9 es taxativo: `correct_answer` NUNCA sale en respuestas al
estudiante antes de enviar. Lo enforzamos en 3 capas:

1. **Pydantic:** `ChallengeQuestionOut` no declara el campo
   → `model_fields.keys()` = `{id, question_type, question_text,
   options_json, order_index}`. FastAPI serializa solo campos
   declarados (`extra="forbid"`).
2. **Serializer explícito:** `challenges.question_to_schema(q)` no
   lee `q.correct_answer`.
3. **Test unitario:** `test_challenge_question_out_omits_correct_answer`
   falla si alguien agrega accidentalmente `correct_answer` al schema.

`correct_answer` solo aparece en:
- `ChallengeQuestionIn` (input del teacher al crear)
- `AttemptSubmitOut.correct_answers` (tras completar el intento)
- `ChallengeQuestion` ORM model (DB only)

---

## 4. Grading semantics

Implementado en `service/attempts.py`:

```python
def grade_answers(questions, submitted) -> tuple[float, list[dict]]:
    # case-insensitive + strip
    # missing answers = wrong
    # score_percent = correct_count / total * 100
```

`is_attempt_correct(challenge_type, score_percent)`:
- `multiple_choice`, `listening` → exige `>= 100.0`
- `open`, `fill_blank` → exige `>= 70.0`

El umbral 70% está hardcoded en `_PARTIAL_CREDIT_THRESHOLD`. Si se
necesita configurable por tenant, mover a `tenants.metadata` o a una
tabla `tenant_settings`.

### Winners slot enforcement

Aunque `list_challenges_for_student` excluye challenges con cupo lleno,
hay una ventana: estudiante A abre un challenge con 9/10 winners, otro
gana y llega al 10/10, A termina y envía. `submit_attempt` revalida
`challenge.current_winners < max_winners` antes de otorgar coins. Si no
hay cupo, `is_correct=True` y `score_percent` siguen, pero
`coins_earned=0` y `xp_earned=0`. Esto prioriza:
- Feedback pedagógico (el alumno ve que respondió bien).
- Integridad del cupo (no se sobrepasa `max_winners`).

---

## 5. Attempts lifecycle

Estados posibles del `ChallengeAttempt`: `{in_progress, completed, abandoned}`
(CHECK constraint en `challenge_attempts_status_check`).

**Contrato implementado:**
- `start_attempt`:
  - Si el alumno ya tiene uno `in_progress` → retorna ese.
  - Si no, verifica `count(attempts) < max_attempts` (cuenta completed
    + in_progress). Si excede → 429.
  - Si OK, crea nuevo con `status='in_progress'`.
- `submit_attempt`:
  - Exige `status='in_progress'` (si no, 409).
  - Tras grading setea `status='completed'`, `completed_at`, `answers`
    (JSONB con detalles), `score_percent`, `is_correct`, `coins_earned`,
    `xp_earned`, `streak_bonus=0`.
  - **No maneja 'abandoned'** — es un estado reservado para cleanup
    jobs futuros (ej: marcar como abandonado tras N horas sin submit).

### Contador de intentos

Usamos `count(*)` por `(tenant_id, challenge_id, student_id)` sin
filtro de `status`. Esto significa que un `in_progress` también cuenta
contra `max_attempts`. Decisión consciente: si dejáramos al alumno
"resetear" abriendo y abandonando, perdería el sentido el límite.
El reuse del `in_progress` existente evita consumir extras.

---

## 6. Anthropic integration (`generator.py`)

### Request shape

```json
POST https://api.anthropic.com/v1/messages
Headers:
  x-api-key: ${ANTHROPIC_API_KEY}
  anthropic-version: 2023-06-01
  content-type: application/json
Body:
  model: claude-sonnet-4-20250514
  max_tokens: 2000
  messages: [{role: user, content: <prompt>}]
Timeout: 45s
```

### Error handling

| Condición | HTTP status |
|---|---|
| `ANTHROPIC_API_KEY` vacío | 503 |
| `httpx.HTTPError` (red/DNS/timeout) | 503 |
| API responde 4xx/5xx | 503 (sin filtrar body) |
| Response sin JSON válido | 502 |
| JSON válido pero sin campos requeridos | 502 |

**Nunca se logea la API key ni el body del error** — los mensajes de
error usan solo el status code. Si se necesita más detalle en prod,
usar Sentry con scrubbing configurado.

### JSON parsing tolerance

`parse_model_output` acepta:
- JSON puro: `{"title": "..."}`
- Wrapping markdown: ` ```json\n{...}\n``` `
- Prosa alrededor: `"Here's your JSON: {...}. Enjoy!"`

Usa regex `r'\{.*\}'` con `DOTALL` y fallback a `json.loads` directo
primero (feliz camino).

### AI usage logging

`log_ai_usage` hace INSERT a `ai_usage_logs` via `text()` con parámetros
nombrados. **Es best-effort**: si falla (tabla bloqueada, etc.), el
error queda en WARNING logs pero el endpoint sigue respondiendo con el
challenge generado. Razón: el logging es telemetría, no business logic.

**Side-channel de tokens:** `generate_challenge` adjunta
`_ai_tokens_used` en `challenge_in.__dict__` para que el router lo lea
y pase a `log_ai_usage`. No es bonito; una alternativa sería devolver
una tupla `(ChallengeCreate, TokenUsage)`. Si se vuelve un patrón,
refactorizar.

---

## 7. Endpoint contract

Mounted at `/challenges`. Full path + auth guard:

| Method | Path | Guard | Body | Returns | HTTP |
|---|---|---|---|---|---|
| POST | `/challenges/` | `require_teacher` | `ChallengeCreate` | `ChallengeOut` | 201 |
| POST | `/challenges/generate` | `require_teacher` | `ChallengeGenerateRequest` | `ChallengeOut` | 201 |
| GET | `/challenges/all` | `require_teacher` | — | `list[ChallengeOut]` | 200 |
| PATCH | `/challenges/{id}/status` | `require_teacher` | `ChallengeStatusUpdate` | `ChallengeOut` | 200 |
| GET | `/challenges/` | `get_current_user` | — | `list[ChallengeOut]` | 200 |
| GET | `/challenges/attempts/history` | `get_current_user` | — | `list[AttemptHistoryOut]` | 200 |
| POST | `/challenges/attempts/{id}/submit` | `get_current_user` | `AttemptSubmitRequest` | `AttemptSubmitOut` | 200 |
| GET | `/challenges/{id}` | `get_current_user` | — | `ChallengeOut` | 200 |
| POST | `/challenges/{id}/attempt` | `get_current_user` | — | `AttemptStartOut` | 201 |

### Defense in depth

- Cada query service filtra por `tenant_id` explícito (WINDSURF §3).
- `update_challenge_status`, `get_challenge` no exponen challenges de
  otro tenant ni siquiera con un `id` filtrado, porque el WHERE incluye
  `tenant_id = auth.tenant_id`.
- `submit_attempt` exige `attempt.student_id == auth.profile_id` —
  un alumno no puede enviar el intento de otro aunque conozca el
  `attempt_id`.

---

## 8. Testing strategy

### What's in the repo

| Level | Count | Needs DB? | Status |
|---|---|---|---|
| Pure unit (grade_answers, is_attempt_correct, parse_model_output, build_prompt) | 17 | No | ✅ |
| Contract HTTP (401/403 via dependency_overrides) | 13 | No | ✅ |
| Integration (CRUD, scoring, capacity) | 12 | Yes | ⏩ skipped |

**Total: 30 corriendo en CI, 12 pendientes de fixture.**

### The `_student_auth_context` trick

Para testear 403 sin DB, usamos:

```python
app.dependency_overrides[get_current_user] = _student_auth_context
try:
    response = client.post("/challenges/", ...)
finally:
    app.dependency_overrides.pop(get_current_user, None)
```

Esto inyecta un `AuthContext(role='student', is_teacher=False)` sin
ejecutar JWT validation ni DB lookup. `require_teacher` corre normal
y devuelve 403. Patrón replicable en futuros módulos.

### Unblocking integration tests

Mismo plan que `engrama_core`: añadir `testcontainers.postgres` + alembic
upgrade fixture en `tests/conftest.py`, luego seed de tenant + teacher +
student + challenge para cada test. Ver `docs/CORE_DEV.md §5` para la
receta completa.

---

## 9. Known gotchas

1. **`Challenge.question_payload` JSONB.** Existe en el modelo (para
   algún caso futuro donde el challenge tenga metadatos tipo "prompt
   original del profe"), pero **no se usa** en Fase 1. Ni create ni
   serialize lo tocan. Si alguien intenta llenarlo, ajustar el
   `create_challenge` para mapearlo.

2. **`ChallengeQuestion.options_json` tipado dict en el ORM pero list
   en el schema.** JSONB acepta ambos. `question_to_schema` tiene
   código defensivo para normalizar cualquiera de las dos formas a
   `list[dict]`. Si el ORM se estrictiza a `list`, podés simplificar.

3. **Grading es textual.** Se compara `answer` con `correct_answer`
   tras normalizar (strip + lower). Para `multiple_choice` esperamos
   que el `correct_answer` guardado sea el **value** de la opción (ej:
   "Paris"), no el **label** ("A"). Establecer convención en el
   frontend: el cliente manda el value, no la letra.

4. **`attempt_number` en `AttemptStartOut`.** Cuenta intentos totales
   (`completed` + `in_progress`). Si `start_attempt` retorna un
   in_progress existente, `attempt_number` sigue reflejando el total
   — incluye el in_progress. Puede confundir al frontend ("creí que
   empezaba el 2 pero dice 2 y ya hice 2"). Documentarlo en el OpenAPI
   cuando se escriban descriptions.

5. **`drako_feedback` siempre `None` por ahora.** Reservado para Fase
   2 cuando implementemos el feedback LLM post-intento. Dejé el campo
   en el response para que el frontend se prepare.

6. **`current_winners` puede superarse bajo carga extrema.** Entre el
   `SELECT challenge` y el `UPDATE current_winners` no hay lock. Si
   dos alumnos envían simultáneamente cuando el cupo es 1, ambos
   pueden recibir coins. Para arreglarlo: añadir `SELECT ... FOR
   UPDATE` en el challenge row dentro de `submit_attempt` (como
   hacemos en `award_coins`). No crítico en Fase 1 con poca carga.

7. **Sin paginación en listados.** `list_challenges_for_student` y
   `list_challenges_for_teacher` devuelven TODO el tenant. Con 1000+
   challenges esto duele. Añadir `?limit` + cursor cuando sea tema.

---

## 10. Verificación del checklist §11

```
[x] GET /challenges/ sin auth       → 401 (curl + TestClient)
[x] POST /challenges/ con JWT student → 403 (TestClient override + curl
                                           con JWT fabricado sin membership)
[x] correct_answer NOT in ChallengeQuestionOut.model_fields
    (test_challenge_question_out_omits_correct_answer)
[x] pytest: 71 passed, 24 skipped in ~1s
[x] ANTHROPIC_API_KEY ya estaba en .env.example (línea 19)
```

---

## 11. Commits

```
8967997 feat(challenges): implement challenge engine with AI generation
```

---

*Last updated: 2026-04-20. Corresponds to commit `8967997`.*
