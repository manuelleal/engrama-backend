# ESPEC · Ola 1 de la economía: Dar y Corregir, presupuesto del profe y tienda con mochila (backend)

Creador · 2026-10-21 · preregistro, commiteado ANTES del código. Rama `juego/ola1-economia`, sobre `f7f7aeb` (`test/fixture-integ`). Base medida hoy en este worktree: **208 no-integ en verde, ruff 0**; la última suite completa medida por otros es **768 passed + 24 skipped** (`f7f7aeb`), y la vuelvo a medir en mi contenedor antes de tocar nada (§9).

Origen: `INGLES/investigacion/producto/14-plan-recuperar-el-juego.md` (ola 1, puntos 1, 2 y 3) y su base `investigacion/producto/11-esencia-del-juego.md` (§4 números, §5 O1-1, O1-2 y O1-3). Sin IA. Todos los números son **PROVISIONALES** (decisión 2 de Christiam en el plan 14, sin responder): cada uno es una variable de configuración (§6), no un literal.

**Migración: `047_economia_ola1`, con `down_revision = "045_correccion_por_pregunta"`.** Las ramas `seg/limites-registro` (`046_limite_compartido`) y `seg/pase-acotado` (`046_anillo_pases`) ya usan el 046 y no están integradas: **al integrar, esta migración se renumera y cambia su `down_revision`** (ERR-45). Mientras tanto, en esta rama la cabeza salta de 045 a 047.

## ADENDA 1 · Decisión 017 de Christiam (2026-10-21, tarde): contrato final, subasta y modo rápido

**Esto manda sobre §1-§4 y §10 donde choquen.** Se despliega hoy. Cambia tres cosas, ANTES de tener resultados de la ola (no se mueve un criterio después de verlo):
1. **Las rutas** pasan a este contrato (lo consume la web en paralelo). Los nombres de §1 (`/teachers/...`, `/core/shop`...) quedan reemplazados. Las reglas de negocio de §1 (topes, plazos, permisos, idempotencia, aislamiento) no cambian.
2. **Se agrega la subasta (puja)** con `auctions` y `auction_bids` (§A.5).
3. **Modo rápido de pruebas:** una prueba por regla de plata (topes, saldo nunca negativo, aislamiento por institución, retención de la puja) y tramposos solo para esas; el humo HE1 se mantiene. Los OE y OT de §2-§3 que no son "de plata" quedan para después.

**Migración: sigue siendo la 047** (`down_revision = 045_correccion_por_pregunta`; se renumera al integrar, ERR-45). Suma a §7: el CHECK de `coin_wallets.owner_type` admite también `'auction'` (la retención de una subasta es una billetera de la subasta); `auctions` gana `ends_at`, `extensions` (0), `item_id` (→ `shop_items`) y `created_by`; índice único parcial "una subasta activa por grupo".

### A.1 Convenciones
- Todo con `Authorization: Bearer <jwt>` (y `X-Tenant-ID` opcional, como el resto). JSON plano, campos en español.
- **Errores:** `{"detail": "<mensaje en español>"}` con el código HTTP: 401/403 sin permiso o rol, **404 lo ajeno o inexistente** (no delata si existe en otra institución o grupo), 409 regla del juego (tope, plazo, agotado, subasta cerrada…), 402 sin saldo o sin presupuesto, 422 dato inválido. Los 422 de validación del esquema siguen el formato de la casa (sin eco).
- **Idempotencia:** toda ruta que mueve monedas acepta `"llave"` opcional (8-64 caracteres `[A-Za-z0-9_-]`, una por toque de botón). Con llave, repetir devuelve **200** con lo mismo y no mueve nada (la primera vez, 201). Sin llave, cada llamada es nueva. La web DEBE mandarla en dar, corregir, comprar, recargar y pujar.
- Fechas en ISO 8601 UTC. Montos enteros.
- Estados de la mochila: `por_entregar`, `entregado`, `devuelto` (no entregado en 14 días: se le devolvió lo pagado).

### A.2 Tienda y mochila
| Ruta | Quién | Cuerpo | Respuesta |
|---|---|---|---|
| `GET /economia/tienda` | todos | — | `[Objeto]`. El estudiante ve solo los activos; profe y admin ven todo el catálogo de su institución |
| `POST /economia/tienda` | profe, admin | `{nombre (3-60), descripcion? (≤200), tipo: "privilegio"\|"fisico", precio: 40\|120\|300\|600, existencias (0-1000), activo? (true)}` | 201 `Objeto`. 422 si el precio no es escalón, el tipo no es de la lista o el texto nombra nota/examen/puntos/nivel/XP… |
| `PATCH /economia/tienda/{id}` | admin (todo) o el profe que lo creó | los mismos campos, opcionales | 200 `Objeto` (extra del contrato: pausar o reponer) |
| `POST /economia/tienda/{id}/comprar` | estudiante | `{llave?}` | 201 `ItemMochila`. 402 sin saldo, 409 agotado o inactivo, 404 de otra institución, 403 si no es estudiante |
| `GET /economia/mochila` | estudiante | — | `[ItemMochila]` (antes devuelve lo vencido) |
| `GET /economia/grupo/{gid}/mochila` | profe del grupo, admin | — | `[ItemMochila]` de los estudiantes del grupo, todos los estados (antes devuelve lo vencido) |
| `POST /economia/mochila/{id}/entregar` | admin, quien creó el objeto o profe de un grupo del estudiante | — | 200 `ItemMochila` (`entregado`; repetir = 200). **409** si ya venció: se devolvió y el `detail` lo dice |

`Objeto = {id, nombre, descripcion, tipo, precio, existencias, activo, creado_por}` (`existencias` null = ilimitado, solo en objetos de antes).
`ItemMochila = {id, objeto_id, nombre, tipo, origen: "tienda"|"subasta", precio_pagado, estado, comprado_en, entregar_antes_de, resuelto_en, estudiante_id, estudiante_nombre}`.

### A.3 Dar, Corregir y presupuesto
| Ruta | Quién | Cuerpo | Respuesta |
|---|---|---|---|
| `GET /economia/grupo/{gid}/saldos` | profe del grupo, admin | — | `[{estudiante_id, nombre, saldo, recibido_semana, cupo_semana}]` (ruta aparte del roster, que sigue sin saldo) |
| `POST /economia/dar` | profe, admin | `{student_id, monto (1-20), motivo: "participacion"\|"ayuda_companero"\|"tarea"\|"esfuerzo"\|"otro", nota? (≤80; obligatoria con "otro"), llave?}` | 201 `{entrega_id, estudiante_id, monto, motivo, nota, creada_en, presupuesto_restante, recibido_semana, cupo_semana}`. 404 si el estudiante no es de un grupo suyo (el admin: de su institución); 409 tope semanal del estudiante (40); 402 presupuesto insuficiente; 422 monto o motivo |
| `POST /economia/corregir` | el profe que dio | `{entrega_id, monto? (por defecto todo lo que queda), nota?, llave?}` | 201 `{correccion_id, entrega_id, monto, corregible_restante, presupuesto_restante}`. 404 si la entrega no es suya; 409 pasados 14 días, si excede lo que queda o si el estudiante ya gastó esas monedas (nunca queda en negativo) |
| `GET /economia/presupuesto` | profe, admin | — | `{saldo, recargado_semana, entregado_semana, tope_recarga_semanal, tope_por_entrega, tope_semanal_por_estudiante, entregas_recientes: [{entrega_id, estudiante_id, monto, motivo, creada_en, corregible, corregible_hasta}]}` (las de los últimos 14 días) |
| `GET /admin/presupuestos` | admin | — | `{bolsa_saldo, bolsa_emitida, profes: [{teacher_id, rol, saldo, recargado_semana, entregado_semana}]}` |
| `POST /admin/presupuestos/{teacher_id}/recargar` | admin | `{monto, nota?, llave?}` | 201 `Movimiento`. 409 si pasa 100 en la semana para ese bolsillo; 402 si la bolsa no alcanza; 404 profe de otra institución |
| `POST /admin/presupuestos/{teacher_id}/devolver` | admin | `{monto, nota?, llave?}` | 201 `Movimiento` (extra: del bolsillo a la bolsa; 409 si pasa el saldo del bolsillo) |

`Movimiento = {movimiento_id, teacher_id, monto, saldo_bolsillo, saldo_bolsa, recargado_semana}`.

### A.4 Subasta
| Ruta | Quién | Cuerpo | Respuesta |
|---|---|---|---|
| `GET /subastas/activa?grupo={gid}` | estudiante del grupo, profe del grupo, admin | — | 200 `Subasta` o `null`. Devuelve la activa; si no hay, la última cerrada hace menos de 120 s (para mostrar el ganador). Si ya pasó la hora, la cierra antes de responder |
| `POST /subastas` | profe del grupo, admin | `{grupo_id, objeto_id? \| titulo?, descripcion?, duracion_segundos? (30-600, 90), puja_minima (1-600)}` | 201 `Subasta`. 409 si el grupo ya tiene una activa o el objeto está agotado |
| `POST /subastas/{id}/pujar` | estudiante del grupo | `{monto, llave?}` (el TOTAL de su puja) | 200 `Subasta`. Primera puja ≥ `puja_minima`; después, `monto − puja_actual` ∈ {5, 10, 25}. 402 sin saldo; 409 cerrada o incremento inválido (otro pujó antes: vuelve a leer) |
| `POST /subastas/{id}/cerrar` | profe del grupo, admin | — | 200 `Subasta` cerrada (repetir = 200) |

`Subasta = {id, grupo_id, objeto_id, titulo, descripcion, puja_minima, puja_actual, lider_id, lider_nombre, termina_en, segundos_restantes, extensiones, estado: "activa"|"cerrada"|"cancelada", ganador_id, incrementos: [5, 10, 25], creada_en}`.

### A.5 Reglas de la subasta
- **Retención:** al pujar, el monto sale del saldo del estudiante y queda **retenido** en la billetera de la subasta (`owner_type='auction'`); al líder anterior se le devuelve **al instante** todo lo suyo. Si el líder sube su propia puja, solo se le retiene la diferencia. Nadie puja con monedas que no tiene ni con las mismas monedas en dos subastas.
- **Extensión:** una puja en los últimos 10 s extiende el cierre 10 s, máximo 3 veces.
- **Cierre** (lo pide el profe o pasa la hora; perezoso al leer o pujar): lo retenido del ganador **vuelve a la bolsa** de la institución y el objeto entra a su mochila (`por_entregar`, origen `subasta`, `precio_pagado` = su puja; aplica la entrega del profe y la devolución de 14 días). Sin pujas: no se mueve nada y el objeto vuelve a la tienda.
- **Objeto:** de la tienda (su existencia se reserva al crear la subasta y se repone si nadie puja) o texto libre (se crea un objeto oculto, inactivo, para la mochila). Siempre del mismo catálogo: nada académico.
- **Una activa por grupo** (índice único). Todo filtrado por institución; lo ajeno, 404.
- Acciones del libro: `auction_hold` (estudiante → retención), `auction_refund` (retención → estudiante), `auction_settle` (retención → bolsa). La conservación del dinero de §1.1 incluye la retención.

### A.6 Pruebas en modo rápido
| Id | Regla de plata | Tramposo |
|---|---|---|
| OE1 | Dar: 21 → 422; 20 → 201 | OT1 sin tope por entrega |
| OE2 | Tope semanal del estudiante entre dos profes (20 + 20, el 1 más → 409) | OT2 tope por profe |
| OE3 | Presupuesto: dar más que el bolsillo → 402 y nada se mueve | OT3 traslado sin mirar saldo |
| OE4 | Profe sin el grupo del estudiante → 404 | OT4 sin exigir asignación |
| OE5 | Corregir lo ya gastado → 409, nunca negativo | (OT3) |
| OE6 | Corregir a los 15 días → 409 | OT6 sin plazo |
| OE10 | Recarga semanal > 100 → 409 | OT10 sin tope de recarga |
| OE11/12 | Comprar sin saldo → 402; sin existencias → 409 | (OT3), OT12 sin stock |
| OE13 | La compra vuelve a la bolsa | OT13 la compra destruye |
| OE14 | Devolución a los 14 días, una sola vez | OT14 no marca la devolución |
| OE15 | Aislamiento: admin, profe y estudiante de T2 no tocan nada de T1 (404) | OT15 compra sin filtro de institución |
| SB1 | Retención: pujar retiene, superar devuelve al instante, conservación | OT20 no devuelve al superado |
| SB2 | Incrementos y puja mínima; sin saldo → 402 | — |
| SB3 | Extensión de 10 s, máximo 3 | OT21 extiende sin límite |
| SB4 | Cierre: a la bolsa y a la mochila; sin pujas, nada se mueve | — |
| SB5 | Aislamiento: un estudiante de otro grupo no puja (404) | — |
| HE1 | El humo de §4, más una subasta | — |


## 0. Medido y leído hoy (sobre `f7f7aeb`)

| # | Hecho | Dónde |
|---|---|---|
| L1 | `award_coins` es la única función que mueve monedas y va siempre de la bolsa al estudiante. No hay gasto, ni devolución, ni presupuesto | `src/engrama_core/service/coins.py:124`; `grep award_coins(` → asistencia, reto, racha, EVA |
| L2 | La billetera es única por `(owner_type, owner_id, currency)` y el CHECK solo admite `system`, `tenant`, `profile`. Una billetera de presupuesto con `owner_type='profile'` sería **una por profe en todo el sistema**, no por institución: un profe con membresía en dos colegios gastaría en B lo que le recargó A (fuga entre instituciones) | `alembic/versions/006_create_coin_wallets.py`; `src/shared/models.py:237-269` |
| L3 | La billetera del estudiante también es global por perfil (`get_wallet` no filtra por institución). No lo cambio (§8) | `coins.py:52-93` |
| L4 | `coin_ledger.idempotency_key` es UNIQUE por `(tenant_id, idempotency_key)` (033): alcanza para la idempotencia de todo lo nuevo, sin migración | `models.py:306-312` |
| L5 | `shop_items` no tiene `created_by`; `inventory` no guarda el precio pagado ni el asiento de la compra; los estados de `inventory` ya incluyen `pending_delivery`, `delivered`, `expired` | migraciones 017-018 |
| L6 | `shop_items` e `inventory` ya tienen RLS con `tenant_isolation_select/insert` (029) y todo cliente perdió el acceso directo (031): el backend es la puerta | `029_rls_policies.py:38-56`; `031_sin_acceso_directo.py` |
| L7 | El ataque D11 inserta en `shop_items` con `price_coins` 0 y 10 y el `item_type` por defecto. **Un CHECK de escalones o de tipo en la base lo rompería**: las reglas de precio y tipo van en la API, no en la base | `tests/seguridad/modulos.py:18-39` |
| L8 | El roster del profe **no lleva saldo** por decisión del pedagogo y X9 lo exige. No se toca: el saldo va en una ruta aparte, de economía | `src/teachers/service/panel.py:47-53`; ESPEC_grupos_y_panel_docente §2.2 |
| L9 | El rol sale de la membresía (`admin`, `teacher`, `student`); `super_admin` solo existe en `profiles.role` y entra a una institución con una membresía `admin`. La recarga de la bolsa de una institución sigue siendo la CLI del operador (`python -m src.onboarding recargar`) | `src/auth/service.py:297-345`; ESPEC_economia_oleada0 §1.6 |
| L10 | La semana de la casa es de lunes a domingo en la hora de la institución (`engrama_utc_offset_hours`, −5) | `src/racha/reglas.py:60`; `src/foco/fechas.py` |
| L11 | `src/shop/` tiene cinco archivos de 0 bytes y no está montado | `ls -la src/shop` |

Lo que fija números en los tests (ERR-25): `alembic_version = "045_correccion_por_pregunta"` en `tests/integ_db.py:66` y en 12 humos (`grep -rn 045_correccion_por_pregunta tests`). Con la 047 pasan a `"047_economia_ola1"`; **es el único cambio permitido en tests existentes**. `tablas_con_rls` (46) y `politicas_public` (51) no cambian: la 047 no crea tablas ni políticas.

## 1. Qué cambia (una cosa)

**La moneda gana destino y el profe gana una palanca acotada: el profe da y corrige monedas desde un bolsillo propio que le recarga el admin, y el estudiante las gasta en una tienda de privilegios de clase que el profe entrega; todo con su asiento de doble entrada y sin que una moneda se cree ni se destruya.**

Es una intención en tres piezas (a, b, c), cada una con su commit de código y sus tests (§10).

### 1.1 El libro: una sola función de traslado
`src/engrama_core/service/libro.py` (nuevo): `billetera(...)` (busca o crea la de `tenant`, `membership` o `profile`, con `FOR UPDATE` opcional) y `transferir(db, tenant_id, desde, hacia, monto, accion, creado_por, metadata, llave)`:
- reclama la llave con `INSERT ... ON CONFLICT (tenant_id, idempotency_key) DO NOTHING` (como `award_coins`); si ya estaba, devuelve `(asiento_existente, False)` y no mueve nada;
- si `desde.balance < monto`, lanza `SaldoInsuficiente` (cada ruta la traduce a su código); el rollback del request deshace el reclamo;
- inserta el asiento, mueve los dos saldos y hace `flush`. No commitea.
- **Orden de bloqueo de toda la ola:** `tenant` → `membership` → `profile` → `shop_items` (igual que `award_coins`: tenant antes que profile). `inventory` se bloquea solo en la entrega y la devolución.
- `award_coins` **no se toca** (identidad: `git diff f7f7aeb -- src/engrama_core/service/coins.py` vacío).

Acciones nuevas del libro: `budget_allocation` (bolsa → bolsillo), `budget_return` (bolsillo → bolsa), `teacher_award` (bolsillo → estudiante), `teacher_reversal` (estudiante → bolsillo), `shop_purchase` (estudiante → bolsa), `shop_refund` (bolsa → estudiante). **Conservación:** la suma de la bolsa, los bolsillos y los saldos de los estudiantes de una institución no cambia con ninguna de estas rutas.

### 1.2 (b) Presupuesto por profe: el bolsillo
- **Qué es:** una billetera con `owner_type = 'membership'` y `owner_id = memberships.id` (la membresía es única por `(tenant, profile)`): **un bolsillo por profe e institución**. Lo puede tener una membresía `teacher` o `admin` activa.
- **Recargar** `POST /admin/teachers/{tid}/budget` `{amount, idempotency_key, note?}` (`tid` = perfil del profe): de la bolsa al bolsillo. `1 ≤ amount ≤ 100`; la suma de recargas a ese bolsillo en la semana (lunes local) más `amount` ≤ **`profe_presupuesto_semanal` = 100**, si no 409 `tope_semanal_presupuesto`. Bolsa sin fondos → 402.
- **Devolver** `POST /admin/teachers/{tid}/budget/return` `{amount, idempotency_key}`: del bolsillo a la bolsa, hasta el saldo del bolsillo (más → 409 `saldo_insuficiente`). Devolver no libera cupo semanal de recarga.
- **Consultas:** `GET /teachers/me/budget` (el profe: saldo, recargado y entregado esta semana, y los tres topes) y `GET /admin/budgets` (el admin: la bolsa — saldo y `coin_pool` emitido — y cada membresía `teacher`/`admin` activa de SU institución con saldo, recargado y entregado esta semana).
- **Permisos:** recargar, devolver y ver todos los bolsillos: `admin` de la institución (`require_admin`). El profe ve solo el suyo. El estudiante: 403. `super_admin`: lo mismo que el admin de la institución donde tiene membresía; recargar la **bolsa** sigue en la CLI (L9).

### 1.3 (a) Dar y Corregir
- **Dar** `POST /teachers/groups/{gid}/students/{sid}/coins` `{amount, reason, note?, idempotency_key}`:
  - `reason` ∈ lista cerrada `participacion`, `ayuda_companero`, `tarea`, `esfuerzo`, `otro`; con `otro`, `note` obligatoria de 3 a 80 caracteres; con los demás, `note` opcional de hasta 80. Fuera de la lista → 422.
  - `1 ≤ amount ≤ `**`profe_entrega_tope` = 20** → si no, 422 `tope_por_entrega`.
  - El grupo debe ser del profe (`access.authorize_group`: asignado por `teacher_groups`; el admin ve todos los de su institución) y `sid` un estudiante activo de ESE grupo (`memberships.group_code`). Grupo ajeno, de otra institución o estudiante que no es del grupo → **404** (no delata si existe).
  - Lo neto que el estudiante recibió de **todos** los profes en la semana (entregas de esta semana menos lo corregido de esas mismas entregas) más `amount` ≤ **`profe_semana_por_estudiante_tope` = 40** → si no, 409 `tope_semanal_estudiante`. Se calcula con la billetera del estudiante ya bloqueada (dos profes a la vez no pasan juntos el tope).
  - Sale del bolsillo de quien da; sin saldo → 402 `presupuesto_insuficiente`. Sin bolsillo (nunca recargado) = saldo 0 → 402.
  - Asiento `teacher_award`, `created_by_profile_id` = el profe, `metadata = {reason, note, group_id}`.
- **Corregir** `POST /teachers/coin-entries/{entry_id}/reverse` `{amount?, note, idempotency_key}` (`note` obligatoria, 3-80):
  - Solo una entrega `teacher_award` **propia** (`created_by_profile_id` = quien corrige) de su institución; ajena o inexistente → 404. Ni el admin corrige la de otro.
  - Hasta **`corregir_plazo_dias` = 14** días desde la entrega → si no, 409 `plazo_vencido`.
  - `amount` (por defecto, todo lo que queda) ≤ original − lo ya corregido → si no, 409 `excede_original` (o `ya_corregida` si no queda nada).
  - **Nunca deja saldo negativo:** si el estudiante tiene menos que `amount` (ya lo gastó), 409 `saldo_insuficiente` con lo máximo corregible; no se toca nada. Tampoco existe "quitar" sin una entrega detrás: no hay ruta para restar por conducta.
  - Asiento `teacher_reversal` del estudiante al bolsillo de origen de la entrega, con `metadata = {original_entry_id, note}`. El asiento original nunca se borra ni se edita.
- **Consultas:** `GET /teachers/groups/{gid}/coins` (lista de economía del grupo: estudiante, saldo, recibido de profes esta semana y cupo semanal que le queda; ruta aparte del roster, L8) y `GET /teachers/me/coin-entries` (mis entregas de los últimos 14 días con lo corregible y hasta cuándo).

### 1.4 (c) Tienda, mochila y entregas
- **Catálogo** (`require_teacher`: profe o admin de la institución):
  - `POST /teachers/shop-items` `{name (3-60), description? (≤200), item_type ∈ {privilegio, fisico}, price_coins ∈ {40, 120, 300, 600}, stock (0-1000), is_active?}`; `created_by` = quien crea.
  - **Sin objetos académicos:** si el nombre o la descripción contienen (sin tildes, sin mayúsculas, palabra completa) alguna de `nota(s)`, `examen(es)`, `exam`, `punto(s)`, `calificacion(es)`, `decima(s)`, `quiz`, `parcial(es)`, `evaluacion(es)`, `grade(s)`, `bonus`, `xp`, `nivel`, → 422 `objeto_academico`. Lista [PEDAGOGO].
  - `PATCH /teachers/shop-items/{id}` (los mismos campos, opcionales, con las mismas reglas): el admin, cualquier objeto de su institución; el profe, solo los que creó; si no, 404.
  - `GET /teachers/shop-items`: todo el catálogo de la institución, activos e inactivos (el admin ve lo que publican sus profes).
- **Comprar** `POST /core/shop/{item_id}/buy` `{idempotency_key}`: solo membresía `student` (otro rol → 403). El objeto debe ser de su institución (si no, 404) y activo (si no, 409 `inactivo`); `stock > 0` (si no, 409 `agotado`; `stock NULL` heredado = ilimitado); saldo ≥ precio (si no, 402). El precio **vuelve a la bolsa** (`shop_purchase`), `stock − 1`, y nace una fila en la mochila con `status = 'pending_delivery'`, `price_paid` y `purchase_ledger_id`. El estudiante ve el catálogo activo en `GET /core/shop` y su mochila en `GET /core/inventory`.
- **Entregar** `POST /teachers/inventory/{id}/deliver`: lo marca `delivered` (`resolved_by`, `resolved_at`). Puede el admin de la institución, quien creó el objeto o un profe asignado a un grupo del estudiante; si no, 404. Entregar dos veces → 200 con lo mismo. `GET /teachers/deliveries` lista las pendientes que esa persona puede entregar, con su fecha límite.
- **Devolución sola a los `tienda_entrega_plazo_dias` = 14 días:** una compra `pending_delivery` con 14 días o más se devuelve: asiento `shop_refund` (bolsa → estudiante) por `price_paid`, con llave `shop_refund:<inventory_id>` (**una sola vez**), `status = 'expired'`, `stock + 1`. Es **perezosa**: corre al leer la mochila (solo las del estudiante), al listar entregas (toda la institución) y al intentar entregar una vencida (que responde 409 `plazo_vencido_devuelto` con la devolución ya hecha y commiteada). Si la bolsa no alcanza para devolver, no devuelve, deja la compra pendiente y escribe un WARNING `devolucion_sin_fondos` (no debería pasar: la bolsa recibió esas monedas).

### 1.5 La moneda es la respuesta correcta
- Dar **no reemplaza** la paga por aciertos y no toca ningún pago existente (`award_coins`, `economia.py` y los topes de reto y EVA quedan idénticos).
- Es una **válvula del profe con techo**: una entrega no pesa más que el reto más caro (20 = `reto_monedas_tope`); a un estudiante no le llega de los profes más de 40 a la semana, menos que una semana típica de juego (52, informe 11 §4); y el profe no da lo que no tiene: 100 por semana, ≈ 6 % de lo que emite un grupo de 30.
- Los motivos son conductas de aprendizaje (participar en inglés, ayudar a entender, entregar la tarea, el esfuerzo), **nunca disciplina**; se guardan en el libro (Lingo los pedía y los tiraba).
- Corregir **no es castigo**: solo deshace un error propio, acotado a la entrega y al saldo.
- La tienda vende privilegios de clase y objetos físicos, **nunca nota, examen, nivel ni XP**; lo gastado vuelve a la bolsa, no se destruye.
- Todo queda con acción propia en el libro: la métrica "% de monedas de la semana que vienen del profe ≤ 15 %" se puede medir con un `GROUP BY action`.

## 2. Qué debe pasar (medible)

Tests nuevos (ids `OE`) en `tests/economia_ola1/` (integ) y unitarios de las reglas puras (no-integ). Cada regla con su tramposo (§3).

| Id | Criterio |
|---|---|
| OE1 | Dar 20 → 201; dar 21 → 422 `tope_por_entrega`; dar 0 → 422. Tras el 422, saldos idénticos |
| OE2 | A un estudiante: profe A da 20 y profe B da 20 → 201 y 201; cualquiera da 1 más → 409 `tope_semanal_estudiante`. Una entrega de la semana pasada (fecha movida al domingo anterior) no cuenta. Corregir 10 de una entrega de esta semana devuelve 10 de cupo |
| OE3 | Bolsillo con 15: dar 16 → 402 `presupuesto_insuficiente`, nada se mueve; dar 15 → 201 y el bolsillo queda en 0 |
| OE4 | Profe B de la misma institución sin el grupo → 404; profe A, en la ruta de SU grupo, con el `sid` de un estudiante de otro grupo → 404; con un estudiante de otra institución → 404; el estudiante no puede dar (403) |
| OE5 | Corregir más de lo que el estudiante tiene (gastó en la tienda) → 409 `saldo_insuficiente`; saldo intacto; nunca negativo |
| OE6 | Entrega de hace 15 días → Corregir 409 `plazo_vencido`; de hace 13 días → 201 |
| OE7 | Entrega de 15: corregir 10 → 201; corregir 6 → 409 `excede_original`; corregir 5 → 201; corregir 1 → 409 `ya_corregida` |
| OE8 | Profe B (o el admin) corrige la entrega del profe A → 404 |
| OE9 | Dar dos veces con la misma llave → 201 y luego 200 con el mismo `entry_id`, **una** fila en el libro; la misma llave con otro monto → 409 `llave_reutilizada` |
| OE10 | Recargar 100 → bolsa −100, bolsillo +100; recargar 1 más la misma semana → 409 `tope_semanal_presupuesto`; un profe recargando → 403; el admin recargando a un profe de otra institución → 404; bolsa con 50 y recarga de 60 → 402; devolver más que el saldo → 409 |
| OE11 | Estudiante con 30 compra un objeto de 40 → 402; stock igual, mochila vacía, saldos iguales |
| OE12 | Objeto con stock 1: primera compra 201, segunda (otro estudiante) 409 `agotado`; stock 0, nunca negativo. Objeto inactivo → 409 `inactivo` |
| OE13 | Comprar: el estudiante −precio, **la bolsa +precio**, una fila `pending_delivery` con `price_paid`; la compra repetida con la misma llave → 200, una fila |
| OE14 | Compra de hace 15 días: al leer la mochila → `expired`, el estudiante recupera el precio, stock +1, y una segunda lectura no devuelve otra vez (una sola fila `shop_refund`). Compra de hace 13 días → sigue `pending_delivery`. Entregar una de 15 días → 409 `plazo_vencido_devuelto` y queda devuelta |
| OE15 | Aislamiento: admin de T2 no ve los bolsillos de T1 ni recarga a un profe de T1 (404); un estudiante de T2 no compra un objeto de T1 (404) ni lo ve en `/core/shop`; un profe de T2 no entrega una compra de T1 ni corrige una entrega de T1 (404); `GET /teachers/shop-items` de T2 no trae objetos de T1 |
| OE16 | Crear un objeto "+1 punto en el examen" o "Subir la nota" → 422 `objeto_academico`; "Elegir la canción" → 201 |
| OE17 | Precio 50 → 422 `precio_fuera_de_escalon`; 40, 120, 300, 600 → 201 |
| OE18 | Entregar: quien creó el objeto → 200 `delivered`; otra vez → 200; un profe de la misma institución sin relación con el objeto ni con el grupo del estudiante → 404; el estudiante → 403 |
| OE19 | El profe B no edita el objeto del profe A (404); el admin sí |
| OE20 | Conservación: en el humo, la suma de la bolsa + bolsillos + saldos de la institución es la misma antes y después |
| OEU | Unitarios: lunes local (domingo 23:30 Bogotá sigue en la semana; lunes 00:00 Bogotá = semana nueva), validaciones de monto, motivo, precio, filtro académico y plazo |

## 3. Cómo sabremos que FALLÓ (tramposos)

`tests/tramposos/test_tramposos_ola1_economia.py` (integ): cada tramposo parchea UNA pieza con una versión rota a propósito, corre el cuerpo del test real y exige `AssertionError` con el mensaje de su mecanismo (patrón de `test_tramposos_bug15.py`). Los de reglas puras también en no-integ.

| Tramposo | Rompe | Debe poner rojo |
|---|---|---|
| OT1 | `reglas.validar_monto_entrega` sin tope (acepta 21) | OE1 |
| OT2 | el tope semanal cuenta solo lo dado por el MISMO profe | OE2 |
| OT3 | Dar sin mirar el bolsillo (el CHECK de la base revienta → 500 en vez de 402) | OE3 |
| OT4 | `authorize_group` sin exigir la asignación (solo institución) | OE4 |
| OT5 | Corregir sin mirar el saldo del estudiante | OE5 |
| OT6 | Corregir sin plazo | OE6 |
| OT7 | Corregir compara con el original sin restar lo ya corregido | OE7 |
| OT8 | Corregir sin exigir que la entrega sea propia | OE8 |
| OT9 | Dar sin llave (no la reclama) | OE9 |
| OT10 | Recargar sin tope semanal | OE10 |
| OT11 | Comprar sin mirar el saldo | OE11 |
| OT12 | Comprar sin mirar el stock | OE12 |
| OT13 | La compra destruye las monedas (`hacia = None`, como Lingo) | OE13 |
| OT14a | La devolución sin llave (devuelve en cada lectura) | OE14 |
| OT14b | El plazo de devolución en 7 días | OE14 |
| OT15 | Comprar busca el objeto sin filtrar por institución | OE15 |
| OT16 | El filtro académico apagado | OE16 |
| OT17 | El precio sin escalones | OE17 |
| OT18 | Entregar sin revisar quién entrega | OE18 |

Si un tramposo no pone rojo su test, el test no prueba nada y se arregla el test **antes** de seguir (se reporta, no se esconde).

## 4. Humo que escribe su archivo y réplica

**Humo HE1** (`tests/integ/test_humo_ola1_economia.py`), escenario fijo, sin azar: una institución con bolsa 10.000; un admin; dos profes (P1 con el grupo 10A, P2 con el 10B); 5 estudiantes por grupo, cada uno con 50 monedas sembradas por `award_coins` (acción `challenge_reward`, como un reto).
1. El admin recarga 100 a P1 y 100 a P2.
2. P1 da 20 (participación) a cada uno de sus 5 → su bolsillo queda en 0; P2 da 10 (tarea) a 3 de los suyos → 70.
3. P1 corrige 5 de la entrega a su primer estudiante → bolsillo 5.
4. El admin crea "Elegir la canción" (privilegio, 40, stock 10); P1 crea "Cinco minutos de pausa" (privilegio, 40, stock 2); P2 crea "Libreta" (fisico, 120, stock 1).
5. Los 5 de P1 compran "Elegir la canción" (todos tienen ≥ 65). Dos de P2 que recibieron 10 compran "Cinco minutos de pausa"; un tercero de P2 intenta y recibe 409 `agotado`. Nadie alcanza "Libreta" (máximo 60) → un intento da 402.
6. P1 entrega 3 de las 5 canciones; P1 entrega las 2 pausas (las creó él).
7. Las 2 canciones sin entregar se mueven a hace 15 días; P1 lista sus entregas → se devuelven.

Escribe `tests/_salida/humo_ola1_economia.json` (en `.gitignore` como los otros humos) **antes** de afirmar, y debe dar exactamente (calculado aquí, antes del código):
```
alembic_version: "047_economia_ola1"
recargas: 200; entregas: 8 (monto 130); correcciones: 1 (monto 5)
compras_201: 7; agotado_409: 1; sin_saldo_402: 1
entregadas: 5; devueltas: 2; pendientes: 0
bolsa: 10000 − 500 − 200 + 7·40 − 2·40 = 9500
bolsillos: {P1: 5, P2: 70}
saldos: P1 (5): [65−40, 70−40, 70−40, 70−40+40, 70−40+40] = [25, 30, 30, 70, 70]
        P2 (5): [60−40, 60−40, 60, 50, 50] = [20, 20, 60, 50, 50]
conservacion: 10000 == bolsa + bolsillos + saldos   (9500 + 75 + 425 = 10000)
stock: {cancion: 10−5+2 = 7, pausa: 0, libreta: 1}
saldo_negativo: 0
```
(Qué estudiantes de P1 quedan sin entregar: los dos últimos en orden de creación; por eso recuperan sus 40.)

**Réplica RE1** (solo con `ENGRAMA_REPLICA_OLA1=1`), entradas que no se usaron al desarrollar: el cambio de semana exacto (entrega el domingo 23:59 local y otra el lunes 00:01: la primera no cuenta en el tope de la semana nueva); un estudiante con saldo exactamente igual al precio de 600 (compra y queda en 0); una corrección a los 14 días menos un minuto (pasa) y a los 14 días más un minuto (409); un admin que da desde su propio bolsillo a un estudiante de un grupo que no tiene asignado (pasa: el admin ve todo su colegio); stock `NULL` heredado (ilimitado, no baja). Criterio: los mismos invariantes (conservación, sin negativos, topes) y los códigos indicados.

## 5. Exploits que se cierran

| Exploit | Cierre |
|---|---|
| Doble toque o reenvío paga dos veces (Dar, Corregir, recargar, comprar) | Llave obligatoria del cliente, reclamada en el UNIQUE del libro (OE9, OE13) |
| Dos profes llenan a la vez a un favorito | Tope semanal por estudiante sumando a todos los profes, calculado con su billetera bloqueada (OE2) |
| Un profe con dos colegios gasta en B lo que le dio A | Bolsillo por membresía, no por perfil (L2, OE15) |
| "Quitar" monedas como castigo o borrar evidencia | Solo Corregir lo propio, ≤ 14 días, ≤ original, sin negativos; el asiento inverso queda (OE5-OE8) |
| El admin se infla un bolsillo para dar sin límite | Tope semanal de recarga por bolsillo (100) y el tope por estudiante; todo en el libro con quién lo hizo (OE10) |
| Vender ventajas académicas con otro nombre | Tipos cerrados, filtro de palabras, escalones fijos; el admin ve todo el catálogo (OE16, OE17) |
| Comprar sin saldo o sin stock, o con dos compras simultáneas | `FOR UPDATE` en la billetera y en el objeto; 402 y 409 (OE11, OE12) |
| El profe cobra y no entrega | Devolución sola a los 14 días, una sola vez (OE14) |
| La compra destruye monedas y la bolsa se agota (Lingo) | La compra vuelve a la bolsa (OE13, OE20) |
| Mirar o tocar otra institución | Todo se filtra por `auth.tenant_id`; ajeno = 404 (OE15) |

## 6. Configuración (todo provisional)
En `src/shared/config.py`: `profe_entrega_tope = 20`, `profe_semana_por_estudiante_tope = 40`, `profe_presupuesto_semanal = 100`, `corregir_plazo_dias = 14`, `tienda_entrega_plazo_dias = 14`, `tienda_escalones = [40, 120, 300, 600]`.

## 7. Migración 047 (aditiva, idempotente; en producción no se baja)
`SQL_SUBIR`:
1. `coin_wallets`: el CHECK `coin_wallets_owner_type_check` pasa a admitir `'membership'` (DROP IF EXISTS + ADD).
2. `shop_items.created_by UUID REFERENCES profiles(id)` (NULL en lo que ya existe).
3. `inventory.price_paid INTEGER` con CHECK `price_paid IS NULL OR price_paid > 0`, e `inventory.purchase_ledger_id UUID REFERENCES coin_ledger(id)`.
4. Índice `idx_ledger_tenant_action_actor (tenant_id, action, created_by_profile_id, created_at)` (topes) e índice parcial `idx_inventory_pendientes (tenant_id, purchased_at) WHERE status = 'pending_delivery'` (el barrido).

`SQL_BAJAR` lo deshace en orden inverso (falla si ya existen bolsillos: es a propósito, no se borra dinero al bajar). Test MG47: sube, baja y vuelve a subir idéntica (patrón `test_migracion_035.sube_baja_sube`, ERR-24).

## 8. Qué NO se toca
- `award_coins`, `economia.py`, asistencia, retos, racha, EVA y sus pagos (diff vacío).
- El roster `GET /teachers/groups/{gid}/students` sigue sin saldo (X9).
- La billetera global del estudiante (L3): si un estudiante está en dos colegios, sus monedas son una sola. Va a "para después".
- La recarga de la bolsa de la institución (CLI del operador).
- Ninguna tabla nueva, ninguna política RLS nueva, ningún CHECK nuevo de precio o tipo en la base (L7).
- Subastas, apuestas, insignias, cosméticos, "Usar" antes de entregar, objetos por grupo, límite de 1 compra por estudiante cada 7 días, aprobación del admin para ≥ 300, relleno automático del lunes, alertas de concentración: **para después** (ola 2 o decisión).
- Web: nada. Producción y piloto: nada.

## 9. Regresión = identidad
Antes del primer commit de código: suite completa de `f7f7aeb` en mi contenedor (`engrama-test-pg-ola1`, 127.0.0.1:55451, plugin fuera del repo, ERR-44). Después de cada commit: los mismos tests existentes en verde, y el único cambio en tests existentes es `alembic_version` 045 → 047 (13 lugares). Si algo más cambia, se detiene.

## 10. Commits
1. Esta espec.
2. Migración 047 + modelos + `alembic_version` en los 13 lugares + MG47.
3. `libro.py` (traslado) + configuración + reglas puras con sus unitarios.
4. (b) Bolsillo: recargar, devolver, consultas + OE10, OE15 parcial.
5. (a) Dar y Corregir + OE1-OE9.
6. (c) Tienda, mochila, entregas y devolución + OE11-OE19.
7. Tramposos OT1-OT18.
8. Humo HE1 y réplica RE1.

## 11. Decisiones abiertas
- **[CHRISTIAM]** Los números (20, 40, 100, 14, escalones). ¿Quién paga los premios físicos?
- **[CHRISTIAM]** ¿El admin puede recargarse a sí mismo para dar? Hoy sí, con el mismo tope semanal (un admin que también enseña no tiene otra membresía).
- **[PEDAGOGO]** La lista de motivos; el saldo visible al profe en la ruta de economía; Corregir como asiento inverso; la lista de palabras prohibidas en la tienda.
