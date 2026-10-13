# ESPEC · Racha semanal por institución, backend

F4 · Creador · 2026-10-12 · preregistro. Rama `test/fixture-integ`, sobre `03c9c0a` (**666 passed + 23 skipped, 178 no-integ, ruff 0**).

Manda el dictamen `investigacion/pedagogia/04-dictamen-racha-y-reto-del-dia.md` §1.1 y §1.2. Cierra L4-b, L4-c y BUG-12 (L4-d) de `docs/AUDITORIA_lingo_L2_L4_L6_L7.md`. Es el bloque 1 de 5 del encargo "reto del día sin profe" (los otros: nivel de práctica y tanda, `solo_refuerzo`, L1, humo).

## 0. Leído (2026-10-12)
| Qué | Dónde |
|---|---|
| La racha de hoy: global del perfil, por días de calendario, solo la mueve el check-in | `profiles.current_streak`; `attendance.compute_next_streak` y `check_in` paso 5 |
| El día de la institución | `fechas.hoy(now, settings.engrama_utc_offset_hours)` (`attendance.py:317`) |
| Dónde se califica una respuesta | `attempts.submit_attempt` (retos), `refuerzo.service.responder` (repaso) y `webhooks.efectos.aplicar` (EVA: `answer.submitted`, que hoy solo se guarda; su `payload.correct` es booleano y trae `item_ref`) |
| La identidad de una pregunta | `refuerzo.reglas.clave_de_forma(item_ref, question_id)` |
| Paga con llave y bolsa agotada | `coins.award_coins(idempotency_key=…)`: `None` si la llave ya pagó, 402 si la bolsa no alcanza; el patrón del SAVEPOINT está en `webhooks.efectos._pagar` |
| `alembic_version` fijado (ERR-25) | `git grep -n "041_refuerzo" -- tests`: 12 líneas (`tests/integ_db.py:66` y 11 `HUMO_ESPERADO`) |

## 1. Qué cambia (una cosa)
**Cada estudiante tiene, por institución, una racha de SEMANAS cumplidas. Una semana (lunes a domingo) se cumple al 3.er día activo; un día es activo por asistir o por responder bien. No cumplir gasta un protector o vuelve la racha a 0; nada más baja.**

### 1.1 Día activo
Un día (fecha local de la institución, con la hora **del servidor**) es activo si:
- (a) hay una asistencia registrada ese día (un check-in que respondió 200, haya pagado o no); o
- (b) ese día tiene **≥ `RACHA_RESPUESTAS_DIA` (6) preguntas respondidas, de las cuales ≥ `RACHA_CORRECTAS_DIA` (4) correctas**, sumando:
  - retos (`/submit`): cada pregunta con respuesta no vacía;
  - repaso (`/challenges/refuerzo/{id}/respuestas`): cada respuesta nueva (no la `repetida`);
  - EVA: cada `answer.submitted` **nuevo** de origen `live`, con `item_ref` y `payload.correct` booleano. La fecha es la de la **recepción** en ENGRAMA (se declara: si EVA entrega el lote al otro día, cuenta para ese día).
- **Cada pregunta cuenta una vez por día, con su mejor resultado.** La identidad es `clave_de_forma` (el mismo ítem en un reto y en EVA es una sola pregunta). Fallarla y después acertarla el mismo día la deja como correcta.
- No cuentan: abrir la app, SET, invitados ni tarjetas `aula:NNN` (no tienen cuenta: no llegan como estudiante).
- Un día ya activo no cambia por nada (L4-c: la segunda sesión del día no hace nada).

### 1.2 Semana, racha y protector
- La semana es la del **lunes** de la fecha local. Al pasar un día a activo:
  - si con él la semana llega a **`RACHA_DIAS_POR_SEMANA` (3)** días activos: `racha_semanas + 1`, `semanas_cumplidas + 1`, `mejor_racha = max(…)` y se intenta el bono (§1.3);
  - si llega a **`RACHA_DIAS_PROTECTOR` (5)**: `protectores + 1`, con tope `RACHA_PROTECTOR_TOPE` (2).
- El estado nace con `racha 0`, `protectores = RACHA_PROTECTOR_INICIAL (1)` y todas las semanas anteriores dadas por cerradas.
- **Cierre perezoso** (sin tarea programada): antes de leer o escribir se cierran, en orden, las semanas terminadas que faltan. Por cada una **no cumplida**: si es la semana en que se creó la membresía → nada; si hay protector → se gasta 1 y la racha queda igual; si no → `racha_semanas = 0`. Una semana cumplida no hace nada al cerrar (ya sumó).
- **Nunca bajan:** `mejor_racha`, `semanas_cumplidas`, las monedas ni el nivel.
- La lectura calcula el cierre y **no escribe**; la escritura lo persiste. Las dos dan lo mismo.
- Las semanas de receso no existen todavía (dictamen §4.3, "Después"): las cubre el protector.

### 1.3 Bono de semana cumplida
`RACHA_BONO_SEMANA` (5) monedas al cumplir la semana, por `award_coins` con la llave `semana:<tenant>:<profile>:<año ISO>-W<semana ISO>` y `action = "streak_week"`. Va en un SAVEPOINT: **si la bolsa no alcanza, la semana cuenta igual y el bono no se paga (nunca 402)**. Con el bono en 0 no se llama a `award_coins`. `streak_bonus` de los intentos sigue en 0.

### 1.4 Lo que se guarda (migración `042_racha_semanal`, aditiva)
```
activity_days (id, tenant_id, profile_id, local_date, via_asistencia BOOL, respuestas INT, correctas INT,
               primeras_correctas INT, activo BOOL, preguntas JSONB {clave: 0|1}, por_origen JSONB {origen: n},
               created_at, updated_at;  UNIQUE (tenant_id, profile_id, local_date))
streak_state  (id, tenant_id, profile_id, racha_semanas, mejor_racha, semanas_cumplidas, protectores,
               ultima_semana_cerrada DATE, created_at, updated_at;  UNIQUE (tenant_id, profile_id))
```
- `preguntas` es la memoria de "una vez por día con su mejor resultado". `primeras_correctas` (aciertos al primer intento del día) y `por_origen` (`reto`, `reto_repetido`, `repaso`, `eva`) son los **datos de vigilancia** del dictamen §2 (riesgos 1, 3 y 8); no deciden nada.
- CHECK: contadores ≥ 0, `correctas <= respuestas`, `mejor_racha >= racha_semanas`, `protectores` entre 0 y 10.
- RLS activo y sin políticas en las dos, como toda tabla desde la 031 (los clientes no tienen acceso directo; el backend filtra por `tenant_id` y `profile_id` en cada consulta).
- Bajada: las dos tablas (se pierde la racha). En producción no se baja.
- **`profiles.current_streak`, `longest_streak` y `last_attendance_date` no se tocan ni se borran:** el check-in los sigue moviendo como hoy y responde lo mismo (sus cuatro campos del desglose incluidos).

### 1.5 La ruta (decisión: ruta propia, no `/auth/me`)
`GET /core/racha` (usuario autenticado; institución activa). Por qué no `/auth/me`: (1) `/auth/me` está congelado byte a byte (`tests/auth/snapshot_me_antes.json`) y lo pide cada pantalla: sumarle tres consultas las paga todo el mundo; (2) la llama necesita el detalle de la semana (siete puntos), que no es "perfil"; (3) la web de hoy lee `current_streak` de `/auth/me` y sigue funcionando sin cambios.
```json
{"racha_semanas": 2, "mejor_racha": 6, "semanas_cumplidas": 14,
 "protectores": 1, "protectores_tope": 2,
 "semana": {"desde": "2026-10-12", "hasta": "2026-10-18", "dias_activos": 2, "meta_dias": 3,
            "cumplida": false, "dias_para_protector": 5,
            "dias": [{"fecha": "2026-10-12", "activo": true, "via_asistencia": true,
                      "respuestas": 0, "correctas": 0}, "… 7, de lunes a domingo"]},
 "hoy": {"fecha": "2026-10-14", "activo": false, "respuestas": 3, "correctas": 2,
         "meta_respuestas": 6, "meta_correctas": 4},
 "semana_pasada": {"dias_activos": 1, "cumplida": false},
 "bono_semana": {"monedas": 5, "pagado": false}}
```
- No escribe nada. Sin filas, responde el estado inicial (racha 0, 1 protector, 7 días inactivos).
- `bono_semana.pagado`: existe la fila del libro con la llave de **esta** semana.
- Los textos son de la web (dictamen: "N semanas", "2 de 3 días esta semana"; al romperse, "Semana nueva. Tu mejor racha: 6. Semanas cumplidas: 14."; prohibido "perdiste"). Con `semana_pasada.cumplida = false` y `racha_semanas = 0` la web sabe que es "semana nueva".
- Ningún contrato existente cambia: `/submit`, el repaso y el check-in responden lo mismo. Para celebrar, la web vuelve a leer `/core/racha` y compara.

### 1.6 Variables nuevas (ninguna es secreto)
| Variable | Por defecto | Rango |
|---|---|---|
| `RACHA_DIAS_POR_SEMANA` | 3 | 1 a 7 |
| `RACHA_DIAS_PROTECTOR` | 5 | 1 a 7 |
| `RACHA_RESPUESTAS_DIA` | 6 | 1 a 100 |
| `RACHA_CORRECTAS_DIA` | 4 | 0 a 100 |
| `RACHA_PROTECTOR_INICIAL` | 1 | 0 a 10 |
| `RACHA_PROTECTOR_TOPE` | 2 | 0 a 10 |
| `RACHA_BONO_SEMANA` | 5 | 0 a 50 |

## 2. Criterios
| # | Criterio | Test |
|---|---|---|
| C1 | **Puro:** día activo (6 y 4; 5 respuestas no; 6 con 3 correctas no; asistencia sola sí); el lunes de una fecha; al 3.er día sube y al 5.º gana protector con tope; el 4.º y el 6.º no hacen nada; los siete valores por defecto | UW1 (no-integ) |
| C2 | **Puro, el cierre:** semana no cumplida con protector → se gasta y la racha queda; sin protector → 0; la semana de la membresía no cuenta; varias semanas de ausencia; `mejor_racha` y `semanas_cumplidas` no bajan; cerrar dos veces da lo mismo | UW2 (no-integ) |
| C3 | **Puro, la memoria del día:** una pregunta cuenta una vez; fallar y luego acertar la deja correcta; acertar y luego fallar la deja correcta; `primeras_correctas` solo mira el primer intento | UW3 (no-integ) |
| C4 | **Respuestas:** 6 preguntas con 4 correctas en retos → día activo; con 5 no; la misma pregunta repetida no suma; el repaso suma; 6 con 3 correctas no | RW1 |
| C5 | **Asistencia y regresión:** un check-in marca el día; el segundo del día no cambia nada; la respuesta del check-in y `profiles.current_streak` son **idénticos** a los de antes (los tests del check-in, sin editar) | RW2 y la suite |
| C6 | **Semana cumplida y bono:** al 3.er día `racha 1` y 5 monedas, una sola vez (la llave); el 4.º día no paga; con la bolsa en 0 la semana cuenta, el bono no se paga y nadie recibe 402 | RW3 |
| C7 | **Cierre por HTTP:** semana sin cumplir con protector → racha igual y protector 0; otra → racha 0 con `mejor_racha` y `semanas_cumplidas` intactos; la lectura no escribe | RW4 |
| C8 | **Por institución (BUG-12):** un perfil en dos instituciones con actividad en una tiene racha 0 y 0 días en la otra; un estudiante no ve la de otro | RW5 |
| C9 | **EVA:** 6 `answer.submitted` (4 correctos) de `live` hacen el día activo; reenviar el lote no suma; el `effect` sigue `none`; el nivel no se toca | RW6 |
| C10 | **Protector:** al 5.º día activo gana uno; con 2 no pasa del tope | RW7 |
| C11 | Migración up/down/up idéntica (ERR-24) | MG42 |
| C12 | Regresión: los 666 previos verdes con solo las ediciones de §4 | la suite |

## 3. Tramposos (diagonal PREDICHA; ERR-23)
| Id | Rompe | Rojo predicho |
|---|---|---|
| ZW1 (no-integ) | Abrir cuenta: cualquier respuesta hace el día activo | UW1 |
| ZW2 (no-integ) | El cierre nunca rompe la racha (la que "nunca se rompía" de Lingo) | UW2 |
| ZW3 (no-integ) | Romper la racha baja también `mejor_racha` | UW2 |
| ZW4 (no-integ) | La misma pregunta cuenta cada vez que se responde | UW3 |
| ZW5 (no-integ) | La semana se cumple al 2.º día por defecto | UW1 |
| ZW6 | `/submit` no registra respuestas | RW1 |
| ZW7 | El bono se paga sin llave (cada día activo tras el 3.º vuelve a pagar) | RW3 |
| ZW8 | La bolsa agotada tumba la respuesta (402) | RW3 |
| ZW9 | La racha se busca sin institución (global, como BUG-12) | RW5 |
| ZW10 | El check-in no marca el día | RW2 |
| ZW11 | La lectura no cierra semanas (muestra la racha vieja) | RW4 |
| ZW12 | EVA cuenta también los eventos duplicados | RW6 |
| ZW13 | El protector no tiene tope | RW7 |

**Tramposos existentes sobre el camino tocado (ERR-26):** `git grep -n "attempts_mod\|attendance_mod\|efectos" -- tests/tramposos`. Predicción: siguen rojos por su razón; el gancho va **después** de calificar, de registrar la asistencia y de guardar el evento, y no cambia el resultado ni la paga.

## 4. Ediciones a lo existente (ERR-25)
`alembic_version` → `042_racha_semanal` en las 12 líneas de §0; `tablas_con_rls` 41 → 43; `tests/seguridad/test_sin_acceso.py` 42 y 42 → 44 y 44; `tests/teachers/test_access.py` gana 1 ruta; `src/engrama_core/service/attendance.py` (el check-in llama al gancho tras registrar), `src/challenge_engine/service/attempts.py` (`submit_attempt` llama al gancho tras calificar), `src/refuerzo/service.py` (`responder`, tras guardar), `src/webhooks/efectos.py` (`aplicar`, para `answer.submitted`), `src/engrama_core/router.py` (la ruta), `src/shared/config.py` (siete variables), `src/shared/models.py`.

## 5. Cuentas (ERR-10)
UW1 a UW3 (3 no-integ) + ZW1 a ZW5 (5 no-integ) + RW1 a RW7 y MG42 (8 integ) + ZW6 a ZW13 (8 integ) = **16 integ y 8 no-integ**. Sobre 666 + 23 y 178: **690 passed + 23 skipped y 186 no-integ**; ruff 0. El humo y la réplica son el bloque 5 (`ESPEC_humo_reto_del_dia.md`).

## 6. Qué NO se toca
`profiles.current_streak` y sus dos compañeras; la respuesta del check-in, de `/submit` y del repaso; `award_coins`; la paga de los retos y de la asistencia; `/auth/me`; el nivel confirmado.

## 7. Riesgos
- **Dos rachas conviven:** la vieja (`current_streak`, en `/auth/me` y en el roster del profe) y la nueva. La web debe pasar la llama a `/core/racha`; mientras tanto pinta la vieja, que sigue igual de rota (L4-b). Retirar la vieja es otra espec.
- **Asistir cuenta igual que estudiar** (pregunta 10 del dictamen, provisional sí): tres clases por semana cumplen la semana sin autoestudio. Lo vigila el riesgo 3 con `por_origen` y `via_asistencia`.
- **El bono sale de la bolsa de la institución:** 5 por estudiante y semana.
- Cambiar los umbrales con semanas en curso no recalcula lo ya contado.
- El tiempo por respuesta (riesgo 1, "< 3 s") no se guarda en `/submit`: ese dato no existe hasta L1.

## 8. Para después
Semanas de receso por institución; "recuperar la racha" (dictamen §4.2); "días activos esta semana" en el roster del profe (pregunta 9); retirar `current_streak` de la web y del roster; purgar al salir de la institución.

## 9. Veredicto
- **FUNCIONA:** las cuentas de §5, la diagonal medida, MG42 verde y los previos verdes con solo las ediciones de §4.
- **NO:** un día se activa por abrir o por hacer clic; la racha de una institución se ve en otra; el bono paga dos veces; la bolsa agotada da 402; `mejor_racha` baja; el check-in responde distinto; un tramposo queda verde.
