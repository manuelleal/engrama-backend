# SPECS/03-challenges.md — Engrama 2.0 Challenges Module
# Estado: APROBADO | Fecha: 2026-04-19
# Para: Windsurf — implementa src/challenge_engine/
# Prerequisito: src/engrama_core/ funcionando (coins + attendance)

## 0. Contexto

Los challenges son ejercicios de inglés que los estudiantes completan
para ganar coins y XP. Un challenge tiene una o más preguntas.

Flujo completo:
  1. Profesor crea challenge (manual o con IA)
  2. Challenge se asigna a un grupo o todo el tenant
  3. Estudiante ve challenge disponible en su feed
  4. Estudiante inicia intento (challenge_attempt)
  5. Estudiante responde preguntas una a una
  6. Al terminar → sistema califica, otorga coins/XP, actualiza streak
  7. Leaderboard se actualiza

---

## 1. Estructura de archivos

```
src/challenge_engine/
├── __init__.py
├── router.py
├── service/
│   ├── __init__.py
│   ├── challenges.py    ← CRUD de challenges
│   ├── attempts.py      ← lógica de intentos
│   └── generator.py     ← generación con IA (Anthropic API)
└── schemas.py
```

---

## 2. Schemas — src/challenge_engine/schemas.py

```python
# --- CHALLENGES ---

class ChallengeQuestionIn(BaseModel):
    question_type: str = 'multiple_choice'
    question_text: str
    options_json: list[dict] | None = None  # [{label, value}]
    correct_answer: str
    order_index: int = 1

class ChallengeCreate(BaseModel):
    title: str
    description: str
    challenge_type: str = 'multiple_choice'
    cefr_level: str | None = None
    skill: str | None = None
    topic: str | None = None
    specific_instructions: str | None = None
    coins_reward: int = 10
    xp_reward: int = 10
    max_attempts: int = 2
    max_winners: int = 10
    group_id: UUID | None = None   # None = todo el tenant
    questions: list[ChallengeQuestionIn]

class ChallengeGenerateRequest(BaseModel):
    cefr_level: str
    skill: str              # 'grammar','vocabulary','reading','listening','writing'
    topic: str
    num_questions: int = 3
    group_id: UUID | None = None
    specific_instructions: str | None = None

class ChallengeQuestionOut(BaseModel):
    id: UUID
    question_type: str
    question_text: str
    options_json: list[dict] | None
    order_index: int
    # NOTA: correct_answer NO se incluye en respuesta al estudiante

class ChallengeOut(BaseModel):
    id: UUID
    title: str
    description: str
    challenge_type: str
    cefr_level: str | None
    skill: str | None
    topic: str | None
    coins_reward: int
    xp_reward: int
    max_attempts: int
    max_winners: int
    current_winners: int
    status: str
    questions: list[ChallengeQuestionOut]
    created_at: datetime

# --- ATTEMPTS ---

class AnswerSubmit(BaseModel):
    question_id: UUID
    answer: str

class AttemptStartOut(BaseModel):
    attempt_id: UUID
    challenge: ChallengeOut
    attempt_number: int    # cuántos intentos ha usado este estudiante

class AttemptSubmitOut(BaseModel):
    attempt_id: UUID
    is_correct: bool
    score_percent: float
    coins_earned: int
    xp_earned: int
    streak_bonus: int
    correct_answers: list[dict]   # [{question_id, correct_answer}] revelados al terminar
    drako_feedback: str | None
    total_attempts_used: int
    attempts_remaining: int
```

---

## 3. Challenges Service — src/challenge_engine/service/challenges.py

### 3.1 create_challenge(db, teacher_id, tenant_id, data: ChallengeCreate) -> Challenge

```python
# Validaciones:
# - teacher_id tiene role teacher/admin en tenant_id
# - si group_id presente → grupo pertenece al tenant
# - len(data.questions) >= 1
# Lógica:
# 1. INSERT challenges
# 2. INSERT challenge_questions (bulk, en orden)
# Retorna: Challenge con questions
```

### 3.2 list_challenges(db, student_id, tenant_id, group_id=None) -> list[Challenge]

```python
# SELECT challenges WHERE:
# - tenant_id = tenant_id
# - status = 'active'
# - (group_id IS NULL OR group_id = student_group_id)
# - current_winners < max_winners
# ORDER BY created_at DESC
# NOTA: excluir challenges donde el estudiante ya agotó max_attempts
```

### 3.3 get_challenge(db, challenge_id, tenant_id) -> Challenge

```python
# SELECT challenge + questions WHERE id=X AND tenant_id=Y
# Lanza: HTTPException 404 si no existe
```

### 3.4 update_challenge_status(db, challenge_id, tenant_id, status) -> Challenge

```python
# UPDATE challenges SET status=X WHERE id=Y AND tenant_id=Z
# Solo teacher/admin puede hacer esto
```

---

## 4. Attempts Service — src/challenge_engine/service/attempts.py

### 4.1 start_attempt(db, student_id, tenant_id, challenge_id) -> ChallengeAttempt

```python
# Validaciones:
# 1. Challenge existe, status='active', tenant correcto
# 2. Cuenta intentos previos del estudiante en este challenge
#    → si count >= challenge.max_attempts: HTTPException 429 "Sin intentos restantes"
# 3. No tiene intento 'in_progress' ya → si tiene: retorna el existente
# Lógica:
# INSERT challenge_attempts (status='in_progress', started_at=now())
# Retorna: AttemptStartOut
```

### 4.2 submit_attempt(db, student_id, tenant_id, attempt_id, answers: list[AnswerSubmit]) -> AttemptSubmitOut

```python
# Validaciones:
# 1. attempt_id pertenece a student_id
# 2. status = 'in_progress'
# 3. len(answers) == len(challenge.questions)

# Calificación:
# Para cada answer:
#   - Busca question por question_id
#   - Compara answer.answer con question.correct_answer (case-insensitive, strip)
#   - Registra {question_id, given_answer, correct_answer, is_correct}
# score_percent = (correctas / total) * 100
# is_correct = score_percent == 100  (para multiple_choice)
#            = score_percent >= 70   (para open/fill_blank)

# Coins y XP:
# Si is_correct:
#   coins_earned = challenge.coins_reward
#   xp_earned = challenge.xp_reward
#   streak_bonus = 0  (reservado para Fase 3)
#   award_coins(db, student_id, tenant_id, coins_earned, 'challenge', {challenge_id, attempt_id})
#   UPDATE profiles SET xp = xp + xp_earned WHERE id = student_id
#   UPDATE challenges SET current_winners = current_winners + 1 WHERE id = challenge_id
# Si not is_correct:
#   coins_earned = 0, xp_earned = 0

# Feedback IA (opcional, no bloquear si falla):
# drako_feedback = await generate_feedback(student_answers, challenge) or None

# UPDATE challenge_attempts SET
#   status='completed', completed_at=now(),
#   answers=answers_json, score_percent=X,
#   is_correct=X, coins_earned=X, xp_earned=X,
#   drako_feedback=X

# Retorna: AttemptSubmitOut
```

### 4.3 get_attempt_history(db, student_id, tenant_id) -> list[ChallengeAttempt]

```python
# SELECT challenge_attempts WHERE student_id=X AND tenant_id=Y
# ORDER BY created_at DESC
# LIMIT 20
```

---

## 5. Generator Service — src/challenge_engine/service/generator.py

```python
# Genera challenges usando Anthropic API

async def generate_challenge(
    cefr_level: str,
    skill: str,
    topic: str,
    num_questions: int,
    specific_instructions: str | None
) -> ChallengeCreate:

# Prompt al modelo:
# - Rol: experto en enseñanza de inglés nivel {cefr_level}
# - Tarea: generar {num_questions} preguntas de opción múltiple sobre {topic}
# - Habilidad: {skill}
# - Formato respuesta: JSON estricto con estructura ChallengeCreate
# - Instrucciones adicionales si las hay

# Usar modelo: claude-sonnet-4-20250514 (NUNCA hardcodear, usar settings)
# max_tokens: 2000
# Parsear respuesta JSON
# Retorna: ChallengeCreate listo para create_challenge()

# Si falla la API → HTTPException 503 "Servicio de IA no disponible"
# Registrar en ai_usage_logs: tokens_used, model, cefr_level, skill, topic
```

---

## 6. Router — src/challenge_engine/router.py

```
# TEACHER endpoints
POST   /challenges/
       - Auth: require_teacher
       - Body: ChallengeCreate
       - Retorna: ChallengeOut

POST   /challenges/generate
       - Auth: require_teacher
       - Body: ChallengeGenerateRequest
       - Retorna: ChallengeOut (crea el challenge directo)

GET    /challenges/all
       - Auth: require_teacher
       - Retorna: list[ChallengeOut] todos del tenant

PATCH  /challenges/{challenge_id}/status
       - Auth: require_teacher
       - Body: {status: str}
       - Retorna: ChallengeOut

# STUDENT endpoints
GET    /challenges/
       - Auth: get_current_user
       - Retorna: list[ChallengeOut] disponibles para el estudiante
       - SIN correct_answer en las preguntas

GET    /challenges/{challenge_id}
       - Auth: get_current_user
       - Retorna: ChallengeOut (sin correct_answer)

POST   /challenges/{challenge_id}/attempt
       - Auth: get_current_user
       - Retorna: AttemptStartOut

POST   /attempts/{attempt_id}/submit
       - Auth: get_current_user
       - Body: {answers: list[AnswerSubmit]}
       - Retorna: AttemptSubmitOut

GET    /attempts/history
       - Auth: get_current_user
       - Retorna: list de intentos del estudiante
```

---

## 7. Registro en main.py

```python
from src.challenge_engine.router import router as challenges_router
app.include_router(challenges_router, prefix="/challenges", tags=["challenges"])
```

---

## 8. Variable de entorno requerida

```
ANTHROPIC_API_KEY=sk-ant-...   # agregar al .env
```

---

## 9. Regla de negocio crítica

**correct_answer NUNCA sale en respuestas al estudiante.**

En `ChallengeQuestionOut` no incluir `correct_answer`.
Solo se revela en `AttemptSubmitOut.correct_answers` DESPUÉS de completar el intento.

---

## 10. Tests — tests/challenge_engine/

```python
# test_challenges.py
# test_create_challenge_teacher → 201
# test_create_challenge_student → 403
# test_list_challenges_student → solo activos del grupo
# test_challenge_hides_correct_answer → correct_answer no en response

# test_attempts.py
# test_start_attempt → attempt creado in_progress
# test_start_attempt_max_exceeded → 429
# test_submit_all_correct → coins_earned > 0, is_correct=True
# test_submit_all_wrong → coins_earned=0, is_correct=False
# test_submit_partial → score_percent correcto
# test_submit_duplicate → 409 (ya completado)
```

---

## 11. Checklist para Windsurf

- [ ] src/challenge_engine/schemas.py
- [ ] src/challenge_engine/service/challenges.py
- [ ] src/challenge_engine/service/attempts.py
- [ ] src/challenge_engine/service/generator.py
- [ ] src/challenge_engine/router.py
- [ ] Registrar router en main.py
- [ ] Agregar ANTHROPIC_API_KEY al .env.example
- [ ] tests/challenge_engine/test_challenges.py
- [ ] tests/challenge_engine/test_attempts.py
- [ ] Verificar:
  - `GET /challenges/` sin auth → 401
  - `POST /challenges/` con JWT estudiante → 403
  - `correct_answer` NO aparece en GET /challenges/
- [ ] Commit: `feat(challenges): implement challenge engine with AI generation`

---

**Próxima spec:** SPECS/04-leaderboard.md
**Generada por:** Claude Sonnet 4.6
**Implementación:** Windsurf (src/challenge_engine/)
