# ESPEC · El admin invita profes por correo, sin terminal y sin contraseñas temporales

- **Fecha:** 2026-10-26. **Autor:** creador (Opus). **Estado:** preregistro (se commitea antes del código).
- **Ramas:** backend `cuentas/invitar-profe` sobre `juego/sprint-backend` @ `d275074`; web `cuentas/invitar-profe` sobre `juego/sprint-web` @ `6ffbea3`.
- **Origen:** Christiam, para empezar las pruebas: "nada de asignar contraseñas de prueba". Es la puerta de cuentas: **método completo**.
- **Base del correo:** `ENGRAMA/despliegue/docs/ESPEC_correo_recuperacion.md` (rama `servidor/correo` de engrama-docs, `f0175b3`): GoTrue v2.196.0 + Brevo, plantilla servida por Caddy en `http://caddy:8091/`.

## 0. En cinco líneas

1. El admin escribe nombre y correo del profe y elige su grupo (o lo crea antes con la ruta de siempre, `POST /admin/groups`).
2. El backend crea el perfil del profe (rol `teacher`, en ESA institución y ese grupo) y responde **de una vez**, sin esperar a GoTrue.
3. Después de responder, el backend crea la cuenta en GoTrue **sin contraseña y sin confirmar**, con `id = profiles.id`, y le pide a GoTrue el correo de **invitación** (`POST /invite`), con su propia plantilla en español.
4. El profe toca "Crear mi contraseña", la escribe y entra. La invitación pasa a "Aceptada" cuando el backend baja la bandera `force_password_reset` (la misma ruta `POST /auth/contrasena` de hoy).
5. Si el correo ya tiene cuenta (en otra institución o donde sea), **todo se ve igual** para el admin: misma respuesta, mismas filas, misma lista. Solo que no sale ningún correo y nadie acepta nunca.

## 1. Qué había (leído y medido el 2026-10-26)

| Qué | Dónde |
|---|---|
| Crear cuentas en GoTrue con el id del perfil | `src/onboarding/cuentas.py` (`GoTrueAdmin.crear(id, correo, clave)`, siempre con contraseña y `email_confirm: true`) |
| La clave de servicio, cercada | `src/registro/cuentas.py` es el ÚNICO módulo del proceso web que la usa; `tests/registro/test_unit.py` SR1 lo hace cumplir |
| El admin crea grupos y asigna docentes | `src/teachers/admin_router.py` M1-M4; `access.authorize_group` da 404 al grupo ajeno |
| Un docente sin cuenta se da de alta por la CLI del operador con contraseña temporal | `src/onboarding/alta.py` + `restablecer.py` (lo que Christiam ya no quiere) |
| La bandera "contraseña temporal" | `profiles.force_password_reset`; la baja `POST /auth/contrasena` cuando GoTrue acepta la nueva (`src/auth/router.py`) |
| Web: canjear un enlace del correo y poner la contraseña | `engrama-web` `src/vistas/recuperar.js` (`#/recuperar?token_hash=`), canje `POST /auth/v1/verify {type: "recovery"}` |
| Caddy ya abre `POST /auth/v1/verify` y `POST /auth/v1/recover` (4 KB) | parche de `ESPEC_correo_recuperacion` §3.1 |
| Suite del backend en la base `d275074` | se mide antes de tocar (§9) |

### 1.1 GoTrue v2.196.0, medido en un banco desechable (P1-P12)

Banco: `public.ecr.aws/supabase/gotrue:v2.196.0` + `supabase/postgres:17.6.1.167` + `supabase/mailpit:v1.30.2`, secretos sintéticos, `GOTRUE_DISABLE_SIGNUP=true`, `GOTRUE_MAILER_AUTOCONFIRM=false` (como el servidor).

| # | Petición | Respuesta medida |
|---|---|---|
| P1 | `POST /admin/users {id, email, email_confirm: false}` **sin** `password` | 200; respeta el `id`; `email_confirmed_at` nulo |
| P2 | `POST /invite {email}` a esa cuenta (existe, sin confirmar) | 200; **1** correo, con el asunto de `GOTRUE_MAILER_SUBJECTS_INVITE` y la plantilla de `GOTRUE_MAILER_TEMPLATES_INVITE` (trae `{{ .TokenHash }}`) |
| P3 | `POST /invite` otra vez, enseguida | 200 y **otro** correo: para la invitación GoTrue **no** aplica `SMTP_MAX_FREQUENCY`. El token cambia y el viejo deja de servir (403 `otp_expired`) |
| P4 | `POST /verify {type: "invite", token_hash}` | 200 con sesión; `sub` = el `id` de P1 |
| P4b | el MISMO token con `type: "recovery"` | **403** `otp_expired`: la web tiene que mandar `type: "invite"` |
| P4d | el mismo token por segunda vez | 403 (sirve una vez) |
| P5-P6 | `PUT /user {password}` con esa sesión; después `POST /token` | 200 y 200 |
| P7 | `POST /invite` a una cuenta ya confirmada | 422 `email_exists` |
| P8 | `POST /admin/users` con un correo que ya existe (también en MAYÚSCULAS) | 422 `email_exists` |
| P9 | `POST /invite` a un correo **sin** cuenta, con el registro apagado | **200 y crea la cuenta** con un id que elige GoTrue. Por eso el backend **nunca** llama `/invite` sin haber creado antes la cuenta con su id |
| P10 | alternativa: crear confirmada sin clave + `POST /recover` | funciona, pero llega el correo de recuperar ("Alguien pidió cambiar la contraseña…"), que no sirve de invitación |
| P11 | login con clave vacía a la cuenta invitada sin aceptar | 400 `invalid_credentials`. `POST /recover` a esa cuenta sin confirmar **sí** manda el correo de recuperar: es la salida si la invitación venció |
| L1 | límite 3 por hora, 5 invitaciones seguidas | 200, 200, 200, 429 `over_email_send_rate_limit`, 429; y un `/recover` después también 429. **Invitar y recuperar gastan el MISMO cubo** de `GOTRUE_RATE_LIMIT_EMAIL_SENT` |

### 1.2 Decisión: el invite de GoTrue con su plantilla (y no el correo de recuperar)

| | Invite de GoTrue (elegido) | Crear confirmada + `/recover` |
|---|---|---|
| Texto del correo | propio: "Te invitaron a ENGRAMA como profe" | el de recuperar: "Alguien pidió cambiar la contraseña…", confunde a quien nunca tuvo cuenta |
| Aceptada | GoTrue confirma el correo al canjear; el backend baja la bandera | igual |
| Reenvío | `/invite` otra vez mientras no esté confirmada (P3) | `/recover` (sujeto a `SMTP_MAX_FREQUENCY` de 60 s) |
| Riesgo | `/invite` crea cuentas si el correo no existe (P9): se cierra llamándolo **solo** después de crear la cuenta con nuestro id y de comprobar por id que es nuestra | ninguno nuevo |
| Cambios fuera del backend | una plantilla más y dos variables de GoTrue; en la web, `type: "invite"` | ninguno |

**Se elige el invite.** El texto equivocado es lo primero que ve un profe de la UIS o del SENA; y el riesgo del invite se cierra en código con una prueba (IP3, tramposo XP2).

### 1.3 Decisión: la respuesta no espera a GoTrue (correo ajeno indistinguible)

El admin no debe aprender si un correo tiene cuenta en otra institución. Hay tres canales por donde se aprendería:

| Canal | Cómo se cierra |
|---|---|
| El código y el cuerpo de la respuesta | `POST /admin/invitaciones` responde **201 con el mismo cuerpo** para un correo nuevo y para uno con cuenta |
| Lo que el admin ve después (la lista de invitaciones, la lista de profes, los presupuestos) | en los dos casos se crean **las mismas filas**: perfil `teacher` con `force_password_reset = true`, membresía con el nombre que escribió el admin, asignación al grupo e invitación. Con el correo ajeno el perfil se queda sin cuenta de GoTrue: nadie entra con él y la invitación se ve "Enviada" para siempre, igual que una que el profe nunca abrió |
| El tiempo | GoTrue se llama **después** de responder (`BackgroundTasks` de FastAPI): la respuesta solo hace trabajo de base, igual en los dos casos. El humo mide los dos tiempos en el banco (H7) |

El reenvío hace lo mismo: 202 con el mismo cuerpo y GoTrue en segundo plano.

**Lo que esto cuesta (dicho una vez):** si GoTrue no manda el correo (caído, o el cubo de 12 por hora lleno: L1), el admin ve "Enviada" igual. Se registra en el log del backend con el id de la invitación (sin correo) y el admin tiene "Reenviar". Contarle al admin "no se pudo enviar" le diría, con el cubo lleno, cuáles correos tienen cuenta en otra parte.

## 2. Qué cambia (UNA cosa)

**El admin de una institución invita a un profe por su correo desde la web; el profe crea su propia contraseña con el enlace y entra con el rol `teacher` en ese grupo.**

Todo lo de abajo es lo mínimo para eso: una tabla, tres rutas, tres métodos del adaptador de GoTrue, una plantilla de correo, una pantalla del admin y el canje del enlace en la web.

## 3. Contrato del backend

Todas bajo `/admin`, con `require_admin` (admin de la institución activa; `super_admin` no existe como rol de membresía: el CHECK de `memberships` solo admite `admin`, `teacher`, `student`, así que el super_admin entra por su membresía `admin` como cualquier admin). La institución sale **siempre** de `auth.tenant_id`, nunca del cuerpo.

### 3.1 `POST /admin/invitaciones`

Cuerpo (estricto, `extra="forbid"`): `{"nombre": str 2-120 sin espacios a los lados, "correo": str 3-254 con forma de correo, "group_id": UUID}`. El correo se guarda en minúsculas.

Orden de las comprobaciones:
1. Cuerpo inválido → **422** (sin eco, el manejador global).
2. Sin GoTrue o sin clave de servicio → **503** `invitar_no_configurado`, 0 filas.
3. Grupo que no es de la institución → **404** `Group not found` (`access.authorize_group`), 0 filas.
4. El admin ya hizo `INVITACIONES_POR_HORA` envíos (invitar + reenviar) en la última hora → **429** `demasiadas_invitaciones` con `Retry-After`, 0 filas. Por admin, en la base (sobrevive a reinicios y a dos procesos), con un candado por admin (`pg_advisory_xact_lock`) para que dos peticiones a la vez no se pasen del tope.
5. Ese correo ya tiene invitación **en esta institución** → **409** `ya_invitado`, 0 filas. (Es dato de su propia institución; otra institución no cuenta.)
6. **201** `InvitacionOut`. Se crean, en una transacción: perfil (`id` nuevo, `documento_id = "inv_" + 24 hex`, `full_name = ""`, `pin_hash = ""`, `role = 'teacher'`, `force_password_reset = true`), membresía `teacher` activa con `full_name = nombre`, `teacher_groups` en ese grupo, la invitación y una fila de `audit_logs` (`invitacion_profe`, `metadata = {invitacion_id, tipo: "invitar"}`, sin correo). Después de responder, `enviar` (§3.4).

### 3.2 `GET /admin/invitaciones`

**200** `[InvitacionOut]` de la institución activa, la más reciente primero.

`InvitacionOut = {id: int, nombre: str, correo: str, group_id: UUID, group_code: str, estado: "enviada" | "aceptada", enviada_en: datetime (el último envío pedido), envios: int}`.

`estado = "aceptada"` si y solo si el perfil ya **no** tiene `force_password_reset` (el profe puso su contraseña con `POST /auth/contrasena`). No se le pregunta a GoTrue: la lista no hace llamadas de red y es igual para el correo ajeno.

### 3.3 `POST /admin/invitaciones/{id}/reenviar`

1. Invitación que no es de la institución activa (o no existe) → **404** `invitacion_no_encontrada`.
2. Ya aceptada → **409** `ya_aceptada`.
3. Pedida hace menos de `INVITACION_ESPERA_REENVIO_S` (60) → **429** `espera_para_reenviar` con `Retry-After`. (GoTrue no limita el reenvío de invitaciones: P3.)
4. Tope del admin → **429** `demasiadas_invitaciones`.
5. **202** `InvitacionOut` con `envios + 1` y `enviada_en` nuevo; auditoría `tipo: "reenviar"`; después de responder, `enviar` (§3.4).

### 3.4 `enviar` (en segundo plano, solo GoTrue y el log)

```
estado = GET /admin/users/{profile_id}
si no existe:
    crear_invitado(profile_id, correo)          # POST /admin/users sin password, email_confirm false
    si correo_en_uso -> "cuenta_ajena": NO se manda nada. Fin.
si existe y su correo no es el de la invitación -> "cuenta_ajena". Fin.   (defensa: nunca pasa con un uuid4)
si existe y ya está confirmada -> POST /recover {correo}   # abrió el enlace y no terminó: correo de recuperar
si no -> POST /invite {correo}
```
Resultado al log (`engrama.invitar`, nivel INFO o ERROR): `invitacion=<id> resultado=<enviada|recuperacion|cuenta_ajena|limite_de_correos|fallo>`. Nunca el correo, el nombre ni la clave de servicio. Ninguna excepción sale de aquí (se registra y termina).

`/invite` se llama **solo** con una cuenta cuyo `id` es el del perfil de ESTA invitación: así nunca reenvía la invitación de otra institución ni crea una cuenta con id ajeno (P9).

### 3.5 Lo que se agrega al código

| Pieza | Qué |
|---|---|
| `alembic/versions/050_invitaciones_docente.py` | tabla `invitaciones_docente` (§3.6). `down_revision = "047_economia_ola1"`: 048 y 049 son de otro agente; al integrar, la que llegue después cambia su `down_revision` (ERR-45) |
| `src/shared/models.py` | modelo `InvitacionDocente` |
| `src/onboarding/cuentas.py` | `GoTrueAdmin.estado_de_cuenta(id)`, `crear_invitado(id, correo)`, `invitar(correo)`, `recuperar(correo)` |
| `src/registro/cuentas.py` | `get_cuentas_de_invitacion()` y el protocolo `CuentasDeInvitacion`. La clave de servicio **sigue en el mismo módulo** (SR1 sin cambios); su docstring suma la invitación |
| `src/invitar/` (nuevo) | `schemas.py`, `service.py` (alta, lista, reenvío, tope), `envio.py` (§3.4), `router.py` (montado en `/admin`) |
| `src/shared/config.py` | `invitaciones_por_hora` (10, de 1 a 100) e `invitacion_espera_reenvio_s` (60, de 0 a 3600) |
| `docs/correo_invitacion.html` | la plantilla del correo (va al servidor como `despliegue/correo/invitacion.html`, §8) |

### 3.6 La tabla

```sql
CREATE TABLE IF NOT EXISTS invitaciones_docente (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  profile_id      UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  group_id        UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  correo          TEXT NOT NULL,
  invitada_por    UUID REFERENCES profiles(id) ON DELETE SET NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  ultimo_envio_en TIMESTAMPTZ NOT NULL DEFAULT now(),
  envios          INTEGER NOT NULL DEFAULT 1,
  CONSTRAINT invitaciones_docente_perfil_key UNIQUE (profile_id),
  CONSTRAINT invitaciones_docente_correo_key UNIQUE (tenant_id, correo),
  CONSTRAINT invitaciones_docente_correo_check CHECK (correo = lower(correo) AND length(correo) BETWEEN 3 AND 254),
  CONSTRAINT invitaciones_docente_envios_check CHECK (envios >= 1)
);
ALTER TABLE invitaciones_docente ENABLE ROW LEVEL SECURITY;   -- y SIN políticas, como 035/036
```

RLS activa y sin políticas: ningún rol de cliente lee ni escribe (además, por la 031, no reciben privilegios sobre tablas nuevas). El aislamiento por institución lo hace el backend (`WHERE tenant_id = auth.tenant_id` en las tres rutas), y lo prueban IP4 y el tramposo XP1. El correo del profe se guarda **solo** aquí, en la fila de su institución.

## 4. Qué debe pasar (medible) y cómo sabremos que FALLÓ

Integración (`tests/invitar/`, Postgres real del arnés, GoTrue con un doble `tests/invitar/_doble.py` que imita lo medido en §1.1). Cada test arma un dict con lo observado y lo compara ENTERO (el mensaje lo trae).

| # | Debe pasar | Falló si (el test se pone rojo) |
|---|---|---|
| IP1 | Invitar un correo nuevo: 201, `estado = "enviada"`, `envios = 1`; en la base, perfil `teacher` con bandera, membresía `teacher` activa con el nombre, `teacher_groups` en el grupo, la invitación y 1 auditoría; GoTrue recibe, en orden, `estado_de_cuenta(perfil)`, `crear_invitado(perfil, correo)`, `invitar(correo)` | falta una fila, otro rol, otra institución, o GoTrue recibe otra cosa |
| IP2 | El profe acepta: con el JWT de su `id`, `POST /auth/contrasena` → 204; la lista dice `aceptada`; `/auth/me` da `teacher` en esa institución con ese grupo y `must_change_password = false` | sigue `enviada`, o el rol o el grupo no son esos |
| IP3 | **Correo con cuenta en otra institución:** la respuesta es la MISMA (estado, claves del cuerpo y valores salvo id, nombre, correo y fechas) que la de un correo nuevo; se crean las mismas clases de filas en la institución A; GoTrue recibe `crear_invitado` → `correo_en_uso` y **nunca** `invitar` ni `recuperar`; la cuenta ajena queda igual (mismo id, mismo correo); nada de la institución B cambia ni aparece en la respuesta de A; el reenvío da 202 igual y tampoco llama `invitar` | cualquier diferencia en lo que ve el admin, o `invitar`/`recuperar` sobre la cuenta ajena |
| IP4 | **Institución y rol:** el admin de B no ve en su lista las invitaciones de A, recibe 404 al reenviar una de A y 404 al invitar al grupo de A (0 filas); un profe y un estudiante de A reciben 403 en las tres rutas | B ve, reenvía o invita en A; un no-admin pasa |
| IP5 | Mismo correo dos veces en la misma institución (también con mayúsculas): 409 `ya_invitado`, 0 filas nuevas, GoTrue recibe una sola invitación | 201, o filas duplicadas |
| IP6 | **Tope por admin** (con `invitaciones_por_hora = 3`): 3 envíos (2 invitar + 1 reenviar) pasan; el 4.º → 429 `demasiadas_invitaciones` con `Retry-After` y 0 filas; otro admin de la misma institución sí puede | el 4.º pasa, o el tope es por institución |
| IP7 | **Espera del reenvío:** reenviar enseguida → 429 `espera_para_reenviar`; con el último envío corrido 61 s atrás → 202, `envios = 2`, y GoTrue recibe `invitar` otra vez; reenviar una aceptada → 409 `ya_aceptada` | el reenvío inmediato pasa, o la aceptada se reenvía |
| IP8 | Cuenta propia ya confirmada y sin contraseña (abrió el enlace y no terminó): el reenvío llama `recuperar(correo)` y no `invitar` | llama `invitar` (GoTrue daría 422) |
| IP9 | GoTrue caído al invitar: 201 igual y las filas quedan; con GoTrue de vuelta, el reenvío (pasada la espera) crea la cuenta y llama `invitar` | 5xx al admin, o el reenvío no recupera |
| IP10 | Sin clave de servicio: 503 `invitar_no_configurado` y 0 filas | otra cosa |
| IP11 | Cuerpo inválido (correo sin @, nombre vacío, campo extra, `group_id` que no es UUID): 422 sin eco | 201, o el 422 trae lo enviado |
| IP12 | **La respuesta no depende de GoTrue:** el alta (`service.invitar`) termina sin hacer NINGUNA llamada a GoTrue (doble que explota en cualquier llamada) y la ruta deja `enviar` en `BackgroundTasks` | el alta llama a GoTrue antes de responder |
| IP13 | Migración 050: sube y baja dos veces (idempotente); RLS activa sin políticas; los roles de cliente sin privilegios | falta RLS o un cliente puede leer |

Sin base (`tests/invitar/test_unit.py`):

| # | Debe pasar | Falló si |
|---|---|---|
| UI1 | `crear_invitado` manda `{id, email, email_confirm: false}` **sin** `password`; 200 → `creada`; 422 `email_exists` → `correo_en_uso` | manda contraseña o `email_confirm: true` (P7: GoTrue ya no invitaría) |
| UI2 | `invitar` 200 → `enviada`; 429 → `limite_de_correos`; 422 `email_exists` → `ya_confirmada`; otro → `ErrorCuenta` | mapea mal un código |
| UI3 | `estado_de_cuenta`: 404 → `None`; 200 → (correo, confirmada) leyendo `email_confirmed_at` | confunde confirmada con no confirmada |
| UI4 | SR1 sigue igual: la clave de servicio solo en `shared/config.py` y `registro/cuentas.py` | la clave aparece en `src/invitar/` |
| UI5 | `enviar` nunca deja salir una excepción y su log no trae el correo | sale una excepción o el correo va al log |

### 4.1 Tramposos (cada uno debe poner rojo SU test, por el motivo dicho)

| Tramposo | Rompe | Rojo |
|---|---|---|
| XP1 | la lista sin `WHERE tenant_id` | IP4: B ve las de A |
| XP2 | con `correo_en_uso`, `enviar` llama `invitar` igual | IP3: `invitar` sobre la cuenta ajena |
| XP3 | con `correo_en_uso`, el alta responde 409 | IP3: respuestas distintas |
| XP4 | sin tope por admin | IP6: el 4.º pasa |
| XP5 | sin espera del reenvío | IP7: el inmediato pasa |
| XP6 | `estado` siempre `enviada` | IP2: no pasa a `aceptada` |
| XP7 | el grupo por id sin `authorize_group` | IP4: invita en el grupo de A |
| XP8 | el alta llama `enviar` antes de responder | IP12: hubo llamadas a GoTrue en el alta |
| XP9 | `crear_invitado` con `email_confirm: true` | UI1 |
| XP10 | el reenvío llama `invitar` sin mirar la cuenta por id | IP3 (reenvío): `invitar` sobre la cuenta ajena |
| XP11 | el correo duplicado no se compara en minúsculas | IP5: la versión en MAYÚSCULAS pasa |

## 5. La web (`engrama-web`, rama `cuentas/invitar-profe`)

| Pieza | Qué |
|---|---|
| `src/vistas/admin/invitar.js` (diferida, en el panel) | `#/admin/invitar`, "Profes: invitar": formulario (nombre, correo, grupo de la lista de grupos o uno nuevo con su código), botón "Invitar", y la lista: cada invitación con ícono y texto ("Enviada" con sobre, "Aceptada" con visto), cuándo se envió y "Reenviar" en las enviadas |
| `src/api/invitaciones.js` | `invitarProfe`, `listarInvitaciones`, `reenviarInvitacion` por `pedirJson` |
| `src/textos_invitar.js` (diferido) | los textos, en español claro |
| `src/vistas/admin/crear_grupo.js` | el enlace "Profes: invitar" en el panel del admin, **solo si** `GET /admin/invitaciones` responde una lista (sin el backend nuevo, el panel queda como antes) |
| `src/app.js` | `#/invitacion?token_hash=` sin sesión (modo `supabase`): la misma pantalla de la contraseña nueva, canjeando con `type: "invite"` y con los textos de bienvenida. El token se lee una vez y se borra de la dirección, como en recuperar |
| `src/auth/supabase_rest.js` | `canjearEnlaceDeInvitacion(tokenHash)` = `POST /auth/v1/verify {type: "invite", token_hash}` |
| `src/vistas/recuperar.js` | acepta textos propios (`ctx.textos`) para la invitación; sin ellos, idéntica |
| `src/navegacion.js` | la fila `/admin/invitar` (rol admin, pestaña Grupos, vuelve a `/admin`) |
| `sw.js` | los módulos nuevos en `DIFERIDOS`; versión `engrama-shell-v79`; las copias rotas de sw.js rehechas |

No se tocan las pantallas del estudiante (otro agente las está cambiando). Vistas con `h()`, sin `innerHTML`; colores solo de tokens.

| # | Debe pasar (`node --test`) | Falló si |
|---|---|---|
| WI1 | Invitar: nombre o correo vacíos, o correo sin @ → mensaje con ícono y 0 peticiones; con datos → 1 `POST /admin/invitaciones` con `{nombre, correo, group_id}` y la lista se vuelve a leer | sale la petición con datos malos, o dos peticiones por un toque |
| WI2 | Grupo nuevo: primero `POST /admin/groups` y después la invitación con el id que devolvió | invita sin grupo o con otro |
| WI3 | La lista pinta cada estado con ícono **y** texto; "Reenviar" solo en las enviadas | estado solo con color, o "Reenviar" en una aceptada |
| WI4 | 409, 429 (con su espera), 404 y sin red → mensajes en palabras; nunca el `detail` crudo | se muestra el código o un texto vacío |
| WI5 | `#/invitacion?token_hash=` sin sesión: 0 peticiones al pintar; al Guardar, `verify` con `type: "invite"`, luego `contrasena` con ese Bearer y `logout`; el token sale de la dirección | canjea al pintar, o con `type: "recovery"` |
| WI6 | `#/recuperar` sigue idéntico (RC1-RC7 en verde, sin tocarlos) | cambia algo de recuperar |
| WI7 | El enlace "Profes: invitar" solo aparece si el backend responde la lista | aparece sin backend |
| WI8 | Los conteos de rutas (admin 7 → 8) y U59 (todo import del panel guardado) en verde | un módulo nuevo sin guardar |

Tramposos de la web: `x_invitar_sin_validar` (WI1), `x_invitar_canjea_como_recovery` (WI5), `x_invitar_estado_sin_texto` (WI3), `x_invitar_reenvia_aceptada` (WI3).

## 6. Humo, réplica y banco

- **Humo (`tests/manual/humo_invitar_banco.py`, banco `tests/manual/banco_invitar/`)**: Docker con GoTrue v2.196.0, Postgres de Supabase, Mailpit (hace de Brevo) y la plantilla servida por Caddy; el backend de esta rama con uvicorn contra esa base. Secretos sintéticos nuevos en cada corrida, solo en el entorno; puertos solo en 127.0.0.1; proyecto propio `engrama-invitar-banco` (no toca el piloto); `down -v` al final. Escribe `tests/_salida/humo_invitar_banco.json` (sin tokens ni secretos). Mide:
  - H1 el admin de A invita un correo nuevo → 201 y llega **1** correo con el asunto en español y el enlace `#/invitacion?token_hash=`;
  - H2 canje `type: "invite"` → `POST /api/auth/contrasena` → 204;
  - H3 login con la contraseña nueva → `/auth/me` `teacher` en A con su grupo; la lista dice `aceptada`;
  - H4 el admin de A invita un correo que ya tiene cuenta en B → 201 con el mismo cuerpo, **0** correos, la cuenta de B sigue entrando con su contraseña; el reenvío → 202 y 0 correos;
  - H5 tiempos de H1 y H4 (la respuesta no espera a GoTrue): se reportan los dos;
  - H6 el reenvío de una aceptada → 409; el admin de B no ve las de A y recibe 404 al reenviar una de A;
  - H7 el tope por admin (con `INVITACIONES_POR_HORA` bajo) → 429;
  - H8 reenvío → llega otro correo; el enlace viejo da 403 y el nuevo sirve.
- **Réplica:** otra corrida del humo con cuentas, secretos y correos nuevos (son al azar en cada corrida): mismo veredicto.

## 7. Qué NO se toca

- `/auth/registro`, el alta de la CLI, `restablecer`, M1-M4 (salvo leer `authorize_group` y crear el grupo por su ruta).
- `POST /auth/contrasena` (se reusa tal cual: ya baja la bandera).
- La cerca de la clave de servicio (SR1): no se agrega ningún módulo a la lista.
- En la web: las pantallas del estudiante, `#/recuperar` (solo acepta textos opcionales), la entrada.
- El Caddyfile, el compose y la plantilla de recuperar del servidor (§8 dice qué agregar; no se aplica aquí).
- Producción: nada se despliega ni se pushea.

### 7.1 Números fijados que este cambio mueve (declarados, ERR-25 y ERR-26)

- `alembic_version` esperado en los humos de integración: `047_economia_ola1` → `050_invitaciones_docente`.
- Tablas de `public` en `tests/seguridad/test_sin_acceso.py` (47 → 48) y las tablas con RLS en `tests/integ_db.py`.
- Web: el conteo de rutas del admin (7 → 8) y la lista de diferidos de `sw.js`.

Nada más debe cambiar: si otro test cambia, se detiene y se reporta.

### 7.2 Errata (2026-10-26, después de la suite completa; candidato a ERR)

La suite completa de la rama dio 4 rojos que §7.1 NO declaraba. Los cuatro son **inventarios de rutas** que existen justamente para ponerse rojos con toda ruta nueva; no hubo ningún cambio de comportamiento fuera de lo declarado:

- `tests/teachers/test_access.py` U4 (dos tests): el mapa `EXPECTED_GUARDS` no traía las 3 rutas nuevas. Se agregan con su guarda (`admin`), en un bloque `_INVITAR`.
- `tests/tramposos/test_tramposos_422_sin_eco.py` ZE1 y ZE2: el tramposo del manejador global de los 422 ahora rompe **32** rutas con cuerpo en vez de 31 (y 30 en vez de 29): la ruta nueva `POST /admin/invitaciones` quedó cubierta sola por el manejador. Se suben los dos números.

Por qué no se declaró: §7.1 se armó buscando `alembic_version` y el conteo de tablas, no los inventarios de rutas. Regla propuesta: toda espec que agregue rutas declara de una vez U4 (`EXPECTED_GUARDS`) y SE2 (rutas con cuerpo).

Además, los tramposos XP12 y XP13 (UI5: `enviar` deja salir la excepción / escribe el correo en el log) se agregaron a los de §4.1.

## 8. Lo que hay que configurar en el servidor (no se aplica aquí)

1. **Plantilla:** copiar `docs/correo_invitacion.html` a `ENGRAMA/despliegue/correo/invitacion.html` (Caddy ya sirve esa carpeta en `:8091`, solo a la red interna).
2. **GoTrue (`docker-compose.yml`, servicio `gotrue`), dos variables:**
   ```
   GOTRUE_MAILER_SUBJECTS_INVITE: "ENGRAMA: crea tu contraseña de profe"
   GOTRUE_MAILER_TEMPLATES_INVITE: http://caddy:8091/invitacion.html
   ```
   Lo demás ya lo pone `ESPEC_correo_recuperacion` (SMTP de Brevo, `GOTRUE_AUTOCONFIRMAR=false`, `GOTRUE_LIMITE_CORREOS`).
3. **Backend:** nada nuevo obligatorio. Ya tiene `SUPABASE_SERVICE_ROLE_KEY` y `GOTRUE_URL`. Opcionales: `INVITACIONES_POR_HORA` (10) e `INVITACION_ESPERA_REENVIO_S` (60).
4. **Caddy:** nada. `POST /auth/v1/verify` ya está abierto por la espec del correo, `/invite` y `/admin` siguen cerrados desde afuera (los llama solo el backend por la red interna), y `/api/admin/invitaciones` va por la ruta `/api` de siempre.
5. **Web:** desplegar el commit integrado; `#/invitacion` no pide bandera en `config.json` (sin el backend nuevo nadie recibe ese enlace).
6. **[DECIDE CHRISTIAM]** `GOTRUE_LIMITE_CORREOS`: hoy 12 por hora para invitar **y** recuperar (L1). Invitar a más de ~10 profes en una hora deja correos sin salir hasta la hora siguiente (se reenvían). Subirlo a 20 sigue bajo los 300 diarios de Brevo si no se usa todas las horas.

## 9. Riesgos que quedan (dichos una vez)

1. **El enlace vence en 1 hora** (`GOTRUE_MAILER_OTP_EXP` es uno solo para todos los correos). Si vence: "Reenviar" del admin, o el profe usa "¿Olvidaste tu contraseña?" con su correo (P11: funciona aunque no haya aceptado).
2. **"Enviada" no garantiza que salió** (§1.3): GoTrue caído o el cubo lleno. Queda en el log del backend y se reenvía.
3. **Un correo mal escrito** deja un profe pendiente para siempre en la institución: no hay "Cancelar invitación" (para después).
4. **Quien ya tiene cuenta en otra institución** no puede entrar a esta por invitación (se ve "Enviada" para siempre). Unir cuentas de dos instituciones es otra espec.
5. **Tiempo residual:** el alta hace el mismo trabajo de base en los dos casos, pero no hay piso de tiempo; H5 lo mide.

## 10. Para después

- Cancelar una invitación (borra perfil, membresía y la cuenta si es nuestra y no aceptó).
- Sumar un profe ya invitado a otro grupo desde la misma pantalla.
- Invitar admins.
- Avisar al admin cuando el profe acepta.
