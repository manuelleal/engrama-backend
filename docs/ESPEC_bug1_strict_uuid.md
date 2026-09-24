# ESPEC · BUG-1: UUID de entrada bajo `strict=True` (frente F4)

Creador · 2026-09-24 · base `4a570a8` · se commitea antes del código.

## 0. Inventario (medido, sin tocar `src/`)
FastAPI valida el cuerpo en **modo Python** (`validate_python` sobre el dict ya parseado). En ese modo, `strict` no convierte `str→UUID`. Sondeado con `model_validate` y por HTTP (`TestClient`, auth y db sustituidas; pydantic 2.12.5).

| Esquema de entrada | Campo de texto | Hoy |
|---|---|---|
| `AnswerSubmit` (`challenge_engine/schemas.py:136`) | `question_id: UUID` `:141` | **422 `is_instance_of`** (vía `AttemptSubmitRequest` `:145`) |
| `ChallengeCreate` (`:51`) | `group_id: UUID \| None` `:67` | **422** si llega un grupo; pasa con `None` |
| `ChallengeGenerateRequest` (`:71`) | `group_id: UUID \| None` `:80` | **422** si llega un grupo; pasa con `None` |
| `ChallengeQuestionIn` `:35`, `ChallengeStatusUpdate` `:84` | ninguno | pasa |
| `AttendanceSessionCreate`, `CheckInRequest` (`engrama_core/schemas.py:73,95`) | ninguno (`float` acepta int) | pasa |

No hay `datetime`, `date`, `Decimal` ni `Enum` en ninguna entrada. `auth/schemas.py` solo tiene salidas y `AuthContext` (interno, `auth/service.py:228`). Los demás `schemas.py` de `src/` están vacíos (0 líneas).

## 1. Qué cambia (una cosa)
En `src/challenge_engine/schemas.py`:

```python
UUIDIn = Annotated[UUID, Strict(False)]  # JSON trae UUID como texto
```

y se aplica **solo** a `:67`, `:80` y `:141`.

**Por qué no `strict=False` en todo el modelo:** en modo laxo, `"10"` pasa a `int` y `"yes"` a `bool` (medido), así que `coins_reward` y los demás aceptarían texto. Con el tipo por campo, el resto sigue estricto: `"10"` sigue dando `int_type` y `extra="forbid"` se mantiene (medido sobre el candidato).

## 2. Qué NO se toca
- `_STRICT` y `extra="forbid"`.
- Los esquemas de salida.
- `auth/` y `engrama_core/`.
- `generator.py`: ya pasa `UUID`.
- `alembic/`.
- Los 5 tests de submit: solo se quita `@_BUG_1` (y su definición, `test_attempts.py:205`) y se agrega al final del primero la escritura del humo (§5).

## 3. Qué debe pasar (medible)

| Id | Comando | Esperado |
|---|---|---|
| A | `python -m pytest -q` | **102 passed, 0 xfailed, 0 failed, 0 skipped** |
| B | `python -m pytest -m "not integ" -q -rA` | Los 71 ids de `tests/_salida/ids_71_antes.txt` siguen en PASSED (`diff` sin quitados), más 3 nuevos = 74 |
| C | `grep -c "_BUG_1" tests/challenge_engine/test_attempts.py` | `0` |

**Corrección al encargo:** "94 → 99" no cuenta los 3 tests nuevos. La suma real es 94 + 5 + 3 = 102.

**Tests nuevos:** `tests/challenge_engine/test_schemas_entrada.py`, sin DB y parametrizado con 3 ids, uno por esquema afectado. Cada caso hace `model_validate` de un dict como el de JSON (`{"question_id": str(u), ...}`) y afirma:
- `campo == u` y es de tipo `UUID`;
- `"no-es-uuid"` da `ValidationError` con tipo `uuid_parsing`;
- una clave extra da `extra_forbidden`.

## 4. Cómo sabremos que FALLÓ: el tramposo
**Tramposo:** volver a `question_id: UUID` en `:141`.

**Esperado:**
- los 5 `test_submit_*` en **FAILED** (ya no xfail), con `assert 422 == 200` y un cuerpo 422 que nombre `question_id` e `is_instance_of`;
- el caso `AnswerSubmit` del test nuevo en rojo.

Cada test de submit afirma 200 **y** contenido concreto (score, monedas, saldos, ledger): la aserción que falla queda identificada (resuelve H-1).

**Tramposo 2:** quitar `UUIDIn` de un `group_id`. Debe ponerse en rojo solo su caso parametrizado.

**Ya medido antes de la espec**, cargando el arreglo en memoria con un plugin de pytest del scratchpad, sin tocar el disco:

| Escenario | Resultado |
|---|---|
| Arreglo candidato | 94 passed y los 5 en `XPASS(strict)` |
| Tramposo (el arreglo sin `:141`) | los 5 dan `assert 422 == 200` |
| Base actual | 94 passed, 5 xfailed |

El `git diff src/` final: solo el arreglo.

## 5. Humo
`humo_integ.json` no cambia.

Se suma `tests/_salida/humo_bug1.json`, que escribe al final `test_submit_all_correct_awards_coins_and_xp` (submit real por HTTP; no es un test nuevo, el conteo sigue en 102):
- `status`: `200`;
- `score_percent`: `100.0`;
- `coins_earned`: `20`;
- `ledger_filas`: `1`.

Si el archivo no existe, no hay veredicto.

## 6. Réplica
- Correr `python -m pytest` dos veces con `uuid4()` nuevos: mismos conteos y `humo_bug1.json` idéntico.
- Sin `engrama-test-pg` al final.
- Los contenedores `*_coins-mvp` en `Up`.

## 7. Veredicto por la letra
**VERDE** solo si se cumplen A, B y C, el tramposo 1 y el tramposo 2 salen en rojo, y existe el humo.

Cualquier otro conteo es **ROJO**: se reporta y no se ajusta ni el test ni la cifra.
