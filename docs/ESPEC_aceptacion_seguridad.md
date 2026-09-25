# ESPEC · Aceptación de seguridad: los ataques de coins-mvp contra el backend

F4 · Creador · 2026-09-24 · base `16de639` · preregistro (decisión 004-A).

## 0. Hallazgo medido
Sondeo desechable (misma imagen, 29 migraciones, puerto 55433, datos sintéticos):
- **Todo acceso `authenticated` que toca `memberships` da `42P17`, recursión infinita:** la política se consulta a sí misma (`029:105` con `029:127-138`). La RLS "rechaza" todo por rotura, también lo legítimo → **BUG-2**. Un test de "rechazo" pasaría vacío (ERR-8).
- Con una política no recursiva **simulada solo en el sondeo**, pasan 7 ataques (BUG-3 a 8). Los controles se sostienen.
- `anon` y `authenticated` tienen todos los privilegios de tabla: **la RLS es la única barrera**. `auth.uid()` lee `request.jwt.claim.sub`.

## 1. Qué cambia (una cosa)
Nace `tests/seguridad/test_aceptacion.py`: un test por ataque que afirma el **rechazo**, más un helper en `integ_db.py`.

## 2. Mapa
| Ataque | Equivalente | Debe dar | Hoy |
|---|---|---|---|
| E1, H-1, H-2 | `anon` SELECT `profiles`; `/auth/me` | 0 filas; sin `pin_hash` | **Rechaza:** 029 solo crea políticas `TO authenticated` (medido); `auth/schemas.py:34-49` |
| E1b | admin de T2 o docente leen `pin_hash` ajeno | 0 filas | **Pasa → BUG-8** (`029:203-231`: el admin no filtra tenant) |
| E2, H-3 | UPDATE `coin_wallets`; rutas | `UPDATE 0`; ninguna ruta escribe saldo | **Rechaza** (medido); `engrama_core/router.py:46-76` solo lee |
| E2b | UPDATE de la propia `current_streak`, `xp` o `role` | no editable | **Pasa → BUG-6** (`029:233-238`); la racha multiplica monedas (`attendance.py:293,302`) |
| E3 | detalle del reto; SELECT `challenge_questions` | sin la respuesta | API **rechaza** (`challenges.py:237-256`); base **pasa → BUG-3** (`029:161-174`) |
| E4 | submit con campos extra; INSERT `challenge_attempts` | 422; 42501 | API **rechaza** (`schemas.py:22`, `attempts.py:221-248`); base **pasa → BUG-4** (`029:111`) |
| E5 | INSERT `memberships` `admin` para otro perfil | 42501 | **Pasa → BUG-5** (`029:105`); agrava: todo JWT válido crea perfil (`auth/service.py:104-117`) |
| E6 | INSERT `coin_ledger` | 42501 | **Rechaza** (medido) |
| E7 | — | — | **No aplica:** `tenants` no tiene clave (`001`); la clave está en `config.py:57` |
| R1 | submit ajeno; intento con `student_id` ajeno | 404; 42501 | API **rechaza** (`attempts.py:190-200`); base **→ BUG-4** |
| R2 | mover monedas ajenas | — | API **rechaza:** solo acredita el tenant (`coins.py:116-121`) |
| R3 | — | — | **No aplica:** no recibe PIN; el login es Supabase Auth |
| R4, H-6 | alumno en rutas `require_teacher` | 403 | **Rechaza:** el rol sale de la membresía (`auth/service.py:226-234`, `deps.py:106-115`). Pero `ProfileOut.role` es editable (BUG-6) |
| H-5 | `USING (true)` | 0 | **Rechaza:** la 029 no tiene ninguna |
| H-7 | JWT por usuario | 401 | **Rechaza** (`deps.py:54-72`, `tests/auth`) |
| Nuevo | el alumno crea `attendance_sessions` y hace check-in | 42501 | **Pasa → BUG-7** (`029:108`; `attendance.py:235-238`) |

H-8 a H-11 no aplican: los secretos son sintéticos (`conftest.py:19`).

## 3. Tests (`integ`)
**Helper `Integ.como(perfil | None, sql)`:** en una transacción:
1. `SET LOCAL ROLE authenticated` (o `anon`);
2. `set_config` de `request.jwt.claim.sub` y de `request.jwt.claims`;
3. ejecuta y devuelve las filas o el SQLSTATE;
4. ROLLBACK.

**A la fixture le falta solo esto:** conecta como superusuario `postgres` (`integ_db.py:71-73`), que ignora la RLS.

**Regla anti-vacío:** cada test de base lleva un **control** en la misma prueba: el dueño lee su fila o la escritura como `postgres` funciona. Rechazo válido = 0 filas, `UPDATE 0` con el valor intacto o **42501**. **`42P17` u otro error = rojo.**

| Id | Afirma | Tramposo | Hoy |
|---|---|---|---|
| A1 | `/auth/me` sin el hash | `profile_to_schema` lo copia en `full_name` | pasa |
| A2 | `/core/coins` solo GET; PATCH → 405 | ruta PATCH agregada | pasa |
| A3 | detalle e intento sin el valor de `correct_answer` | `question_to_schema` lo pone en `question_text` | pasa |
| A4 | extra `coins_earned` → 422, saldo intacto; todo mal → 0 | `is_attempt_correct` → `True` | pasa |
| A5 | B envía el intento de A → 404; sigue `in_progress` | submit con el dueño del intento | pasa |
| A6 | `profiles.role='super_admin'` con membresía de alumno → 403 | `build_auth_context` toma `profile.role` | pasa |
| A7 | `X-Tenant-ID` ajeno → 403; reto de T2 → 404 | `get_challenge` sin tenant | pasa |
| D1 | `anon`: SELECT → 0; INSERT → 42501 | política `TO anon USING (true)` | pasa |
| D4 | E6 | `WITH CHECK (true)` | pasa |
| D10 | 0 políticas `true` o `TO anon` | se crea una | pasa |
| D2 | E1b | `USING (true)` | xfail BUG-2 → 8 |
| D3 | E2, con el control del dueño | ídem | xfail BUG-2 |
| D5-D9 | E3, E4/R1, E5, E2b y nuevo (el check-in → 404) | ídem | xfail BUG-3 a 7 |
| D11 | INSERT de alumno en 8 tablas de módulos vacíos (parametrizado) | ídem | xfail BUG-9 (predicho) |

- Tramposos: `tests/tramposos/test_tramposos_seguridad.py`, patrón de `test_tramposos_integ.py`.
- Los xfail llevan `strict=True, raises=AssertionError`; su tramposo se corre en la espec de su BUG.

## 4. Hoy o después
- **Hoy, por API:** auth, challenges, core.
- **Hoy, en la base (las tablas existen):** D11 cubre `shop_items`, `inventory`, `bets`, `auction_bids`, `badge_unlocks`, `announcements`, `teacher_groups` y `groups`.
- **Exige módulos:** R2 por compra, apuesta o subasta; las escrituras del docente (teachers); `xp` en el ranking (`feat/leaderboard`).

## 5. Criterio medible
- `python -m pytest -q` → ~~112 passed~~ **122 passed, 15 xfailed, 0 failed**. Corregido por ERR-10: los 10 tramposos también se recolectan (102 + 10 + 10).
- Los 102 ids anteriores, en PASSED.
- 10 tramposos, cada uno en rojo en su test. **Excepción documentada (ERR-10):** los tramposos D1 y D4 abren una política `USING (true)` o `WITH CHECK (true)`, que es justo lo que D10 detecta, así que también ponen en rojo a D10. Cualquier otro rojo fuera de la diagonal es fallo.
- El motivo de cada xfail registra el SQLSTATE obtenido.

**Falló si:**
- un test pasa con su tramposo;
- un rechazo no tiene control;
- un xfail cae por otra excepción;
- cambia uno de los 102.

## 6. Humo y réplica
- **Humo:** D1, D4 y D7 escriben `tests/_salida/humo_seguridad.json` (`id, rol, sqlstate, filas, veredicto`). Sin él no hay corrida grande.
- **Réplica:** se invierte el sentido (B ataca a A, T1 ataca a T2), `uuid4` nuevos, conteos idénticos.

## 7. Qué NO se toca
- `src/**` y `alembic/versions/**`. BUG-2 cambiará `politicas_public = 51`; ese criterio va en su espec, antes del código.
- Los 102 tests, `HUMO_ESPERADO`, las líneas existentes de `integ_db.py`, coins-mvp, `engrama-test-pg` y Supabase remoto.

**Para Christiam:** ¿`authenticated` escribe directo (ADR-003) o todo pasa por `service_role` (`db.py:3-8`)? Cambia cómo se arreglan BUG-4 a BUG-7, no los tests.

**Después:** check-in o intento en otro grupo (`attendance.py:235-238`, `attempts.py:122`); carreras en `max_attempts` y `current_winners`.
