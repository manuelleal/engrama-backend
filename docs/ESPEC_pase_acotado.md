# ESPEC · El pase acotado: lo que viaja a EVA y a SET deja de ser el token de sesión (S-10)

Creador · 2026-10-20 · preregistro. Worktree `engrama-backend-pase`, rama `seg/pase-acotado`, desde `f7f7aeb` (versión `demo-21oct`: **768 passed + 24 skipped, 208 no-integ, ruff 0**, según el mensaje de ese commit; los 208 no-integ, medidos hoy en este worktree).

Origen: auditoría de seguridad 03, hallazgo **S-10** («el pase a EVA y SET es el token completo»); `ENGRAMA/despliegue/LEEME_piloto.md` §12.1 punto 9; decisión 013 (enlace con `pase=`). Es una condición para abrir el sistema a internet. **No se despliega nada antes del 22 de octubre** (después de la conferencia del 21), y el piloto no se toca.

## 0. Cómo funciona hoy, de punta a punta (leído el 2026-10-20)

### 0.1 Qué viaja
El «pase» es el **access token de GoTrue** (JWT HS256, `aud=authenticated`, vence a los 3.600 s: `despliegue/docker-compose.yml:73`, `GOTRUE_JWT_EXP: ${JWT_EXP:-3600}`). Es la misma credencial que abre **toda** la API de ENGRAMA como esa persona.

| Pieza | Qué hace con el pase | Dónde |
|---|---|---|
| **web**: emite | `pedirPase: () => authActivo.token()`: el token de sesión, tal cual | `engrama-web/src/app.js:187` |
| web: lo pide al tocar | `const pase = await ctx.pedirPase()` | `engrama-web/src/anillo/abrir.js:86` |
| web: arma el enlace | `pase=<token>` en el fragmento, con `tenant=` para SET | `engrama-web/src/anillo/enlace.js:44` y `:56` |
| **backend**: valida | No hay «pase»: se valida como cualquier Bearer (`validate_jwt`) y abre cualquier ruta | `src/auth/service.py:46`, `src/shared/deps.py:59` |
| **EVA** celular | Lee `#pase=`, lo borra de la barra, lo guarda en memoria y lo manda en `POST /api/unirse`. **Si falla, lo conserva para reintentar** | `EVAGAME/servidor/estaticos/estudiante.js:31`, `:35`, `:191`, `:195` |
| EVA tablero y Escamas | `POST /api/entrar-profe {pase}` y luego usa su propio token de sala | `estaticos/tablero.js:21-22`, `:492`; `estaticos/escamas.js:16-20`, `:75` |
| EVA servidor | `GET /auth/me` con `Authorization: Bearer <pase>` y `X-Tenant-ID`; usa id, membresías, `is_active`, `must_change_password`, `active_tenant_id`, `consent_version`. **Una vez por entrada**; después la sala da su propio token | `servidor/pases.py:91-103` (verificar), `:105-125` (consulta), `servidor/anillo.py:128-151` (el código de sala se revisa ANTES de llamar al backend) |
| **SET** estudiante (página) | Lee `#pase=`, lo guarda en `sessionStorage` (`set_engrama_pase`), lo manda en `get_config` y lo borra al recibir la sesión de SET | `SET/local/portal/anillo_cliente.js:21`, `:28-40`, `:71`, `:84` |
| SET estudiante (función) | `GET /auth/me` con el pase; luego abre una sesión propia de SET (6 h). El código del examen se revisa ANTES (404 sin tocar el pase) | `SET/supabase/functions/grade-exam/index.ts:27327-27378`, `:28340-28403`, `:27381` |
| **SET docente** (`revisar.html`) | Guarda el pase en memoria y lo manda en **CADA** llamada (`writing_pendientes`, cada página, `writing_calificar`) | `SET/local/portal/revisar.html:136-145`, `:186-189` |
| SET docente (función) | En cada llamada: `GET /auth/me` **y** `GET /teachers/groups` con el pase | `grade-exam/index.ts:28609-28610` (`gruposDelDocente`), `:28628-28636` (`accesoDocente`) |

(Líneas de SET leídas en `universal/examen` `cee543a`, que contiene a `2ca1dac`, la de `demo-21oct`; de EVA en `main` `8b009d6`; de la web en `main` `d9dbf85`.)

### 0.2 El riesgo
Si EVA o SET dejan escapar lo que reciben (un registro, un error con el cuerpo, una extensión, el historial del navegador antes del `replaceState`, el `sessionStorage` de un equipo compartido), quien lo tenga **entra a ENGRAMA como esa persona durante lo que le quede de la hora**: ve y responde sus retos, pide su historial, y si es docente, ve y opera sus grupos. Cerrar sesión en ENGRAMA no lo revoca (S-10). Con S-1 cerrado ya no sirve para cambiar correo y contraseña (Caddy deja pasar solo `POST /auth/v1/token` y `/logout`).

### 0.3 Lo que esta espec mide del backend (no cambia)
| Qué | Dónde |
|---|---|
| Mapa de guardas de todas las rutas | `tests/teachers/test_access.py` (`EXPECTED_GUARDS`) |
| Rutas públicas declaradas, y bloqueo de la contraseña temporal en todas las demás | `tests/auth/test_todas_las_rutas.py` (`PUBLICAS`, AH19) |
| 422 sin eco en toda ruta con cuerpo, descubierta de `app.routes` | `tests/seguridad/test_422_sin_eco.py` (SE2) |
| Los clientes de Supabase no tienen privilegios en `public`, tampoco en lo que se cree después | `031_sin_acceso_directo.py`; `tests/seguridad/test_sin_acceso.py` (D12: **47** tablas hoy) |
| `alembic_version` fijado en 12 humos y en el arnés (ERR-25) | `git grep -l 045_correccion_por_pregunta -- tests`: 14 archivos (12 humos, el arnés y el test de la propia 045, que no cambia) |
| `tablas_con_rls: 46` | `tests/integ_db.py:67` |
| Caddy: `/api/events*` responde 404 desde afuera; EVA y SET llegan al backend por la red interna (`http://backend:8000`) | `despliegue/Caddyfile:111-119`; `docker-compose.yml:223` y `:333` |

## 1. Qué cambia (una cosa)
**Lo que viaja en el enlace a EVA y a SET deja de ser el token de sesión y pasa a ser un pase acotado:** corto, de un solo uso, atado a una audiencia (`eva` o `set`) y a una institución, que solo el backend canjea, y solo por la identidad mínima que esa pieza ya usa hoy. Fuera del canje no sirve para nada en ENGRAMA.

Este repo (backend) hace la parte **aditiva**: emite y canjea. Las demás piezas cambian en las fases 2 a 4 (§6), especificadas aquí para otros agentes.

### 1.1 El pase
- Forma: `pa1_` + 43 caracteres de `secrets.token_urlsafe(32)` (256 bits al azar) = 47 caracteres, solo `[A-Za-z0-9_-]` después del prefijo. El prefijo permite a EVA y a SET distinguirlo de un JWT (que empieza por `eyJ` y lleva puntos) sin preguntar a nadie.
- **La base guarda solo `sha256(pase)` en hexadecimal**, nunca el pase. Con 256 bits al azar no hace falta sal ni secreto adicional.
- Vida: `ANILLO_PASE_TTL_S`, **300 s por defecto (PROVISIONAL)**, entre 30 y 900. Razón: el camino largo es el estudiante que corrige en EVA un código de sala mal escrito (EVA revisa el código antes de canjear, así que el error no gasta el pase); el resto se canjea en segundos. Vencido el plazo sin uso, muere.
- **Un solo uso.** El primer intento de canje lo gasta, salga bien o mal (audiencia equivocada, vencido, cuenta suspendida…). Gastarlo es atómico: `UPDATE … SET usado_en = now() WHERE hash = :h AND usado_en IS NULL RETURNING …`, con **commit inmediato, antes de cualquier otra revisión**. Dos canjes a la vez del mismo pase: gana uno.
- **Atado a la institución activa** al emitirlo (la que resolvió `get_current_user` con `X-Tenant-ID`). El canje responde con esa institución como activa; SET ya no depende del `tenant=` del enlace para saber cuál es.
- **Atado a la audiencia:** `eva` o `set`. Quien canjea declara la suya; si no coincide, 401. Un pase para EVA que llegue a SET no abre nada (y queda gastado).

### 1.2 `POST /anillo/pases` (emitir)
- **Guarda `user`** (`get_current_user`): JWT válido, perfil, cuenta activa, contraseña definitiva (con la temporal: 403 `must_change_password`, como toda ruta fuera de las 4 permitidas; AH19 lo vigila solo), membresía activa y `X-Tenant-ID` como en todas las rutas.
- **Cuerpo** estricto, `extra="forbid"`: `{"audiencia": "eva" | "set"}`. Otra cosa: 422 (sin eco, SE2).
- **201** `{"pase": "pa1_…", "audiencia": "eva", "expira_en_s": 300}`, con `Cache-Control: no-store`.
- **Tope:** 10 pases vivos (sin usar y sin vencer) por persona (`ANILLO_PASES_VIVOS_MAX`, 1 a 100). El 11.º: **429** `demasiados_pases`, sin escribir nada.
- **Limpieza:** cada emisión borra los pases vencidos hace más de 24 h (de cualquiera). Sin tarea programada.
- No guarda IP ni dispositivo.

### 1.3 `POST /anillo/canje` (canjear)
- **Pública para la aplicación** (no lleva JWT: lo autentica el propio pase) y **cerrada en el borde**: Caddy responde 404 a `/api/anillo/canje*` desde afuera, igual que a `/api/events*` (fase 1, `despliegue/Caddyfile`). EVA y SET la llaman por la red interna (`http://backend:8000/anillo/canje`), como ya llaman a `/auth/me`.
- **Cuerpo** estricto: `{"pase": "<1 a 4.096 caracteres>", "audiencia": "eva" | "set"}`. El tope es el que EVA y SET ya aceptan para un pase; con él, un token de sesión (más de 200 caracteres) recibe el 401 de PA8 y no un 422 (corregido al medir PA8: con un tope de 200 daba 422; el criterio no cambió).
- **Orden:** (1) gastar el pase y hacer commit; (2) si no existía, ya estaba usado, venció o es de otra audiencia: **401** `pase_invalido`, un solo cuerpo para los cuatro casos; (3) las revisiones de `get_current_user`, con el mismo `detail` que hoy devuelve `/auth/me`: perfil inexistente (403 `Account has no ENGRAMA profile`), suspendida (403 `account_suspended`), contraseña temporal (403 `must_change_password`), sin membresías y con inscripción pendiente (403 `pending_approval`), sin membresía activa en la institución del pase (403 `User is not a member of the requested tenant`). EVA y SET ya saben explicar esos `detail` (`EVAGAME/servidor/pases.py:22-29`; `grade-exam/index.ts:27315-27321`).
- **200**: el carné (`Cache-Control: no-store`). Es un subconjunto de `ProfileOut` con los mismos nombres, para que EVA y SET reusen su lectura de `/auth/me` sin tocarla:

```json
{
  "id": "<uuid del perfil>",
  "full_name": "<nombre de la membresía de esa institución, o el del perfil>",
  "is_active": true,
  "must_change_password": false,
  "consent_version": "2026-10-v1",
  "active_tenant_id": "<la institución del pase>",
  "memberships": [ { "tenant_id": "<la misma>", "tenant_name": "…", "tenant_slug": "…",
                     "role": "student", "group_code": "UIS-01", "is_active": true, "full_name": "…" } ],
  "audiencia": "set",
  "grupos_docente": null
}
```
  - **Una sola membresía:** la de la institución del pase. No viajan las otras instituciones ni sus nombres.
  - **No viajan** `documento_id`, `xp`, `level`, rachas, `last_attendance_date` ni `confirmed_level`: ni EVA ni SET los leen (§0.1).
  - `grupos_docente`: solo con `audiencia = "set"` y rol `teacher`, los códigos de los grupos que `GET /teachers/groups` le mostraría (`access.visible_groups`), ordenados. `null` en todo lo demás (para un `admin`, SET ya entiende `null` como «toda la institución»). Con esto SET deja de llamar a `/teachers/groups` con la credencial del docente.
- No escribe nada más que `usado_en`.

### 1.4 Lo que el pase NO abre
Un pase (vivo o gastado) como `Authorization: Bearer` en cualquier otra ruta: **401**, porque no es un JWT (`validate_jwt` lo rechaza). Y presentarlo así **no lo gasta**. Al revés, un token de sesión presentado en `/anillo/canje`: 401 `pase_invalido` (no está en la tabla).

### 1.5 Migración `046_anillo_pases` (aditiva)
```sql
CREATE TABLE IF NOT EXISTS anillo_pases (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  hash        TEXT NOT NULL,
  profile_id  UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  audiencia   TEXT NOT NULL,
  creado_en   TIMESTAMPTZ NOT NULL DEFAULT now(),
  expira_en   TIMESTAMPTZ NOT NULL,
  usado_en    TIMESTAMPTZ,
  CONSTRAINT anillo_pases_hash_key UNIQUE (hash),
  CONSTRAINT anillo_pases_audiencia_check CHECK (audiencia IN ('eva','set')),
  CONSTRAINT anillo_pases_hash_check CHECK (hash ~ '^[0-9a-f]{64}$')
);
CREATE INDEX IF NOT EXISTS idx_anillo_pases_perfil ON anillo_pases (profile_id);
CREATE INDEX IF NOT EXISTS idx_anillo_pases_expira ON anillo_pases (expira_en);
ALTER TABLE anillo_pases ENABLE ROW LEVEL SECURITY;   -- sin políticas, como la 045
```
- La hora la pone siempre la base (`now()`), al emitir y al canjear: el reloj de la aplicación no entra (el de la base de pruebas retrocede, `ESPEC_login_piloto.md` §3, y aquí no importa porque se compara en la misma transacción).
- Los privilegios de clientes ya los niega la 031 (`ALTER DEFAULT PRIVILEGES`); D12 lo vuelve a medir con 48 tablas.
- Downgrade: `DROP TABLE IF EXISTS anillo_pases`. En producción no se baja.

### 1.6 Configuración nueva
`ANILLO_PASE_TTL_S` (300; 30 a 900) y `ANILLO_PASES_VIVOS_MAX` (10; 1 a 100). Sin secretos nuevos.

## 2. Qué NO se toca
- `validate_jwt`, `get_current_user`, `/auth/me`, `/auth/session`, `/teachers/groups` y todas las rutas que existen: **idénticas**. EVA y SET siguen funcionando con el token completo hasta la fase 4 (§6).
- La lista de rutas permitidas con contraseña temporal (4 pares, UP3).
- La puerta de eventos (`/events/batch`) y sus secretos.
- El piloto, sus bases y sus contenedores. Supabase de SET (local o producción). Nada se despliega.
- En este commit: engrama-web, EVA, SET y `despliegue/` (sus cambios van en §6, para otros agentes).

## 3. Criterios (qué debe pasar, medible) y cómo sabremos que FALLÓ

| Id | Qué se mide | Pasa si | Su tramposo (debe ponerlo ROJO) |
|---|---|---|---|
| PA1 | Forma del pase (no-integ) | 2.000 pases: todos `^pa1_[A-Za-z0-9_-]{43}$`, todos distintos; el hash es `sha256` en hex y no contiene el pase | ZA1: `token_urlsafe(16)` (22 caracteres) |
| PA2 | Emitir | 201, `{pase, audiencia, expira_en_s: 300}`, `Cache-Control: no-store`; en la base hay UNA fila con `sha256(pase)`, la persona, la institución activa (la de `X-Tenant-ID` en una persona de dos instituciones) y vida de 300 s; **el pase no aparece en ninguna columna** | ZA2: guardar el pase en claro en `hash` |
| PA3 | Canjear da el carné mínimo | Estudiante en dos instituciones, pase emitido con la segunda: `active_tenant_id` = la segunda; `memberships` = solo esa; sin `documento_id`, `xp`, `level`; `audiencia` = la pedida; `grupos_docente` = `null`. Docente con `set`: sus grupos (solo los asignados, ordenados); con `eva`: `null` | ZA3: devolver todas las membresías |
| PA4 | Un solo uso | El segundo canje del mismo pase: 401 `pase_invalido` | ZA4: el `UPDATE` sin `usado_en IS NULL` |
| PA5 | Audiencia | Pase `eva` canjeado como `set`: 401; después, como `eva`: 401 (quedó gastado) | ZA5: no comparar la audiencia |
| PA6 | Vencido | Con `expira_en` en el pasado: 401 | ZA6: no mirar `expira_en` |
| PA7 | Las revisiones de la cuenta y el gasto | Suspendida: 403 `account_suspended`; contraseña temporal: 403 `must_change_password`; sin membresía en la institución del pase: 403. **En los tres, después de reparar la cuenta, el mismo pase da 401** (el primer intento lo gastó) | ZA7: hacer commit DESPUÉS de las revisiones (el 403 deshace el gasto y el reintento da 200) |
| PA8 | El pase no sirve para nada más | Un pase vivo como `Bearer` en TODAS las rutas no públicas de `app.routes`: 401 en todas; y después sigue sin gastar (`usado_en` nulo) y canjea 200. Un token de sesión en `/anillo/canje`: 401 | ZA8: `validate_jwt` que acepta pases vivos como sesión |
| PA9 | Tope de pases vivos | 10 vivos: el 11.º da 429 `demasiados_pases` y no escribe; un pase gastado o vencido no cuenta (después de gastar uno, se emite otro) | ZA9: sin tope |
| PA10 | Dos canjes a la vez | Dos sesiones de base canjean el mismo pase a la vez: exactamente uno lo obtiene | ZA10: «leer y luego escribir» (un `SELECT` y después el `UPDATE`), con las dos lecturas forzadas antes de las escrituras |
| PA11 | Guardas | `POST /anillo/pases` = `user`; `POST /anillo/canje` = `public` y declarada en `PUBLICAS` de AH19 | (U4 y AH19 ya fallan con una ruta nueva no declarada: ZH19b) |
| MG46 | Migración | sube, baja y vuelve a subir idéntica; RLS sin políticas; las tres restricciones y los dos índices | — (como MG45) |

Además, **sin regresión**: la suite completa da los mismos resultados que en `f7f7aeb` salvo los números que esta espec declara que se mueven (§4.2). Si algo más cambia, se detiene todo.

**Humo (HPA1).** Semilla fija `random.Random(46)`: 2 instituciones, 4 estudiantes (uno en las dos) y 1 docente con 2 grupos. Cada persona emite un pase por audiencia, se canjean todos, se reintenta uno (elegido con la semilla), se cruza uno de audiencia, se vence uno y se prueba uno como Bearer en `/auth/me`. Escribe `tests/_salida/humo_pase_acotado.json` (en `.gitignore`) **antes** de afirmar, con: `alembic_version`, conteos de 201/200/401/403, filas en `anillo_pases`, cuántas gastadas, y si algún pase aparece en la base (`false`). Valores esperados, fijados antes de correrlo: 13 emitidos (201), 11 canjes 200, 3 canjes 401 (el reintento, el cruzado y el vencido), 0 canjes 403, `/auth/me` con el pase como Bearer 401, 13 filas y 13 gastadas, la estudiante de dos instituciones entra por la del pase, y la docente recibe `["H-1", "H-2"]`.

**Réplica (RPA1).** Solo con `ENGRAMA_REPLICA_PASE=1`: entradas que no se usaron al desarrollar: una docente en tres instituciones que emite en la tercera; 10 pases emitidos y canjeados en orden inverso; una persona con nombre con ñ y tildes en la membresía; y un pase con un carácter cambiado (401, **y el verdadero sigue sirviendo**: adivinar mal no gasta el pase de nadie). Escribe `tests/_salida/humo_pase_acotado_replica.json`. Mismo veredicto que el humo, o vale el menor.

## 4. Archivos (backend, este commit)
### 4.1 Nuevos
`src/anillo/__init__.py`, `schemas.py`, `service.py`, `router.py`; `alembic/versions/046_anillo_pases.py`; `tests/anillo/` (PA1 a PA11, ZA1 a ZA10, HPA1, RPA1); `tests/integ/test_migracion_046.py`.
### 4.2 Que cambian, y solo en esto
- `src/main.py`: incluir el router en `/anillo`.
- `src/shared/config.py`: las dos variables de §1.6.
- `src/shared/models.py`: la clase `AnilloPase` (el arnés trunca por `Base.metadata`).
- `tests/teachers/test_access.py`: las 2 rutas en `EXPECTED_GUARDS`.
- `tests/auth/test_todas_las_rutas.py`: `("/anillo/canje", "POST")` en `PUBLICAS`.
- `tests/integ_db.py`: `alembic_version` → `046_anillo_pases`, `tablas_con_rls` 46 → 47.
- `tests/seguridad/test_sin_acceso.py`: 47 → 48 tablas (D12).
- `tests/tramposos/test_tramposos_422_sin_eco.py`: el número de rutas con cuerpo que ZE1 y ZE2 ponen rojas sube en 2 (22 → 24 y 20 → 22): las dos rutas nuevas tienen cuerpo y SE2 las descubre solo.
- Los 12 humos con `alembic_version` fijado: `045_correccion_por_pregunta` → `046_anillo_pases` (ERR-25; solo esa cadena).
- `.gitignore`: los dos archivos de salida nuevos (`tests/_salida/humo_pase_acotado.json` y `humo_pase_acotado_replica.json`).

## 5. Diseño: por qué así (y lo descartado)
- **Opaco y en la base, no un JWT firmado.** Un JWT de corta vida no da «un solo uso» sin guardar estado, y firmarlo con el secreto de GoTrue lo haría válido en `validate_jwt` (justo lo que se quiere evitar). Una fila con hash es lo más simple que da un solo uso, revocación y auditoría.
- **El canje responde con la forma de `/auth/me`** (subconjunto con los mismos nombres): en EVA y en SET el cambio es la llamada HTTP, no la lectura.
- **Sin firma de servicio en el canje (por ahora).** El canje está cerrado en Caddy y la audiencia la declara la pieza honesta que canjea; con un pase robado solo se obtiene, una vez, el carné de esa persona para esa pieza. **Para después:** si EVA corre fuera de la red interna (un portátil en el aula) o SET pasa a la nube, el canje debe ir firmado con el secreto HMAC de ese origen (el de `/events`) y con límite de intentos. Eso es otra espec.
- **Descartado: que el pase sirva en `/auth/me`.** Mantendría a EVA y a SET sin cambios, pero el pase seguiría siendo una credencial de la API.
- **Descartado: varios usos dentro de la vida.** SET docente reusa hoy la credencial en cada llamada; se resuelve con una sesión de SET (fase 2), no ensanchando el pase.

## 6. Plan por pieza y orden de despliegue (compatibilidad durante la transición)
El anillo no se rompe en ningún paso: cada fase funciona con la anterior y con la siguiente, y cada una se revierte sola.

| Fase | Pieza | Qué cambia | Funciona con | Se revierte |
|---|---|---|---|---|
| **1** | backend (este commit) + Caddy | Emitir y canjear (§1). Caddy: `@puertaCanje path /api/anillo/canje*` → 404, antes de `handle /api/*` | web, EVA y SET de hoy: nada cambia para ellos | quitar el router (la tabla puede quedar) |
| **2** | EVA y SET | Doble camino: pase que empieza por `pa1_` → `POST /anillo/canje`; si no, el camino de hoy (`/auth/me`). SET docente pasa a sesión de SET | web de hoy (token completo) y web nueva (pase acotado) | volver a la versión anterior |
| **3** | web | `pedirPase(audiencia)` llama a `POST /api/anillo/pases`; el enlace lleva el `pa1_…` | EVA y SET de la fase 2 | volver a la versión anterior (EVA/SET aún aceptan el token) |
| **4** | EVA, SET y guiones de `despliegue/` | Cierre: un pase que no empieza por `pa1_` se rechaza (401) **sin llamar al backend**; se quita el camino viejo. Los guiones E2E emiten pases por la API | web de la fase 3 | volver a la fase 2 |

**S-10 queda cerrado al terminar la fase 3** (el token de sesión ya no sale de ENGRAMA) **y blindado en la fase 4** (aunque alguien vuelva a mandarlo, EVA y SET no lo aceptan). La fase 4 solo se despliega cuando la regresión del anillo pasó con la fase 3 desplegada.

### 6.1 Fase 1 · despliegue (Caddy)
En `despliegue/Caddyfile`, junto a `@puertaEventos`:
```
@puertaCanje path /api/anillo/canje*
handle @puertaCanje {
	respond "No encontrado" 404
}
```
Criterio: desde afuera, `POST /api/anillo/canje` → 404; `POST /api/anillo/pases` con sesión → 201; desde el contenedor de EVA, `POST http://backend:8000/anillo/canje` → 401 con un pase falso. Tramposo: sin el bloque, el POST de afuera responde 401 (llega al backend) en vez de 404.

### 6.2 Fase 2 · EVA (`EVAGAME/servidor`)
- `pases.py`: `VerificadorPases._consultar(pase)` → si `pase.startswith("pa1_")`: `POST {backend}/anillo/canje` con `{"pase": pase, "audiencia": "eva"}` (sin `Authorization`, con el mismo abridor sin proxies ni redirecciones); si no, `GET /auth/me` como hoy. La lectura (`_perfil`, `_exigir_contrato`, `_tiene_rol`) no cambia: el carné tiene esos campos. `active_tenant_id` del carné debe ser `self.tenant_id`; si no, 403 `pase_sin_acceso` (ya lo hace).
- 401 del canje → `ErrorSala("pase", 401, "Tu enlace de ENGRAMA ya se usó o venció. Vuelve a ENGRAMA y toca «Clase en vivo» otra vez.")` (texto PROVISIONAL; en el tablero, «… y abre el tablero otra vez»).
- `estaticos/estudiante.js:191`: con 401 el pase se suelta (no se reintenta con él); con 403 `codigo_sala` se conserva, como hoy (el código va antes del canje: `anillo.py:144-146`).
- Doble del backend (`tests/servidor/doble_backend.py`) con `POST /anillo/canje` de un solo uso.
- Criterios: E-PA1 un pase `pa1_` entra una vez y el segundo `unirse` con él da 401; E-PA2 con código de sala malo el pase NO se gasta (el doble cuenta 0 canjes) y con el bueno entra; E-PA3 un JWT sigue entrando por `/auth/me` (fase 2); E-PA4 el pase no aparece en ningún registro ni respuesta (el A02 que ya existe, extendido). Tramposos: canjear antes de revisar el código (E-PA2 rojo); mandar el pase en `Authorization` al canje (el doble lo rechaza).

### 6.3 Fase 2 · SET (`SET/supabase/functions/grade-exam/index.ts` y `local/portal/`)
- `preguntarAEngrama(pase, tenant, roles)`: si `pase` empieza por `pa1_`, `POST {ENGRAMA_API_URL}/anillo/canje` con `{"pase", "audiencia": "set"}`; si no, `GET /auth/me` como hoy. Con el carné, el `tenant=` del enlace solo se compara: si viene y no es `active_tenant_id`, 400 `tenant_invalido` (T-1 de hoy, sin preguntar más). Con una sola membresía en el carné, la regla 409 `tenant_requerido` ya no se dispara.
- **Docente (`revisar`): sesión de SET.** El primer `writing_pendientes` con pase canjea UNA vez y abre una sesión de docente en SET (id al azar; guarda `profile_id`, `tenant_id`, rol y **los grupos**: `grupos_docente` del carné, o los de `/teachers/groups` en el camino viejo); vida **1 h** (igual que hoy el token). La respuesta trae `engrama.sesion`; `revisar.html` la guarda en memoria y la manda en las llamadas siguientes en lugar del pase. `accesoDocente` acepta `engrama.sesion` (lee la identidad y los grupos de la sesión). Tabla nueva en la base de SET (p. ej. `engrama_sesiones_docente`) o columna `rol` en `engrama_sesiones`: lo decide el creador de SET, con su migración y su prueba de privilegios.
- Estudiante: sin cambios en la página (la sesión de SET ya existe); en la función, solo el cambio de `preguntarAEngrama`.
- `local/doble_backend.js`: `POST /anillo/canje` de un solo uso, con audiencia.
- Criterios: S-PA1 `get_config` con un pase `pa1_` vincula y un segundo `get_config` con el mismo pase da 401; S-PA2 con un código de examen inexistente (404) el pase NO se gasta; S-PA3 `revisar` con pase: la primera llamada canjea, las siguientes (página 2, calificar) no llaman al backend de ENGRAMA (el doble cuenta 1 canje y 0 `/teachers/groups`); S-PA4 un JWT sigue entrando por `/auth/me` (fase 2); S-PA5 un pase de audiencia `eva` no abre SET. Tramposos: revisar que reenvía el pase en cada llamada (S-PA3 rojo); canjear antes de buscar el examen (S-PA2 rojo).
- SET tiene su propia puerta de verificación: usarla (`/puerta-verificacion`).

### 6.4 Fase 3 · engrama-web
- `src/app.js:187`: `pedirPase: (audiencia) => pedirPaseAcotado(audiencia)`, una función nueva en `src/api/` que hace `POST /api/anillo/pases` con el Bearer y el `X-Tenant-ID` de siempre y devuelve `pase`. Errores: 403 `must_change_password` y 429 con su texto; ningún error lleva el pase.
- `src/anillo/abrir.js:86`: `ctx.pedirPase(audienciaDe(destino))`, con `audienciaDe = destino.startsWith('set_') ? 'set' : 'eva'`.
- `enlace.js` no cambia (el formato del enlace es el de la decisión 013); su comentario pasa a decir que el pase es acotado.
- Criterios: W-PA1 el enlace lleva `pase=pa1_…` y nunca el token de sesión (el doble de la API marca el token y el E2E lo busca en la URL de salida); W-PA2 la audiencia sale del destino (los 5); W-PA3 el pase sigue sin estar en `href`, consola ni almacenamiento (los U31 de hoy). Tramposos: `pedirPase` que devuelve el token (W-PA1 rojo); audiencia fija `eva` (W-PA2 rojo con `set_examen`).

### 6.5 Fase 4 · cierre
- EVA y SET: un pase que no empieza por `pa1_` → 401 sin llamar al backend; se borra el camino de `/auth/me` y el de `/teachers/groups`. Tramposo: un JWT válido del doble entra (debe dar 401).
- `despliegue/`: los guiones que arman enlaces con el token (`anillo_enlaces.mjs`, `anillo_eva.mjs`, `anillo_set.mjs`, `clase_eva_piloto.mjs`, `e2e_anillo*.mjs`, `e2e_set_universal.mjs`, `humo_anillo*.mjs`, `recorrido_enlaces.mjs`, `verificar_anillo_set_vivo.mjs` y los demás de `grep -l pase despliegue/*.mjs`) emiten un pase por la API para **cada** entrada (un pase ya no sirve para varios estudiantes por HTTP).
- La decisión 013 recibe una adenda: «el pase es acotado (`pa1_…`), de un solo uso, por audiencia; ver ESPEC_pase_acotado».

## 7. Riesgos declarados
- **Un fallo después del canje gasta el pase** (EVA: sala llena o cerrada; SET: examen sin ítems, sesión que no abre, «ya presentó»). La persona vuelve a ENGRAMA y toca otra vez. Es el precio del solo uso; los textos lo dicen.
- **Doble toque o recarga en EVA/SET** con el pase ya gastado: 401 y el mismo texto. La web ya bloquea el segundo toque (`abrir.js`).
- **La sesión de docente de SET guarda los grupos por 1 h**: un docente al que le quitan un grupo lo sigue viendo en SET hasta que venza (hoy pasa lo mismo con el token, que dura 1 h).
- **La tabla crece** con cada salida a EVA o SET; la limpieza de 24 h la acota a un día de uso.
