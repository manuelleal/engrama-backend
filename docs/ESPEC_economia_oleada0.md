# ESPEC · Economía, oleada 0: cerrar lo que desborda (backend)

F4 · Creador · 2026-10-07 · preregistro, SIN código. Rama `test/fixture-integ`, sobre `5aad55e` (base medida hoy: **139 no-integ**, 455 deseleccionados; la última suite completa medida es **572 passed + 22 skipped**, `ESPEC_refuerzo.md` §12, y desde entonces solo hubo commits de docs).

Origen: `investigacion/juego/01-lingo-coins-vs-engrama-brechas-y-superacion.md` (§3 brechas 1, 2, 4, 7, 20, 21 y 22; §5.5; §7 oleada 0) e `investigacion/pedagogia/03-dictamen-err16-...` (C.2: el tope de 20 de EVA solo es sano con reto = 10; C.3: avisar antes de que la bolsa se agote). No usa IA. **No necesita migración: la cabeza sigue en `041_refuerzo`.**

Datos que no se discuten aquí (Christiam, 2026-10-07): el reto individual vale **10**; el tope de una sesión en vivo de EVA es **20**; el refuerzo da **0**; el pool es de **200.000** por institución (provisional). La moneda premia el dominio, no la velocidad ni el azar; sin castigos.

Todos los números nuevos de esta espec son **PROVISIONALES del arquitecto** y Christiam puede vetar cada uno: por eso cada uno es una variable de configuración (§5), no un literal en el código.

## 0. Medido y leído (2026-10-07, `grep -n` y lectura de hoy sobre `5aad55e`)

### 0.1 Lo que dice el informe del diseñador, cotejado contra el código
| # | Afirmación del informe | Veredicto | Dónde |
|---|---|---|---|
| A1 | El check-in paga 50, con ×1,5 (racha ≥7) y ×2 (racha ≥14) | **CONFIRMADA** en el código; **matizada** en el efecto (ver A2) | `src/engrama_core/service/attendance.py:52` (base), `:55-58` (tabla), `:91-96` (`streak_multiplier`), `:341-342` (`int(ATTENDANCE_COINS_BASE * multiplier)`). No es un descuido: lo pedía `SPECS/02-engrama-core.md:263-268` |
| A2 | "50 / 75 / 100" como economía vivida; "100 a 200 solo por asistir con 2 sesiones" (§5.5.1) | **NO SE SOSTIENE tal cual.** La racha solo sube si la asistencia anterior fue **ayer** (`attendance.py:105`); con cualquier hueco vuelve a 1 (`:107-108`). Un grupo con clase martes y jueves **nunca** pasa de racha 1: cobra 50 siempre, 100 por semana. 75 y 100 exigen 7 y 14 días de calendario seguidos, fines de semana incluidos | `attendance.py:99-110` |
| A3 | No existe la puntualidad | **CONFIRMADA.** `starts_at` se escribe al crear la sesión (`:182`) y `check_in` (`:257-380`) nunca lo lee | `attendance.py:182`, `:286-291` |
| A4 | No hay límite de un pago de asistencia por día | **CONFIRMADA.** El único UNIQUE es por sesión; el control de duplicado también | `alembic/versions/009_create_attendance.py:33` (`UNIQUE (session_id, student_id)`), `src/shared/models.py:391`, `attendance.py:295-303`. La paga va sin llave (`:360-372`) |
| A5 | Una segunda sesión el mismo día reinicia la racha a 1 | **CONFIRMADA.** Con `last_attendance_date == today` la función cae al último `return 1`. El comentario de esa línea y el encabezado del módulo dicen que "el UNIQUE lo bloquea": **es falso**, ese UNIQUE no existe | `attendance.py:109-110` (el `return 1`), `:17` (el comentario falso), `:330-338` (se escribe la racha) |
| A6 | La racha va por día UTC y es global por perfil | **CONFIRMADA.** `now = datetime.now(UTC)` y `today = now.date()`. Consecuencia que el informe no dice: una clase a las 19:00 de Bogotá ya es "mañana" en UTC. Dos clases en días seguidos, una a las 18:00 y otra a las 19:30, quedan a **2 días UTC** y la racha se rompe | `attendance.py:286`, `:329`; `models.py:106-108` (columnas en `profiles`, que es global) |
| A7 | `coins_reward` no tiene tope | **CONFIRMADA.** Solo `ge=0`; la columna no tiene CHECK | `src/challenge_engine/schemas.py:86`; `alembic/versions/010_create_challenges.py:36`; `models.py:425-427` |
| A8 | `max_winners` no tiene tope y su defecto es 10 | **CONFIRMADA** (`ge=1`, defecto 10). **Matiz:** no es por sí mismo un desborde: una sola paga por (reto, estudiante) (`attempts.py:281`) y la barrera de grupo ya acotan los ganadores al tamaño del grupo. Lo que daña es el **defecto 10**: al llegar a 10 el reto desaparece del feed de todos (`challenges.py:190`) y un acierto posterior no cobra (`attempts.py:270`): es la carrera | `schemas.py:89`; `010:39`; `challenges.py:190`; `attempts.py:270` |
| A9 | El reto paga todo o nada | **CONFIRMADA** (100 % en `multiple_choice` y `listening`; ≥70 % en `open` y `fill_blank`). **No se toca en esta oleada** | `src/challenge_engine/service/attempts.py:111-116`, `:270-285` |
| A10 | La billetera de la institución no tiene recarga | **CONFIRMADA.** Si la institución existe "la billetera NUNCA se recarga"; la CLI tiene cuatro órdenes (`alta`, `restablecer`, `suspender`, `reactivar`); `coin_pool` solo se escribe al nacer | `src/onboarding/alta.py:77-82`, `:83-87`; `src/onboarding/__main__.py:59-81`; `grep -rn coin_pool src` → solo `alta.py:83` |
| A11 | No hay alerta de bolsa baja | **CONFIRMADA.** `award_coins` solo responde 402 cuando ya no alcanza | `src/engrama_core/service/coins.py:160-167`; `grep -rn "umbral\|alerta" src` → 0 |
| A12 | Diferencia de redondeo entre JavaScript y Python | **CONFIRMADA como hecho del lenguaje, REFUTADA como defecto de hoy.** Medido hoy: Python `round(2.5) = 2` y `round(0.5) = 0`; Node `Math.round(2.5) = 3` y `Math.round(0.5) = 1`. Pero en `src/` **no hay ningún `round(`** (`grep` → 0): el único cálculo fraccionario de monedas es `int(50 * multiplier)` (`attendance.py:342`, trunca) y su gemelo en el mock es `Math.round(50 * m)` (`engrama-web@cba7150:herramientas/mock/rutas_core.mjs:58`); los dos dan 50, 75 y 100 exactos. La diferencia aparecería con el bono de racha de la oleada 1 (2,5). La función única de esta oleada es **preventiva** | ver arriba |
| A13 | Las tres cifras que el diseñador dijo haber verificado | **CONFIRMADAS** | `attendance.py:52`; `challenge_engine/schemas.py:86`; `src/webhooks/efectos.py:27` |
| A14 | "El sembrador tiene que pasar `max_winners` al tamaño del grupo" (§7, oleada 0) | **YA ESTÁ HECHO** en la herramienta de la web: pide `student_count` y lo manda | `engrama-web@cba7150:herramientas/sembrar_retos.mjs:56-62`, `sembrar/mapeo.mjs:151` |
| A15 | "Alerta al 20 %" (§7) | El encargo del arquitecto fija **10 %**. Manda el encargo; queda como variable | §5 |

No cotejado (fuera de esta oleada): el resto del inventario de §2.1 y §2.2 del informe (tienda, insignias, refuerzo, foco, Grader, ranking).

### 0.2 Hallazgos propios que el informe no trae
| # | Hallazgo | Dónde |
|---|---|---|
| H1 | **Con la bolsa agotada, el check-in entero falla con 402 y la asistencia NO queda registrada** (la transacción revierte). EVA ya lo resuelve con un SAVEPOINT; la asistencia no. Fuera de alcance: va a §10 y a la pregunta P9 | `attendance.py:357-372`; contraste en `webhooks/efectos.py:57-68` |
| H2 | `attendance.py` tiene **434 líneas** y `check_in` unas 125: ya pasa los máximos de `REGLAS.md` §4 (400 y 40). Esta oleada no puede agrandarlo | `wc -l` de hoy |
| H3 | El ayudante de los tests crea las sesiones con `starts_at = ahora − 1 h`: con la regla nueva, **todo check-in de los tests existentes es "no puntual"** | `tests/integ_ayudante.py:244` |
| H4 | Los tests de racha siembran "ayer" en UTC. Con el día local, entre las 19:00 y las 24:00 de Bogotá "ayer UTC" ya no es "ayer local": hay que cambiarlos o fallan según la hora | `tests/engrama_core/test_attendance.py:158-160`, `:270`, `:282`, `:306` |
| H5 | `coin_ledger.from_wallet_id` admite NULL y la llave de idempotencia ya es UNIQUE por institución: alcanzan para la recarga y para "un pago por día" **sin migración** | `models.py:286-288`, `:306-312`; migración `033` |
| H6 | Las coordenadas de referencia del grupo nunca se escriben (nadie asigna `last_admin_lat`): la geocerca siempre da `reference_missing`. Fuera de alcance | `grep -rn last_admin_lat src` → solo la lectura en `attendance.py:180` |

### 0.3 Lo que fija números hoy en los tests (ERR-25) y los tramposos del camino tocado (ERR-26)
| Qué | Dónde |
|---|---|
| 50, 75 y 100 del check-in | `tests/engrama_core/test_attendance.py:243`, `:260`, `:272-276`, `:295-297`, `:319-321`, `:345`, `:349`; `tests/engrama_core/test_bug14_checkin_grupo.py:167-169` |
| La tabla de multiplicadores (10 tests no-integ, contados hoy con `--collect-only`) | `test_attendance.py:33-46` (`TestStreakMultiplier`) |
| `compute_next_streak` (4 tests no-integ) | `test_attendance.py:49-70` |
| T2: parchea `streak_multiplier` y exige rojo en `test_checkin_streak_7_awards_75` | `tests/tramposos/test_tramposos_integ.py:78-84`. **Pierde su blanco** con esta oleada |
| Y7 y Y9: parchean `_buscar_sesion`; Y8 y Y14: envuelven `check_in` con `**resto` | `tests/tramposos/test_tramposos_bug14.py:109-119` |
| Y1, Y4 y T1: reemplazan `award_coins` entero | `test_tramposos_bug13.py:161`, `:176`; `test_tramposos_integ.py:70-73` |
| `alembic_version` | **no se toca**: no hay migración |

## 1. Qué cambia (una cosa)
**Los seis grifos por donde hoy se puede desbordar la economía quedan cerrados con números de configuración: la asistencia paga 5 + 5 sin multiplicadores, una sola vez por estudiante, grupo y día; la racha no se rompe por una segunda sesión; un reto no puede valer más de 20 ni correr a los 10 primeros; la bolsa se puede recargar y avisa antes de agotarse; y todo cálculo de monedas es entero.**

Es una sola intención en **nueve commits**, uno por pieza (§6). Cada pieza sirve sola y deja la suite en verde.

### 1.1 Asistencia: 5 por asistir + 5 por puntualidad, sin multiplicadores
- `monedas = ASISTENCIA_MONEDAS_BASE + (ASISTENCIA_MONEDAS_PUNTUALIDAD si es puntual)`.
- **Puntual** = el check-in ocurre a `ASISTENCIA_MINUTOS_PUNTUALIDAD` minutos o menos de `attendance_sessions.starts_at` (el instante en que el profe abrió la sesión). El límite es **inclusivo**: a los 5:00 exactos es puntual; a los 5:01 no. Un check-in anterior a `starts_at` (relojes) cuenta como puntual.
- La racha **no multiplica nada**. Se borran `ATTENDANCE_COINS_BASE`, `_STREAK_MULTIPLIERS` y `streak_multiplier`.
- La regla vive en una función **pura** de un módulo nuevo, `src/engrama_core/service/economia.py` (recibe los dos instantes y los tres números; no lee la base ni la configuración). `check_in` la llama.
- El asiento del libro lleva en `metadata`: `session_id`, `streak`, `geo_status`, `base`, `puntualidad` (0 o el bono) y `puntual`; desde §1.3, también `dia`. Desaparece `multiplier` (nadie lo lee: `grep` en `src`, `tests` y `engrama-web@cba7150:src` → 0).
- `CheckInResult` **no cambia de forma**: los mismos cuatro campos. `message` conserva su formato (`Check-in exitoso! +N coins`).
- Para poder probar la hora, `attendance.py` gana la costura `_ahora()` (como `foco/service.py:29` y `refuerzo/service.py:32`); `create_session` y `check_in` la usan.

### 1.2 El día es el de la institución, y la racha no se reinicia el mismo día
- "Hoy" = `foco.fechas.hoy(_ahora(), settings.engrama_utc_offset_hours)` (ya existe; `src/foco/fechas.py:15-17`). Se usa para `attendance.attendance_date`, para `profiles.last_attendance_date` y para la racha.
- `compute_next_streak` conserva su firma y sus cuatro casos de hoy (sus 4 tests no se tocan) y gana **un** resultado: si `last_attendance_date >= today` devuelve **0 = "sin cambio"** (antes: 1). `check_in` deja la racha, la más larga y la fecha como estaban.
- No cambia nada más de la racha: sigue siendo por días de calendario seguidos y global por perfil. Eso es la oleada 3.

### 1.3 Un solo pago de asistencia por estudiante, grupo y día
- La paga lleva la llave `attendance:<group_id>:<student_id>:<AAAA-MM-DD>` (el día de §1.2). La garantía es el UNIQUE `(tenant_id, idempotency_key)` de la 033, el mismo mecanismo de BUG-13: dos check-ins simultáneos a dos sesiones no pueden cobrar dos veces.
- **Una segunda sesión el mismo día: la asistencia se registra** (fila en `attendance` con `coins_awarded = 0`) y la respuesta es **200** con `coins_awarded: 0` y la racha sin cambio. No es un error: el estudiante sí asistió.
- Manda **la primera** del día: si la primera fue tarde (5) y la segunda puntual, no hay +5.
- El 409 de "misma sesión dos veces" queda igual (`attendance.py:295-303`).
- Si el monto es 0 (configuración en 0) no se llama a `award_coins`.

### 1.4 Tope de `coins_reward`: 20
- **Al crear** (`POST /challenges/`): `coins_reward > RETO_MONEDAS_TOPE` → **422** con el campo `coins_reward`, y el reto no se crea. El defecto sigue en 10 (`schemas.py:86`).
- **Al pagar y al mostrar**, una sola función pura, `economia.recompensa_del_reto(coins_reward, tope) = min(coins_reward, tope)`: es lo que se paga en `submit_attempt` y lo que sale en `ChallengeOut.coins_reward`. Así un reto guardado por encima del tope (sembrado antes, o insertado a mano) **muestra y paga lo mismo**. La columna no se reescribe.
- Sin CHECK en la base: el tope es configurable y puede haber filas viejas por encima.

### 1.5 `max_winners` por defecto = tamaño del grupo
- `ChallengeCreate.max_winners` pasa a `int | None = None` (`ge=1` si viene). Un valor explícito se respeta tal cual.
- Si no viene: `max(estudiantes activos, RETO_GANADORES_PISO)`, donde "estudiantes activos" es `teachers.service.panel.student_count` del grupo del reto (`panel.py:26-36`), o los estudiantes activos de la institución si el reto es global.
- **El piso es un añadido del Creador al alcance del arquitecto** (se veta poniéndolo en 1). Motivo: un grupo se siembra a veces **vacío** (con el autorregistro los estudiantes entran después) y el tamaño daría 0 o 1: la carrera volvería, con un solo ganador. Con piso 40 no hay carrera en ningún grupo de hasta 40.
- La columna sigue `INTEGER NOT NULL`: el número se resuelve al crear y **no crece** si el grupo crece después (límite declarado, P6).

### 1.6 Recarga de la bolsa por el operador
```
python -m src.onboarding recargar --slug <slug> --monedas <n> \
    --operador "<quién>" --motivo "<por qué>" --referencia <id único>
→ stdout {"institucion": "uis", "recargado": 50000, "saldo": 244858, "emitido": 250000, "repetida": false}
```
- Solo toca la base (entra a `SOLO_BASE`: sin GoTrue, sin `--salida`). Credenciales por `DATABASE_URL`, como las demás.
- **Todo o nada, en una transacción:** candado sobre la billetera de la institución; una fila en `coin_ledger` (`from_wallet_id` NULL = emisión, `to_wallet_id` = la billetera de la institución, `action = 'pool_topup'`, `idempotency_key = 'topup:<referencia>'`, `metadata = {operador, motivo, saldo_antes, saldo_despues}`); `balance += n`; `tenants.coin_pool += n`.
- **Quién y cuándo:** `metadata.operador` (texto obligatorio; el operador no es un perfil) y `created_at`.
- `tenants.coin_pool` pasa a significar **lo emitido en total** (lo inicial más las recargas). Deja de estar congelado.
- **Idempotente por referencia:** la misma referencia con el mismo monto → salida 0, `repetida: true`, nada cambia. La misma referencia con **otro** monto → salida 1, nada cambia.
- Salida 2 sin tocar la base: falta un argumento, `--monedas` ≤ 0 o mayor que `BOLSA_RECARGA_MAXIMA`. Salida 1 sin cambios: la institución no existe, o lo emitido pasaría de 2.000.000.000 (la columna es `INTEGER`).
- **No hay ruta HTTP.** Correrla con datos reales es producción: el sí de Christiam.

### 1.7 Alerta de bolsa baja
- `umbral = economia.redondear_monedas(emitido × BOLSA_UMBRAL_ALERTA_PCT, 100)`. **En alerta** = `saldo < umbral`. Con `emitido = 0` o el porcentaje en 0 no hay alerta.
- **Aviso activo:** cuando una paga hace que el saldo **cruce** el umbral (`saldo_antes >= umbral > saldo_despues`), `award_coins` escribe **una** línea `WARNING` en el logger `engrama.economia`: `bolsa_baja institucion=<id> saldo=<n> umbral=<n> emitido=<n>`. Sin datos de personas. Una por cruce, no una por paga.
- **Estado a pedido:** `python -m src.onboarding bolsa --slug <slug>` → `{"institucion", "saldo", "emitido", "umbral", "porcentaje", "en_alerta"}`; salida **0** si está bien, **3** si está en alerta (sirve para una tarea programada).
- **La alerta nunca bloquea una paga.** El 402 sigue siendo solo por fondos insuficientes.
- Costo: una lectura por clave primaria de `tenants` por paga.

### 1.8 Una sola función entera de redondeo
- `economia.redondear_monedas(numerador: int, denominador: int) -> int`: el entero más cercano a la fracción, **la mitad hacia arriba** (2,5 → 3; 0,5 → 1), solo con aritmética entera. Exige `numerador >= 0` y `denominador > 0`.
- Es la única forma permitida de pasar de una fracción a monedas. En esta oleada la usa el umbral (§1.7); la oleada 1 (tramos, bono) la hereda.
- **Guardia estática**, una función de test que recorre el AST y exige dos cosas:
  1. en los dos módulos que solo calculan monedas (`engrama_core/service/economia.py` y `onboarding/recarga.py`): ninguna llamada a `round`, ninguna constante `float` y ninguna división `/`;
  2. en todo `src/`: ninguna llamada a `round` (hoy hay 0).

  No se puede pedir lo primero a `attendance.py` ni a `attempts.py`: tienen `float` y `/` legítimos que no son monedas (la distancia de la geocerca, `attendance.py:80-88`; el porcentaje del intento, `attempts.py:107`). Por eso la regla de la casa es que **todo monto sale de una función de `economia.py`**.

## 2. Criterios
| # | Criterio | Test |
|---|---|---|
| C1 | **Puro:** la tabla de la asistencia (0 s → 10; 5:00 → 10; 5:01 → 5; antes de abrir → 10; con 4, 3 y 10 min → 7 y 4); la función no recibe la racha; los defectos son 5, 5 y 5 | UE3 (no-integ) |
| C2 | Check-in puntual: 200, `coins_awarded: 10`; una fila en el libro de 10 con `base: 5`, `puntualidad: 5` y `puntual: true`; la bolsa baja 10 | EA1 |
| C3 | En el límite y después: a los 5:00 paga 10; a los 5:01 paga 5 (`puntualidad: 0`) | EA2 |
| C4 | **Son configuración:** con base 4, puntualidad 3 y 10 minutos, paga 7 al minuto 8 y 4 al minuto 11, sin tocar código | EA3 |
| C5 | **Sin multiplicadores:** con racha 6 → 7 y con 13 → 14 se paga lo mismo que con racha 1 | los dos tests editados de `test_attendance.py` (§3.1) |
| C6 | **Puro:** `compute_next_streak` con la misma fecha y con una fecha futura → 0; sus 4 casos de hoy, idénticos | UE4 (no-integ) |
| C7 | Racha 5 con última asistencia ayer: la primera sesión de hoy → 6; **la segunda sesión de hoy → sigue en 6** (respuesta, `current_streak`, `longest_streak` y fecha) | ER1 |
| C8 | **El día es el local:** última asistencia ayer (local) y check-in a las 19:30 de Bogotá (ya es otro día en UTC) → la racha sube 1. Con dos días locales de hueco → 1 | ER2 |
| C9 | Dos sesiones del mismo grupo el mismo día: la segunda responde 200 con `coins_awarded: 0`; hay **2 filas** en `attendance` y **1** asiento de asistencia, con su `dia` en `metadata`; saldo y bolsa no se mueven. Aunque la segunda sea puntual y la primera no. Otro estudiante del grupo cobra lo suyo ese mismo día (control) | ED1 |
| C10 | **El día de la paga es el local:** 18:00 y 19:30 de Bogotá del mismo día → una paga. A las 00:10 del día siguiente → paga de nuevo | ED2 |
| C11 | Dos check-ins **a la vez** a dos sesiones del mismo día → exactamente una paga (técnica de `test_replica_bug13a15.py`) | ED3 |
| C12 | **Puro:** 21 → error de validación en `coins_reward`; 20 y 0 pasan; con el tope en 30, 25 pasa; `recompensa_del_reto(50, 20) = 20`; `max_winners` omitido → `None` | UE6 (no-integ) |
| C13 | `POST /challenges/` con 21 → 422 y 0 filas; con 20 → 201. Un reto **ya guardado** con 50: quien lo gana recibe 20 (respuesta, asiento y saldo) y `GET` lo muestra con 20 | ET1 |
| C14 | Sin `max_winners`: grupo de 12 activos (más 1 inactivo y el docente) → 12 con piso 1 y 40 con piso 40; reto global → los activos de la institución; `max_winners: 3` explícito → 3 | EG1 |
| C15 | **Se acabó la carrera:** 13 estudiantes de un grupo de 13 ganan el mismo reto creado sin `max_winners` → los 13 cobran; ninguno queda sin paga por cupo | EG2 |
| C16 | **Puro (CLI):** sin `--operador`, sin `--motivo` o sin `--referencia`; con `--monedas` 0, negativo o sobre el máximo → salida 2 y la base ni se abre | UE7 (no-integ) |
| C17 | Recarga: salida 0; billetera +n; `coin_pool` +n; **una** fila `pool_topup` con origen NULL, operador, motivo, saldos y fecha; ninguna billetera de estudiante cambia. Repetirla → `repetida: true` y nada cambia. La misma referencia con otro monto → salida 1 y nada cambia. Institución inexistente → salida 1 | EP1 |
| C18 | **Todo o nada:** un fallo provocado después de mover el saldo → saldo, `coin_pool` y libro idénticos a antes | EP2 |
| C19 | **Puro:** umbral = 10 % de lo emitido con el redondeo único; en alerta solo por debajo; el cruce se detecta una vez; emitido 0 o porcentaje 0 → sin alerta | UE5 (no-integ) |
| C20 | Emitido 1.000, saldo 105: una paga de 10 (queda 95) escribe **una** línea `bolsa_baja`; la siguiente paga no escribe otra; la paga ocurre igual (200, no 402) | EB1 |
| C21 | `bolsa --slug`: salida 0 y `en_alerta: false` por encima; salida 3 y `en_alerta: true` por debajo; tras una recarga que supera el umbral, vuelve a 0 | EB2 |
| C22 | **Puro:** `redondear_monedas` 5/2 → 3, 1/2 → 1, 3/2 → 2, 7/2 → 4, 12/5 → 2, 13/5 → 3, 0/7 → 0, 20/1 → 20; denominador 0 o negativo y numerador negativo → error | UE1 (no-integ) |
| C23 | La guardia estática de §1.8 da 0 violaciones sobre el código real, y lista la violación cuando se le da un texto con `round(`, con un `float` o con `/` | UE2 (no-integ) |
| C24 | El humo escribe su archivo con los números de §3.4, **predichos aquí** | HE0 |
| C25 | Regresión: lo previo en verde con **solo** las ediciones de §3.1 | la suite |

## 3. Tramposos, humo y réplica

### 3.1 Ediciones a lo existente (declaradas; nada más cambia)
- `tests/engrama_core/test_attendance.py`: se borra `TestStreakMultiplier` (`:33-46`, **10 tests**) y su import (`:23`); `_hoy_utc` pasa a ser el día local (`:158-160`, `:270`, `:282`, `:306`); 50 → **5** en `:243`, `:260`, `:272`, `:276`, `:345` y `:349`; 950 → **995** en `:273`; `test_checkin_streak_7_awards_75` y `test_checkin_streak_14_awards_100` pasan a llamarse `..._paga_lo_mismo` y esperan **5** y bolsa **995** (la racha 7 y 14 se sigue afirmando).
- `tests/engrama_core/test_bug14_checkin_grupo.py:167-169`: `(50, 1)` → `(5, 1)`, saldo 5 y `POOL - 5`; los docstrings de `:14` y `:151`.
- `tests/tramposos/test_tramposos_integ.py`: se borra **T2** (`:78-84` y la línea `:10`). **Lo releva ZT1** (ERR-26).
- `tests/integ_ayudante.py:220-249`: `crear_sesion_asistencia` gana `inicio` opcional; sin él, `ahora − 1 h` como hoy.
- `src/`: `engrama_core/service/attendance.py`, `coins.py` (solo el aviso de §1.7, después de mover los saldos), `challenge_engine/schemas.py`, `service/challenges.py` (crear e `hydrate`), `service/attempts.py` (la línea de la paga), `shared/config.py`, `onboarding/__main__.py`; nuevos: `engrama_core/service/economia.py` y `onboarding/recarga.py`.
- `SPECS/02-engrama-core.md` §7: una línea que remite a esta espec (el documento dice 50; constitución §1).
- `.gitignore`: `tests/_salida/humo_economia_oleada0.json`.
- `attendance.py` **no puede quedar con más de sus 434 líneas de hoy**; las reglas nuevas viven en `economia.py`.

### 3.2 Diagonal PREDICHA (el código no existe; ERR-23)
No-integ, cada uno contra su test puro:

| Id | Rompe | Rojo predicho |
|---|---|---|
| ZE1 | El redondeo usa `round(n / d)` | **UE1** (as: 5/2 da 2) |
| ZE2 | La guardia no mira las constantes `float` (se le da `economia.py` con `BASE * 1.5`) | **UE2** (as: 0 violaciones donde debe haber una) |
| ZE3 | La puntualidad se paga siempre | **UE3** (as: 5:01 da 10) |
| ZE4 | La misma fecha devuelve 1 | **UE4** (as) |
| ZE5 | La bolsa nunca está en alerta | **UE5** (as) |
| ZE6 | El tope no se valida ni se aplica | **UE6** (as: 21 pasa) |
| ZE7 | `recargar` acepta sin `--operador` | **UE7** (as: salida distinta de 2) |

Integ:

| Id | Rompe | Rojo predicho | Verde predicho y por qué |
|---|---|---|---|
| ZT1 | Vuelve el multiplicador de racha (×1,5 y ×2) | los dos tests `..._paga_lo_mismo` (as: 7 en vez de 5) | EA1-EA3 y HE0: su racha no llega a 7 |
| ZT2 | La base es 50 fija en el código | **EA1** (as), EA2, EA3, ED1, HE0 | — |
| ZT3 | La puntualidad nunca se paga | **EA1** (as: 5), EA2, EA3, HE0 | ED1: su primera sesión es tarde |
| ZT4 | El día es el UTC | **ER2** (as: racha 1), ED2, HE0 | ER1 y ED1: sus dos sesiones caen en el mismo día UTC |
| ZT5 | La paga de asistencia va sin llave | **ED1** (as: 2 asientos), ED2, ED3, HE0 | — |
| ZT6 | La llave no lleva el día | **ED2** (as: el día siguiente no paga), HE0 | ED1 |
| ZT7 | La llave no lleva al estudiante | **ED1** (as: el segundo estudiante no cobra), HE0 | — |
| ZT8 | La segunda sesión del día reinicia la racha a 1 | **ER1** (as: 1 en vez de 6), HE0 | ED1: no mira la racha |
| ZT9 | La segunda sesión del día suma racha | **ER1** (as: 7), HE0 | — |
| ZT10 | La segunda sesión del día responde 409 y no registra | **ED1** (as: 1 fila en `attendance`), HE0 | — |
| ZT11 | Al pagar no se aplica el tope | **ET1** (as: recibe 50) | HE0: sus retos valen 10 |
| ZT12 | Al crear no se valida el tope | **ET1** (as: 201 con 21) | — |
| ZT13 | `max_winners` omitido = 10 | **EG1** (as), EG2, HE0 (as: 14 aciertos sin paga por semana) | ET1 |
| ZT14 | La recarga ignora la referencia | **EP1** (as: la segunda suma otra vez) | — |
| ZT15 | La recarga no deja fila en el libro | **EP1** (as) | EB2 |
| ZT16 | La recarga hace commit a mitad | **EP2** (as: el saldo quedó movido) | EP1 |
| ZT17 | La recarga no actualiza `coin_pool` | **EP1** (as), EB2 | — |
| ZT18 | El cruce del umbral no avisa | **EB1** (as: 0 líneas) | EB2: lee el estado, no el log |
| ZT19 | Por debajo del umbral la paga da 402 | **EB1** (as) | HE0: su bolsa no baja del umbral |

**Tramposos existentes (ERR-26), predicción:** Y7 y Y9 siguen rojos: `_buscar_sesion` no se toca. Y8 y Y14 siguen rojos: `check_in` conserva su nombre y sus parámetros por palabra clave. Y1, Y4 y T1 siguen rojos: reemplazan `award_coins` entero y el aviso va después de mover los saldos. **T2 se borra** y lo releva ZT1.

**Matriz a medir:** 19 tramposos integ × 16 columnas (EA1-EA3, ED1-ED3, ER1, ER2, ET1, EG1, EG2, EP1, EP2, EB1, EB2 y HE0) = **304 celdas**, más RE0 con la bandera. Una corrida por tramposo, sobre un export limpio del commit, como en `ESPEC_refuerzo.md` §12.

### 3.3 Qué pasa con los saldos y las pagas que ya existen
**Nada se recalcula hacia atrás.** Ni un saldo, ni un asiento, ni una racha.
- El libro es de doble partida y solo agrega: corregir el pasado sería reescribir asientos o restar monedas ya vistas y quizá ya planeadas. Eso es un castigo retroactivo, y la casa no tiene castigos.
- Las reglas nuevas rigen **desde el despliegue**. Efectos de transición, una sola vez por estudiante, que se aceptan:
  1. Las asistencias viejas no tienen llave: quien ya marcó **el mismo día del despliegue** con el código viejo puede cobrar otra vez ese día. Mitigación: desplegar fuera del horario de clase.
  2. `last_attendance_date` vieja está en día UTC: el primer check-in posterior puede contar la racha con un día de desfase (sube cuando no debía, o no sube). No se corrige.
  3. Un reto ya creado por encima de 20 **paga y muestra 20** desde el despliegue; lo ya pagado se queda.
  4. Un reto ya creado con `max_winners = 10` **sigue con 10**. Subirlo es un `UPDATE` sobre datos reales: producción, con el sí de Christiam.
- Antes de desplegar, el operador mide (solo lectura): `SELECT count(*) FROM challenges WHERE coins_reward > 20;` y `SELECT count(*) FROM challenges WHERE status = 'active' AND max_winners <= 10;`.
- `tenants.coin_pool` de una institución existente ya es lo emitido al nacer: sirve tal cual para el umbral.

### 3.4 Humo HE0 (escribe `tests/_salida/humo_economia_oleada0.json` antes de afirmar)
Datos sintéticos, `random.Random(42)`, contra el código real (rutas HTTP y la CLI), con el reloj fijado por `_ahora()`.

**Escenario.** Una institución con bolsa de **200.000** y un grupo de **30**: 6 muy activos, 18 típicos y 6 que solo asisten (la mezcla 20/60/20 del informe §5.4). **4 semanas**, clase martes y jueves a las 18:00 de Bogotá. En la semana 2 hay además clase el **miércoles a las 19:30** (tres días seguidos) y el jueves el profe abre una **segunda sesión a las 19:30** (ya es viernes en UTC): **9 días de clase, 10 sesiones**. 3 retos por semana (**12**), de 5 preguntas de opción múltiple, creados **sin** `coins_reward` ni `max_winners`. Una sesión de EVA por semana, por la puerta de eventos.

| Perfil | Asistencia | Retos | EVA por sesión |
|---|---|---|---|
| Muy activo | a las 10 sesiones, siempre puntual | los 12, perfectos al primer intento | 12 + 8 + 4 (el tercero choca con el tope) |
| Típico | a las 10; puntual martes y miércoles, tarde los jueves | por semana: el reto 1 perfecto; el reto 2 con 4 de 5 en sus dos intentos; el reto 3 no lo abre | 12 |
| Solo asiste | a las 10, siempre tarde | ninguno | 12 |

A la segunda sesión del jueves todos llegan **puntuales**. La semilla decide quién es de cada perfil, el minuto exacto de llegada dentro de su franja, qué pregunta falla el típico y **el orden** en que se envían los retos. **Ninguno de los totales depende de la semilla**: esa es la afirmación (la moneda no premia el orden de llegada ni el azar).

**Predicción (fijada aquí, antes del código):**
```json
{"alembic_version":"041_refuerzo","semilla":42,"estudiantes":30,"semanas":4,"dias_de_clase":9,"sesiones":10,"retos":12,
 "perfiles":{"muy_activo":{"n":6,"asistencia":90,"retos":120,"eva":80,"total":290},
             "tipico":{"n":18,"asistencia":70,"retos":40,"eva":48,"total":158},
             "solo_asiste":{"n":6,"asistencia":45,"retos":0,"eva":48,"total":93}},
 "emision":{"asistencia":2070,"retos":1440,"eva":1632,"total":5142},
 "bolsa":{"emitido":200000,"saldo":194858,"umbral":20000,"en_alerta":false},
 "asistencias_registradas":300,"pagos_de_asistencia":270,"asistencias_sin_paga":30,
 "max_pagos_de_asistencia_por_estudiante_y_dia":1,"mayor_pago_de_asistencia":10,
 "pagos_de_reto":144,"mayor_pago_de_reto":10,"ganadores_del_reto_mas_ganado":24,"aciertos_sin_paga_por_cupo":0,
 "racha_tras_la_segunda_sesion":{"3":30},"racha_mas_larga":3,
 "eva_no_acreditadas_por_tope":24,"descuadre":0}
```
Las cuentas: asistencia 9 días × 10 = 90; (5 × 10) + (4 × 5) = 70; 9 × 5 = 45. Retos 12 × 10 = 120; 4 × 10 = 40. EVA 4 × 20 = 80 y 4 × 12 = 48. Emisión 6 × 290 + 18 × 158 + 6 × 93 = **5.142**. Pagos de reto (4 × 24) + (8 × 6) = 144. `descuadre` = emitido − saldo de la bolsa − suma de saldos de los 30.

Por semana: muy activo **72,5**; típico **39,5**; solo asiste **23,25** (11,25 sin EVA). Promedio del grupo: 42,85 por estudiante y semana; a ese ritmo 200.000 duran unas 155 semanas con 30 estudiantes y unas 15,5 con 300.

**Lo que el humo deja a la vista y NO es criterio de esta oleada:** con el reto todavía en todo o nada, la clase (asistencia + EVA) es el **75 %** de lo que gana el típico (118 de 158) y el 59 % del muy activo; la meta del dictamen C.2 es 50 % o menos. Lo corrige la oleada 1 (tramos), no esta.

**Contraste calculado, no medido:** el mismo calendario con el código de `5aad55e` paga 50 por sesión: 30 × 10 × 50 = **15.000** de asistencia, contra 2.070.

### 3.5 Réplica RE0 (`ENGRAMA_REPLICA_ECONOMIA=1`)
Entradas que no se usaron al desarrollar: semilla **7**; grupo de **45** (9/27/9); **3 semanas**, clase lunes, miércoles y viernes, con una doble sesión; configuración **cambiada** (base 4, puntualidad 3, 10 minutos, tope de reto 15, piso de ganadores 1, umbral 25 %); retos con `coins_reward: 15` explícito y uno insertado a mano con 50; bolsa de **3.000** para que el aviso salte, una recarga a mitad y el aviso otra vez; y un estudiante inscrito en **dos instituciones** que marca en las dos el mismo día (cobra en cada una). Los esperados los calcula el test con su propia aritmética, sin importar `economia.py`.

## 4. Cuentas (ERR-10)
Base: 572 passed, 22 skipped, 139 no-integ. Una función de test por id; cada tramposo, un id.

| Commit | Sale | Entra (no-integ) | Entra (integ) | passed | no-integ |
|---|---|---|---|---|---|
| E1 asistencia 5 + 5 | 10 no-integ y T2 | UE3, ZE3 | EA1-EA3, ZT1-ZT3 | 569 | 131 |
| E2 día local y racha | — | UE4, ZE4 | ER1, ER2, ZT4, ZT8, ZT9 | 576 | 133 |
| E3 un pago por día | — | — | ED1-ED3, ZT5-ZT7, ZT10 | 583 | 133 |
| E4 tope del reto | — | UE6, ZE6 | ET1, ZT11, ZT12 | 588 | 135 |
| E5 ganadores | — | — | EG1, EG2, ZT13 | 591 | 135 |
| E6 redondeo único | — | UE1, UE2, ZE1, ZE2 | — | 595 | 139 |
| E7 recarga | — | UE7, ZE7 | EP1, EP2, ZT14-ZT17 | 603 | 141 |
| E8 alerta | — | UE5, ZE5 | EB1, EB2, ZT18, ZT19 | 609 | 143 |
| E9 humo y réplica | — | — | HE0 (y RE0 saltado) | **610** | **143** |

**Final: 610 passed + 23 skipped; 143 no-integ; ruff 0 y mypy 0.** Nuevos: 14 no-integ y 35 integ; salen 11.

## 5. Variables nuevas (ninguna es secreto; todas PROVISIONALES)
| Variable | Por defecto | Rango | Quién la fija |
|---|---|---|---|
| `ASISTENCIA_MONEDAS_BASE` | 5 | 0 a 50 | Christiam |
| `ASISTENCIA_MONEDAS_PUNTUALIDAD` | 5 | 0 a 50 | Christiam |
| `ASISTENCIA_MINUTOS_PUNTUALIDAD` | 5 | 0 a 60 | Christiam |
| `RETO_MONEDAS_TOPE` | 20 | 1 a 1.000 | Christiam |
| `RETO_GANADORES_PISO` | 40 | 1 a 10.000 | Christiam (añadido del Creador) |
| `BOLSA_UMBRAL_ALERTA_PCT` | 10 | 0 a 100 (0 = apagada) | Christiam |
| `BOLSA_RECARGA_MAXIMA` | 1.000.000 | 1 a 100.000.000 | Christiam |
| `ENGRAMA_UTC_OFFSET_HOURS` | −5 | ya existe (`config.py:76`) | — |

Lo que **no** se vuelve variable aquí: el valor del reto (10, ya es el defecto de `schemas.py:86` y lo manda quien siembra); el tope de EVA (20, constante con nombre en `webhooks/efectos.py:27`; moverla a configuración es de otra espec); y el pool (200.000): `alta --monedas` **no tiene defecto a propósito** (`__main__.py:63-65`), el número va en la orden del operador.

## 6. Plan de encargos para el implementador (un cambio por commit)
Cada encargo: rama actual, un commit, sus tests y sus tramposos en rojo, la suite completa con las cuentas de §4, ruff 0 y mypy 0, y nada fuera de los archivos de §3.1. Sin instalar nada en el `.venv` (ERR-11) y sin tocar otro contenedor que `engrama-test-pg` (ERR-21). El coordinador commitea.

| # | Commit | Qué hace | Depende de |
|---|---|---|---|
| E0 | `docs: ESPEC_economia_oleada0` | esta espec, antes de todo código | — |
| E1 | `feat(economia): la asistencia paga 5 + 5 por puntualidad, sin multiplicadores de racha` | §1.1; `economia.py` nace con la función de la asistencia; tres variables; ediciones de §3.1 a los tests de 50, 75 y 100; T2 → ZT1 | E0 |
| E2 | `fix(asistencia): el día es el de la institución y una segunda sesión no reinicia la racha` | §1.2 | E1 |
| E3 | `feat(asistencia): un solo pago por estudiante, grupo y día` | §1.3 | E2 |
| E4 | `feat(retos): tope de coins_reward (422 al crear; se paga y se muestra el mínimo)` | §1.4 | E0 |
| E5 | `feat(retos): max_winners por defecto = tamaño del grupo, con piso` | §1.5 | E0 |
| E6 | `feat(economia): una sola función entera de redondeo y la guardia estática` | §1.8. Va después de E1 y E4, que son los que crean y llenan `economia.py` | E1, E4 |
| E7 | `feat(onboarding): recargar la bolsa de la institución (todo o nada, idempotente, con quién y cuándo)` | §1.6 | E0 |
| E8 | `feat(economia): alerta de bolsa baja (aviso al cruzar el umbral y la orden bolsa)` | §1.7 | E6, E7 |
| E9 | `test(economia): humo de 4 semanas con 30 estudiantes y réplica` | §3.4 y §3.5; después, la matriz de 304 celdas medida y anotada en esta espec (una sección nueva, §13 "Medido") | E1-E8 |

E1-E3 son rutinarios una vez leída esta espec (Implementador). E7 y E8 tocan el libro y `award_coins`: Creador, o Implementador con auditoría antes del commit. Después de E9: Auditor (LISTO / NO LISTO) y Probador con la suite completa y la réplica.

## 7. Compatibilidad con engrama-web (`cba7150`, leído con `git show`, sin tocarlo)
**La web real no se rompe.** No fija ningún número del check-in: pinta lo que llega.
- `src/vistas/estudiante/asistencia.js:73` arma "Asistencia marcada · +N monedas · constancia R" con `coins_awarded` y `streak`; `:76` los pasa al sello. `:21-26` traduce 404, 409 y 410. `message` no se lee en ninguna parte de `src/`.
- `src/ui/sello.js:20-22`: con `monedas: 0` no hay ficha, ni vuelo, ni confeti (ya tiene su tramposo, `x_asistencia_sin_sello_si_0`). `:59-64` celebra la constancia **solo si sube** (`ui/ultimo_visto.js`): con la racha igual no celebra, que es lo correcto.
- `CheckInResult`, `ChallengeOut` y los códigos HTTP no cambian de forma.

**Lo que se verá distinto y conviene que la web atienda después (no bloquea):**
1. En la segunda sesión del día el texto dirá "Asistencia marcada · +0 monedas · constancia R". Es verdad, pero no explica. Texto propuesto: "Asistencia marcada. La de hoy ya la cobraste."
2. El "+5 por puntualidad" no se distingue en pantalla: el desglose es de la oleada 1.
3. El contrato guardado (`contratos/openapi_c7a8b89.json`) es anterior: `ChallengeCreate.max_winners` pasa a aceptar `null` y su defecto deja de ser 10.

**El mock y el sembrador quedan desalineados (los cambia el chat de la web, con esta lista):**
| Archivo en `engrama-web` | Hoy | Debe quedar |
|---|---|---|
| `herramientas/mock/rutas_core.mjs:10`, `:22-26`, `:58` | base 50, ×1,5 y ×2, `Math.round` | 5 + 5 por puntualidad, sin multiplicador, sin redondeo |
| `herramientas/mock/rutas_core.mjs:28-32` | la misma fecha reinicia la racha a 1 | la misma fecha no la cambia |
| `herramientas/mock/rutas_core.mjs:48-49`, `:52`, `:65` | día UTC; sin tope por día | día local; la segunda sesión del día paga 0 con la llave de `mock/monedas.mjs:19-23` |
| `herramientas/mock/rutas_challenges.mjs:128-129` | `coins_reward ?? 5`, `max_winners ?? 10` | `?? 10`; el tamaño del grupo con piso; 422 sobre el tope |
| `herramientas/mock/estado.mjs:51`, `:69` | bolsa de 1.000.000 | 200.000 |
| `herramientas/sembrar/mapeo.mjs:11` | `COINS_REWARD = 5` | **10** (decisión del 2026-10-07) |
| `herramientas/demo.mjs:33`, `fluidez.mjs:76`, `galeria_juego.mjs:29`, `largos_fin_reto.mjs:19` | `coins_reward` 30 y 40 | contra el backend real darán **422**; bajarlos a 20 o menos |

`sembrar_retos.mjs:56-62` ya manda `max_winners = student_count`: no cambia. Ojo: si siembra un grupo todavía vacío mandará 0 y recibirá 422 (`ge=1`); es mejor que **omita** el campo y deje que el servidor aplique el piso.

## 8. Qué NO se toca
`grade_answers`, `is_attempt_correct` y la paga todo o nada; la llave de BUG-13; `_buscar_sesion` y el 404 de BUG-14; `filtro_grupo_estudiante`; el tope y los efectos de EVA (`webhooks/efectos.py`); el refuerzo, el foco, el Grader y el nivel confirmado; `alta` (sigue sin recargar nunca); la forma de `CheckInResult` y de `ChallengeOut`; la semántica de la racha fuera del caso "mismo día"; `alembic/`; engrama-web.

## 9. Riesgo para producción
- No hay migración. El despliegue es solo código y variables; aun así, con datos reales necesita el sí de Christiam.
- Desde E1 un estudiante gana por asistir entre 5 y 10 donde ayer ganaba 50: **lo va a notar**. Conviene decirlo en clase antes (P1).
- Desplegar fuera del horario de clase (§3.3, efecto 1).
- `award_coins` hace una lectura más por paga (§1.7).
- `recargar` contra una base real es emisión de monedas: el sí de Christiam cada vez.

## 10. Oleadas siguientes (anotadas; aquí no se especifican)
- **Oleada 1:** pago por tramos con mínimo 60 % y bono de racha; desglose en pantalla; textos de bolsa agotada. Candidato a sumarse: que la asistencia se registre aunque la bolsa esté agotada (H1).
- **Oleada 2:** L1 (corrección y explicación por pregunta) y la pista.
- **Oleada 3:** racha por sesiones del grupo, con descansos y falta excusada.
- **Después:** la tienda; dar monedas el profe; lo colectivo; las insignias; `challenges.solo_refuerzo`.
- Vistos y fuera de alcance: una ruta para que el admin vea la bolsa; que el cupo crezca con el grupo; el tope de EVA como variable; la geocerca sin coordenadas (H6); bajar `attendance.py` a 400 líneas (H2).

## 11. Preguntas para Christiam (cada una con su provisional; ninguna bloquea)
| # | Pregunta | Provisional |
|---|---|---|
| P1 | ¿Asistencia 5 + 5, con 5 minutos de puntualidad? | Sí: 5, 5 y 5 |
| P2 | ¿La puntualidad se cuenta desde que **el profe abre la sesión**? (No hay horario de clase en la base: si el profe abre tarde, todos son puntuales) | Sí |
| P3 | Segunda sesión el mismo día: ¿se registra la asistencia con 0 monedas, o se rechaza? | Se registra, con 0 y la racha igual |
| P4 | Si la primera del día fue tarde y la segunda puntual, ¿hay +5? | No: manda la primera |
| P5 | ¿Tope de 20 por reto? Y un reto ya creado por encima, ¿paga y muestra 20? | Sí a las dos |
| P6 | ¿Piso de 40 ganadores cuando no se indica cupo? ¿Y debe crecer el cupo si el grupo crece después? | Piso 40; no crece (para después) |
| P7 | La recarga: ¿quién la autoriza, hay máximo por recarga, y el pool de 200.000 es por semestre? | Usted, cada vez; máximo 1.000.000; sin periodo |
| P8 | La alerta al 10 %: ¿quién la recibe y cómo? (El dictamen C.3 propone otro umbral: 20 × el grupo más grande) | El operador, por el log y la orden `bolsa`; sin pantalla |
| P9 | Con la bolsa agotada hoy el check-in falla y **no queda la asistencia**. ¿Debe quedar, sin monedas? | No se toca en esta oleada; propuesto para la 1 |
| P10 | ¿El día cambia a la medianoche de Colombia? | Sí (`ENGRAMA_UTC_OFFSET_HOURS = -5`) |
| P11 | Los retos ya sembrados con cupo 10, ¿se suben a mano? | No se tocan |
| P12 | ¿Hay hoy una base con estudiantes reales corriendo este backend? De eso depende que §3.3 importe | Se supone que sí y se despliega con cuidado |

## 12. Veredicto
- **FUNCIONA:** las cuentas de §4; la matriz de 304 celdas medida con cada tramposo rojo por aserción en su diagonal; HE0 escrito e **igual a la predicción de §3.4**; RE0 verde; los tramposos existentes rojos por su razón; lo previo verde con solo las ediciones de §3.1.
- **HAY ALGO MODESTO:** todo lo anterior, pero un número sigue sin el sí de Christiam, o no se probó contra engrama-web con el mock actualizado.
- **NO:** un estudiante cobra dos asistencias el mismo día; una segunda sesión cambia la racha; vuelve un multiplicador; un reto paga más que el tope; un acierto queda sin paga por cupo en un reto sin cupo indicado; una recarga se duplica o queda a medias; un saldo o un asiento anterior cambia; HE0 no coincide con §3.4; un tramposo queda verde.

Si un número de §3.4 no sale, **no se ajusta la predicción**: se registra como ERR con su causa y se escribe el criterio nuevo antes de volver a correr (METODO, regla 8).
