# ESPEC · Ingesta de eventos del anillo (`POST /events/batch`), backend

F4 · Creador · 2026-10-06 · preregistro. Rama `test/fixture-integ`, sobre el autorregistro, las solicitudes de datos y el endurecimiento (meta **453 passed + 17 skipped y 125 no-integ**).

Origen: la decisión 011 §4 y encargos 3.1, 3.2 y 3.4, y los dos contratos que escribieron las otras piezas (solo lectura): `EVAGAME/docs/ENCARGO_backend_eventos.md` y `SET/docs/ENCARGO_backend_nivel.md`. **Esta espec los unifica en UNA puerta**; donde difieren, decide, y lo que cada pieza debe ajustar está en §9.

## 0. Medido y leído (2026-10-06)
| Qué | Dónde |
|---|---|
| No hay entrada de mensajes de otras piezas | `src/shared/events.py` y `src/webhooks/*.py` tienen 0 líneas; `src/main.py` no monta nada de eso |
| El libro de monedas y la bolsa de la institución | `src/engrama_core/service/coins.py:88` (`award_coins`): toma con candado la billetera de la institución y la del estudiante, 402 si la bolsa no alcanza, y con `idempotency_key` paga **una vez por llave** (033, BUG-13; UNIQUE `(tenant_id, idempotency_key)`) |
| El nivel confirmado no existe | `/auth/me` no trae nivel; `student_progress.cefr_level` existe sin uso y es por destreza, no por persona |
| `/auth/me` congelado byte a byte | SP1 (`tests/auth/test_login_piloto.py`, `CLAVES_NUEVAS_RAIZ`) |
| Los dos encargos coinciden en la firma | `X-Engrama-Source`, `X-Engrama-Timestamp` y `X-Engrama-Signature: sha256=<hex>` de `HMAC_SHA256(secreto, timestamp + "." + cuerpo crudo)`; ventana de ±300 s |
| Y difieren en | la ruta (`/events/batch` y `/events`), el sobre (lote y evento suelto), el campo del contenido (`payload` y `data`), las respuestas (por evento y por código HTTP) y el nombre de la variable de SET |
| **`alembic_version` fijado en los tests** (ERR-25) | `tests/integ_db.py:66` y los `HUMO_ESPERADO` de `tests/integ/test_humo_bug11.py`, `_bug13a15.py`, `_consentimiento.py`, `_autorregistro.py` y `_solicitudes_datos.py` |
| Otros números que una tabla nueva mueve | `tests/integ_db.py:67` (`tablas_con_rls: 30`) y `tests/seguridad/test_sin_acceso.py` (31 y 31) |
| Tramposos existentes sobre el camino tocado (ERR-26) | Y1 e Y4 de BUG-13 y T-integ parchean `coins_mod.award_coins`; A1 parchea `auth_router.profile_to_schema`. Predicción en §3 |

## 1. Qué cambia (una cosa)
**Un satélite del anillo entrega un lote de eventos firmado; el backend guarda cada evento una sola vez y aplica dos efectos: las monedas de la clase en vivo y el nivel confirmado por SET.**

### 1.1 La puerta
```
POST /events/batch
```
Sin JWT: la autentica la firma. No pasa por `get_current_user`, no mira `Authorization` ni `X-Tenant-ID`. Un Bearer válido sin firma → 401.

**Orden de las comprobaciones:**
1. **Tamaño:** más de **262.144 bytes** (por `Content-Length` o al leer) → **413**.
2. **Firma** (§1.2) → **401 `{"detail": "invalid_signature"}`**, el mismo cuerpo en todos los casos.
3. **JSON y raíz** → **422** si no es JSON o la raíz no cumple.
4. **`events`** con más de **200** elementos → **413**; con 0 → 422.
5. Cada evento, uno por uno (§1.4). **200** con el resumen.

Con 401, 413 o 422, **0 filas**.

### 1.2 La firma
- `X-Engrama-Source`: el **origen**. Hoy `live` (EVA) o `set` (SET).
- `X-Engrama-Timestamp`: segundos Unix, en texto. `|ahora − timestamp| > 300` → 401.
- `X-Engrama-Signature`: `sha256=<hex>` de `HMAC_SHA256(secreto del origen, <timestamp> + "." + <bytes exactos del cuerpo>)`. Se firma lo que viajó, no el JSON vuelto a escribir. Se compara con `hmac.compare_digest`.
- **Un secreto por origen**, solo por variable de entorno: **`EVENTS_SECRET_LIVE`** y **`EVENTS_SECRET_SET`**. No es el secreto JWT ni la clave de servicio.
- **Un origen sin secreto, o con uno de menos de 32 caracteres, está apagado:** 401. Así una variable olvidada no deja una puerta con secreto vacío.
- Dan el mismo 401: falta un encabezado, origen desconocido, origen apagado, timestamp que no es un entero o fuera de la ventana, firma mal formada y firma que no coincide.
- El secreto no sale en respuestas, errores ni logs.

### 1.3 El lote
```json
{"schema_version": 1, "batch_id": "humo-aula-1:000000-000199", "instance": "eva-aula",
 "session_id": "aula-3f9c2a1b7d4e5f60", "events": [ … ]}
```
- Claves de la raíz: `schema_version` (= 1), `batch_id` (1 a 128), `instance` (1 a 64), `events` (1 a 200) y `session_id` (texto o `null`; **se puede omitir**: SET no tiene sesión). Una clave de más → 422.
- Cada evento tiene **exactamente** estos 9 campos:

| Campo | Regla |
|---|---|
| `event_id` | texto de 1 a 256. La llave de idempotencia. El backend no lo interpreta |
| `tenant_id` | UUID |
| `subject_id` | UUID o `null` |
| `source` | quién produjo el hecho (tabla de §1.5) |
| `type` | uno de los permitidos al origen (§1.5) |
| `item_ref` | texto (1 a 128) o `null` |
| `payload` | objeto, según el tipo (§1.5) |
| `occurred_at` | ISO 8601 **con zona**. Más de 10 minutos en el futuro → `invalid_event` |
| `schema_version` | `1` |

### 1.4 Evento por evento, y la respuesta
```json
{"accepted": 187, "duplicates": 12, "rejected": [{"event_id": "…", "reason": "unknown_subject"}],
 "not_credited": [{"event_id": "…", "reason": "pool_exhausted"}]}
```
- **`accepted + duplicates + len(rejected) == len(events)`**, siempre.
- El lote **no es todo o nada**: uno malo no tapona la cola del satélite. Cada evento aceptado y su efecto van en **su propia transacción**.
- **Idempotencia por `(tenant_id, event_id)`** (UNIQUE en la base):
  - mismo `event_id` y **mismo contenido** → `duplicates`; la fila no cambia y **ningún efecto se repite**;
  - mismo `event_id` y **otro contenido** → `rejected` con `conflict`; **gana la primera**, nunca se sobrescribe;
  - dos veces en el mismo lote: la primera vale y la segunda es `duplicates` (o `conflict` si difiere).
  - "Mismo contenido" es la igualdad de los 9 campos ya leídos (una huella SHA-256 del evento con las claves ordenadas): el orden de las claves y los espacios no cuentan.
- **Motivos de rechazo** (permanentes; un evento rechazado **no se guarda**):

| `reason` | Cuándo |
|---|---|
| `invalid_event` | falta o sobra un campo, un tipo de dato no cuadra, el `payload` no cumple, o la fecha está en el futuro |
| `unknown_type` | el `type` no está permitido para ese origen, o el `source` o la presencia de `subject_id` no corresponden a ese tipo |
| `unknown_tenant` | el `tenant_id` no existe |
| `unknown_subject` | el `subject_id` no es un perfil con membresía **activa**, del rol que el tipo pide, en ese `tenant_id` |
| `conflict` | ver arriba |

- **`not_credited`** (nuevo, §1.6): eventos `coins.granted` **aceptados y guardados** cuyas monedas no se acreditaron. Si no hay ninguno, la lista va vacía.

### 1.5 Qué puede emitir cada origen
Una sola tabla (`src/shared/events.py`), que es la lista de permitidos: lo que no está, no entra.

| Origen | `type` | `source` | `subject_id` | `payload` |
|---|---|---|---|---|
| `live` | `live.session.started` | `teacher` | docente o admin activo | `{session_id, n_items}` |
| `live` | `item.exposed` | `live` | `null` | `{session_id, kind}`, `kind` ∈ original, twin |
| `live` | `answer.submitted` | `live` | estudiante activo | `{session_id, kind, attempt, choice, correct, distractor, late, response_ms, structure}` |
| `live` | `coins.granted` | `live` | estudiante activo | `{session_id, amount, reason}`, `amount` de 1 a 20, `reason` ∈ correct, twin, group_goal |
| `live` | `live.session.closed` | `teacher` | docente o admin activo | `{session_id, goal_met, fire_points, fire_attempts}` |
| `set` | `level.assessed` | `set` | estudiante activo | `{estado, nivel_global, score_total, provisional, cortes, destrezas, evidencia}` |

- De `coins.granted` y `level.assessed` se valida **todo** lo que el efecto usa (abajo). De los otros cuatro se valida que el `payload` sea un objeto con `session_id` (texto de 1 a 128): son materia prima y se guardan como llegan.
- `level.assessed`: `estado` = `confirmado_por_set`; `nivel_global` ∈ A1, A2, B1, B2, C1, C2; `score_total` entero de 0 a 100; `provisional` booleano; `evidencia` objeto con `intento_id` (texto). `cortes` y `destrezas` se guardan sin interpretar.
- **`set` no puede emitir `coins.granted`, y `live` no puede emitir `level.assessed`:** `unknown_type`.

### 1.6 Efecto 1: las monedas de la clase en vivo
`coins.granted` de `live`, **solo cuando el evento es nuevo**:
- acredita `amount` de la **bolsa de la institución** a la billetera del estudiante con `award_coins` (`action = "live"`, `metadata = {event_id, session_id, reason}`), y con **`idempotency_key = "event:" + event_id`**. La paga queda protegida dos veces: por el UNIQUE del evento y por el del libro (BUG-13).
- **Bolsa agotada** (el 402 de `award_coins`): el evento **se guarda igual** y va a `not_credited` con `pool_exhausted`. No se pierde el hecho; no hay monedas. La paga se intenta dentro de un `SAVEPOINT`, para deshacer solo eso.
- **Tope por sesión:** la suma de monedas acreditadas a un estudiante en una misma `payload.session_id` no pasa de **20** (el tope que el motor de EVA ya aplica, según su encargo). Lo que pase: se guarda y va a `not_credited` con `session_cap_exceeded`. No se acredita en parte. Es la segunda barrera contra un satélite que se equivoque o esté comprometido. Se cuenta con la billetera de la institución ya bloqueada: dos lotes a la vez no lo pasan.
- **Nada con origen `live` mueve el nivel, el XP ni el progreso** (007 §6 y la regla 7 de ENGRAMA): solo la billetera y el libro.
- Lo que no se acreditó **no se acredita después solo** (un reenvío es un duplicado, sin efecto). La fila guarda por qué (`effect`), para liquidarlo a mano o con una herramienta futura.

### 1.7 Efecto 2: el nivel confirmado por SET
`level.assessed` de `set`, cuando el evento es nuevo:
- guarda el nivel confirmado del estudiante **en esa institución** (una fila por `(tenant_id, profile_id)`): `cefr`, `source = "set"`, `provisional`, `score` y `assessed_at = occurred_at`.
- **Gana el `occurred_at` más reciente** (o igual: así el evento con la escritura ya calificada reemplaza al provisional del mismo intento). Un evento **anterior** se guarda en el expediente y **no** cambia el nivel.
- **Una sola función escribe el nivel** (`engrama_core/service/level.py`, ERR-26). El juego, el modo en vivo y las monedas no la llaman. El Grader y el profe (L10) la usarán con su propia `source`, cuando existan.
- **`/auth/me` y `/auth/session` ganan `confirmed_level`**, para el escudo:
  ```json
  "confirmed_level": {"cefr": "B1", "source": "set", "provisional": true,
                      "assessed_at": "2026-10-06T15:04:05Z"}
  ```
  o `null` si no hay. Es el de la **institución activa**. Ningún campo previo cambia. Cuesta una consulta más en esas dos rutas (no en las demás).

### 1.8 Lo que se declara y no se resuelve aquí
- **Un secreto por origen vale para todas las instituciones.** Quien tenga `EVENTS_SECRET_LIVE` puede acreditar monedas (hasta 20 por estudiante y sesión, y hasta agotar la bolsa) a estudiantes de cualquier institución; quien tenga `EVENTS_SECRET_SET` puede fijar el nivel confirmado de cualquier estudiante. EVA corre en el portátil del profe: **ese secreto vive en un portátil.** Un secreto por instancia (por institución o por profe) queda en "para después" y debería ir antes de un segundo colegio.
- **Sin límite de intentos en esta ruta:** un 401 cuesta un HMAC. El tope de tamaño de Caddy (H-15) es del despliegue.
- **La hora del evento la pone el satélite.** Solo se rechaza el futuro (más de 10 minutos). Un satélite con el reloj atrasado puede perder contra un nivel más nuevo.
- **El nivel es por institución**, como pide SET. Un estudiante en dos instituciones tiene dos (o uno y `null`).

### 1.9 Migración `037_eventos_anillo`
```sql
CREATE TABLE IF NOT EXISTS learning_events (
  id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  event_id       TEXT NOT NULL,
  origin         TEXT NOT NULL,
  source         TEXT NOT NULL,
  type           TEXT NOT NULL,
  subject_id     UUID REFERENCES profiles(id) ON DELETE CASCADE,
  item_ref       TEXT,
  payload        JSONB NOT NULL,
  occurred_at    TIMESTAMPTZ NOT NULL,
  schema_version INTEGER NOT NULL,
  body_hash      TEXT NOT NULL,
  batch_id       TEXT NOT NULL,
  instance       TEXT NOT NULL,
  session_id     TEXT,
  effect         TEXT NOT NULL DEFAULT 'none',
  coins          INTEGER NOT NULL DEFAULT 0,
  received_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT learning_events_tenant_event_key UNIQUE (tenant_id, event_id),
  CONSTRAINT learning_events_event_id_check CHECK (char_length(event_id) BETWEEN 1 AND 256),
  CONSTRAINT learning_events_effect_check CHECK (effect IN
    ('none','coins_credited','pool_exhausted','session_cap_exceeded','level_set','level_older')),
  CONSTRAINT learning_events_coins_check CHECK (coins >= 0 AND (coins = 0) = (effect <> 'coins_credited'))
);
CREATE INDEX IF NOT EXISTS idx_learning_events_subject ON learning_events (tenant_id, subject_id, type);
CREATE INDEX IF NOT EXISTS idx_learning_events_session ON learning_events (tenant_id, session_id);
ALTER TABLE learning_events ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS confirmed_levels (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  profile_id  UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  cefr        TEXT NOT NULL,
  source      TEXT NOT NULL,
  provisional BOOLEAN NOT NULL DEFAULT FALSE,
  score       INTEGER,
  assessed_at TIMESTAMPTZ NOT NULL,
  event_id    BIGINT REFERENCES learning_events(id) ON DELETE SET NULL,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT confirmed_levels_tenant_profile_key UNIQUE (tenant_id, profile_id),
  CONSTRAINT confirmed_levels_cefr_check CHECK (cefr IN ('A1','A2','B1','B2','C1','C2')),
  CONSTRAINT confirmed_levels_source_check CHECK (source IN ('set','grader','teacher')),
  CONSTRAINT confirmed_levels_score_check CHECK (score IS NULL OR score BETWEEN 0 AND 100)
);
ALTER TABLE confirmed_levels ENABLE ROW LEVEL SECURITY;
```
- RLS activo y sin políticas en las dos. Las políticas siguen en 51.
- **`live` y `game` no están en el CHECK de `source` del nivel:** ni un código roto puede guardar un nivel con esa fuente.
- El expediente es de solo agregar: el backend no actualiza ni borra `learning_events`, salvo `effect` y `coins`, que se escriben en la misma transacción que la fila.
- **Bajada:** `DROP TABLE` de las dos. **Se pierden el expediente y los niveles confirmados; las monedas ya acreditadas se quedan en el libro.** En producción no se baja.

**Ediciones a lo existente, todas declaradas (ERR-25):**
- `tests/integ_db.py`: `alembic_version` → `037_eventos_anillo` y `tablas_con_rls` 30 → 32; `alembic_version` en los 5 humos de §0;
- `tests/seguridad/test_sin_acceso.py`: 31 y 31 → 33 y 33;
- `tests/teachers/test_access.py`: `("/events/batch", POST): "public"`;
- `tests/auth/test_todas_las_rutas.py` (H-19): `/events/batch` entra al conjunto de rutas públicas esperadas;
- `tests/auth/test_login_piloto.py`: `confirmed_level` entra a `CLAVES_NUEVAS_RAIZ` (SP1);
- `src/auth/schemas.py` (`ProfileOut.confirmed_level`) y `src/auth/router.py` (lo llena);
- `src/shared/config.py` (los dos secretos), `src/shared/models.py` (dos modelos), `src/main.py` (el router) y `.gitignore` (el humo);
- `src/shared/events.py` y `src/webhooks/{router,schemas,service}.py` dejan de estar vacíos.
- Si la medición encuentra otra, se corrige esta lista primero (regla 8).

## 2. Criterios
| # | Criterio | Test |
|---|---|---|
| C1 | Un lote válido de 5 eventos de `live` (uno de cada tipo) → 200, `accepted: 5`; 5 filas; el estudiante recibe `amount` y hay 1 fila en el libro con `action = live` y la llave `event:<event_id>`; la bolsa baja lo mismo | EV1 |
| C2 | El mismo lote otra vez → `duplicates: 5`, siguen 5 filas, **el saldo no cambia** y el libro sigue con 1 fila | EV2 |
| C3 | **Firma:** falsa; válida para **otro** cuerpo; sin encabezados; origen desconocido; firmada con el secreto del otro origen; origen sin secreto configurado; un Bearer válido sin firma; y el mismo JSON con otro orden de claves pero con la firma del original → todos **401 con el mismo cuerpo** y 0 filas. Control: ese JSON reordenado, firmado sobre **sus** bytes → 200. El secreto no aparece en ninguna respuesta ni en los logs | EV3 |
| C4 | Timestamp de hace 10 minutos → 401; de dentro de 10 minutos → 401; no numérico → 401. Control: de hace 299 s → 200 | EV4 |
| C5 | 201 eventos → 413; un cuerpo de más de 262.144 bytes → 413; raíz con una clave de más, sin `events`, con `events: []` o `schema_version: 2`, y un cuerpo que no es JSON → 422. Siempre 0 filas. Control: 200 eventos → 200 | EV5 |
| C6 | Mismo `event_id` con otro `amount` → `rejected: conflict`; el saldo y la fila son los del primero. El mismo evento dos veces en un lote → `accepted: 1, duplicates: 1` | EV6 |
| C7 | En un lote de 9: sujeto de otra institución, sujeto inexistente, institución inexistente, tipo fuera de la lista, `coins.granted` con `source: teacher`, `item.exposed` con sujeto, un campo de más, `amount: 21` y uno bueno → cada uno con su `reason`, **el bueno entra** (`accepted: 1`) y la suma cuadra | EV7 |
| C8 | Dos lotes iguales **a la vez** (dos hilos, barrera después del primer INSERT) → entre los dos, `accepted` suma 5 y `duplicates` suma 5; 5 filas; el saldo se acredita una vez | EV9 |
| C9 | **Nivel:** antes, `confirmed_level: null`. Un lote de 1 de `set` → `accepted: 1`; `/auth/me` y `/auth/session` traen `{cefr: B1, source: set, provisional: true, assessed_at}` con la fecha del evento; repetirlo → `duplicates: 1` y nada cambia | NV1 |
| C10 | **Gana el más reciente:** uno anterior se guarda (`effect: level_older`) y el nivel no retrocede; uno posterior lo cambia (B2, `provisional: false`); uno con la misma fecha que llega después, también | NV2 |
| C11 | **A quién toca:** sujeto de otra institución, sujeto docente o sujeto inexistente → `unknown_subject` y ningún nivel escrito. El nivel es de la institución: el mismo estudiante con `X-Tenant-ID` de su otra institución ve `null`; otro estudiante ve `null` | NV3 |
| C12 | **Lista por origen:** `coins.granted` firmado como `set` → `unknown_type` y 0 monedas; `level.assessed` firmado como `live` → `unknown_type` y sin nivel. `nivel_global: B3`, `score_total: 101`, `estado` distinto y fecha de mañana → `invalid_event` | NV4 |
| C13 | **El juego no mueve el nivel:** con B1 confirmado, el estudiante gana un reto por `/submit` (cobra monedas y XP) y llegan 100 `answer.submitted` correctos y un `coins.granted` de `live` → `confirmed_level` **idéntico**. Otro estudiante sin nivel recibe lo mismo y sigue en `null` | NV5 |
| C14 | **Bolsa agotada:** con 5 en la bolsa, un `coins.granted` de 10 → `accepted: 1` y `not_credited: pool_exhausted`; el evento está guardado, el saldo es 0 y el libro tiene 0 filas. Uno de 5 después → se acredita | MC1 |
| C15 | **Tope por sesión:** 12 y 8 en la misma sesión → 20. Uno más de 1 → `not_credited: session_cap_exceeded` y el saldo sigue en 20. En otra sesión → se acredita. A otro estudiante en la primera sesión → se acredita | MC2 |
| C16 | **La firma, pura:** `firmar` y `verificar` coinciden; cambia un byte del cuerpo, el timestamp o el secreto → falso; sin el prefijo `sha256=` → falso; un secreto de 31 caracteres → falso | UE1 |
| C17 | **El catálogo, puro:** `live` permite exactamente 5 tipos y `set` exactamente 1; la huella del evento no depende del orden de las claves y cambia si cambia cualquier valor | UE2 |
| C18 | Migración up/down/up idéntica de las dos tablas (ERR-24) | MG37 |
| C19 | Regresión: los 453 previos verdes con solo las ediciones de §1.9; SP1 byte a byte sin contar `confirmed_level`; D12 da 0 y 0 | la suite completa |

## 3. Tests, tramposos, humo y réplica
- `tests/webhooks/_ayuda.py` (firmar, armar eventos y lotes, lecturas); `test_firma_y_lote.py` (EV3, EV4, EV5); `test_eventos.py` (EV1, EV2, EV6, EV7, EV9); `test_monedas.py` (MC1, MC2); `test_nivel.py` (NV1-NV5); `test_unit.py` (UE1, UE2; no-integ).
- `tests/integ/test_migracion_037.py` (MG37) y `tests/integ/test_humo_eventos_anillo.py` (HE1 y RE1).
- Los secretos de prueba son sintéticos y se ponen en `settings` dentro de cada test.

**Tramposos** (`tests/tramposos/test_tramposos_eventos.py` y `_unit.py`), diagonal PREDICHA (ERR-23: el código no existe):

| Id | Rompe | Rojo predicho | Verde predicho y por qué |
|---|---|---|---|
| ZE1 | La ruta no verifica la firma | **EV3** (as). EV4 (as: la ventana va dentro de la verificación) | los que firman bien |
| ZE2 | Toda fila es nueva (sin idempotencia) | **EV2** (as: 10 filas). EV6, EV9, NV1 y HE1 (as) | el libro no paga doble (su llave lo frena): el rojo sale de las filas y de `duplicates` |
| ZE3 | Los duplicados repiten el efecto, y la paga va sin llave | **EV2** (as: el saldo se duplica). EV9 y HE1 (as) | EV6: el conflicto no es duplicado |
| ZE4 | La firma se calcula sobre el JSON vuelto a escribir | **EV3** (as: el reordenado con la firma del original da 200) | — |
| ZE5 | Sin ventana de tiempo | **EV4** (as) | EV3: sus timestamps son de ahora |
| ZE6 | Sin tope de eventos | **EV5** (as: 201 → 200) | — |
| ZE7 | El conflicto sobrescribe (`DO UPDATE`) | **EV6** (as: la fila cambia) | — |
| ZE8 | Lote todo o nada | **EV7** (as: el bueno no entra) | los lotes sin rechazos |
| ZE9 | Comprobar y después insertar, sin `ON CONFLICT` | **EV9** (as: el UNIQUE lo frena y un lote da 500) | los secuenciales |
| ZE10 | No se valida la membresía del sujeto | **NV3** (as: el de otra institución queda con nivel). EV7 (as) | — |
| ZE11 | Un evento anterior pisa el nivel | **NV2** (as) | NV1: un solo evento |
| ZE12 | Cualquier origen emite cualquier tipo | **NV4** (as: `set` acredita monedas) | — |
| ZE13 | El nivel se lee sin la institución | **NV3** (as: se ve desde su otra institución) | NV1 y NV2: una sola institución |
| ZE14 | `answer.submitted` correcto de `live` sube el nivel | **NV5** (as) | — |
| ZE15 | Sin tope por sesión | **MC2** (as: 21) | MC1 |
| ZE16 | La bolsa agotada tumba el evento (sin `SAVEPOINT`: no se guarda) | **MC1** (as) | — |
| ZE17 | El 401 trae el secreto esperado | **EV3** (as) | — |
| ZE18 (no-integ) | `verificar` siempre dice que sí | **UE1** (as) | — |
| ZE19 (no-integ) | `set` también puede emitir `coins.granted` | **UE2** (as) | NV4 cruzaría; no se corre aquí |

**Tramposos existentes sobre el camino tocado (ERR-26), predicción:** Y1 e Y4 (BUG-13) y T-integ parchean `coins_mod.award_coins`: el efecto de monedas la llama por el módulo `coins`, así que también lo alcanzarían; siguen midiendo sus tests, que no cambian. A1 parchea `auth_router.profile_to_schema`: `confirmed_level` se agrega **después** con `model_copy`, como `consent_version`; A1 sigue rojo por su razón.

**Matriz a medir:** 17 tramposos integ × 18 columnas (EV1-EV7, EV9, NV1-NV5, MC1, MC2, MG37 y HE1; son 17 tests y la columna de SP1) = **306 celdas**, más RE1 con la bandera.

**Humo HE1** escribe `tests/_salida/humo_eventos_anillo.json` antes de afirmar. Semilla `random.Random(37)`. Una clase sintética: 1 profe y 6 estudiantes; el generador arma el lote como lo haría EVA (inicio, 4 ítems expuestos, respuestas con acierto al azar, monedas por acierto con tope 20, cierre) y lo manda **dos veces**; después SET manda el nivel de 2 estudiantes.
```json
{"alembic_version":"037_eventos_anillo","semilla":37,"eventos":N,"primera":{"accepted":N,"duplicates":0,"rejected":0},
 "segunda":{"accepted":0,"duplicates":N,"rejected":0},"filas":N,"monedas_acreditadas":M,"filas_en_el_libro":K,
 "bolsa":1000-M,"niveles":{"accepted":2},"con_nivel":2,"sin_nivel":4,"firma_falsa":401}
```
`N`, `M` y `K` salen de la semilla: **se fijan al medir el humo por primera vez con el código bueno** y desde ahí no se mueven (se declara en el commit de la matriz).

**Réplica** (`ENGRAMA_REPLICA_EVENTOS=1`; 1 test saltado sin la bandera): **RE1**, con entradas nuevas: semilla 38; un lote de exactamente 200; `event_id` de 256 caracteres con `:`, `@`, tildes y espacios; un estudiante en dos instituciones con el mismo `event_id` en las dos (son dos eventos); y dos lotes que se solapan en la mitad de sus eventos.

## 4. Cuentas (ERR-10)
**Ajuste del preregistro, escrito ANTES del código (no hay nada medido que mover):** los 19 criterios de §2 no cambian, pero varios comparten test, para que cada test arme su escenario una sola vez. Donde §2 y §3 nombran un test que no existe, vale esta tabla:

| Test | Criterios que afirma |
|---|---|
| EV1 | C1 y C2 (el lote y su reenvío) |
| EV3 | C3 y C4 (la firma y la ventana de tiempo) |
| EV5 | C5 |
| EV6 | C6 |
| EV7 | C7 |
| EV9 | C8 |
| NV1 | C9 y C10 (el nivel y "gana el más reciente") |
| NV3 | C11 y C12 (a quién toca y la lista por origen) |
| NV5 | C13 |
| MC1 | C14 y C15 (la bolsa y el tope por sesión) |
| UE1 (no-integ) | C16 y C17 |
| MG37 y HE1 | C18 y el humo |

Los tramposos apuntan al test que absorbió su criterio: ZE1, ZE4, ZE5 y ZE17 → EV3; ZE2 y ZE3 → EV1; ZE10, ZE12 y ZE13 → NV3; ZE11 → NV1; ZE15 y ZE16 → MC1; ZE18 y ZE19 → UE1.

| Grupo | integ | no-integ |
|---|---|---|
| EV1, EV3, EV5, EV6, EV7 y EV9 | 6 | — |
| NV1, NV3 y NV5 | 3 | — |
| MC1 | 1 | — |
| MG37 y HE1 | 2 | — |
| UE1 | — | 1 |
| ZE1-ZE17 | 17 | — |
| ZE18 y ZE19 | — | 2 |
| **Nuevos** | **29** | **3** |
| RE1 (saltado sin bandera) | 1 skipped | — |

- **passed:** 453 + 29 + 3 = **485**; **skipped:** 17 + 1 = **18**; **no-integ:** 125 + 3 = **128**; ruff 0 y mypy 0.
- Si lo anterior cierra con N, S y M: N + 32, S + 1 y M + 3.
- **Matriz a medir:** 17 tramposos integ × 12 columnas (los 10 tests de arriba, MG37 y HE1) = **204 celdas**, más RE1 con la bandera. (Reemplaza la cifra de §3.)

## 5. Plan de commits
1. `docs`: esta espec.
2. `feat(eventos)`: la 037, los modelos, `shared/events.py`, `webhooks/`, `engrama_core/service/level.py`, `confirmed_level` en `/auth/me`, los tests, los tramposos, el humo, la réplica y las ediciones de §1.9.
3. `docs`: la matriz medida, los números del humo y "Antes de aplicar la 037".

## 6. Variables nuevas
`EVENTS_SECRET_LIVE` y `EVENTS_SECRET_SET`: 32 caracteres o más, al azar, distintos entre sí y distintos por entorno. Vacías = ese origen apagado.

## 7. Contrato, con un ejemplo de cada pieza
**EVA** (`X-Engrama-Source: live`):
```json
{"schema_version":1,"batch_id":"aula-3f9c:000000-000001","instance":"eva-aula","session_id":"aula-3f9c",
 "events":[{"event_id":"aula-3f9c:coins.granted:p01@v2:7b0c…:correct","tenant_id":"0b7e…","subject_id":"7b0c…",
   "source":"live","type":"coins.granted","item_ref":"p01@v2",
   "payload":{"session_id":"aula-3f9c","amount":2,"reason":"correct"},
   "occurred_at":"2026-10-06T15:04:05.123456+00:00","schema_version":1}]}
→ 200 {"accepted":1,"duplicates":0,"rejected":[],"not_credited":[]}
```
**SET** (`X-Engrama-Source: set`), un lote de 1:
```json
{"schema_version":1,"batch_id":"5b1f0c1e-…","instance":"set-local",
 "events":[{"event_id":"5b1f0c1e-…","tenant_id":"…","subject_id":"…","source":"set","type":"level.assessed",
   "item_ref":null,"payload":{"estado":"confirmado_por_set","nivel_global":"B1","score_total":52,
   "provisional":true,"cortes":"set-cefr-2026","destrezas":{…},"evidencia":{"intento_id":"1234",…}},
   "occurred_at":"2026-10-06T15:04:05.000Z","schema_version":1}]}
→ 200 {"accepted":1,"duplicates":0,"rejected":[],"not_credited":[]}
```
**engrama-web:** `GET /api/auth/me` trae `confirmed_level` (o `null`): el escudo deja de decir "Por confirmar" cuando no es `null`, y muestra "provisional" si lo es.

## 8. Riesgo para producción y qué NO se toca
- **Aplicar la 037 es producción:** el sí de Christiam, con respaldo. **Va antes o junto con el código:** sin `confirmed_levels`, `/auth/me` da 500 y **nadie entra**.
- No se toca: `award_coins` (se usa como está), `/submit`, la asistencia, el XP, `student_progress`, `EVAGAME/`, `SET/` ni `engrama-web`.

## 9. Diferencias con los encargos: qué debe ajustar cada pieza
**EVA** (`EVAGAME/docs/ENCARGO_backend_eventos.md`): el contrato se adopta casi entero.
| Tema | Su encargo | Queda | Qué ajusta EVA |
|---|---|---|---|
| Ruta | `/events/batch` (preguntaba si `/events`) | `/events/batch` | nada |
| Respuesta | 3 claves | 4: se agrega `not_credited` | aceptar la clave nueva; usarla para el texto "monedas de esta clase" (su pregunta 2) |
| Bolsa agotada | sugería un `reason` en `rejected` | el evento se **acepta**; va a `not_credited: pool_exhausted` | no apartarlo como rechazado |
| Tope de 20 por sesión | preguntaba si el backend lo repite | sí: `not_credited: session_cap_exceeded` | nada, si su motor ya lo aplica; **confirmar que 20 es el número** |
| El profe en `live.session.*` | sugería validarlo | se valida: docente o admin activo en la institución; si no, `unknown_subject` | mandar el `id` del perfil del profe |
| `session_id` de la raíz | obligatorio | opcional (SET no lo tiene) | nada |
| Claves de la raíz "de menos → 422" | exactas | `session_id` puede faltar | nada |
| Lote de 0 eventos | no lo dice | 422 | no mandar lotes vacíos |
| Fecha futura | no lo dice | más de 10 min en el futuro → `invalid_event` | reloj del portátil en hora |
| Secreto | uno por satélite | uno por origen, mínimo 32 caracteres | `EVA_SECRETO_EVENTOS` = `EVENTS_SECRET_LIVE` |
| 415 si no es JSON | 415 o 422 | 422 | nada (no reintenta ninguno de los dos) |
| Su test EV8 | "el nivel del escudo no cambia" | es NV5 | — |

**SET** (`SET/docs/ENCARGO_backend_nivel.md`): cambia el sobre, no el contenido.
| Tema | Su encargo | Queda | Qué ajusta SET |
|---|---|---|---|
| Ruta | `POST /events` | `POST /events/batch` | la URL (`ENGRAMA_EVENTS_URL`) |
| Sobre | el evento suelto | un lote de 1: `{schema_version, batch_id, instance, events: [evento]}` | envolver; `batch_id` puede ser el `event_id`, `instance` = `set-local` |
| Contenido | campo `data` | campo **`payload`** | renombrar |
| `item_ref` | no existe | obligatorio (puede ser `null`) | agregar `"item_ref": null` |
| Respuestas | 201 nuevo, 200 duplicado, 409 conflicto, 422 sujeto, 403 tipo | siempre **200** con `accepted`, `duplicates`, `rejected[]` | leer el cuerpo: entregado si `accepted + duplicates == 1`; rechazado definitivo si viene en `rejected` (`conflict`, `unknown_subject`, `unknown_type`, `invalid_event`, `unknown_tenant`) |
| Cuerpo del 401 | `firma inválida` | `invalid_signature` | mirar solo el código |
| Variable | `EVENTS_SECRET_SET` en el backend | igual | `SET_EVENTS_SECRET` con el mismo valor, de 32 o más |
| Dónde se ve el nivel | proponía `nivel: {valor, fuente, estado, provisional, fecha}` | `confirmed_level: {cefr, source, provisional, assessed_at}` | nada (lo lee engrama-web) |
| Escritura calificada después | otro `event_id`, mismo intento | así: gana la fecha más reciente **o igual** | mandar el segundo evento con `occurred_at` igual o posterior |
| "Gana el más reciente entre SET, Grader y profe" | sí | sí, la misma función; hoy solo existe `set` | — |
| Pase corto `POST /auth/pase` | lo pide, "no bloquea" | **no se hace aquí** | sigue usando el pase del estudiante contra `/auth/me` |
| Su doble (`doble_backend.js`) | el contrato viejo | — | actualizarlo a este |

## 10. Para después
Un secreto por instancia; liquidar los `not_credited`; el pase corto para SET (`POST /auth/pase`); el nivel puesto por el profe (L10) y por el Grader, con la misma función; leer el expediente para el repaso y el panel; un límite de intentos en la puerta; purgar o exportar el expediente de una persona.

**Para el pedagogo y para Christiam (ERR-16):** qué dice el escudo con un nivel `provisional`; qué ve el estudiante cuando sus monedas de la clase no se acreditaron; y el número 20.

## 11. Veredicto
- **FUNCIONA:** las cuentas de §4, la matriz medida, HE1 escrito, MG37 verde y los previos verdes con solo las ediciones declaradas.
- **HAY ALGO MODESTO:** todo lo anterior medido contra los dobles de este repo, sin correr contra el EVA y el SET reales (que deben ajustarse antes, §9).
- **NO:** un evento repetido deja dos filas o paga dos veces; una firma falsa entra; un conflicto sobrescribe; algo de `live` mueve el nivel; un origen emite un tipo que no es suyo; el nivel de uno se ve en otra institución; un tramposo queda verde.
