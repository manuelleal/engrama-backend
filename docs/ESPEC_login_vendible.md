# ESPEC · Login vendible (decisión 008), backend

F4 · Creador · 2026-09-25 · preregistro. Sin pantallas. **Va después de aceptar grupos** (usa `authorize_group`).

## 0. Medido (grep, sin ejecutar)
`validate_jwt`: solo HS256 y `aud`, **sin `iss`** (`src/auth/service.py:55-59`); sin membresías, 403 (`:199`). `profiles.pin_hash` NOT NULL (M3 pone `''`). Sin licencias ni argon2. Docs de Supabase leídas el 2026-09-25.
**Medido el 2026-09-25 para las decisiones de F6:**
- M3 crea perfiles con `uuid4` y `pin_hash=''` (`src/teachers/service/roster.py:119`), y nada los distingue de un usuario de Supabase: de ahí `profiles.managed`.
- El backend no tiene `supabase/`.
- `supabase init` de la CLI 2.117.0 (caché de npx, corrido en un directorio temporal) genera `[local_smtp] port = 54324` y `email_sent = 2`, con la nota "requires auth.email.smtp".

## 1. Qué cambia (una cosa)
**El backend sabe quién entra y qué puede usar:** de un JWT válido saca el perfil, el colegio, el rol y los módulos.
**Supabase:** contraseñas, verificación, recuperación, enlace mágico, OAuth (Google, Microsoft) y refresco. **Backend:** validar el JWT (firma, `exp`, `aud`, `iss`), `/auth/me`, onboarding, PIN y licencias.

**Migración `032_login_vendible` (reversible):**
- `tenants.kind` ∈ {school, personal};
- `tenant_modules(tenant_id, module ∈ {engrama, set, grader, live}, valid_until, limits jsonb)` (003; live = EVAGAME);
- `groups.class_code`: único, base32 de 8 caracteres;
- `memberships.username` (único por colegio) y `memberships.pin_hash`;
- `pin_attempts(group_id, username, fails, window_start, locked_until, lock_level)`;
- `profiles.managed boolean NOT NULL DEFAULT false`: cuenta gestionada por el colegio (menor sin correo). La pone en `true` solo M3 al crear el perfil (ajuste A4, §2). El perfil que crea `get_or_create_profile` con un JWT de Supabase queda en `false`;
- `ip_limits(ip_hmac, scope ∈ {live_join, managed_login}, count, window_start, lock_level, locked_until)`, con PK `(ip_hmac, scope)`. La IP se guarda solo como HMAC, y la fila se borra 24 h después de su último `window_start` o `locked_until`.

*Decidido el 2026-09-25 (recomendación de F6, aprobada provisionalmente por Christiam):* las tres últimas líneas.

### 1.1 Sesión del gestionado: JWT propio
**Descartadas:** usuario de Supabase con contraseña = PIN (`/auth/v1/token` limita por IP, `rate-limits`: la fuerza bruta se salta nuestro límite); anónimo (se pierde al cambiar de dispositivo, `auth-anonymous`); `generateLink` (no verificado).

**Elegida: JWT del backend** (por la 005 nadie usa PostgREST): HS256 con `ENGRAMA_SESSION_SECRET` (distinto al de Supabase), `iss=engrama-backend`, `aud=engrama-managed`, `sub` y `tid` (fija el colegio); 8 h sin refresh. `validate_jwt` elige la llave por `iss` (desconocido → 401); en producción no arranca sin `SUPABASE_ISSUER`.

### 1.2 Rutas
- **`GET /auth/me`,** sin exigir membresía: `needs_onboarding`, `active_tenant {id, name, kind, role}` y los `modules` vigentes (`valid_until IS NULL OR > now`).
- **`POST /auth/onboarding {nombre}`:** sin membresías crea el tenant `personal`, la membresía `admin` y la licencia gratis; con membresías, 409.
- **`POST /auth/managed/groups/{gid}/credentials {consentimiento_representante: true, regenerar?}`:** `require_teacher` + `authorize_group`; crea `class_code` y `username` faltantes; devuelve **una vez** un PIN de 6 dígitos (`secrets`), guarda argon2id y registra en `audit_logs`. Sin consentimiento, 422.
  - *Decidido el 2026-09-25 (recomendación de F6, aprobada provisionalmente por Christiam):* **el PIN es solo para cuentas gestionadas por el colegio** (menores sin correo): membresía `student` con `profiles.managed = true`. Los demás miembros del grupo no reciben PIN, su `pin_hash` no cambia y salen en `sin_pin: [{username, motivo: "cuenta_con_correo"}]`.
- **`POST /auth/managed/login {class_code, username, pin}`:** todo error da el mismo 401 (con hash señuelo). Un hash vacío nunca entra, y una cuenta no gestionada (`managed = false`) tampoco, aunque tenga `pin_hash`.
  - **Límite R3:**
    - 5 fallos por (grupo, usuario), exista o no, bloquean la cuenta;
    - la clase se cierra con 20 fallos en 15 min o con 100 en 24 h;
    - bloqueado → 429 aun con el PIN correcto.
  - **Bloqueo progresivo por cuenta** (*decidido el 2026-09-25, recomendación de F6, aprobada provisionalmente por Christiam*):
    - `lock_level` sube en 1 con cada bloqueo; la duración es nivel 1 → 15 min, nivel 2 → 1 h, nivel 3 o más → 24 h;
    - `fails` vuelve a 0 al bloquear;
    - `lock_level` vuelve a 0 con un login correcto, cuando el profe regenera el PIN, o tras 24 h sin fallos contadas desde el fin del último bloqueo.
    - Tope por cuenta: 15 intentos el primer día y 5 por día después.
  - **Límite por IP** (*mismo origen*): `ip_limits` con `scope = managed_login`.
    - 150 fallos en 15 min desde una IP (exista o no la clase o el usuario) la bloquean con la misma escalera: 15 min, 1 h, 24 h;
    - IP bloqueada → 429 antes de verificar el hash, aun con el PIN correcto;
    - **un login correcto no reinicia el contador ni el nivel de la IP**: si lo hiciera, el atacante lo reiniciaría con su propia cuenta;
    - tope desde una IP: unos 450 intentos el primer día, repartidos entre todas las clases.
    - 150 y no menos, porque un colegio entero sale por un NAT.
  - **Riesgo residual del PIN de 6 dígitos: riesgo aceptado, provisional; revisar con el primer colegio real** (*decidido el 2026-09-25, recomendación de F6, aprobada provisionalmente por Christiam*).
    - **Cifra aprobada:** ~**0,4 %/día** bajo ataque en una clase de 40 (100·40/10⁶).
    - **Cuenta a la vista (ERR-10):** el tope de clase deja 100 intentos/día por clase, y cada intento acierta con probabilidad 1/10⁶. Entonces P ≤ 100/10⁶ = **0,01 %/día por clase**. El factor ×40 supondría 100 intentos por estudiante, y el tope de clase no lo permite.
    - La cifra aprobada es entonces una cota pesimista, y la diferencia queda como **candidata a ERR**. No cambia la decisión: aceptar 0,4 % cubre 0,01 %.
    - **Condiciones de la aceptación:** el bloqueo progresivo por cuenta y por IP (arriba) y el PIN solo para cuentas gestionadas (§1.2, credenciales).
    - **Lo que el riesgo incluye:** un compañero puede cerrar la clase un día. Desde el NAT del colegio, un estudiante con un script puede además bloquear la IP del colegio para el login con PIN (15 min, luego 1 h, luego 24 h). Por eso el desbloqueo por el admin queda en "Para después".

### 1.3 Licencia gratis (propuesta; decide Christiam)
`engrama {"grupos":1,"estudiantes":40}` + `live {"jugadores":40}`, sin vencimiento; sin `set`, `grader` ni `ai`. Aquí solo se muestra; cumplirla es A3.

### 1.4 Invitado del modo en vivo
*Agregado por acuerdo con F6 (2026-09-25); decisiones 007 y 008.*
- **`POST /live/join {code, alias}`** (sin auth) → 201 `{token, participant_id, expires_at}`. Token HS256 con `ENGRAMA_SESSION_SECRET`, `iss=engrama-backend`, `aud=engrama-live-guest`, `role=guest`, `sid` (una sesión), `tid`, `jti`; **sin `profile_id`**, `sub=guest:<jti>` (no es UUID). `exp` = fin de la sesión, máximo 3 h; sin refresh.
- **Solo llama** `/live/sessions/{sid}/*` con `sid` = su claim; otra sesión → 403. **`get_current_user` rechaza `role=guest` con 403 antes de `get_or_create_profile`**: hoy esa función crea un perfil `student` para cualquier `sub` desconocido (`src/auth/service.py:80`), y el invitado caería en el roster.
- **Sesión:** puerto `LiveSessionLookup.resolve(code) → {sid, tid, ends_at, open} | None`; los tests usan un doble y una ruta de eco del fixture. Código inexistente o sesión cerrada → 404.
- **Anti-abuso** (tabla `live_guest_joins(sid, alias, jti, ip_hmac, created_at)` en la 032, `UNIQUE(sid, alias)`):
  - alias solo de `GUEST_ALIASES` (enum; menores y Ley 1581: nada de texto libre); si no, 422; repetido, 409 `alias_en_uso`;
  - **el tope real es por sesión:** `limits.live.jugadores` invitados (40 gratis); el siguiente → 409 `sesion_llena`;
  - *Decidido el 2026-09-25 (recomendación de F6, aprobada provisionalmente por Christiam):*
    - **150 intentos por IP en 10 min** (antes 60) → 429. `ip_limits` con `scope = live_join`, ventana fija y sin escalera.
    - La IP se guarda solo como HMAC y se borra a las 24 h.
    - **El 409 `alias_en_uso` no cuenta** contra el tope de IP. Todo lo demás cuenta: 201, 404, 422 y 409 `sesion_llena`.
  - **Orden de evaluación:** IP sobre el tope → 429; código inexistente o sesión cerrada → 404; alias fuera del enum → 422; alias repetido → 409 `alias_en_uso`; sesión llena → 409 `sesion_llena`.
    - El alias va antes que el tope de sesión: así, quien reintenta con su alias ya aceptado nunca suma a la cuenta de la IP.
  - **Límite conocido (cuenta a la vista):**
    - en 10 min y tras un mismo NAT caben 2 clases de 40 con hasta 70 errores entre las dos (80 + 70 = 150), o 3 clases con hasta 30 (120 + 30 = 150);
    - con 4 clases simultáneas (160 joins > 150) el 429 es seguro;
    - se revisa con el primer colegio real.
- **Nunca aparece:** `/auth/me` 403; cero filas en `profiles`, `memberships` o `pii` (fuera del roster, T5 y T7); ningún evento con su id: sin `answer.submitted` ni `coins.granted`.
- **Qué NO entra:** el motor y las rutas reales de live (F6, se porta a `src/live/`). `src/auth/guest_aliases.py` copia `GUEST_ALIASES` hasta el porte; después queda una sola.

## 2. CSV ENGRAMA v1 (superconjunto de M4)
- **Lectura:** UTF-8 con o sin BOM, o cp1252. Separador `;` o `,`, detectado en la cabecera. Cabeceras sin tildes y en minúsculas.
- **Obligatorias:** `documento_id` (o `documento`, `codigo`; sin puntos ni espacios, luego la regex de M4) y `nombre_completo` (o `nombre`, o `nombres` + `apellidos`).
- **Opcionales:** `usuario` (si falta, se genera), `correo` (vacío para menores; **no se guarda**) y `grupo` (debe coincidir). `pin` y el resto se ignoran y se reportan.
- **Regresión:** un CSV válido hoy en M4 da idéntico.

```
Nombres;Apellidos;Código;Correo;Grupo
Ana Sintética;Prueba Uno;SINT-0001;;10A
Beto Ficticio;Prueba Dos;SINT-0002;;10A
```

**Ajustes a grupos** (commits aparte, tras aceptarlo):
A1, M4 adopta v1; A2, en un tenant `personal` M1 asigna al creador en `teacher_groups` (si no, no ve T5 ni T7); A3, los límites gratis; A4 (*decidido el 2026-09-25, recomendación de F6, aprobada provisionalmente por Christiam*), M3 crea el perfil con `managed = true` (`enroll_student`, `src/teachers/service/roster.py:119`), y un perfil que ya existía no cambia. Hasta que A4 entre, los tests de esta espec ponen `managed` en el fixture.

## 3. Tests (sin parametrize)
**A (integ):**
- **A1:** JWT de otro proyecto (usuario **con** membresía) → 401.
- **A2a/b:** vencido, Supabase / gestionado → 401.
- **A3:** PIN malo, usuario o clase inexistentes → mismo 401; `pin_hash=''` + PIN `''` → 401.
- **A4:** 5 fallos + PIN correcto → 429; `locked_until` pasado → 200.
- **A4b** (progresivo por cuenta; *decidido el 2026-09-25*):
  - 5 fallos → `locked_until` ≈ ahora + 15 min;
  - con `locked_until` puesto en el pasado, 5 fallos más → ≈ + 1 h, y 5 más → ≈ + 24 h (±1 min);
  - un login correcto deja `lock_level = 0`.
- **A5:** 20 fallos repartidos → 429 a un usuario válido.
- **A6:** estudiante en A y B, token de A + `X-Tenant-ID: B` → 403; código de B + usuario de A → 401.
- **A7:** independiente P2 pide el tenant de P1 → 403; `/teachers/groups` sin grupos de P1.
- **A8:** solo `grader`, `set` vencido, `engrama` ajeno → `modules == ["grader"]`.

**A invitado** (*agregado por acuerdo con F6, 2026-09-25*):
- **A9:** token de S1 en S2 → 403.
- **A10:** invitado en `/teachers/groups` y `/auth/me` → 403; `profiles` no crece.
- **A11:** alias fuera de la lista o libre → 422; repetido → 409.
- **A12:** token de invitado vencido → 401.
- **A13:** join + eco de 2 invitados → `coin_ledger`, wallets y `learning_events` sin filas nuevas (el 0 `coins.granted` en una sesión real es T3(f) del motor, al portar).
- **A14:** invitado 41 → 409 `sesion_llena`. Desde otra IP, 150 joins con código inexistente → 150 × 404 y ningún 429; el 151 → 429. *Antes: "intento 61 → 429"; cambia por la decisión del 2026-09-25.*

**Decidido el 2026-09-25 (recomendación de F6, aprobada provisionalmente por Christiam):**
- **A15 (clase tras un NAT):** todo desde una IP y en menos de 10 min, **0 respuestas 429**:
  - 40 joins (201);
  - 30 códigos mal escritos (404);
  - 100 reintentos con un alias ya aceptado (409 `alias_en_uso`).

  Cuentas del test:
  - contados: 40 + 30 = 70 ≤ 150;
  - con el 409 contado: 170 > 150 → 429 (Z25 en rojo);
  - con el tope en 60: 70 > 60 → 429 (Z26 en rojo).

  El escenario del encargo (40 joins + 20 reintentos = 60) cabe en el tope viejo de 60, porque el 429 llegaba en el intento 61. Con ese escenario, **ninguno de los dos tramposos se pondría rojo**. Por eso el test sube los números sin cambiar el criterio.
- **A16 (IP en el login gestionado):**
  - desde la IP X, 149 logins con `class_code` inexistente → 149 × 401;
  - un login correcto desde X → 200, y el contador de X sigue en 149;
  - el fallo 150 desde X → 401; después, un usuario válido con su PIN correcto desde X → 429;
  - el mismo usuario desde la IP Y → 200;
  - con el `locked_until` de X en el pasado, 150 fallos más → `locked_until` ≈ + 1 h;
  - son unas 300 verificaciones del hash señuelo: el test es lento, con una duración a medir en L6.
- **A17 (PIN solo para gestionados):** grupo con un estudiante `managed = true` y otro creado por `get_or_create_profile` (`managed = false`).
  - Las credenciales devuelven PIN solo al gestionado; el otro sale en `sin_pin` y su `pin_hash` no cambia.
  - Con un `pin_hash` argon2id válido puesto a mano en el no gestionado, su login → el mismo 401 que el de un usuario inexistente.

**F (integ):** F1 onboarding 201 y luego 409; F2 sin membresía lo demás sigue en 403; F3 solo `$argon2id$` en la base y regenerar invalida el PIN viejo; F4 E 403, DO/DT/AB 404, D y AA de control.

**U (no-integ):** U1, llave por `iss`, llaves cruzadas y `alg:none`; U2, el arranque; U3-U8, hash, PIN, bloqueo, usuario, vigencia y licencia.
- **U9** (*decidido el 2026-09-25*): la escalera como función pura.
  - `lock_duration(1..4)` = 15 min, 1 h, 24 h, 24 h;
  - el nivel baja a 0 a las 24 h sin fallos contadas desde `locked_until`, y no antes.

**Tramposos. Diagonal PREDICHA** (ERR-15: el código no existe; `?` = cruce posible):
- Z1 sin firma → A1, U1, 2 de `tests/auth`
- Z2 sin `exp` Supabase → A2a, 2 de `tests/auth`
- Z3 sin `exp` gestionado → A2b
- Z4 `iss` propio con llave de Supabase → U1
- Z5 hash vacío válido → A3
- Z6 contador de la cuenta en memoria → A4, A4b, A5, H1
- Z7 sin límite de clase → A5
- Z8 ignora `tid` → A6, H1
- Z9 tenant compartido → A7, F1?
- Z10 `/me` con todos los módulos → A8, H1, F1?
- Z11 ignora `valid_until` → U7, A8
- Z12 licencias sin colegio → A8
- Z13 PIN en claro → F3
- Z14 sin `authorize_group` → F4
- Z15 GRANT en la 032 → D12
- Z16 mensaje distinto al inexistente → A3, A17?
- Z17 bloqueo al 6.º → U5, A4, A4b?
- Z18 `random` de 4 dígitos → U4
- Z19 ignora `sid` → A9
- Z20 el invitado pasa a `get_or_create_profile` → A10, A13?
- Z21 alias `str` libre → A11
- Z22 sin `exp` en el token de invitado → A12
- Z23 el join abre wallet y da 1 moneda → A13
- Z24 sin tope ni límite por IP → A14

*Decidido el 2026-09-25 (recomendación de F6, aprobada provisionalmente por Christiam).* Todo sigue siendo **predicción**: el código no existe (ERR-15).
- Z25 el 409 `alias_en_uso` cuenta contra la IP → A15
- Z26 tope de IP del invitado en 60 → A14, A15
- Z27 bloqueo fijo de 15 min, sin escalera (no-integ) → U9, A4b, A16
- Z28 sin límite por IP en el login gestionado → A16
- Z29 un login correcto reinicia el contador de la IP → A16
- Z30 PIN para todo estudiante del grupo (ignora `managed`) → A17
- Z31 el login gestionado acepta `managed = false` → A17

Cruces que se predice que **no** ocurren:
- Z24, sin límites, deja A15 en verde: ningún 429 es justo lo que A15 pide.
- Z25 no toca A11 ni A14: ninguno manda más de un alias repetido.
- Z26 no toca A9 a A13: ninguno pasa de 60 intentos.

Matriz a medir antes de aceptar: 31 × (69 + 13 de `tests/auth` + D12) = 31 × 83 = **2.573 celdas** (antes, 24 × 71 = 1.704). Se mantiene la fórmula heredada, que usa como columnas todos los tests nuevos, incluidos los propios tramposos.

## 4. Cuentas
N (passed) y M (no-integ) se **miden** al aceptar grupos (su espec predice 269 y 96). Nuevos: 8 U + 4 tramposos no-integ (Z4, Z11, Z17, Z18) + 19 integ (9 A + 3 F + 4 prohibidas + 2 controles + H1) + 14 tramposos integ = 45; invitado (acuerdo con F6): 6 A + 6 tramposos, todo integ = 12.

*Decidido el 2026-09-25 (recomendación de F6, aprobada provisionalmente por Christiam)*, 12 más:
- 4 integ nuevos: A4b, A15, A16 y A17 (A14 cambia pero no suma);
- 1 no-integ: U9;
- 6 tramposos integ: Z25, Z26, Z28, Z29, Z30 y Z31;
- 1 tramposo no-integ: Z27.
- H3 es manual, como H2, y no suma.

Sumas:
- **Total:** 45 + 12 + 12 = **69**.
- **No-integ:** 12 + 1 (U9) + 1 (Z27) = **14**.
- **Tramposos:** 18 + 6 + 7 = **31**.

**Meta: N + 69 passed, M + 14 no-integ**, 0 failed, ruff 0, mypy 0. *Antes: N + 57 y M + 12.*

## 5. Humo y réplica
- **H1** escribe `tests/_salida/humo_login.json` = `{"onboarding":201,"me_modulos":["engrama","live"],"pin_ok":200,"pin_mal":401,"bloqueo":429,"otro_colegio":403}`.
- **Correo en desarrollo** (*decidido el 2026-09-25*):
  - Christiam todavía no tiene cuenta SMTP. El desarrollo y **todos** los tests de correo y enlace mágico usan el buzón local del Supabase en Docker; ningún test manda correo real.
  - **Buzón:** en la CLI v2.117.0 es **Mailpit**. El binario de la caché de npx trae `axllent/mailpit:v1.30.2`, aunque por dentro todavía dice `inbucket`.
  - **Puerto:** el `config.toml` que genera `supabase init` 2.117.0 tiene la sección `[local_smtp]` con `port = 54324` (interfaz web y API) y `# smtp_port = 54325` comentado. `ENGRAMA/coins-mvp/supabase/config.toml:104-109` trae lo mismo.
  - El backend no tiene `supabase/`: L7 lo crea con `npx supabase@2.117.0 init`.
  - **El test lee el enlace de la API del buzón:**
    - `GET http://127.0.0.1:54324/api/v1/search?query=to:<correo>` → id;
    - `GET /api/v1/message/{id}` → cuerpo;
    - de ahí saca el enlace `/auth/v1/verify?...type=magiclink`.
    - Las rutas son de la API v1 de Mailpit y **no se corrieron**. Se verifican al primer `supabase start` (ERR-14: cada comando se corre antes de fijarlo) y, si difieren, se corrigen aquí antes de fijar H2.
- **H2** (manual, `npx supabase start`): JWT **real** por enlace mágico (leído de Mailpit) → `/auth/me` 200; escribe `humo_login_supabase.json` con `alg` e `iss`.
- **H3 · límite de envío alcanzado** (*decidido el 2026-09-25*; manual, Supabase local, contra Mailpit):
  - **H3a:** con `[auth.email] max_frequency = "60s"`, dos enlaces mágicos a la misma dirección en menos de 60 s → el segundo da 429 con `error_code = over_email_send_rate_limit`, y Mailpit muestra 1 mensaje.
  - **H3b:** con `[auth.rate_limit] email_sent = 2`, tres direcciones distintas en la misma hora → el tercero da 429 y Mailpit muestra 2.
    - La plantilla dice que `email_sent` "requires auth.email.smtp to be enabled". Por eso H3b apunta `[auth.email.smtp]` al SMTP interno de Mailpit; el host y el puerto se miden con `docker ps` al primer arranque.
  - Escribe `tests/_salida/humo_correo_limite.json` = `{"buzon":"mailpit","frecuencia":{"segundo":429,"error_code":"over_email_send_rate_limit"},"por_hora":{"enviados":2,"tercero":429}}`.
  - **Tramposos:**
    - `max_frequency = "0s"` → H3a no ve 429;
    - `email_sent = 100` → H3b no ve 429.
  - La web tendrá que mostrar un mensaje para ese `error_code`; eso va con las pantallas, no aquí.
- **Réplica** (`ENGRAMA_REPLICA_LOGIN=1`):
  - `José.P `, PIN `004821`, clase de 40, onboardings simultáneos, `valid_until = now`, CSV cp1252;
  - *entradas nuevas del 2026-09-25:* dos clases de 40 tras una IP con 70 errores → 0 × 429; una cuarta clase → 429 (el límite conocido de §1.4); 149 fallos de una IP + un login correcto + 1 fallo → IP bloqueada.

## 6. Qué NO se toca
- `src/teachers`, `src/admin`, `tests/teachers`, `integ_ayudante.py`, migraciones ≤ 031, `/core`, `/challenges`, `.venv` (argon2 con `poetry add`; ERR-11).
- **Para después:**
  - JWKS/ES256 (**bloquea el despliegue** con signing keys, `signing-keys`);
  - `require_module`;
  - revocar el token al regenerar el PIN;
  - desbloqueo de cuenta o IP por el admin del colegio;
  - SAML y vincular identidades.
  - *El límite por IP en el login gestionado sale de esta lista y entra en §1.2 por la decisión del 2026-09-25.*
- **Candidato a BUG:** M3 reusa perfiles entre colegios por `documento_id`.

## 7. Ley 1581 (no es concepto jurídico; lo revisa un abogado antes del primer colegio)
- **Dato mínimo del menor:** nombre, código escolar interno (no la tarjeta de identidad), usuario y hash del PIN.
- **Consentimiento:** el colegio lo declara al emitir credenciales; `audit_logs` guarda quién, cuándo y qué grupo. Ni PIN ni token en logs.

## 8. Pasos de Christiam (claves solo en el panel de Supabase, jamás en archivos ni en el chat)
**0. JWT Keys:** dile al coordinador si ves "Legacy JWT secret" o "signing keys".

**1. Correo** (el SMTP de Supabase solo envía al equipo, 2/h, `auth-smtp`). **No bloquea la implementación:** es una fila de la checklist de producción del login y se hace solo antes de abrir a usuarios reales. Mientras tanto, todo usa Mailpit local (§5).
- **Proveedor configurable, por elegir** (*decidido el 2026-09-25*): Resend, Brevo o SES.
  - Ningún archivo del repo nombra ni fija el proveedor, y el backend no envía correo: lo envía Supabase.
  - Host, puerto, usuario, clave y remitente viven en el panel (producción) o en `env(...)` del `config.toml` (local).
  - Cambiar de proveedor no cambia código ni tests.
- **Pasos al elegirlo:**
  - crea la cuenta y verifica tu dominio;
  - pega sus datos en *Authentication → SMTP*;
  - sube el límite por hora (*Rate Limits*); H3 prueba qué pasa al alcanzarlo;
  - activa *Confirm email*;
  - pon la web en *URL Configuration*.

**2. Google** (console.cloud.google.com): proyecto "ENGRAMA"; *Branding*: nombre y correo; *Audience*: External; *Clients → Web application* con *origins* = la web y *redirect URI* = la de *Providers → Google* en Supabase (local: `http://127.0.0.1:54321/auth/v1/callback`). Copia ID y secreto en Supabase y publica.

**3. Microsoft** (portal.azure.com; `auth-azure`):
*Entra ID → App registrations → New* ("cualquier directorio y cuentas personales"); *Redirect URI* Web = la callback (local: `localhost`); *Certificates & secrets*: crea un secreto y agenda su vencimiento; *Manifest*: claims `email` y `xms_edov`. Copia ID y secreto en *Azure* de Supabase, *Tenant URL* vacía. La web pide el scope `email`.

## 9. Orden y veredicto
**Orden** (un commit cada uno):
- L1, la 032;
- L2, `validate_jwt` (U1, U2, Z1-Z4);
- L3, `/me` y onboarding;
- L4, licencias;
- L5, credenciales (A17, Z30, Z31);
- L6, PIN con escalera y límite por IP (A4b, A16, U9, Z27-Z29);
- L6b, invitado (A9-A15, Z19-Z26);
- L7, `supabase init`, humo (H1-H3) y réplica;
- L8, matriz medida.

**Veredicto:**
- **FUNCIONA:** cuentas exactas, matriz = §3, H1, H2, H3 y réplica en verde, lo previo idéntico.
- **HAY ALGO MODESTO:**
  - H2 falla solo por llegar ES256;
  - o H3b no se puede montar porque `email_sent` exige el SMTP y Mailpit no se deja apuntar. H3a sigue siendo obligatoria.
- **NO:** A1-A8 dan 2xx, un tramposo queda verde, un PIN en claro o cambia algo previo.

## 10. Erratas por el login del piloto (`ESPEC_login_piloto.md` §9; aplicar ANTES de implementar la 008)
El subconjunto del piloto ya está en el código. Esta espec se escribió antes y supone cosas que ya no son ciertas. Nada de la 008 se implementa sin corregir primero estos puntos en su texto:

1. **`get_or_create_profile` ya no existe.** `get_profile` nunca escribe, y un JWT válido sin perfil recibe 403 `Account has no ENGRAMA profile`.
   - La 008 crea el perfil explícitamente en `POST /auth/onboarding`.
   - Su `/auth/me` "sin exigir membresía" debe aceptar también "sin perfil" como `needs_onboarding`.
   - Si genera un `documento_id`, nunca `sub[:8]` (era el choque que daba 500). Se sugiere el `sub` completo sin guiones: 32 caracteres, cabe en `DOC_ID_PATRON` y solo choca con otro `sub`.
2. **`/auth/me` ya trae `active_tenant_id`, `must_change_password`, `memberships[].full_name` y `full_name` de la membresía activa.** La 008 **agrega** `active_tenant {…}`, `needs_onboarding` y `modules` sin quitar esos campos.
3. **Rutas con contraseña temporal.** Toda ruta nueva de la 008 queda bloqueada con 403 `must_change_password` mientras la bandera esté puesta, salvo que entre a `RUTAS_CON_CONTRASENA_TEMPORAL` (`src/auth/service.py`) con su `(path, método)`. Por defecto, no entra. `test_up3_permitidas_por_path_y_metodo` se pone rojo si alguien la agrega sin decidirlo.
4. **§6 "Qué NO se toca":** el piloto sí tocó `src/teachers/schemas.py` y `roster.py` (D1: M3 valida `documento_id` con `DOC_ID_PATRON`).
5. **Base de sus cuentas:** la suite ya no parte de la cifra de §4; parte de la que deje el login del piloto con BUG-16 (ver `ESPEC_login_piloto.md` §5 y `ESPEC_bug16.md` §4, medidas).
6. **"Candidato a BUG: M3 reusa perfiles entre colegios por `documento_id`"** queda resuelto por D1: la identidad es global a propósito, y `documento_id` es opaco (documento nacional o código con el prefijo de la institución).
7. **La 034 ya no es de la 008.** El login del piloto no usó ninguna migración, pero el registro del consentimiento tomó `034_consentimiento` (`ESPEC_consentimiento.md`). La 008 usa la siguiente libre, sobre esa, y enumera con `git grep -n alembic_version -- tests` lo que fija la versión (ERR-25).
   - **`/auth/me` también trae `consent_version`,** y existe `POST /auth/consentimiento`. El consentimiento de un menor (tutor) es de la 008 y no está resuelto.
8. **El alta del operador (`python -m src.onboarding`) y el CSV ENGRAMA v1 (§2) son cosas distintas.** El del alta tiene `nombre, correo, documento, tipo_documento, grupo, rol` y lo corre el operador; el v1 lo sube un admin de colegio por HTTP. La 008 decide si conviven o si uno reemplaza al otro.
