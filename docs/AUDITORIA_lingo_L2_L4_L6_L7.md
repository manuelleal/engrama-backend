# Auditoría (solo lectura) de L2, L4, L6 y L7 del encargo Lingo · 2026-09-28

- **Fuente:** `ENGRAMA/engrama-web/docs/ENCARGO_F4_lingo.md` (engrama-web `cb3f0e9`, de ARQUITECTO).
- **Auditor:** agente `auditor`, sobre el HEAD `587fc67`. Todo se hizo por lectura de código, sin ejecutar nada. Las citas se tomaron con `grep -n` en el momento; `models.py` estaba en edición por BUG-11, así que sus líneas pueden haberse corrido.
- El coordinador persiste este informe (ERR-3).

| # | Hallazgo | Veredicto | Severidad | ¿Antes del login 008? |
|---|---|---|---|---|
| L2 | Doble paga de un mismo reto, **secuencial**: no hace falta concurrencia | CONFIRMADO, peor de lo descrito | BLOQUEA (economía) | Sí → **BUG-13** |
| L4-a | El check-in no valida el grupo de la sesión | CONFIRMADO; no cruza colegios | BLOQUEA (seguridad y economía) | Sí → **BUG-14** |
| L6 | Un estudiante abre y juega retos de otro grupo del mismo colegio | CONFIRMADO para "otro grupo"; REFUTADO para "otro colegio" | BLOQUEA (seguridad y economía) | Sí → **BUG-15** |
| L4-b | La racha cuenta por día calendario, no por sesiones del grupo | CONFIRMADO | DEBE ARREGLARSE (pedagogía) | No; va con el pedagogo (ERR-16) |
| L4-c | Dos sesiones el mismo día reinician la racha; el comentario de `attendance.py:109` es falso | CONFIRMADO | DEBE ARREGLARSE | No; con L4-b |
| L4-d | Racha global en `Profile` (BUG-12) | CONFIRMADO | DEBE ARREGLARSE | No |
| L7 | La rama `feat/leaderboard` (`5d8168b`) toma el nombre de `profiles.full_name`, no usa `visible_groups` y responde 403 en vez de 404 | CONFIRMADOS los tres | DEBE ARREGLARSE (rama sin fusionar) | No; se porta con las 3 correcciones |

## Evidencia

**L2**
- `src/challenge_engine/service/attempts.py:113-174` (`start_attempt`) solo valida `total_attempts >= max_attempts` (`:154`).
- No existe el chequeo "¿ya ganó antes?". `grep -rn "with_for_update\|has_correct_before\|already_won" src/challenge_engine/` da 0 resultados.
- `:229` paga si `is_correct and current_winners < max_winners`, sin mirar si el estudiante ya cobró.
- `models.py:421-429` trae por defecto `max_attempts=2` y `max_winners=10`, así que el segundo intento correcto paga otra vez.
- `award_coins` (`src/engrama_core/service/coins.py:87-127`) no es idempotente por `(challenge_id, student_id)`.

**L4-a**
- `src/engrama_core/service/attendance.py:235-238` busca la sesión solo por `session_code` + `tenant_id`, sin cruzarla con la `Membership` ni con el grupo de la sesión.
- Paga `ATTENDANCE_COINS_BASE=50` por el multiplicador (`:52`, `:302-303`).
- El UNIQUE es por `(session_id, student_id)`, así que cada sesión ajena es otra paga.

**L4-b y L4-c**
- `compute_next_streak` (`attendance.py:99-110`) hace aritmética de fechas civiles.
- Una clase de martes y jueves siempre reinicia la racha a 1.
- Dos asistencias el mismo día caen en el `return 1` (`:110`).

**L6**
- `src/challenge_engine/router.py:214-228` (GET) y `:231-249` (POST attempt) llaman a `get_challenge` (`service/challenges.py:185-198`), que filtra solo por `tenant_id`.
- `group_filter` (`:125-139`) solo existe en el feed (`list_challenges_for_student`, `:107-164`).
- Combinado con L2, un estudiante cobra un reto que no le asignaron.

**L7**
- `git show 5d8168b:src/leaderboard/service.py` selecciona `Profile.full_name` (el patrón de BUG-11).
- `_resolve_scope` devuelve el grupo pedido a cualquier docente o admin (el patrón de BUG-10).
- A un estudiante de otro grupo le responde 403.
- El aislamiento por tenant sí está.

## Orden decidido por el coordinador
BUG-11 (en curso) → **BUG-13/14/15**, una espec (`ESPEC_bug13a15.md`) → login 008 → el resto del encargo Lingo, en el orden de ARQUITECTO. L4-b, L4-c y L4-d pasan antes por el pedagogo.
