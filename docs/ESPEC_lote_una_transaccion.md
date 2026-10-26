# ESPEC · Un lote de eventos, una sola transacción (`POST /events/batch`)

Creador · sobre `f7f7aeb` (rama `perf/lote-una-transaccion`). Sin migración. Contrato HTTP sin cambios.

## 0. Por qué
En el servidor de la casa (disco mecánico TOSHIBA MQ04ABF1, Postgres 17.6 con `synchronous_commit=on` y `fsync=on`), el humo del anillo dio AN8 FALLA el 2026-10-21:
- una clase de EVA de **68 eventos** tardó **10,65 s** en entrar (`received_at` de 03:31:24.37 a 03:31:35.02), unos **157 ms por evento**; la segunda clase tardó **12,14 s** (179 ms por evento);
- en el piloto de Windows (SSD), las mismas 68 filas entran en **0,77 a 0,90 s** (11 a 13 ms por evento).

La causa es `src/webhooks/service.py:179`: **un `COMMIT` por evento aceptado**, y cada commit espera un `fdatasync` del WAL. En un disco mecánico eso son unos 150 ms por evento. El cliente de EVA corta a los **5 s** (`EVAGAME/servidor/devolucion.py:63`, timeout de socket): el lote se reintenta mientras el primero sigue corriendo, y EVA solo cuenta lo que aceptó la respuesta que sí recibió. El dinero cuadra (UNIQUE + `ON CONFLICT DO NOTHING`), pero el profe ve un conteo falso, y un lote de 200 (`TOPE_LOTE`) tardaría unos 30 s.

ESPEC_eventos_anillo §4 ya lo dejaba como "no medido: un lote de 200 hace 200 transacciones".

## 1. Qué cambia (UNA cosa)
`procesar_lote` abre **una sola transacción** para el lote y hace **un solo `COMMIT` al final**. `procesar_evento` ya no hace `commit` ni `rollback`:
- **aceptado:** guarda la fila y aplica el efecto; luego `flush()` y `expire_all()` (la billetera se relee de la base, dentro de la misma transacción, como antes);
- **rechazado:** no escribió nada (los rechazos salen de lecturas), así que **no se deshace nada**: ni el evento ni sus vecinos;
- **excepción inesperada:** se propaga, `get_db` hace rollback de **todo el lote** y el satélite recibe un 500 y reintenta (es idempotente). Antes quedaban guardados los eventos anteriores al que falló; el satélite tampoco avanzaba su cursor, así que reintentaba igual.

El SAVEPOINT de `_pagar` (bolsa agotada → 402 → se deshace solo la paga) no cambia.

## 2. Qué debe pasar (medible)
| # | Criterio | Medida |
|---|---|---|
| LT1 | Un lote de **38 eventos** válidos (5 tipos, 4 estudiantes) hace **1 `COMMIT`** en la base | eventos `commit` del `Engine` de SQLAlchemy durante el POST = **1** (hoy, 38); y `count(distinct received_at)` de esas filas = **1** (hoy, 38: `now()` es el inicio de la transacción); saldos `[8, 8, 8, 8]` |
| LT2 | Un rechazado **en medio** no deshace a los aceptados de antes ni de después | lote `[monedas est0 (2), respuesta, sujeto ajeno, monedas est1 (3), respuesta]` → `(200, 4, 0, [unknown_subject], [])`, 4 filas, saldos `[2, 3]` |
| LT3 (réplica) | Un reenvío **solapado** (lo que pasa tras un timeout del satélite): 30 eventos, luego los 60 que los contienen | segunda respuesta `(200, 30, 30, [], [])`, 60 filas, 1 commit en el segundo POST, monedas pagadas una sola vez |
| humo | Un lote de **200** (el tope) entra con 1 commit | escribe `tests/_salida/humo_lote_una_transaccion.json` con `{eventos: 200, aceptados: 200, commits: 1, instantes_de_recepcion: 1}` y lo relee |

Regresión = identidad: EV1, EV3, EV5, EV6, EV7, EV9, NV1, NV3, NV5, MC1, HE1, UE1 a UE3 y los tramposos ZE1 a ZE20 **pasan sin tocarlos**.

## 3. Cómo sabremos que FALLÓ
- **ZE21 (commit por evento, el código de hoy):** con `_aceptar` seguido de `db.commit()`, LT1 da `'commits': 38` → rojo.
- **ZE22 (rollback del lote al rechazar):** si el rechazo hiciera `db.rollback()` (el `rollback` de hoy en `procesar_evento:174`, que con una transacción por lote se llevaría a los vecinos), LT2 da `'filas': 2` y el saldo de est0 en 0 → rojo.

## 4. Qué NO se toca
El contrato HTTP (`accepted`, `duplicates`, `rejected`, `not_credited`), la firma, los topes, la idempotencia por `(tenant_id, event_id)`, `efectos.py`, los modelos, las migraciones, EVA, SET, `Caddyfile` y `docker-compose.yml` del despliegue (ERR-41). No se despliega.

## 5. Riesgos que se aceptan (no medidos)
- **El candado de la bolsa** (`for_update` en `acreditar_monedas`) y las filas de `streak_state` del lote quedan tomados hasta el commit del lote, no hasta el del evento. Con el lote en una transacción eso dura lo que tarda el lote (se estima 1 a 3 s para 200 en el disco mecánico, sin medir allá).
- **Interbloqueo posible** con una petición que tome la bolsa y luego la racha del mismo estudiante mientras el lote tiene la racha y espera la bolsa: Postgres aborta una de las dos al segundo. Si cae el lote, el satélite recibe 500 y reintenta (idempotente); si cae la otra, ese estudiante ve un error. No se reprodujo.
- **Subtransacciones:** cada `coins.granted` abre el SAVEPOINT de `_pagar`. Con más de 64 en una transacción, Postgres desborda la caché de subtransacciones mientras dura el lote. Es corto y la concurrencia del piloto es baja, así que no se midió.

## 6. Tramposo, humo y réplica
- Tramposos: ZE21 y ZE22 en `tests/tramposos/test_tramposos_eventos.py`, con la misma diagonal que ZE1 a ZE20.
- Humo: HL1 en `tests/webhooks/test_lote_una_transaccion.py`, que escribe `tests/_salida/humo_lote_una_transaccion.json` (ignorado por git, como los demás humos).
- Réplica: LT3, con entradas que no usa ningún otro test: un solape parcial y 6 estudiantes.
