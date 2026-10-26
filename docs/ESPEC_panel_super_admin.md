# ESPEC · Panel del super admin y tablero del admin (preregistro)

- **Fecha:** 2026-10-26. **Autor:** Creador (Opus). **Método:** completo (D11: es una puerta de datos y permisos).
- **Ramas:** backend `panel/super-admin` sobre `juego/sprint-backend` @ `d275074`; web `panel/super-admin` sobre `juego/sprint-web` @ `6ffbea3`.
- **Plan:** `investigacion/producto/16-arquitectura-y-plan-de-lanzamiento.md` §3 y fase 1.2. **Referencia de experiencia:** Lingo Coins
  (`coins-mvp/admin.html` "Super Admin Dashboard" y "School Dashboard", `modules/institutions.js` `loadDashboard`/`loadEconomy`): tarjetas de
  escuelas activas, profes, estudiantes, grupos, monedas en circulación y una tabla de monedas por escuela. Se porta la experiencia, no el código.
- **Maqueta:** `diseno/arte/prototipos/super-admin/` (otro agente): "Todo ENGRAMA", registros por día, monedas emitidas y gastadas, lista de
  clientes "Cliente NN", detalle del cliente con su etiqueta privada; "Tu institución" para el admin.
- **Copia idéntica** en `engrama-backend/docs/` y `engrama-web/docs/`.

## 0. El problema en dos líneas
Christiam (super admin) no tiene cómo ver, sin terminal, cuántos profes, grupos y estudiantes tiene cada cliente, quién está activo y cómo se
mueven las monedas; el rector o coordinador (admin) tampoco ve las cifras de su institución. Lo que podría fallar: que un admin vea otro
cliente, que alguien que no es super admin vea todo, o que una cifra mienta (contar monedas que no son emisión, actividad de otro cliente).

## 1. Qué cambia (UNA cosa)
**Una puerta de solo lectura con las métricas por cliente:** `GET /super/clientes` y `GET /super/clientes/{tenant_id}` solo para
`profiles.role = 'super_admin'`, y `GET /admin/metricas` para el admin, limitada a su institución activa. En la web, las pantallas que las pintan.

Sin migraciones: todo sale de tablas que ya existen. Sin escrituras: ningún `INSERT`, `UPDATE` ni `commit` en estas rutas.

### 1.1 Quién es super admin
- `profiles.role = 'super_admin'` (CHECK de la 002). Las membresías NO admiten ese rol (CHECK `memberships_role_check`), y ningún camino del
  backend lo escribe (`alta` usa `student/teacher/admin`, el registro y M3 escriben `student`): solo se pone por SQL, a mano, con el sí de Christiam.
- Dependencia nueva `require_super_admin` (`src/panel/acceso.py`): valida el JWT, exige el perfil, la cuenta activa (H-8) y la clave definitiva
  (como `get_current_user`), y exige `profile.role == 'super_admin'`. NO exige membresía (el super admin no tiene por qué pertenecer a un cliente)
  y NO mira `X-Tenant-ID`. Rol distinto → **403** `"Super admin role required"`; sin token → **401**.
- `require_admin` no se toca: un super admin que además es admin de un cliente ve `/admin/metricas` de ESE cliente, como cualquier admin.

### 1.2 Los clientes no llevan nombre visible
- **Código neutro** `"Cliente NN"`: el puesto del tenant ordenado por `(created_at, id)` entre TODOS los tenants, con dos dígitos (`Cliente 01`).
  Sale en `/super/*` y es estable mientras no se borre un tenant (los tenants no se borran desde la plataforma).
- **Etiqueta privada** = `tenants.name`, SOLO en las respuestas de `/super/*`.
- `/admin/metricas` no lleva ni código, ni etiqueta, ni `slug`, ni id del tenant: la respuesta no tiene ningún campo de nombre.
- Lo que ya existe y NO cambia aquí: `/auth/me` devuelve `tenant_name` a todo miembro (va a "Después").

### 1.3 Las métricas (todas filtradas por `tenant_id` explícito; el backend se conecta sin RLS)
| Campo | Definición exacta |
|---|---|
| `profes` | membresías activas `role='teacher'` del tenant |
| `admins` | membresías activas `role='admin'` del tenant |
| `grupos` | filas de `groups` del tenant |
| `estudiantes` | membresías activas `role='student'` del tenant |
| `activos_7d` | estudiantes con membresía activa en el tenant que, en las últimas 168 h (`ahora − 7 días`), tienen en ESE tenant un intento de reto (`challenge_attempts.started_at`), una asistencia (`attendance.created_at`) o un evento del anillo como sujeto (`learning_events.occurred_at`). Distintos |
| `registros_30d` | membresías `role='student'` del tenant (activas o no) creadas en los 30 días locales que terminan hoy |
| `registros_por_dia` | 30 entradas `{dia, n}`, de hace 29 días a hoy, en el día LOCAL (`settings.engrama_utc_offset_hours`, −5), con 0 donde no hubo; `Σ n = registros_30d` |
| `monedas.bolsa` | saldo de la billetera `owner_type='tenant'` del tenant (0 si no existe) |
| `monedas.emitidas` | Σ `amount` de los asientos del tenant que van de la institución (`tenant` o `membership`) a un estudiante (`profile`), salvo `action='shop_refund'`; MENOS Σ de los que van de un `profile` a un `membership` (la corrección del profe) |
| `monedas.gastadas` | Σ de los asientos `profile → tenant` (compras) + Σ `auction → tenant` (liquidación de una puja); MENOS Σ `tenant → profile` con `action='shop_refund'` (devolución de una compra). La retención de una puja (`profile → auction`) y su reembolso no cuentan |
| `monedas_por_semana` | 8 entradas `{semana, emitidas, gastadas}` (lunes local; de hace 7 semanas a la actual), con las mismas reglas |

Lo que NO es emisión ni gasto: `pool_topup` (recarga de la bolsa, `NULL → tenant`), `budget_allocation`/`budget_return` (bolsa ↔ bolsillo del
profe). Las reglas van por la DIRECCIÓN de la billetera, no por el nombre de la acción, para que una acción nueva de premio cuente sin tocar esto.

### 1.4 Las respuestas
- `GET /super/clientes` → `{hoy, totales: Metricas, registros_por_dia, monedas_por_semana, clientes: [ClienteResumen]}`, clientes en orden de
  código. `ClienteResumen = {id, codigo, etiqueta, suspendido, creado, metricas: Metricas}`. `totales` = suma de los clientes (campo a campo).
- `GET /super/clientes/{tenant_id}` → `{...ClienteResumen, registros_por_dia, monedas_por_semana}`. Id que no existe → **404**; no UUID → **422**.
- `GET /admin/metricas` → `{hoy, metricas: Metricas, registros_por_dia, monedas_por_semana}`, del `auth.tenant_id` (el tenant activo que ya
  resuelve `build_auth_context`, con `X-Tenant-ID` validado contra las membresías). Sin parámetro de tenant: no hay forma de pedir otro.
- `Metricas = {profes, admins, grupos, estudiantes, activos_7d, registros_30d, monedas: {bolsa, emitidas, gastadas}}`.

### 1.5 Crear cliente desde la web: NO en esta ola
`alta.asegurar_institucion` es simple, pero (a) no hay dónde guardar la etiqueta privada sin una migración: `tenants.name` sale hoy a todo miembro
por `/auth/me`; (b) nace con monedas (emisión: pide reautenticación, plan §3); (c) sin el admin invitado (GoTrue, otra rama) el cliente queda vacío.
Va a la siguiente ola con su migración 051 (`etiqueta_privada`, `codigo` fijo) y la reautenticación.

## 2. Qué debe pasar (medible) y el test que se pone rojo
Pruebas de integración contra Postgres real (`engrama-test-pg-super`, 127.0.0.1:55445), en `tests/panel/`. Dos clientes sintéticos A y B con
cifras distintas y conocidas (semilla fija).

| Id | Criterio | Test | Tramposo que lo pone rojo |
|---|---|---|---|
| PS1 | el super admin ve A y B con las cifras exactas (profes, admins, grupos, estudiantes, activos, registros, monedas) y `totales` = A + B | `test_ps1` | — (la base de los demás) |
| PS2 | admin, profe, estudiante → 403 en `/super/clientes` y `/super/clientes/{id}`; sin token → 401 | `test_ps2` | **TP1** `require_super_admin` que acepta `is_admin` |
| PS3 | super admin con la cuenta suspendida → 403; con la clave temporal → 403 `must_change_password` | `test_ps3` | **TP2** `require_super_admin` sin `exigir_cuenta_activa` |
| PS4 | detalle: 404 si el id no existe, 422 si no es UUID; el de A trae sus series | `test_ps4` | — |
| PS5 | `registros_por_dia`: 30 entradas consecutivas que terminan hoy (local); el de hace 30 días no entra, el de hoy sí, `Σ = registros_30d` | `test_ps5` | **TP3** ventana de 31 días |
| PS6 | `activos_7d`: actividad de hace 8 días no cuenta; actividad en B de un estudiante de A no lo hace activo en A; un no estudiante no cuenta | `test_ps6` | **TP4** actividad sin filtro de tenant |
| PS7 | monedas: cada flujo (reto, Dar, corrección, compra, devolución, puja liquidada, puja reembolsada, recarga, bolsillo) suma donde dice §1.3 | `test_ps7` | **TP5** emitidas que cuentan `shop_refund` y no restan correcciones |
| AM1 | el admin de A ve EXACTAMENTE las cifras de A (iguales a las del super admin para A), nunca las de B | `test_am1` | **TP6** métricas del admin sin filtro de tenant |
| AM2 | admin de A con `X-Tenant-ID` de B (sin membresía) → 403; admin de A que es profe en B, con `X-Tenant-ID` de B → 403 | `test_am2` | — (lo cubre `build_auth_context`) |
| AM3 | profe y estudiante → 403 en `/admin/metricas` | `test_am3` | — |
| AM4 | la respuesta del admin no tiene `etiqueta`, `codigo`, `id`, `slug`, ni el nombre del tenant en ninguna parte del cuerpo | `test_am4` | **TP7** la respuesta del admin con la etiqueta |
| RO1 | solo lectura: tras llamar las tres rutas, las filas y saldos de `tenants`, `memberships`, `coin_wallets`, `coin_ledger`, `profiles` quedan idénticos | `test_ro1` | — |
| RG1 | regresión = identidad: el inventario de rutas de la app es el de `d275074` más EXACTAMENTE las 3 nuevas | `test_rg1` (se congela ANTES del cambio) | — |

Los tramposos viven en `tests/tramposos/test_tramposos_panel_super.py` (patrón de `test_tramposos_ola1_economia.py`: parchar UNA pieza,
correr el test real y exigir `AssertionError` con su mensaje).

Unitarias (sin base, `tests/panel/test_unit.py`): `codigo_de(n)`, la ventana de 30 días locales, las 8 semanas, con su tramposo de fecha.

## 3. Humo y réplica
- **Humo** `tests/integ/test_humo_panel_super.py`: siembra A y B (semilla 20261026), llama las tres rutas y escribe
  `tests/_salida/humo_panel_super.json` (sin nombres de tenant: solo códigos y cifras). Si no escribe el archivo, no hay corrida grande.
- **Réplica** `tests/integ/test_replica_panel_super.py`: tres clientes con otra semilla y otras cifras que no se usaron al desarrollar; las mismas
  afirmaciones (PS1, AM1, AM4) deben pasar.

## 4. La web (`engrama-web`, rama `panel/super-admin`)
| Pieza | Qué |
|---|---|
| `src/api/panel.js` (diferido) | `listarClientes`, `detalleCliente(id)`, `metricasAdmin` por `pedirJson` |
| `src/ui/graficas.js` (diferido) | geometría pura (puntos de la línea, alturas de las barras, marcas del eje) + SVG con `createElementNS`, clases por token |
| `src/vistas/super/clientes.js` (diferido) | `#/super` "Todo ENGRAMA": cifras, registros por día (línea), monedas por semana (barras), selector "Ver un cliente" y la lista "Cliente NN · etiqueta" |
| `src/vistas/super/cliente.js` (diferido) | `#/super/cliente/:tid`: el detalle del cliente, con la etiqueta marcada "privada, solo la ves tú" |
| `src/vistas/admin/tablero.js` (diferido) | `#/admin/tablero` "Tu institución": las mismas cifras y gráficas de SU institución, sin nombre; si `sesion.superAdmin`, un enlace "Todos los clientes" |
| `src/textos_panel.js` (diferido) | los textos |
| `estilos/panel.css` (diferido) | las gráficas y las tarjetas; solo `var(--token)`; oro (`--color-oro*`) SOLO en monedas |
| `src/auth/perfil_actual.js` | la sesión gana `superAdmin: profile.role === 'super_admin'` (solo pinta el enlace; la puerta es el backend) |
| `src/navegacion.js` | filas `/admin/tablero`, `/super`, `/super/cliente/:tid` (rol `admin`; pestaña `tablero`) |
| `src/ui/nav_inferior.js` | el admin gana la pestaña "Tablero" (Grupos · Tablero · Perfil): **cambia la barra de toda pantalla del admin**, declarado |
| `src/app.js` | las tres rutas con `import()` (no tocan `panel_docente.js`) |
| `sw.js` | los módulos nuevos en `DIFERIDOS`; `engrama-shell-v80` (la v79 la toma `cuentas/invitar-profe`) |

- Un no super admin que escribe `#/super` ve "Esta pantalla es solo del super admin" (el backend dice 403) y un enlace a su tablero: nunca datos.
- Correcto e incorrecto con ícono y texto; móvil primero (375 sin desborde, toques de 44 px); h() sin `innerHTML`.
- Pruebas `tests/unit/panel_*.test.mjs`: la geometría de las gráficas (con tramposo), que la vista del admin nunca pinta una etiqueta aunque
  llegue (tramposo), que `#/super` sin permiso no pinta cifras (tramposo), los textos de oro solo en monedas, la tabla de navegación (U61).
- Capturas a 375 y 1280 contra el backend real local (o el doble con las mismas formas) en `ENGRAMA/despliegue/salida/panel_super/`.

## 5. Qué NO se toca
- Ninguna migración (la 048-050 son de otros agentes; la 051 queda para crear clientes). `src/shared/models.py` y `src/shared/deps.py` no cambian.
- Las rutas existentes de `/admin`, `/auth`, `/economia` y el resto: idénticas (RG1 y la suite completa).
- En la web: las pantallas del estudiante, `src/vistas/admin/crear_grupo.js`, `recuperar.js`, `supabase_rest.js` (son de `cuentas/invitar-profe`)
  y `panel_docente.js`.
- Ningún secreto en archivos; nada contra producción; sin push ni despliegue.

## 6. Veredicto por la letra
- **FUNCIONA** si PS1-PS7, AM1-AM4, RO1, RG1 pasan, los 7 tramposos ponen rojo su test, el humo escribe su archivo, la réplica pasa, las suites
  completas de los dos repos dan 0 fallas, ruff y mypy 0, y hay capturas a 375 y 1280.
- **NO** si un admin ve cifras de otro cliente, si alguien que no es super admin lee `/super/*`, o si la respuesta del admin trae un nombre.
