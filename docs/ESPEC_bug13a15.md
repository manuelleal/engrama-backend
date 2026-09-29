# ESPEC · BUG-13, 14 y 15: una sola paga por reto, check-in solo del propio grupo y retos solo del propio grupo

F4 · Creador · 2026-09-28 · preregistro. Rama `test/fixture-integ`. Se leyó con HEAD `7a5d6d1` y BUG-11 sin commitear; al cerrar, BUG-11 ya estaba en `632546e` (la 032) y `566ae0c`, y las citas de `models.py` se re-verificaron con `grep -n`: no se movieron. Origen: `docs/AUDITORIA_lingo_L2_L4_L6_L7.md` (`4e147c6`) y `ENGRAMA/engrama-web/docs/ENCARGO_F4_lingo.md` (L2, L4-a y L6).

**Alcance: solo tres huecos.** BUG-13 (L2), BUG-14 (L4-a) y BUG-15 (L6). La racha (L4-b, L4-c y BUG-12) queda **fuera**: va con el pedagogo (§9).

**Depende de BUG-11.** Esta espec se implementa cuando BUG-11 esté commiteado (032 + código). Parte de su meta final: **280 passed + 9 skipped y 100 no-integ**, que no está medida hoy (§4).

## 0. Medido y leído
**Medido (2026-09-28, sin Docker, solo git):**
- `git log --all --oneline -- 'alembic/versions/033*' 'alembic/versions/034*'` sale vacío: no hay 033 ni 034 en ninguna rama.
- `alembic/versions/032_nombre_por_membresia.py` se leyó sin commitear; al cerrar esta espec ya está en `632546e`.
- `ESPEC_login_vendible.md` (`59045e4`) todavía dice `032_login_vendible`. `ESPEC_bug11.md` §6.1 la movió a 033 en el papel.
- La suite **no se corrió**: el encargo prohíbe tocar Docker (ERR-21), y la cuenta no-integ de hoy depende del WIP de BUG-11.

**Leído con `grep -n` en el momento, sin ejecutar.** Las líneas de `src/shared/models.py` están **sujetas a la 032**: se tomaron con los cambios de BUG-11 en el disco (`Membership.full_name`, desde la 158) y se re-verificaron contra `632546e` (`CoinLedger` en 276, UNIQUE de asistencia en 383, `max_attempts` en 421 y `ChallengeAttempt` en 486). Si la 032 se corrige, pueden correrse.

| Qué | Dónde |
|---|---|
| **L2 · lectura del intento sin bloqueo** | `src/challenge_engine/service/attempts.py:189-205`: `select(ChallengeAttempt)` sin `with_for_update`, y el chequeo `status != "in_progress"` → 409 (`:201-205`) |
| L2 · condición de la paga | `attempts.py:229`: `if is_correct and challenge.current_winners < challenge.max_winners`. **No mira si el estudiante ya cobró** |
| L2 · efectos de la paga | `attempts.py:232-242` (`award_coins` con `metadata = {challenge_id, attempt_id}`), `:244-246` (XP al perfil), `:248` (`current_winners + 1`, leer-modificar-escribir sin bloqueo) |
| L2 · `start_attempt` | `attempts.py:113-174`. Solo limita `total_attempts >= max_attempts` (`:154`). Reusa el `in_progress` (`:130-136`) sin bloqueo ni UNIQUE, así que dos POST simultáneos pueden crear dos intentos `in_progress` |
| L2 · valores por defecto | `models.py:421-429` (sujeto a la 032): `max_attempts=2`, `max_winners=10`, `current_winners=0`. **Con los valores por defecto, el segundo intento correcto cobra otra vez** |
| `ChallengeAttempt` sin UNIQUE | `models.py:486-546` (sujeto a la 032): solo tiene CHECK de `status` e índices |
| **`award_coins` no es idempotente** | `src/engrama_core/service/coins.py:87-150`. Toma los locks en orden tenant → perfil (`:116-121`), revisa el saldo con 402 (`:124-131`), hace el INSERT en el ledger (`:134-143`) y mueve los saldos (`:146-147`). No hay llave |
| El lock de la billetera del tenant serializa todas las pagas del colegio | `coins.py:116-118` (`for_update=True`), `get_wallet` `:60-66` |
| La billetera es global por perfil | `coins.py:60-64` busca sin `tenant_id`, y `models.py:267-269` (sujeto a la 032) tiene UNIQUE `(owner_type, owner_id, currency)`. Va a "Para después" (§9) |
| `coin_ledger` | `models.py:276-312` (sujeto a la 032); `alembic/versions/007_create_coin_ledger.py`. No tiene columna de llave; `metadata` es JSONB |
| **L4-a · búsqueda de la sesión** | `src/engrama_core/service/attendance.py:234-244`: solo `session_code` + `tenant_id`. Después vienen el 410 (`:246-252`), el duplicado 409 (`:254-264`), la racha **global** del perfil (`:282-299`), el monto (`:302-303`) y `award_coins` (`:321-333`) |
| La ruta de check-in | `src/engrama_core/router.py:121-142`. **No tiene guarda de rol:** usa `get_current_user`, así que un docente también marca y cobra |
| La sesión siempre tiene grupo | `models.py:324` (sujeto a la 032), `AttendanceSession.group_id NOT NULL`; `session_code` UNIQUE global en `:327` |
| UNIQUE de asistencia | `models.py:383` (sujeto a la 032), `attendance_session_student_key (session_id, student_id)` |
| **L6 · detalle y arranque sin filtro de grupo** | `src/challenge_engine/router.py:214-228` (GET `/{challenge_id}`) y `:231-249` (POST `/{challenge_id}/attempt`). Los dos pasan por `get_challenge` (`service/challenges.py:185-198`), que filtra solo por `tenant_id` |
| El filtro de grupo existe solo en el feed | `challenges.py:123-139` (`group_filter`: global o `group_id` ∈ grupos del tenant con ese `group_code`), usado en `:153-163` |
| `get_challenge` tiene otros llamadores | `attempts.py:208` (`submit`) y `src/teachers/service/panel.py:156` (T6; archivo con cambios de BUG-11, línea sujeta a la 032). **No cambian** |
| **De dónde sale el grupo del estudiante** | `src/auth/service.py:224-235` (`build_auth_context`): toma la membresía del tenant activo (`X-Tenant-ID` o la primera) y `group_code = membership.group_code` (`:232`). UNIQUE `(tenant_id, profile_id)` en `models.py:166` (sujeto a la 032): **un estudiante tiene un solo grupo por colegio** |
| `visible_groups` y `authorize_group` | `src/teachers/service/access.py:45-83`. Son **solo para el personal** (docente y admin). Su principio (404, nunca 403) es el mismo que usan BUG-14 y BUG-15, pero su código no aplica a un estudiante |

**El hueco, paso a paso (predicho por lectura; los A lo miden en el commit 1):**
1. **BUG-13:** E gana el reto R (20 monedas y 15 XP), abre un segundo intento (201) y lo gana: `attempts.py:229` paga otra vez. Resultado: 2 filas en `coin_ledger`, 40 monedas, 30 XP y `current_winners = 2`. **Un solo estudiante gasta dos cupos de ganador.** El doble toque sobre el mismo intento también paga dos veces, porque las dos lecturas ven `in_progress`.
2. **BUG-14:** E2 (grupo G2) recibe el código de la sesión de G1 y marca: 200, +50 monedas y la racha sube. Si la sesión de G1 ya expiró, recibe **410**: se entera de que ese código existe.
3. **BUG-15:** E1 (G1) abre el reto de G2 por su id (200), lo arranca (201) y, junto con BUG-13, lo cobra.

## 1. Qué cambia
Una espec y **tres cambios, cada uno en su commit** (§10).

### 1.1 BUG-13 · Una sola paga por (reto, estudiante)
**Decisión: las dos cosas, cada una con su papel.**

| Mecanismo | Qué cierra | Qué no cierra solo |
|---|---|---|
| **`SELECT … FOR UPDATE` del intento en `submit`** | El doble toque sobre **el mismo** intento: el segundo espera el commit del primero, ve `completed` y responde **409**. Además el intento no se califica ni se escribe dos veces | Dos intentos **distintos** en vuelo (la carrera de `start_attempt`, `:130-167`). Tampoco cierra caminos futuros que paguen sin pasar por aquí (el `finish` de L1) ni la paga secuencial |
| **Llave de idempotencia en `coin_ledger` con UNIQUE en la BD** | La paga: **una fila** por `(tenant, "challenge:<reto>:<estudiante>")`, venga por donde venga (secuencial, concurrente, `/submit` o el futuro `/finish`). No depende del orden de los locks | Con solo la llave, el doble toque responde **200 + 200** (el segundo con 0 monedas) y escribe el intento dos veces. El encargo pide un 409 |

**Por qué no basta un chequeo en la app** ("¿ya cobró?" antes de pagar): dos intentos en vuelo leen "no" a la vez y los dos pagan. A13-3 lo pone en rojo (predicho). Leer después del lock del tenant sí sería correcto hoy, pero depende de un detalle de `award_coins` (`coins.py:116-118`) que nadie garantiza. **La regla de dinero vive en la BD**, igual que el CHECK de BUG-11.

**Migración `alembic/versions/033_una_paga_por_reto.py`** (revisión `033_una_paga_por_reto`, sobre `032_nombre_por_membresia`). Sigue el patrón de la 032: tuplas `SQL_SUBIR` y `SQL_BAJAR` a nivel de módulo, que `upgrade()` y `downgrade()` recorren con `op.execute`.

`SQL_SUBIR`, idempotente:
```sql
ALTER TABLE coin_ledger ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
WITH candidatos AS (
  SELECT l.id, l.tenant_id, l.created_at,
         'challenge:' || (l.metadata->>'challenge_id') || ':' || w.owner_id::text AS clave
    FROM coin_ledger l
    JOIN coin_wallets w ON w.id = l.to_wallet_id AND w.owner_type = 'profile'
   WHERE l.action = 'challenge' AND l.metadata ? 'challenge_id' AND l.idempotency_key IS NULL
), primeros AS (
  SELECT DISTINCT ON (c.tenant_id, c.clave) c.id, c.clave
    FROM candidatos c
   WHERE NOT EXISTS (SELECT 1 FROM coin_ledger x
                      WHERE x.tenant_id = c.tenant_id AND x.idempotency_key = c.clave)
   ORDER BY c.tenant_id, c.clave, c.created_at, c.id
)
UPDATE coin_ledger l SET idempotency_key = p.clave FROM primeros p WHERE l.id = p.id;
ALTER TABLE coin_ledger DROP CONSTRAINT IF EXISTS coin_ledger_idempotency_key;
ALTER TABLE coin_ledger ADD CONSTRAINT coin_ledger_idempotency_key UNIQUE (tenant_id, idempotency_key);
```

`SQL_BAJAR`:
```sql
ALTER TABLE coin_ledger DROP CONSTRAINT IF EXISTS coin_ledger_idempotency_key;
ALTER TABLE coin_ledger DROP COLUMN IF EXISTS idempotency_key;
```

**Por qué así:**
- **Nullable, con UNIQUE `(tenant_id, idempotency_key)`.** En PostgreSQL los NULL no chocan entre sí: la asistencia y todo lo que no pase llave queda **idéntico**.
- **Backfill:** a la fila de reto **más antigua** de cada (tenant, reto, estudiante) le pone la llave. Las repetidas (dobles pagas históricas) quedan en NULL: se cuentan en §7 y **no se revierten solas**. El `NOT EXISTS` hace que correrlo dos veces no choque.
- **La asistencia no usa llave.** `attendance_session_student_key` (`models.py:383`) ya hace única la paga por (sesión, estudiante) en la misma transacción.
- **No crea tablas, vistas, secuencias ni funciones:** D12 y D13 no cambian, y las políticas siguen en 51. El índice del UNIQUE es relkind `i`, que D12 no mira.
- **El downgrade** solo pierde las llaves, que el código viejo no lee.

**Contrato nuevo de `award_coins`** (`coins.py`):
```python
async def award_coins(db, *, student_id, tenant_id, amount, action, metadata=None,
                      created_by_profile_id=None, idempotency_key: str | None = None
                      ) -> CoinLedger | None
```
- **`idempotency_key=None`:** el comportamiento de hoy, byte a byte (K2 y S13). Devuelve la fila.
- **Con llave:**
  1. los mismos locks, en el mismo orden;
  2. **reclamar** la llave con `INSERT … ON CONFLICT (tenant_id, idempotency_key) DO NOTHING RETURNING`;
  3. si no se insertó nada, devuelve **`None`**: no mueve saldos y **no da 402**;
  4. si se insertó, revisa el saldo (402 → rollback del request, que también deshace el reclamo) y mueve los saldos.
- **Consecuencia buscada:** si el código nuevo corre sin la 033, el `ON CONFLICT` falla (42P10) y la paga no ocurre (500, sin dinero). Falla cerrado (§7).

**`submit_attempt`** (`attempts.py`):
- **`_tomar_intento(db, *, attempt_id, tenant_id, student_id) -> ChallengeAttempt | None`:** el mismo SELECT de `:190-195` con `.with_for_update()`. Se llama por su nombre global del módulo, porque es el punto que parchea Y2.
- **`llave_reto(challenge_id, student_id) -> str`** = `f"challenge:{challenge_id}:{student_id}"`. Formato idéntico al del backfill.
- **El orden no cambia:** tomar intento → 409 si no está `in_progress` → `get_challenge` → `get_questions` → calificar → pagar. `get_questions` es el punto donde los tests ponen la barrera (§3).
- **La paga:** si `is_correct` y hay cupo, `entrada = award_coins(..., idempotency_key=llave_reto(...))`.
  - Solo si `entrada is not None` se suman XP y `current_winners`, y se ponen `coins_earned` y `xp_earned`.
  - Si es `None`: `coins_earned = 0` y `xp_earned = 0`, con el intento `completed` y `is_correct` real.
- **Efecto secundario declarado:** quien vuelve a ganar ya no gasta un cupo de `max_winners`.
- Se corrige el docstring (`:17-22`).

**Qué NO cambia en L2:** `start_attempt` sigue permitiendo repasar hasta `max_attempts`. Si alguien falla el intento 1 y gana el 2, cobra, como hoy. La regla de D3 ("solo paga el **primer intento terminado**") depende de los tramos de L3 y **va con L3**; la llave la soporta sin cambios (§9).

### 1.2 BUG-14 · El check-in exige ser estudiante del grupo de la sesión
**A quién identifica (ERR-7):** al titular del JWT (`sub` → perfil) en su **membresía del tenant activo** (`build_auth_context`, `auth/service.py:224-235`), con su `role` y su `group_code`.

- **`_buscar_sesion(db, *, session_code, tenant_id, group_code, es_estudiante) -> AttendanceSession | None`** (`attendance.py`, llamada por nombre global):
  - devuelve `None` si `not es_estudiante` o si `group_code is None`;
  - si no, `select(AttendanceSession).join(Group, Group.id == AttendanceSession.group_id).where(session_code, AttendanceSession.tenant_id == tenant_id, Group.tenant_id == tenant_id, Group.group_code == group_code)`.
- **`check_in`** recibe además `group_code` y `es_estudiante`. Si `_buscar_sesion` da `None`, lanza el **mismo** `404 {"detail": "Session code not found"}` de hoy (`:241-244`).
  - **La visibilidad se decide ANTES del 410:** una sesión expirada de otro grupo da 404, no 410.
  - El 410, el 409 del duplicado, la racha, el monto y `award_coins` quedan **idénticos** para el caso visible.
- **El router** (`engrama_core/router.py:126-142`) pasa `group_code=auth.group_code` y `es_estudiante=(auth.role == "student")`.
- **Cambio de contrato declarado:** un docente o admin que marca asistencia recibe 404, aunque su membresía tenga `group_code`. Hoy cobra 50 (§8).

### 1.3 BUG-15 · Detalle y arranque de un reto solo si es del grupo del estudiante
**Una sola fuente del filtro** (`service/challenges.py`), llamada por nombre global:
- **`filtro_grupo_estudiante(tenant_id, group_code) -> ColumnElement[bool]`:** el cuerpo actual de `:125-139`, extraído sin cambios. El feed (`list_challenges_for_student`) pasa a usarlo (refactor de identidad: `test_list_challenges_student_filters_by_group` no cambia).
- **`get_challenge_for(db, challenge_id, *, tenant_id, group_code, es_personal) -> Challenge`:**
  - si `es_personal`, delega en `get_challenge` (el personal **no cambia**, como pide el encargo; el resto de BUG-10 para el personal queda en §9);
  - si no, `select(Challenge).where(id, tenant_id, filtro_grupo_estudiante(tenant_id, group_code))`;
  - sin fila → **el mismo `404 {"detail": "Challenge not found"}`** de `get_challenge`. Nunca 403.
- **El router GET `/{challenge_id}`** usa `get_challenge_for` con `es_personal = auth.is_teacher or auth.is_admin`.
- **`start_attempt`** recibe `group_code` y `es_personal` y usa `get_challenge_for`; el router los pasa.
- **`get_challenge` queda igual:** solo por tenant. La siguen usando `submit` (`attempts.py:208`), T6 (`panel.py:156`) y el PATCH de estado.

## 2. Criterios (qué debe pasar, medible)
| # | Criterio | Test que se pone rojo si falla |
|---|---|---|
| C1 | **Una paga, en secuencia:** E gana el intento 1 (20 monedas y 15 XP) y gana un intento 2 `in_progress` sembrado en la base. La 2.ª respuesta es 200 con `is_correct: true`, `coins_earned: 0` y `xp_earned: 0`. Hay **1** fila `action='challenge'` con ese `challenge_id`. Saldo de E = 20; tenant = pool − 20; `profiles.xp` = 15; `current_winners` = 1; el intento 2 queda `completed` con `coins_earned = 0` | A13-1 |
| C2 | **Doble toque:** dos `submit` simultáneos del **mismo** intento (con barrera) dan exactamente `[200, 409]`. El 200 trae `coins_earned: 20`, hay 1 fila y el saldo es 20 | A13-2 |
| C3 | **Dos intentos en vuelo:** dos intentos `in_progress` distintos del mismo E y del mismo reto, enviados a la vez con barrera, dan `[200, 200]`, con `coins_earned` que suma 20, **1** fila y saldo 20. **Control:** la barrera no se rompió (los dos llegaron): si se rompió, `PruebaRota` | A13-3 |
| C4 | **Idempotencia de `award_coins`:** la misma llave en 2 transacciones da fila y luego `None`, con 1 fila y los saldos movidos una vez. La misma llave dos veces en **una** transacción, igual. La repetición con el banco del tenant en 0 da `None`, **no 402** | K1 |
| C5 | **Identidad sin llave:** dos `award_coins` sin llave dan 2 filas y los saldos movidos dos veces, igual que hoy | K2 |
| C6 | **Invariante en la BD:** dos filas con la misma `(tenant, llave)` dan **23505** con `coin_ledger_idempotency_key` en el mensaje. La misma llave en otro tenant entra; dos NULL entran | C13 |
| C7 | **Backfill (033):** sobre un esquema previo a la 033 (preparado con `DROP … IF EXISTS`), `SQL_SUBIR`: la fila de reto más antigua de (T, R, E1) recibe `challenge:R:E1`; la repetida queda en NULL; la de E2 recibe la suya; las de asistencia y de reto sin `challenge_id` quedan en NULL. Las demás columnas no cambian. Correrlo 2 veces no falla ni cambia nada | B1 |
| C8 | **Rollback:** `SQL_BAJAR` quita la columna y el UNIQUE (`information_schema.columns` y `pg_constraint`). Volver a subir deja la columna, el UNIQUE y el backfill | B2 |
| C9 | **Identidad de la primera paga:** la respuesta de `submit` de una primera victoria, la fila del ledger (`amount`, `action` y las claves de `metadata`) y los saldos dan **byte a byte** el snapshot congelado **antes** del cambio (ids normalizados por posición) | S13 |
| C10 | **Check-in de otro grupo:** E2 (G2) con el código de una sesión activa de G1 → 404 con un cuerpo **idéntico** al de un código inexistente. Hay 0 asistencias y 0 filas en el ledger, el tenant sigue con el pool, y la racha y `last_attendance_date` de E2 no cambian | A14-1 |
| C11 | **No delata que existe:** la sesión **expirada** de G1, con E2, da 404 (hoy 410), con el mismo cuerpo | A14-2 |
| C12 | **Solo estudiantes:** un docente del tenant con `group_code = G1` en la sesión de G1 → 404, con el mismo cuerpo. Un estudiante sin `group_code` → 404 | A14-3 |
| C13 | **Controles de check-in** (verdes antes y después): E1 (G1) en G1 → 200, 50 monedas y racha 1. Un código inexistente → 404. Un estudiante de otro colegio con el código → 404 | S14 |
| C14 | **Reto de otro grupo, detalle:** E1 (G1) `GET /challenges/{reto de G2}` → 404 con cuerpo **idéntico** al de un UUID inexistente. E0 (sin grupo) `GET` del reto de G1 → 404 | A15-1 |
| C15 | **Reto de otro grupo, arranque:** E1 `POST /challenges/{reto de G2}/attempt` → 404, mismo cuerpo, y 0 filas en `challenge_attempts` | A15-2 |
| C16 | **Controles de retos** (verdes antes y después): E1 abre el de G1 (200) y el global (200) y arranca el de G1 (201). E0 abre el global (200). **Un docente sin asignación y un admin abren el de G2 → 200** (el personal no cambia). Un estudiante de otro colegio → 404 | S15 |
| C17 | **Una sola fuente del filtro:** el feed y el detalle usan `filtro_grupo_estudiante` | cruce Y10 × `test_list_challenges_student_filters_by_group` (predicho rojo; §3) |
| C18 | Regresión: los 280 previos siguen verdes, sin más edición que `HUMO_ESPERADO`. D12 da 0 y 0; hay 51 políticas | suite completa |

## 3. Tests y tramposos
**Tests nuevos** (integ). Siembra sintética con las fábricas de `tests/integ_ayudante.py`. **ERR-9:** el estado previo se siembra en la base, así que cada A depende solo del endpoint que prueba.
- **`tests/challenge_engine/test_bug13_una_paga.py`:** A13-1, A13-2, A13-3, S13, K1, K2 y C13.
  - Retos con `crear_challenge(respuestas=("A","B"), coins=20, xp=15)`. Intentos `in_progress` con `crear_intento(status="in_progress")`.
  - Estudiantes con `saldo=0`, para que la billetera exista y la concurrencia no choque con su creación perezosa.
  - **A13-1..3 no nombran `idempotency_key`:** cuentan filas por `action = 'challenge' AND metadata->>'challenge_id' = :r`. Así corren en el commit 1 con `xfail(strict=True, raises=AssertionError, reason="BUG-13")`.
  - **Concurrencia (A13-2 y A13-3):**
    - `monkeypatch` sobre `challenges_mod.get_questions` con una envoltura que espera en `threading.Barrier(2, timeout=3)` y sigue si la barrera se rompe (`BrokenBarrierError`);
    - los dos envíos van en 2 hilos, **cada uno con su propio `TestClient(app)` sin `with`**: portal y event loop por request, así que la concurrencia es real;
    - A13-3 exige que la barrera **no** se haya roto (control; si no, `PruebaRota`);
    - A13-2 cuesta unos 3 s con el código bueno, porque el primero espera en la barrera hasta el timeout mientras el segundo está bloqueado en el `FOR UPDATE`.
  - **S13:** el snapshot se genera **una vez en el commit 1**, antes de cualquier cambio, y se versiona en `tests/challenge_engine/snapshot_bug13_primera_paga.json`. No selecciona `idempotency_key`.
  - **C13:** SQL crudo con asyncpg en `BEGIN … ROLLBACK`; cada inserción en su `SAVEPOINT`. La excepción se captura a mano y se afirma con `assert`, **no con `pytest.raises`**: así un tramposo la pone en rojo con `AssertionError` y no con `Failed`.
- **`tests/integ/test_migracion_033.py`:** B1 y B2.
  - Patrón de `test_migracion_032.py`: conexión propia, `BEGIN`, preparación, siembra, `_subir()`/`_bajar()` (funciones del módulo de test, que son el punto que parchean Y5 e Y6) y **ROLLBACK** siempre. El SQL se importa con `importlib` desde el archivo de la 033.
  - **Preparación de B1 y B2 (ERR-23):** `ALTER TABLE coin_ledger DROP CONSTRAINT IF EXISTS coin_ledger_idempotency_key; ALTER TABLE coin_ledger DROP COLUMN IF EXISTS idempotency_key;`, **siempre con `IF EXISTS`**. Después, siembra sin la columna y con `created_at` explícitos (en una transacción `now()` empata).
- **`tests/engrama_core/test_bug14_checkin_grupo.py`:** A14-1, A14-2, A14-3 (xfail estricto en el commit 1) y S14.
  - Siembra: tenant (pool 1000), G1 y G2, docente T (`rol="teacher"`, `group_code="G1"`, como `_escenario` de `test_attendance.py:151`), E1 (G1), E2 (G2) y E0 (sin grupo).
  - Sesiones con `crear_sesion_asistencia` (activa, y expirada con `expira_en` negativo).
  - El cuerpo de referencia sale de un check-in con un código inexistente, en el mismo test.
- **`tests/challenge_engine/test_bug15_reto_de_grupo.py`:** A15-1, A15-2 (xfail estricto en el commit 1) y S15.
  - Siembra: G1 y G2; retos global, de G1 y de G2; E1, E0, un docente sin `teacher_groups`, un admin y un estudiante de otro colegio.

**Ediciones a lo existente** (corregido tras la medición del paso 2, ERR-25; `git grep -n alembic_version -- tests` en `508d568`): `tests/integ_db.py:66` y `tests/integ/test_humo_bug11.py:35`, los dos `HUMO_ESPERADO["alembic_version"] = "033_una_paga_por_reto"`. El humo de BUG-11 registra la versión de la cabeza; sus demás claves no cambian. Las demás claves no cambian: la 033 no crea tablas ni toca la RLS.

**Tramposos:** `tests/tramposos/test_tramposos_bug13.py` (Y1-Y6), `test_tramposos_bug14.py` (Y7-Y9 y Y14) y `test_tramposos_bug15.py` (Y10-Y13). Todos integ, con el patrón de `test_tramposos_integ.py`: monkeypatch en el módulo donde se **usa** y `pytest.raises(AssertionError)` sobre el cuerpo del test real. Cada tramposo automatiza su **diagonal (negrita)**.

**Diagonal y cruces PREDICHOS** (ERR-15, 19 y 23: el código no existe). Cada celda roja dice qué la pone roja: aserción (as), excepción (ex) o preparación (prep).

| Id | Rompe (mecanismo) | Rojo predicho | Verde predicho y por qué |
|---|---|---|---|
| Y1 | `coins_mod.award_coins` = cuerpo viejo, que acepta `idempotency_key` y lo descarta | **A13-1** (as: 2 filas), **A13-3** (as: 2 filas; **prueba que el `FOR UPDATE` solo no basta**), K1 (as), H1 (as) | A13-2: el `FOR UPDATE` da el 409. S13: la primera paga es igual. K2: sin llave. C13: SQL directo. Lo demás no paga con llave |
| Y2 | `attempts_mod._tomar_intento` sin `.with_for_update()` | **A13-2** (as: `[200, 200]`, aunque haya 1 fila por la llave; **prueba que la llave sola no basta**) | A13-1, A13-3, H1 y `test_submit_twice_returns_409`: son secuenciales o de intentos distintos |
| Y3 | `DROP CONSTRAINT coin_ledger_idempotency_key` en la base de la sesión, restaurado en `finally` | **C13** (as: no hay 23505). Además, por **excepción** (`ON CONFLICT` sin índice árbitro, 42P10): A13-1, A13-2, A13-3, K1, S13, H1, `test_submit_all_correct_awards_coins_and_xp`, `test_submit_twice_returns_409` y `test_submit_increments_current_winners_only_if_correct` | K2, check-in y S14: pagan sin llave. B1 y B2: su preparación usa `IF EXISTS` y su `_subir` recrea el UNIQUE dentro de la transacción. A15 y S15: no pagan. El `finally` no choca con duplicados: C13 siempre hace ROLLBACK, y los que pagan fallan antes de insertar |
| Y4 | `award_coins` sin llave deduplica: usa `f"{action}:{student_id}"` | **K2** (as) | `test_award_coins_*`: una sola paga por test. Check-in: una por estudiante y test. Los retos ya pasan llave. **Inalcanzable sin bandera:** R2 (paga 2 asistencias al mismo estudiante) |
| Y5 | `_subir()` sin el UPDATE del backfill | **B1** (as), B2 (as: el backfill tras volver a subir) | La 033 no tiene CHECK que la bloquee (a diferencia de ERR-23 con la 032): con todo en NULL, el UNIQUE entra |
| Y6 | `_bajar()` sin `DROP COLUMN` | **B2** (as) | B1: su preparación es SQL propio, no `_bajar` |
| Y7 | `attendance_mod._buscar_sesion` = búsqueda vieja (solo tenant) | **A14-1** (as: 200), A14-2 (as: **410**), A14-3 (as: 200), H1 (as) | S14 y los check-in existentes: son de su propio grupo |
| Y8 | `attendance_mod.check_in` trasplantado: busca por tenant, **410 primero** y después el 404 de grupo | **A14-2** (as: 410) | A14-1 y A14-3: la sesión está activa, dan 404. H1: sesiones activas |
| Y9 | `_buscar_sesion` ignora `es_estudiante` | **A14-3** (as: T con `group_code = G1` → 200) | E0 sigue en 404 por `group_code NULL`; A14-1, A14-2 y H1 (D no marca) |
| Y14 | `check_in` trasplantado: si el código existe en el tenant pero no es visible, 404 con `detail` "Session belongs to another group" | **A14-1** (as: cuerpo), A14-2 (as), A14-3 (as) | H1 y S14: miran status o casos visibles. `test_checkin_invalid_session_code_returns_404`: el código no existe |
| Y10 | `challenges_mod.filtro_grupo_estudiante = lambda *_: true()` | **A15-1** (as), A15-2 (as), H1 (as), `test_list_challenges_student_filters_by_group` (as: **C17, una sola fuente**) | S15: todos sus casos siguen igual (el de otro colegio cae por `tenant_id`) |
| Y11 | `attempts_mod.start_attempt` trasplantado con `get_challenge` (solo tenant) | **A15-2** (as: 201), H1 (as: `intento_otro_grupo`) | A15-1: el GET sigue filtrado. S15 |
| Y12 | `challenges_mod.get_challenge_for` ignora `es_personal` (filtra también al personal) | **S15** (as: el docente y el admin → 404) | A15: son estudiantes. H1: D crea por POST (usa `hydrate`, no `get_challenge_for`). T6 y el PATCH usan `get_challenge` |
| Y13 | `get_challenge_for` responde **403** si el reto existe en el tenant pero no es del grupo | **A15-1** (as), A15-2 (as), H1 (as) | S15: el de otro colegio sigue en 404 por la barrera de tenant |

**Inalcanzables (se tachan, ERR-19):**
- Y1-Y4 × B1/B2: SQL de migración, no pasa por `award_coins`.
- Y5-Y6 × todo lo que no sea B: solo los B llaman `_subir`/`_bajar`.
- Y7-Y9, Y14 × BUG-13/15: no hacen check-in.
- Y10-Y13 × A13, K y C13: los intentos se siembran en la base.
- R1-R3 sin bandera.

**Barreras que producen cada 404 (ERR-19):**
- A14: el JOIN de grupo en `_buscar_sesion`.
- A15: `filtro_grupo_estudiante` dentro de `get_challenge_for`.
- Otro colegio (S14, S15): el `tenant_id` de la misma consulta.
- Código o UUID inexistente: no hay fila.

**La matriz se mide completa antes de aceptar** y se escribe aquí, con una columna "Rojo medido". Son 14 tramposos × 27 tests = **378 celdas**:
- los 17 nuevos no tramposos: A13-1..3, S13, K1, K2, C13, B1, B2, A14-1..3, S14, A15-1, A15-2, S15 y H1;
- 10 existentes que ejecutan el código tocado: `test_submit_all_correct_awards_coins_and_xp`, `test_submit_twice_returns_409`, `test_submit_increments_current_winners_only_if_correct`, `test_award_coins_double_entry`, `test_checkin_valid_awards_50_and_streak_1`, `test_checkin_invalid_session_code_returns_404`, `test_checkin_expired_session_returns_410`, `test_f4_cerrar_expira_y_bloquea_checkin`, `test_list_challenges_student_filters_by_group` y `test_d12_catalogo_sin_privilegios_de_clientes`.

Lo no medido no es "no cruza". Un cruce no previsto se corrige por ERR en esta espec **antes** de aceptar; el test no se toca (regla 8, ERR-9).

**Concurrencia no determinista:** si A13-2 o A13-3 no dan el mismo resultado en 5 corridas seguidas, con el código bueno y con su tramposo, se declaran **"no medibles de forma determinista"**, no verdes (encargo L2), y se reporta. La alternativa de servicio queda **preregistrada ahora**: dos `AsyncSession` en un mismo loop, con `asyncio.Event` como barrera. Solo se usa si el arnés de hilos no logra concurrencia real (el control de A13-3 lo dice), y se declara como tal.

## 4. Cuentas (ERR-10: la suma a la vista)
**Base: la meta final de BUG-11**, `ESPEC_bug11.md` §4: **280 passed + 9 skipped y 100 no-integ**. No está medida. Si BUG-11 cierra con otra cifra N + S, las metas pasan a N + 31 y S + 3, y el no-integ no cambia.

| Grupo | integ | no-integ |
|---|---|---|
| A13-1..3, A14-1..3, A15-1..2 | 8 | — |
| S13, S14, S15 | 3 | — |
| K1, K2, C13 | 3 | — |
| B1, B2 | 2 | — |
| Y1-Y14 | 14 | — |
| H1 (humo) | 1 | — |
| **Nuevos** | **31** | **0** |
| R1-R3 (réplica, saltados sin bandera) | 3 skipped | — |

- **passed:** 280 + 31 = **311**;
- **skipped:** 9 + 3 = **12**;
- **no-integ:** 100 + 0 = **100**;
- ruff 0 y mypy 0;
- ningún archivo nuevo pasa de 400 líneas (por eso los tramposos van en 3 archivos).
- Con `ENGRAMA_REPLICA_BUG13A15=1`: 314 passed + 9 skipped.

`HUMO_ESPERADO` no cambia la cuenta. **Regla de ERR-19:** fusionar, partir o agregar un test actualiza esta tabla en el mismo commit.

## 5. Humo y réplica
**Humo (H1, `tests/integ/test_humo_bug13a15.py`).** Escribe `tests/_salida/humo_bug13a15.json` **antes** de afirmar; el archivo se agrega al `.gitignore`.

- **Semilla fija:** `random.Random(13)` elige:
  - las 3 respuestas correctas, de `"ABCD"`;
  - el orden en que actúan los estudiantes (`shuffle`);
  - cuál estudiante de G1 hace el doble envío.
- **Siembra:** tenant con pool 100000, grupos `H13-G1` y `H13-G2`, docente D y 4 estudiantes por grupo, con las fábricas.
- **Flujo, todo por la API:**
  1. D crea R1 (de G1) y R2 (de G2) con `POST /challenges/` (20 monedas, 15 XP, `max_attempts` 3 y `max_winners` 30).
  2. Cada estudiante de G2 hace `GET R1` y `POST R1/attempt`. Cada estudiante de G1 hace `GET R1`.
  3. Cada estudiante de G1 arranca R1, lo gana, lo arranca otra vez y lo gana otra vez. El elegido envía **dos veces** su segundo intento, en secuencia.
  4. D abre una sesión de `H13-G1` (`POST /core/attendance/sessions`). Marcan los 4 de G2 y después los 4 de G1.
- **Contenido exacto:**
  ```json
  {"alembic_version":"033_una_paga_por_reto","semilla":13,"estudiantes":[4,4],
   "reto_propio":[200,200,200,200],"reto_otro_grupo":[404,404,404,404],
   "intento_otro_grupo":[404,404,404,404],"intentos_otro_grupo_en_base":0,
   "primera_victoria":[20,20,20,20],"segunda_victoria":[0,0,0,0],"doble_envio":[200,409],
   "paga_una_vez":1,"filas_reto":4,"checkin_propio":[200,200,200,200],
   "checkin_otro_grupo":[404,404,404,404],"asistencias":4,"monedas_otro_grupo":0}
  ```
  `paga_una_vez` = el máximo de filas por (reto, estudiante). `paga_una_vez`, `reto_otro_grupo` y `checkin_otro_grupo` son las claves que luego resume `humo_lingo.json` del encargo.
- Si no escribe el archivo, no hay corrida grande.

**Réplica** (`tests/integ/test_replica_bug13a15.py`, `ENGRAMA_REPLICA_BUG13A15=1`). Son entradas que no se usaron al desarrollar:
- **R1:** **10** envíos simultáneos del mismo intento (10 hilos, sin barrera) → un 200 con 20 monedas y nueve 409, 1 fila y saldo 20. Además, 5 estudiantes ganan 3 intentos cada uno por la API → 5 filas y 20 monedas cada uno.
- **R2:** E marca en G1 (200) y abre el reto de G1 (200). Se le cambia el `group_code` a G2 en la base: no hay ruta para mover estudiantes, y se declara así. Después: una sesión nueva de G1 → 404, el reto de G1 → 404, el reto de G2 → 200 y una sesión de G2 → 200.
- **R3, códigos iguales en dos colegios:** P tiene membresía en A (grupo `G1`) y en B (grupo `G1`).
  - Con `X-Tenant-ID: B`, la sesión y el reto de A-G1 → 404; con `X-Tenant-ID: A` → 200.
  - Una membresía con `group_code = "g1"` (minúscula) frente al grupo `G1` → 404 en los dos: la comparación es exacta y falla cerrada.

## 6. Numeración de migraciones: la 033 pasa a BUG-13 y el login 008 pasa a la 034
**Declarado:** Alembic es una cadena lineal, y el número sigue el orden de aplicación. BUG-13 se aplica **antes** del login 008 (orden del coordinador en la auditoría), así que toma la **033**, y `033_login_vendible` pasa a **`034_login_vendible`**, sobre `033_una_paga_por_reto`. Es el mismo movimiento que hizo BUG-11 con la 032.

Hay que corregirlo, en commits aparte y **antes** de implementar la 008:
- `docs/ESPEC_login_vendible.md`: §1, §1.4, Z15, L1 y §6 (que diga "migraciones ≤ 033");
- `docs/ESPEC_bug11.md` §6.1 y §6.5: una nota de erratas, "033 → 034 por ESPEC_bug13a15 §6";
- `TABLERO.md` (lo hace el coordinador);
- **fuera de este repo, aviso a ARQUITECTO:** `engrama-web/docs/ENCARGO_F4_lingo.md:15` y `ESPEC_mvp_uis.md:206` dicen "migración 033".

**Otros efectos sobre la 008:**
- Su `/auth/me` no cambia por esta espec.
- L9 no se toca.
- L5 (la pista cobra) puede reusar la llave: `hint:<attempt>:<question>`, sin migración.

## 7. Producción: nada remoto sin el sí de Christiam
engrama-2.0 está **pausado**. Nada de esto se corre contra un Supabase real sin el sí de Christiam en esa sesión (REGLAS §2). Al implementar, se agrega a `docs/PRODUCCION_030.md` la sección **"Antes de aplicar la 033"**:
- **Respaldo restaurado en local** y, sobre él, las dobles pagas históricas:
  ```sql
  select count(*) from (select l.tenant_id, l.metadata->>'challenge_id', w.owner_id
    from coin_ledger l join coin_wallets w on w.id = l.to_wallet_id and w.owner_type = 'profile'
   where l.action = 'challenge' group by 1, 2, 3 having count(*) > 1) s;
  ```
  Si da más de 0, la 033 deja esas filas repetidas en NULL y **no devuelve monedas**. Revertirlas (una fila inversa por cada una) lo decide Christiam: toca saldos de estudiantes. No está verificado; se espera 0.
- **Orden: primero la migración y después el código.**
  - El código **viejo** con la 033 funciona igual que hoy: no pasa llave, así que sigue con el hueco, pero no rompe nada.
  - El código **nuevo** sin la 033 falla cerrado: 500 en toda victoria (42P10), sin pagar.
  - BUG-14 y BUG-15 no tienen migración y se despliegan cuando sea.
- **Bloqueos:** `ADD COLUMN` sin default es solo metadato. El UPDATE y el `ADD CONSTRAINT UNIQUE` (que construye el índice) bloquean `coin_ledger`. Con el tamaño actual no importa. Si crece: `CREATE UNIQUE INDEX CONCURRENTLY`, fuera de la transacción, y `ADD CONSTRAINT … USING INDEX`.
- **Downgrade:** solo pierde las llaves.
- Después de aplicar: existe `coin_ledger_idempotency_key`, la consulta de D12 da 0 y 0, y `pg_policies` de `public` = 51.

## 8. Impacto en el cliente (contratos): solo códigos de estado y valores
Ningún esquema de respuesta cambia (`AttemptSubmitOut`, `ChallengeOut`, `AttemptStartOut`, `CheckInResult`).

| Ruta | Hoy | Después |
|---|---|---|
| `POST /challenges/attempts/{id}/submit`, 2.ª victoria del mismo reto | 200, paga otra vez | 200 con `coins_earned: 0` y `xp_earned: 0` (`is_correct` real) |
| Mismo `submit`, doble toque simultáneo | 200 + 200, paga dos veces | 200 + **409** (`"Attempt already completed or abandoned"`, el 409 que ya existe) |
| `POST /core/attendance/check-in`, sesión de otro grupo | 200 y cobra | **404** `{"detail":"Session code not found"}` |
| Mismo check-in, sesión expirada de otro grupo | 410 | **404** (igual) |
| Mismo check-in, docente o admin | 200 y cobra 50 | **404** (igual) |
| `GET /challenges/{id}`, estudiante, reto de otro grupo | 200 | **404** `{"detail":"Challenge not found"}` |
| `POST /challenges/{id}/attempt`, estudiante, reto de otro grupo | 201 | **404** (igual) |

Lo que el cliente ya hace (ocultar "Jugar" en un reto ganado y bloquear el doble toque) sigue siendo correcto. El mock de engrama-web agrega estos 404 y el 0.

## 9. Qué NO se toca, la racha y "para después"
**No se toca:**
- `start_attempt`: solo recibe los parámetros de visibilidad; el conteo de intentos no cambia.
- El feed (salvo extraer su filtro sin cambios), `grade_answers`, `is_attempt_correct`, `get_challenge`, `/submit` (su forma), `/challenges/all`, T6 y el PATCH de estado.
- De la asistencia: `compute_next_streak`, `streak_multiplier`, `ATTENDANCE_COINS_BASE`, `create_session`, `list_active_sessions` y `expire_sessions`.
- `src/teachers/**`, `access.py`, `src/auth/**`, las migraciones 000-032, las políticas, los privilegios de la 031 y `models.py`, salvo `CoinLedger.idempotency_key` (después de que BUG-11 commitee).
- Los tests existentes, salvo `HUMO_ESPERADO`. También `pyproject.toml`, `poetry.lock` y `.venv` (ERR-11: nada de `poetry env use`).
- Docker Desktop (ERR-21), coins-mvp, Supabase remoto, `ESPEC_login_vendible.md` (§6 lo corrige otro commit) y engrama-web.

**La racha (L4-b, L4-c y BUG-12, con el pedagogo):**
- Esta espec **no cambia su semántica**.
- La **roza** BUG-14: un check-in rechazado (otro grupo o personal) ya no toca `profiles.current_streak`, `longest_streak` ni `last_attendance_date`, porque el 404 llega antes de `:282-299`. La regla de días calendario y la racha global quedan como están.
- BUG-13 no toca la racha: `streak_bonus` sigue en 0.

**ERR-16:** el orden, las métricas y lo que ve el profe no cambian. T5 lee `challenge_attempts.answers`, que se sigue guardando completo en toda victoria repetida. El XP no se muestra en `/teachers`. **No se marca para el pedagogo.** Queda **una pregunta para L3** (sí o no, no bloquea): con los tramos de L3, ¿paga solo el **primer intento terminado** (D3 literal) o la **primera victoria** (lo de hoy, que esta espec conserva)?

**Para después** (candidatos, leídos y no medidos):
1. **Carrera de `current_winners`:** `attempts.py:248` lee, suma y escribe sin bloquear el reto. Dos ganadores distintos a la vez pueden pasar `max_winners` y contar uno de menos.
2. **Carrera de `start_attempt`:** `:130-167`, sin UNIQUE parcial sobre `in_progress`, crea dos intentos. La plata queda cubierta por la llave; el conteo de intentos, no.
3. **Un reto con `coins_reward = 0`** (`schemas.py:70`, `ge=0`) hace que una victoria dé **400** (`coins.py:108-112`, `amount <= 0`).
4. **La billetera es global por perfil** (`models.py:267-269`, `coins.py:60-64`). Un estudiante en dos colegios cobra en la billetera del primero, y `get_balance` del segundo le muestra 0. Es de la familia de BUG-12.
5. **El personal juega y cobra retos:** `/attempt` y `/submit` no tienen guarda de rol.
6. **El personal ve cualquier reto del colegio** por `GET /challenges/{id}` y `/challenges/all`. Es el resto de BUG-10 (el docstring de `access.py`); el encargo pide que el personal no cambie aquí.
7. **Cambio de grupo:** `submit` usa `get_challenge` (solo tenant), así que un `in_progress` de un reto que ya no es visible se sigue pudiendo cobrar.
8. **`create_session` y `/attendance/sessions/active`** no pasan por `visible_groups` (BUG-10).
9. **Doble check-in simultáneo** (auditor H-1): `attendance.py:254-264` hace un `SELECT` de duplicado sin `FOR UPDATE` antes del `INSERT`, con `autoflush=False` (`src/shared/db.py:50`). Dos check-ins simultáneos del mismo estudiante a la misma sesión chocan con `UNIQUE(session_id, student_id)` en el flush de `coins.py:149`: **500 sin manejar** en vez de 409. No hay pérdida de plata (la transacción aborta entera). Se aplica el mismo razonamiento de BUG-13 ("un chequeo en la app no basta"); el arreglo candidato es capturar el 23505 o usar `ON CONFLICT`. Fuera del alcance de esta espec.

## 10. Orden de commits (cada uno con 0 failed; solo después de que BUG-11 esté commiteado)
1. **`test`:** A13-1..3, A14-1..3 y A15-1..2 con `xfail(strict=True, raises=AssertionError)`; S13 (con el snapshot generado aquí), S14 y S15 en verde. Esperado: 280 + 3 = **283 passed + 8 xfailed + 9 skipped**; 100 no-integ. **Aquí se ven los tres huecos en rojo por la API.**
2. **`fix(bug13)`:** la 033, `CoinLedger.idempotency_key`, `award_coins`, `_tomar_intento` y `llave_reto`, la paga condicionada, `HUMO_ESPERADO`, K1, K2, C13, B1, B2 e Y1-Y6. Se quitan los 3 xfail de A13. Esperado: 283 + 3 + 5 + 6 = **297 passed + 5 xfailed + 9 skipped**.
3. **`fix(bug14)`:** `_buscar_sesion`, `check_in` y el router, más Y7, Y8, Y9 e Y14. Se quitan los 3 xfail de A14. Esperado: 297 + 3 + 4 = **304 passed + 2 xfailed + 9 skipped**.
4. **`fix(bug15)`:** `filtro_grupo_estudiante`, `get_challenge_for`, el feed, `start_attempt` y el router, más Y10-Y13. Se quitan los 2 xfail de A15. Esperado: 304 + 2 + 4 = **310 passed + 9 skipped**.
5. **`test`:** H1, el `.gitignore` y R1-R3 → **311 passed + 12 skipped**; 100 no-integ.
6. **`docs`:** "Antes de aplicar la 033" en `PRODUCCION_030.md` y la matriz medida (§3, columna "Rojo medido").
7. **`docs`, aparte:** la renumeración de §6 en `ESPEC_login_vendible.md` y la nota en `ESPEC_bug11.md`.

## 11. Verificación y veredicto
```
poetry run pytest -m "not integ" -q        # 100 passed
poetry run pytest -q                       # 311 passed, 12 skipped
ENGRAMA_REPLICA_BUG13A15=1 poetry run pytest tests/integ/test_replica_bug13a15.py -q
poetry run ruff check . ; poetry run mypy .
```
**Réplica manual de la migración:** en el contenedor desechable del fixture, `alembic upgrade head` → `downgrade 032_nombre_por_membresia` → `upgrade head`, con Alembic real. `coin_ledger` (`information_schema.columns` + `pg_constraint`) debe coincidir en las dos subidas, y D12 debe dar 0 y 0. Nadie gestiona el ciclo de vida de Docker (ERR-21): si no arranca, se para y se reporta.

- **FUNCIONA:**
  - las cuentas exactas de §4;
  - los 8 A en rojo en el commit 1 y en verde en su `fix`;
  - la matriz medida = §3, o corregida por ERR antes de aceptar;
  - H1 escrito y exacto;
  - la réplica y el ciclo up/down/up en verde;
  - los 280 intactos.
- **HAY ALGO MODESTO:** A13-2 o A13-3 quedan declarados "no medibles de forma determinista" (§3), con todo lo demás en verde.
- **NO:**
  - un estudiante cobra dos veces el mismo reto, en cualquier test o en la réplica;
  - un check-in o un reto de otro grupo da algo distinto de 404 con el cuerpo idéntico;
  - un tramposo de la diagonal queda verde;
  - cambia algo previo que la espec no declara;
  - aparece otra migración que no es la 033;
  - se toca `src/teachers`, `src/auth` o la racha.
