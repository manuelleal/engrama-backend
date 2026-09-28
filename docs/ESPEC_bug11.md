# ESPEC · BUG-11: el nombre del estudiante vive en la membresía, no en `profiles`

F4 · Creador · 2026-09-28 · preregistro. Rama `test/fixture-integ`, base `84ce99a`. Origen: ERR-19 y `ESPEC_grupos_y_panel_docente.md` §6 (BUG-11, **bloqueante para producción**).

**Dirección decidida por el coordinador (no se reabre aquí):** el nombre, y cualquier dato que ponga el colegio, se guarda **por membresía**. La identidad sigue siendo global: `documento_id` único y un solo `profile_id`. Ver la tensión D1 en §9.

## 0. Medido y leído
**Medido (2026-09-28, `.venv` oficial, sin Docker):** `poetry run pytest -m "not integ" -q` da **98 passed, 170 deselected**. 98 + 170 = 268 = 262 passed + 6 skipped, lo mismo que el TABLERO para `84ce99a`. La suite integ **no se re-midió** (el encargo prohíbe tocar Docker; ERR-21).

**Leído con `grep -n` en `84ce99a`, sin ejecutar:**

| Qué | Dónde |
|---|---|
| `documento_id` es UNIQUE **global** | `alembic/versions/002_create_profiles.py:24`, `src/shared/models.py:101` |
| El nombre es una sola columna global | `002_create_profiles.py:25`, `models.py:102` (`profiles.full_name TEXT NOT NULL`) |
| `memberships` no tiene nombre | `003_create_memberships.py:22-34`, `models.py:137-167`. UNIQUE `(tenant_id, profile_id)` en `:161` |
| **Escritura del nombre (M3 y M4)** | `src/teachers/service/roster.py:117` busca el perfil por documento **en todo el sistema**. `:118-124` solo crea el perfil si falta, con `full_name=nombre_completo` (`:120`). Si el perfil ya existe (lo creó **otro** colegio), `nombre_completo` se **descarta en silencio**. `:134-142` crea la membresía sin nombre |
| M4 pasa por el mismo camino | `roster.py:281-282` (`import_csv` → `enroll_student`). La validación contra la base (`:234-260`) solo mira la membresía del **mismo** colegio |
| Entrada de M3 | `src/teachers/admin_router.py:92-95`; `src/teachers/schemas.py:116` (`nombre_completo: str`, **sin** `min_length`) |
| **Lectura del nombre (T2)** | `src/teachers/service/panel.py:67` (`select(Profile.id, Profile.full_name, …)`) y `:76` (`order_by(Profile.full_name, Profile.id)`) |
| T5 hereda el nombre y el orden de T2 | `src/teachers/service/achievement.py:256` (`panel_service.roster`) y `:261` (`full_name=s.full_name`) |
| T7 usa el roster, pero **no expone nombres** | `src/teachers/service/item_errors.py:201-207`: solo toma `profile_id` |
| Esquemas que exponen el nombre | `src/teachers/schemas.py:48` (`StudentRosterOut.full_name`), `:219` (`StudentAchievementOut.full_name`) |
| Otros que escriben o leen `profiles.full_name` | `src/auth/service.py:104-111` (stub con el correo o `User <sub>`) y `:167` (`/auth/me`). No son datos de un colegio (§6) |

**El hueco, paso a paso (predicho por lectura; A1 lo mide en el commit 1):**
1. AA (colegio A) matricula D con N1. Se crea el perfil P con `full_name = N1` y la membresía (A, P).
2. AB (colegio B) matricula D con N2. `roster.py:117` encuentra P, no toca el nombre, crea (B, P) y responde **201 `inscrito`**. El colegio B no recibe ningún aviso de que su N2 no se guardó.
3. `GET /teachers/groups/{GB}/students` le muestra N1 al colegio B. T5 le muestra lo mismo. **Un dato que escribió el colegio A sale en el colegio B.**

**Otros hechos que afectan el diseño:**
- 3 tests existentes toman el nombre de `profiles`:
  - `tests/teachers/test_m3_students.py:28` afirma que M3 lo escribe allí;
  - `tests/teachers/test_t2_roster.py:30-31` saca de allí el valor esperado;
  - `tests/teachers/test_t5_achievement.py:45-48` siembra el orden de F5 con `update profiles set full_name`.
- `tests/integ_ayudante.py:128-160` (`crear_perfil`) pone `full_name = "Persona <hex>"` en el perfil y crea la membresía sin nombre. `afiliar` (`:162-181`) solo se usa con `rol="teacher"` (`tests/teachers/_actores.py:66`).
- Los INSERT crudos en `memberships` de `tests/seguridad/test_aceptacion.py:311` (D7) y `test_bug2_funcion.py:72` usan `role='admin'`. Un CHECK solo para estudiantes no los toca.
- Una base nueva **dentro** del contenedor de pruebas no tiene el esquema `auth`, y `029_rls_policies.py` usa `auth.uid()`. Por eso los tests de migración de §3 no migran una base aparte: corren el SQL de la 032 dentro de una transacción que se deshace (no medido; ver §10).
- La siguiente migración libre es la **032**: no existe `alembic/versions/032*` en ninguna rama (`git log --all -- 'alembic/versions/032*'` está vacío). `ESPEC_login_vendible.md` §1 **tiene reservada** la 032 sin haberla escrito, y pasa a 033 (§6).

## 1. Qué cambia (una cosa)
**El nombre que ve un colegio sale de la membresía de ese colegio.** Nace `alembic/versions/032_nombre_por_membresia.py` (revisión `032_nombre_por_membresia`, sobre `031_sin_acceso_directo`). M3 y M4 escriben el nombre en la membresía, y T2 y T5 lo leen de allí.

**La migración** expone dos tuplas de SQL a nivel de módulo, `SQL_SUBIR` y `SQL_BAJAR`, y `upgrade()` y `downgrade()` solo las recorren con `op.execute`. Así, los tests de §3 ejecutan exactamente el SQL que corre Alembic.

`SQL_SUBIR`, idempotente:
```sql
ALTER TABLE memberships ADD COLUMN IF NOT EXISTS full_name TEXT;
UPDATE memberships m SET full_name = p.full_name
  FROM profiles p
 WHERE p.id = m.profile_id AND m.role = 'student' AND m.full_name IS NULL;
ALTER TABLE memberships DROP CONSTRAINT IF EXISTS memberships_student_full_name_check;
ALTER TABLE memberships ADD CONSTRAINT memberships_student_full_name_check
  CHECK (role <> 'student' OR full_name IS NOT NULL);
```

`SQL_BAJAR` devuelve el comportamiento viejo, **con su hueco**:
```sql
UPDATE profiles p SET full_name = m.full_name
  FROM (SELECT DISTINCT ON (profile_id) profile_id, full_name
          FROM memberships
         WHERE role = 'student' AND full_name IS NOT NULL
         ORDER BY profile_id, created_at, id) m
 WHERE p.id = m.profile_id AND p.full_name = '';
ALTER TABLE memberships DROP CONSTRAINT IF EXISTS memberships_student_full_name_check;
ALTER TABLE memberships DROP COLUMN IF EXISTS full_name;
```

**Por qué así:**
- **La columna es nullable, con un CHECK solo para estudiantes.** Docentes y admins no tienen un nombre puesto por el colegio: M2 exige una membresía previa, y el onboarding de la 008 crea admins. Obligar el nombre en todos los roles tocaría seeds y rutas que no son de esta espec.
- **El backfill es solo de estudiantes:** es exactamente lo que leen T2 y T5.
- **T2 no tiene respaldo en `profiles.full_name`:** un `COALESCE` reabriría el hueco. El CHECK garantiza que un estudiante nunca llega sin nombre.
- **La 032 no toca `profiles`** (ni DDL ni datos al subir): la tabla queda byte a byte igual (B1).
- **El downgrade restaura** el nombre del perfil desde la membresía **más antigua**, pero solo donde `profiles.full_name = ''`. Es justo lo que habría hecho el código viejo. Pierde el N2 de los demás colegios, **a propósito** (§7).

**Qué pasa con `profiles`:**
- `profiles.full_name` **se queda** (NOT NULL, sin cambios de esquema). Desde la 032 significa **"nombre propio de la cuenta"**: el correo o el stub de `get_or_create_profile`, y el `nombre` del onboarding de la 008. **Nunca un dato que puso un colegio.**
- M3 y M4 crean los perfiles nuevos con `full_name = ''`, con el mismo precedente que `pin_hash = ''` (`roster.py:121`).
- Las filas viejas no se tocan: los perfiles que creó M3 antes de la 032 conservan el nombre del primer colegio. Ninguna ruta de `/teachers` ni de `/admin` lo lee (U1), y `/auth/me` no las alcanza, porque un perfil de M3 no tiene cuenta. Limpiarlas va con la 008 (§6).
- `documento_id` sigue siendo UNIQUE global y el `profile_id` sigue siendo uno (dirección decidida; D1).

**Cambios de código** (los hace el implementador; aquí solo se fijan):
- `models.py`: `Membership.full_name: Mapped[str | None]`, más el `CheckConstraint` en `__table_args__`.
- `roster.py` (`enroll_student`):
  - un perfil nuevo lleva `full_name=""`;
  - una membresía nueva lleva `full_name=nombre_completo`;
  - una membresía existente (`ya_estaba`) **no se toca**: se mantiene el contrato de M3 ("sin pisar el nombre"), ahora en la membresía;
  - se corrige el docstring (`:113-115`).
- `panel.py:67` y `:76`: `Membership.full_name` en lugar de `Profile.full_name`, tanto en el `select` como en el `order_by`. `achievement.py` e `item_errors.py` no cambian: heredan de `roster`.
- `tests/integ_ayudante.py` (`crear_perfil`): la membresía de un `student` lleva el mismo `"Persona <hex>"` que el perfil. Así, lo que devuelven los 262 tests queda idéntico.
- `tests/integ_db.py:66`: `HUMO_ESPERADO["alembic_version"] = "032_nombre_por_membresia"`. Las demás claves no cambian: la 032 no crea tablas, no toca la RLS y no agrega políticas.

## 2. Criterios (qué debe pasar, medible)
| # | Criterio | Test que se pone rojo si falla |
|---|---|---|
| C1 | **Aislamiento del nombre (el hueco):** A matricula D con N1, B matricula D con N2, y los dos reciben 201 `inscrito` con el **mismo** `profile_id`. T2 de GA contiene N1 y **no** N2; T2 de GB contiene N2 y **no** N1 | A1 |
| C2 | Lo mismo en T5 (`students[].full_name`) | A2 |
| C3 | Lo mismo por CSV (M4). Reimportar en B con otro nombre da `creados 0, ya_estaban 1` y **no pisa** el nombre de B | A3 |
| C4 | El orden alfabético (§2.2 de grupos) usa el nombre **de ese colegio**. Con P y Q en los dos colegios y órdenes opuestos, cada uno ve el suyo | A4 |
| C5 | **Nada del colegio en `profiles`:** tras C1, `profiles.full_name` de D es `''` y hay 1 sola fila con ese `documento_id` | A1 (parte de base) |
| C6 | **Identidad del caso sin cruce:** con un solo colegio y 3 estudiantes por M4, T2 y T5 de D dan **byte a byte** el snapshot congelado en `84ce99a` (con los `profile_id` normalizados por posición) | S1 |
| C7 | **Backfill:** en datos anteriores a la 032, cada membresía `student` recibe el `full_name` de su perfil, y las de docente quedan NULL. `profiles` queda idéntica (`select * order by id`), y correr `SQL_SUBIR` dos veces no falla ni cambia nada | B1 |
| C8 | **Rollback:** `SQL_BAJAR` restaura en `profiles` el nombre de la membresía más antigua donde estaba `''`, y quita la columna y el CHECK. Volver a subir deja la columna, el CHECK y el backfill (la pérdida del N2 es la declarada) | B2 |
| C9 | **Invariante en la base:** una membresía `student` sin nombre da **23514** con `memberships_student_full_name_check` en el mensaje. Una `teacher` sin nombre entra | C1-test (`test_c1_check_estudiante_sin_nombre`) |
| C10 | Ningún `.py` de `src/teachers/` lee `Profile.full_name` ni `profile.full_name`. El control es que se escanearon 8 archivos o más | U1 |
| C11 | Regresión: los 262 siguen verdes, con solo las 3 ediciones declaradas en §3. D12 da 0 y 0, y hay 51 políticas | suite completa |

## 3. Tests y tramposos
**Tests nuevos:**
- **`tests/teachers/test_bug11_nombre_por_colegio.py`** (integ):
  - A1, A2, A3, A4 y S1.
  - Siembra: `armar(integ)`, más `TeacherGroup(DT, GB)`, para que DT sea el docente de GB.
  - Datos sintéticos: los documentos `SINT-B11-0001`, `-0101`, `-0102` y `-0201`; nombres como `Ana Prueba Alfa` y `Ana Prueba Beta`. Ninguno es subcadena de otro.
  - A1-A4 afirman **por la API**. Solo A1 mira además `profiles`. **Ninguno nombra `memberships.full_name`**: así pueden correr en `84ce99a` con `xfail(strict=True, raises=AssertionError)`.
  - A4 filtra por sufijo (`Alfa` o `Beta`), porque GA también tiene a E.
  - El snapshot de S1 se genera una vez en `84ce99a` y se versiona en `tests/teachers/snapshot_bug11_un_colegio.json`.
- **`tests/integ/test_migracion_032.py`** (integ):
  - **B1, B2 y el test de C9.** Cada uno abre su propia conexión, hace `BEGIN`, siembra con SQL crudo, corre `SQL_SUBIR` o `SQL_BAJAR` (importados con `importlib` desde el archivo de la 032) y termina con **ROLLBACK**. La base de la sesión queda como estaba.
  - B2 siembra los `created_at` explícitos (A = now − 1 día). Dentro de una transacción `now()` empata, y el desempate por `id` sería azar.
  - Las funciones `_subir()` y `_bajar()` del módulo son el punto que parchean Y5 e Y7.
- **`tests/teachers/test_bug11_estatico.py`** (no-integ): **U1**, con la función `lecturas_nombre_global(fuentes)` y el lector `_fuentes()`, que Y8 parchea.

**Ediciones declaradas a tests existentes.** Cambia **dónde** está el dato, no el criterio (regla 8):
- F9 (`test_m3_students.py:28`): pasa a afirmar `profiles.full_name == ''` y la membresía (A, P) = `'Ana Nueva'`, también después del segundo POST con `"OTRO NOMBRE"`.
- F2 (`test_t2_roster.py:30-31`): el valor esperado sale de `memberships` (tenant A, perfil E). Hoy pasaría igual, porque el ayudante pone el mismo nombre en los dos lados, pero pasaría **por la razón equivocada** (ERR-19).
- F5 (`test_t5_achievement.py:45-48`): `update memberships set full_name = … where profile_id = :p and tenant_id = :t`. Sin esto, F5 se cae (ValueError en `.index`).

**Tramposos** (`tests/tramposos/test_tramposos_bug11.py`, integ, con el patrón de `test_tramposos_grupos.py`; más `test_tramposos_bug11_estatico.py`, no-integ). **Diagonal PREDICHA** (ERR-15 y ERR-19: el código no existe; cada rojo nombra su mecanismo):

| Id | Rompe (mecanismo) | Rojo predicho | Por qué |
|---|---|---|---|
| Y1 | `panel_mod.roster` vuelve a leer `Profile.full_name` en el `select` y el `order_by` (monkeypatch) | **A1**, A2, A3, A4, S1, H1; F5 (ValueError, no AssertionError); R1-R3 con la bandera | Los perfiles de M3 y M4 ahora tienen `''`. F5 siembra los nombres en la membresía. **No** F2: el ayudante pone el mismo nombre en perfil y membresía. **No** U1: es estático (inalcanzable, nota 5 de grupos) |
| Y2 | `enroll_student` viejo trasplantado: el perfil nuevo guarda el nombre y la membresía copia `profile.full_name` | **A1**, A2, A3, A4, H1, F9; **R1-R3 con la bandera** (corregido tras la medición del paso 4, ERR-23: la membresía copia el nombre del perfil y B y C heredan el de A; el rojo sale de la aserción) | B hereda N1. F9 ve el nombre en `profiles`. **No** S1: con un solo colegio el nombre coincide |
| Y3 | El perfil nuevo guarda `nombre_completo` y la membresía queda bien | **A1** (parte de base), F9, H1 (`nombre_en_profiles`) | T2 y T5 se ven bien: solo lo detecta mirar `profiles` (C5) |
| Y4 | `ya_estaba` pisa el nombre de la membresía | **F9**, A3 | Contrato de M3 "sin pisar el nombre" |
| Y5 | `_subir()` sin el UPDATE del backfill | **B1**, B2 | ~~B2 vuelve a subir y afirma el backfill~~ **Corregido tras la medición (ERR-23):** el rojo no sale de la aserción del backfill, sino de que el CHECK impide aplicar la 032 sin backfill (23514 en `SQL_SUBIR`). Celdas iguales, otro mecanismo |
| Y6 | `DROP CONSTRAINT memberships_student_full_name_check` en la base de la sesión, restaurado en `finally` (patrón `_privilegios`) | **C9**, **B1** | ~~Nadie más inserta un estudiante sin nombre.~~ **Corregido tras la medición (ERR-23):** B1 también cae (`UndefinedObjectError`), porque su preparación hace `DROP CONSTRAINT` sin `IF EXISTS` para volver al esquema previo a la 032. Es un cruce de la preparación, no del criterio de B1; se anota y no se toca el test (ERR-9). **No** D7: inserta `admin` |
| Y7 | `_bajar()` sin el UPDATE de `profiles` | **B2** | El perfil queda con `''` |
| Y8 | `_fuentes()` agrega un `falso.py` sintético con `select(Profile.id, Profile.full_name)` | **U1** | Tramposo de validador (ERR-17) |

Negrita = la diagonal que automatiza la suite. Lo demás son cruces predichos. **Antes de aceptar se mide la matriz completa** y se escribe aquí, con una columna "Rojo medido", igual que en grupos §3. Son 8 tramposos × 17 tests (los 10 nuevos no tramposos; F2, F5, F9, F10, F11 y F12; y D12) = **136 celdas**. Lo no medido no es "no cruza" (ERR-19). Un cruce no previsto se corrige por ERR antes de aceptar (regla 8).

## 4. Cuentas (ERR-10: la suma a la vista)
Base en `84ce99a`: **262 passed + 6 skipped**, **98 no-integ** (el 98 medido hoy; el 262 es del TABLERO).

| Grupo | integ | no-integ |
|---|---|---|
| A1-A4, S1 | 5 | — |
| B1, B2, C9 | 3 | — |
| H1 (humo) | 1 | — |
| U1 | — | 1 |
| Y1-Y7 | 7 | — |
| Y8 | — | 1 |
| **Nuevos** | **16** | **2** |
| R1-R3 (réplica, saltados sin bandera) | 3 skipped | — |

- **passed:** 262 + 16 + 2 = **280**;
- **skipped:** 6 + 3 = **9**;
- **no-integ:** 98 + 2 = **100**;
- ruff 0, mypy 0, ningún archivo nuevo pasa de 400 líneas (`test_tramposos_grupos.py` ya tiene 344: por eso Y1-Y7 van en un archivo propio).
- Con `ENGRAMA_REPLICA_BUG11=1`: 283 passed + 6 skipped.

Las 3 ediciones de §3 y el `HUMO_ESPERADO` no cambian la cuenta. **Regla de ERR-19:** fusionar, partir o agregar un test actualiza esta tabla en el mismo commit.

## 5. Humo y réplica
**Humo (H1, `tests/integ/test_humo_bug11.py`)** escribe `tests/_salida/humo_bug11.json` **antes** de afirmar, y el archivo va al `.gitignore`.
- **Semilla fija:** `random.Random(11)` elige de listas sintéticas fijas (`NOMBRES`, `APELLIDOS`). Cada nombre lleva el sufijo del colegio (`… A3`, `… B3`), así que los de un colegio no son subcadena de los del otro.
- **Flujo:** 5 documentos `SINT-H11-0001..0005`. A los inscribe por **M4** (CSV con `,`) y B por **M3**, uno a uno, con nombres distintos: se cubren los dos caminos de escritura. Después, T2 de D en GA y T2 de DT en GB.
- **Contenido exacto:** `{"alembic_version":"032_nombre_por_membresia","semilla":11,"documentos":5,"perfiles":5,"inscritos":[5,5],"nombres_propios":[5,5],"nombres_ajenos":[0,0],"nombre_en_profiles":0}`.
- Si no escribe el archivo, no hay corrida grande.

**Réplica** (`ENGRAMA_REPLICA_BUG11=1`, entradas que no se usaron al desarrollar):
- **R1:** el mismo documento en **3** colegios, con nombres Unicode (`José Ñúñez O'Neil`, `María-José D'Alessandro`, `Zoë Ünal`). Cada T2 devuelve el suyo byte a byte. **No** se afirma un orden con tildes: depende del *collation*.
- **R2:** un documento que es **docente** en A se matricula como estudiante en B con N2 → 201 en B. En A no cambia nada: M2 sigue resolviendo por la membresía `teacher`, y su nombre en A queda NULL.
- **R3:** A importa 20 documentos. B importa 40 por CSV con `;` y BOM, 20 de ellos ya existentes en A → `creados 40`. T2 de B muestra 40 nombres de B y 0 de A; T2 de A, 20 de A. `profiles` = 40.

**Réplica de la migración, manual y como en bug3a9 §6:** en el contenedor desechable del fixture, `alembic upgrade head`, `downgrade 031_sin_acceso_directo` y `upgrade head` con Alembic real. El esquema de `memberships` (`information_schema.columns` + `pg_constraint`) debe coincidir en las dos subidas, y la consulta de D12 debe dar 0 y 0. **Nadie gestiona el ciclo de vida de Docker Desktop (ERR-21):** si Docker no arranca, se para y se reporta.

## 6. Impacto sobre el login 008 (`ESPEC_login_vendible.md`)
Se corrige en esa espec **antes** de implementarla (regla 8). Ninguno de estos puntos bloquea BUG-11.
1. **Número de migración:** `032_login_vendible` pasa a **`033_login_vendible`**, sobre `032_nombre_por_membresia`. Cambian §1, §1.4 ("`live_guest_joins` … en la 032"), Z15 ("GRANT en la 033 → D12") y L1.
2. **§6 "Qué NO se toca":** "migraciones ≤ 031" pasa a "≤ 032". La línea "Candidato a BUG: M3 reusa perfiles…" se reemplaza por "resuelto por `ESPEC_bug11.md`".
3. **`/auth/me`:** `full_name` sale de `memberships.full_name` del **tenant activo** si no es NULL, y si no, de `profiles.full_name` (el nombre propio). Para el gestionado con `tid` fijo, eso muestra lo que escribió **su** colegio. **Test nuevo en la 008:** un estudiante en A (N1) y en B (N2) con login gestionado por B → `/me` da N2. **Tramposo:** `/me` lee `profiles.full_name`. La 008 suma +1 test integ y +1 tramposo integ; su meta pasa de N + 69 a **N + 71** (lo confirma quien corrija la 008).
4. **A4 (`managed = true` en M3):** la cita `roster.py:119` se mueve. El perfil gestionado nace con `full_name = ''` y `managed = true`.
5. **Limpieza de las filas viejas (opcional, en la 033):** una vez que exista `managed`, `UPDATE profiles SET full_name = '' WHERE managed AND …`. Cómo identificar los perfiles viejos de M3 (`pin_hash = ''` y ningún `auth.users`) lo decide esa espec.
6. **CSV v1:** `nombres` + `apellidos` se concatenan en `memberships.full_name`. La regresión "un CSV válido hoy en M4 da idéntico" se mantiene.
7. `memberships.username` y `memberships.pin_hash` (008 §1) siguen **el mismo principio**: lo que pone el colegio vive en la membresía. BUG-11 es su precedente.

## 7. Producción: nada remoto sin el sí de Christiam
engrama-2.0 está **pausado**. Nada de esto se corre contra un Supabase real sin el sí de Christiam en esa sesión (REGLAS §2). Al implementar, se agrega a `docs/PRODUCCION_030.md` la sección **"Antes de aplicar la 032"**:
- **Respaldo restaurado en local** y, sobre él, cuántos estudiantes comparten perfil entre colegios:
  ```sql
  select count(*) from (select profile_id from memberships where role = 'student'
    group by profile_id having count(distinct tenant_id) > 1) s;
  ```
  Si da más de 0, el backfill le copia a cada colegio el nombre del **primero**. El N2 nunca se guardó y **no se puede recuperar**: Christiam decide si esos colegios vuelven a escribir los nombres. Se espera 0, porque ningún grupo real se matriculó mientras BUG-11 seguía abierto (grupos §6), pero **no está verificado**.
- **La migración y el código van juntos:**
  - el código viejo con la 032 aplicada da 23514 (500) en M3 y M4: crea la membresía sin nombre;
  - el código nuevo sin la 032 falla por la columna inexistente;
  - M3 y M4 no se usan en producción hoy.
- **Bloqueos:** `ADD COLUMN` sin default es solo metadato; el UPDATE y el `ADD CONSTRAINT` recorren `memberships` con bloqueo exclusivo. Con el tamaño actual no importa. Si crece, se usa `NOT VALID` y después `VALIDATE`.
- **El downgrade pierde datos:** los nombres de los colegios que no fueron el primero. En producción no se hace downgrade: se restaura el respaldo.
- Después de aplicar: la consulta de D12 da 0 y 0, `pg_policies` de `public` = 51, y `memberships_student_full_name_check` existe.

## 8. Qué NO se toca
- `src/auth/**`: `/auth/me` sigue leyendo `profiles.full_name`, y el cambio va en la 008 (§6.3). Tampoco `src/engrama_core/**`, `src/challenges/**`, las migraciones 000-031, `profiles` (ni esquema ni datos al subir), el UNIQUE de `documento_id`, las políticas, los privilegios de la 031, `app_private` ni `service_role`.
- En `src/teachers`: las rutas, los esquemas de respuesta (mismos campos), las guardas, `access.py`, T3, T4, T6, T7, M1 y M2.
- Los tests existentes, salvo las 3 ediciones de §3; `integ_db.py`, salvo `HUMO_ESPERADO`; `test_replica_grupos.py`; `pyproject.toml`, `poetry.lock` y `.venv` (ERR-11: nada de `poetry env use`).
- Docker Desktop (ERR-21), coins-mvp, Supabase remoto y `ESPEC_login_vendible.md` (§6 lo corrige otro commit).

**Para después (no se toca ahora):**
- **Candidato a BUG-12 (fuga entre colegios de la constancia).** `check_in` sube la racha **global** del perfil con la asistencia de cualquier colegio (`src/engrama_core/service/attendance.py:291-299`), y T2 la muestra (`panel.py:67`, `consistency.current_streak`). El colegio B ve una racha armada con la asistencia en A.
  - **Va al pedagogo (ERR-16):** pasarla a una constancia por colegio cambia un indicador que el profe ve sobre un estudiante.
  - Mientras tanto, esta espec no la toca.
- M3 acepta `nombre_completo` vacío o solo espacios (`schemas.py:116` sin `min_length`), mientras que M4 lo rechaza (`roster.py:222`).
- Renombrar a un estudiante en su colegio (un PATCH de la membresía). Hoy `ya_estaba` no pisa el nombre.
- `src/teachers/service.py` (0 líneas) está versionado y queda tapado por el paquete `src/teachers/service/`.
- El TABLERO está desactualizado:
  - la fila de `engrama-backend` dice 163 passed y "implementador en curso";
  - dice que `integ_db.py` tiene 729 líneas, y hoy tiene 340.

**ERR-16 (el pedagogo):** el nombre **no entra en ninguna métrica**. T5 calcula el logro sin mirarlo y T7 no lo expone. Lo único que cambia es **la clave del orden alfabético**, que ahora es el nombre que escribió ese colegio. La regla (§2.2 de grupos: alfabético, nunca por desempeño) no cambia, así que **no se marca para el pedagogo**. Sí se marca BUG-12.

## 9. Decisión para Christiam (una)
**D1 · ¿Qué es `documento_id`?** La identidad global por `documento_id` supone que es un documento **oficial** (cédula o tarjeta de identidad). Pero hay dos señales en contra:
- la 008 §7 pide, por la Ley 1581, guardar el **"código escolar interno (no la tarjeta de identidad)"**;
- la regex de M4 (`^[A-Za-z0-9_-]{3,32}$`) acepta `001`.

Si los colegios usan códigos internos, **dos niños distintos de dos colegios con el mismo código comparten perfil**: la racha, el XP y, con la 008, la cuenta. Esta espec evita que se crucen los **nombres** en los dos casos, pero no evita que se fusionen las identidades.

- **Recomendación provisional:** decidirlo antes de la A4 de la 008.
  - Si es un código interno: `UNIQUE (tenant_id, documento_id)` y un perfil por colegio, en otra espec.
  - Si es un documento oficial: tratarlo como dato sensible de un menor.
- No bloquea BUG-11.

## 10. Orden de commits (cada uno con 0 failed)
1. **`test`:** S1 (snapshot generado en `84ce99a`) + A1-A4 con `xfail(strict=True, raises=AssertionError, reason="BUG-11")`. Esperado: **263 passed + 4 xfailed + 6 skipped**; 98 no-integ. **Aquí se ve el hueco en rojo por la API.**
2. **`fix`:** la 032, más `models.py`, `roster.py`, `panel.py`, el ayudante, `HUMO_ESPERADO`, las 3 ediciones de §3, B1, B2, C9 e Y1-Y7, y se quitan los 4 xfail. Es un solo cambio: la migración sin el código rompe M3 y M4 (§7). Esperado: 263 + 4 + 3 + 7 = **277 passed + 6 skipped**; 98 no-integ.
3. **`test`:** U1 + Y8 → **279 + 6**; **100** no-integ.
4. **`test`:** H1 + `.gitignore` + R1-R3 → **280 passed + 9 skipped**; 100 no-integ.
5. **`docs`:** "Antes de aplicar la 032" en `PRODUCCION_030.md`, y la matriz medida (§3, columna "Rojo medido").

## 11. Verificación y veredicto
```
poetry run pytest -m "not integ" -q        # 100 passed
poetry run pytest -q                       # 280 passed, 9 skipped
ENGRAMA_REPLICA_BUG11=1 poetry run pytest tests/teachers/test_bug11_nombre_por_colegio.py tests/integ/test_humo_bug11.py -q
poetry run ruff check . ; poetry run mypy .
```
- **FUNCIONA:** las cuentas exactas de §4; A1-A4 en rojo en el commit 1 y en verde en el 2; la matriz medida = §3 (o corregida por ERR antes de aceptar); H1 escrito y exacto; la réplica y el up/down/up manual en verde; los 262 intactos, salvo las 3 ediciones declaradas.
- **HAY ALGO MODESTO:** la réplica falla solo en R1, por Unicode o *collation*, sin cruce de nombres.
- **NO:**
  - un colegio ve un nombre que escribió otro (en T2, T5 o la réplica);
  - `profiles.full_name` recibe un dato de un colegio;
  - un tramposo de la diagonal queda verde;
  - cambia algo previo que la espec no declara;
  - aparece una migración que no es la 032;
  - se toca `src/auth` o `profiles`.
