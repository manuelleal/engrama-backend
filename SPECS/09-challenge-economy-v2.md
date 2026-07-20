# SPECS/09-challenge-economy-v2.md — Economía v2 del challenge_engine
# Estado: 📝 spec listo — pendiente de implementación
# Tipo: ENMIENDA a src/challenge_engine/ (ver SPECS/03-challenges.md)
# Fecha: 2026-07-19

## 0. Objetivo

Reemplazar el sistema de recompensas binario (correcto → coins fijo, incorrecto → 0) por
una economía graduada que premia DOMINIO. Activar `streak_bonus` y `drako_feedback` (hoy
siempre 0 y None). Añadir tope diario anti-farming y tracking de habilidades débiles en
`StudentProgress`. No se crean tablas ni migraciones: todos los campos ya existen.

---

## 1. Cambios vs spec 03

| Aspecto | Antes (spec 03) | Después (v2) |
|---|---|---|
| Coins/XP base | `challenge.coins_reward` fijo si is_correct | Tabla por score_percent (§3.1) |
| streak_bonus | Siempre 0 ("reservado Fase 3") | Multiplicador activo por racha |
| drako_feedback | Siempre None ("TODO Fase 2") | Plantillas determinísticas |
| weak_skills en attempt | Siempre [] | Skills con accuracy < 60% |
| StudentProgress | No se actualiza | UPSERT por skill al completar |
| Tope diario | Sin límite | Máx 50 coins/día por challenges |
| Recompensa por posición | — | Pendiente Fase D (config `reward_mode`) |

---

## 2. Schemas — src/challenge_engine/schemas.py

`AttemptSubmitOut` añade tres campos (sin tocar los existentes):

```python
class AttemptSubmitOut(BaseModel):
    # ... campos existentes sin cambio ...
    # --- nuevos ---
    daily_coins_remaining: int  # cuántos coins más puede ganar hoy (para UI)
    weak_skills: list[str]      # skills con accuracy < 60% y >= 3 intentos
    coins_capped: bool          # True si el tope diario recortó la recompensa
```

---

## 3. Lógica — src/challenge_engine/service/economy.py (archivo nuevo)

Funciones puras, sin I/O, testeables sin DB.

### 3.1 compute_rewards(score_percent, streak) -> (coins, xp)

Tabla base (del MVP `computeChallengeRewards`). Redondeo: `round()` estándar Python.

| score_percent | base_coins | xp |
|---|---|---|
| == 100 | 5 | 10 |
| >= 80 | 4 | 8 |
| >= 60 | 3 | 5 |
| >= 40 | 2 | 3 |
| < 40 | 0 | 1 |

Multiplicador de racha sobre base_coins (se suma, no multiplica total):

| streak | bonus |
|---|---|
| >= 7 | round(base_coins * 0.50) |
| >= 3 | round(base_coins * 0.25) |
| >= 1 | +1 fija |
| 0 | 0 |

`streak_bonus_amount(base_coins, streak) -> int` devuelve solo el bonus para el payload.

### 3.2 remaining_daily_cap(awarded_today: int) -> int

```python
DAILY_CAP_COINS = int(os.getenv("CHALLENGE_DAILY_CAP", 50))

def remaining_daily_cap(awarded_today: int) -> int:
    return max(0, DAILY_CAP_COINS - awarded_today)
```

`awarded_today` se consulta sobre `coin_ledger` filtrando `action='challenge'`,
`to_wallet.owner_id == student_id`, y `date(created_at AT TIME ZONE 'America/Bogota') == today`.
XP nunca se topa; si `remaining == 0`, `coins_earned = 0` pero `xp_earned` se otorga igual.

### 3.3 drako_message(score_percent, weak_skills, streak) -> str

Plantillas determinísticas (sin LLM, Fase inicial):

| score | mensaje base |
|---|---|
| 100 + streak >= 7 | "🐉 Perfect score AND a {streak}-day streak? You're absolutely on fire!" |
| 100 | "🐉 Perfect score! Outstanding work!" |
| >= 80 | "🐉 Great job! You're very close to mastery." |
| >= 60 | "🐉 Good effort! Keep practicing." |
| >= 40 | "🐉 You're making progress. Don't give up." |
| < 40 | "🐉 This was tough, but I believe in you!" |

Si `weak_skills` no vacío, añade: `"Focus on: {', '.join(weak_skills)}."`.
Si `streak >= 1` (scores < 60), añade: `"Keep that {streak}-day streak alive!"`.

### 3.4 update_skill_progress(db, *, student_id, tenant_id, skill, cefr_level, is_correct) -> list[str]

UPSERT en `student_progress` (ON CONFLICT tenant+student+skill):
- `total_attempts += 1`, `correct_attempts += (1 if is_correct else 0)`
- `accuracy_percent = correct_attempts / total_attempts * 100`
- `is_weak = accuracy_percent < 60 AND total_attempts >= 3`
- Devuelve lista de skills con `is_weak = True` para el estudiante (para `weak_skills` en attempt y Drako).

---

## 4. Flujo de submit_attempt (orden de operaciones)

```
1. Validar attempt (igual que spec 03)
2. Calificar → score_percent, is_correct (igual que spec 03)
3. Leer profile.current_streak
4. economy.compute_rewards(score_percent, streak) → (total_coins, xp)
5. economy.streak_bonus_amount(base_coins, streak) → streak_bonus (desglose)
6. Consultar awarded_today → remaining = remaining_daily_cap(awarded_today)
7. coins_to_award = min(total_coins, remaining); coins_capped = coins_to_award < total_coins
8. Si coins_to_award > 0 Y cupo max_winners disponible → award_coins(); challenge.current_winners += 1
9. profile.xp += xp  (siempre, sin tope)
10. update_skill_progress(skill=challenge.skill) → weak_skills
11. drako_feedback = economy.drako_message(score_percent, weak_skills, streak)
12. Persistir attempt: streak_bonus, weak_skills, drako_feedback, coins_earned=coins_to_award, xp_earned
13. Retornar AttemptSubmitOut con daily_coins_remaining, weak_skills, coins_capped
```

---

## 5. Permisos — sin cambios

Igual que spec 03 §6. No se añaden ni modifican roles ni rutas.

---

## 6. Tests — tests/challenge_engine/test_economy.py (nuevo, sin DB)

```python
# compute_rewards
# test_rewards_100_no_streak      → (5, 10)
# test_rewards_100_streak_7       → (8, 10)   # 5 + round(5*0.5)=3 → 8? verificar Python round
# test_rewards_80_streak_3        → (5, 8)    # 4 + round(4*0.25)=1 → 5
# test_rewards_60_streak_1        → (4, 5)    # 3 + 1
# test_rewards_39_no_streak       → (0, 1)
# test_rewards_40_no_streak       → (2, 3)

# remaining_daily_cap
# test_cap_zero_earned → 50; test_cap_45_earned → 5; test_cap_exceeded → 0

# drako_message
# test_drako_perfect_hot_streak → contiene "fire"
# test_drako_weak_skills_hint   → contiene "Focus on"
# test_drako_below_40_streak    → contiene "I believe" y "streak"

# Integración (mock DB)
# test_submit_capped_daily      → coins_capped=True, daily_coins_remaining=0
# test_submit_updates_progress  → student_progress.total_attempts incrementa
# test_submit_marks_weak_skill  → is_weak=True tras 3 intentos con accuracy<60
```

---

## 7. Migración

No se necesita migración de schema. Verificar antes de implementar:

| Campo | Tabla | Estado en models.py |
|---|---|---|
| `streak_bonus` Integer default 0 | `challenge_attempts` | OK (línea 511) |
| `weak_skills` JSONB default [] | `challenge_attempts` | OK (línea 513) |
| `drako_feedback` Text nullable | `challenge_attempts` | OK (línea 516) |
| `student_progress` completa con `is_weak` | `student_progress` | OK (líneas 602-641) |

---

## 8. Pendiente / Fase D

- **Modo competitivo por posición**: recompensa 40/20/10 coins al top-3 por llegada
  (docx v2 fundador). Config por challenge: `reward_mode: 'score' | 'position'`.
- **Feedback LLM de Drako**: reemplazar plantillas por Anthropic API con contexto de
  weak_skills e historial. Registrar en `ai_usage_logs`.
- **Power-ups durante el reto**: pistas a 2 coins (sink ya documentado en el MVP).
- **`recommendNextChallenge()`** de Drako con UI en el panel de resultados.

---

**Archivos a crear/modificar:**
- `src/challenge_engine/service/economy.py` — nuevo (funciones puras)
- `src/challenge_engine/service/attempts.py` — modificar submit_attempt (§4.2 spec 03)
- `src/challenge_engine/schemas.py` — añadir 3 campos a AttemptSubmitOut
- `tests/challenge_engine/test_economy.py` — nuevo

**Generada por:** Claude Sonnet 4.6
