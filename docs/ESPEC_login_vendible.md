# ESPEC · Login vendible (decisión 008), backend

F4 · Creador · 2026-09-25 · preregistro. Sin pantallas. **Va después de aceptar grupos** (usa `authorize_group`).

## 0. Medido (grep, sin ejecutar)
`validate_jwt`: solo HS256 y `aud`, **sin `iss`** (`src/auth/service.py:55-59`); sin membresías, 403 (`:199`). `profiles.pin_hash` NOT NULL (M3 pone `''`). Sin licencias ni argon2. Docs de Supabase leídas el 2026-09-25.

## 1. Qué cambia (una cosa)
**El backend sabe quién entra y qué puede usar:** de un JWT válido saca el perfil, el colegio, el rol y los módulos.
**Supabase:** contraseñas, verificación, recuperación, enlace mágico, OAuth (Google, Microsoft) y refresco. **Backend:** validar el JWT (firma, `exp`, `aud`, `iss`), `/auth/me`, onboarding, PIN y licencias.

**Migración `032_login_vendible` (reversible):**
- `tenants.kind` ∈ {school, personal};
- `tenant_modules(tenant_id, module ∈ {engrama, set, grader, live}, valid_until, limits jsonb)` (003; live = EVAGAME);
- `groups.class_code`: único, base32 de 8 caracteres;
- `memberships.username` (único por colegio) y `memberships.pin_hash`;
- `pin_attempts(group_id, username, fails, window_start, locked_until)`.

### 1.1 Sesión del gestionado: JWT propio
**Descartadas:** usuario de Supabase con contraseña = PIN (`/auth/v1/token` limita por IP, `rate-limits`: la fuerza bruta se salta nuestro límite); anónimo (se pierde al cambiar de dispositivo, `auth-anonymous`); `generateLink` (no verificado).

**Elegida: JWT del backend** (por la 005 nadie usa PostgREST): HS256 con `ENGRAMA_SESSION_SECRET` (distinto al de Supabase), `iss=engrama-backend`, `aud=engrama-managed`, `sub` y `tid` (fija el colegio); 8 h sin refresh. `validate_jwt` elige la llave por `iss` (desconocido → 401); en producción no arranca sin `SUPABASE_ISSUER`.

### 1.2 Rutas
- **`GET /auth/me`,** sin exigir membresía: `needs_onboarding`, `active_tenant {id, name, kind, role}` y los `modules` vigentes (`valid_until IS NULL OR > now`).
- **`POST /auth/onboarding {nombre}`:** sin membresías crea el tenant `personal`, la membresía `admin` y la licencia gratis; con membresías, 409.
- **`POST /auth/managed/groups/{gid}/credentials {consentimiento_representante: true, regenerar?}`:** `require_teacher` + `authorize_group`; crea `class_code` y `username` faltantes; devuelve **una vez** un PIN de 6 dígitos (`secrets`), guarda argon2id y registra en `audit_logs`. Sin consentimiento, 422.
- **`POST /auth/managed/login {class_code, username, pin}`:** todo error da el mismo 401 (con hash señuelo); un hash vacío nunca entra.
  - **Límite R3:** 5 fallos por (grupo, usuario), exista o no, bloquean 15 min; la clase se cierra con 20 fallos en 15 min o 100 en 24 h; bloqueado → 429 aun con el PIN correcto.
  - **Riesgo residual:** 100·40/10⁶ ≈ **0,4 %/día** en una clase de 40, y un compañero puede cerrarla un día. **Decide Christiam.**

### 1.3 Licencia gratis (propuesta; decide Christiam)
`engrama {"grupos":1,"estudiantes":40}` + `live {"jugadores":40}`, sin vencimiento; sin `set`, `grader` ni `ai`. Aquí solo se muestra; cumplirla es A3.

### 1.4 Invitado del modo en vivo
*Agregado por acuerdo con F6 (2026-09-25); decisiones 007 y 008.*
- **`POST /live/join {code, alias}`** (sin auth) → 201 `{token, participant_id, expires_at}`. Token HS256 con `ENGRAMA_SESSION_SECRET`, `iss=engrama-backend`, `aud=engrama-live-guest`, `role=guest`, `sid` (una sesión), `tid`, `jti`; **sin `profile_id`**, `sub=guest:<jti>` (no es UUID). `exp` = fin de la sesión, máximo 3 h; sin refresh.
- **Solo llama** `/live/sessions/{sid}/*` con `sid` = su claim; otra sesión → 403. **`get_current_user` rechaza `role=guest` con 403 antes de `get_or_create_profile`**: hoy esa función crea un perfil `student` para cualquier `sub` desconocido (`src/auth/service.py:80`), y el invitado caería en el roster.
- **Sesión:** puerto `LiveSessionLookup.resolve(code) → {sid, tid, ends_at, open} | None`; los tests usan un doble y una ruta de eco del fixture. Código inexistente o sesión cerrada → 404.
- **Anti-abuso** (tabla `live_guest_joins(sid, alias, jti, ip_hmac, created_at)` en la 032, `UNIQUE(sid, alias)`):
  - alias solo de `GUEST_ALIASES` (enum; menores y Ley 1581: nada de texto libre); si no, 422; repetido, 409;
  - tope: `limits.live.jugadores` invitados por sesión (40 gratis); el siguiente → 409;
  - 60 intentos por IP en 10 min → 429 (alto: una clase sale por un NAT); la IP solo como HMAC, borrada a las 24 h.
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
A1, M4 adopta v1; A2, en un tenant `personal` M1 asigna al creador en `teacher_groups` (si no, no ve T5 ni T7); A3, los límites gratis.

## 3. Tests (sin parametrize)
**A (integ):**
- **A1:** JWT de otro proyecto (usuario **con** membresía) → 401.
- **A2a/b:** vencido, Supabase / gestionado → 401.
- **A3:** PIN malo, usuario o clase inexistentes → mismo 401; `pin_hash=''` + PIN `''` → 401.
- **A4:** 5 fallos + PIN correcto → 429; `locked_until` pasado → 200.
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
- **A14:** invitado 41 → 409; intento 61 de una IP → 429.

**F (integ):** F1 onboarding 201 y luego 409; F2 sin membresía lo demás sigue en 403; F3 solo `$argon2id$` en la base y regenerar invalida el PIN viejo; F4 E 403, DO/DT/AB 404, D y AA de control.

**U (no-integ):** U1, llave por `iss`, llaves cruzadas y `alg:none`; U2, el arranque; U3-U8, hash, PIN, bloqueo, usuario, vigencia y licencia.

**Tramposos. Diagonal PREDICHA** (ERR-15: el código no existe; `?` = cruce posible):
- Z1 sin firma → A1, U1, 2 de `tests/auth`
- Z2 sin `exp` Supabase → A2a, 2 de `tests/auth`
- Z3 sin `exp` gestionado → A2b
- Z4 `iss` propio con llave de Supabase → U1
- Z5 hash vacío válido → A3
- Z6 contador en memoria → A4, A5, H1
- Z7 sin límite de clase → A5
- Z8 ignora `tid` → A6, H1
- Z9 tenant compartido → A7, F1?
- Z10 `/me` con todos los módulos → A8, H1, F1?
- Z11 ignora `valid_until` → U7, A8
- Z12 licencias sin colegio → A8
- Z13 PIN en claro → F3
- Z14 sin `authorize_group` → F4
- Z15 GRANT en la 032 → D12
- Z16 mensaje distinto al inexistente → A3
- Z17 bloqueo al 6.º → U5, A4
- Z18 `random` de 4 dígitos → U4
- Z19 ignora `sid` → A9
- Z20 el invitado pasa a `get_or_create_profile` → A10, A13?
- Z21 alias `str` libre → A11
- Z22 sin `exp` en el token de invitado → A12
- Z23 el join abre wallet y da 1 moneda → A13
- Z24 sin tope ni límite por IP → A14

Matriz a medir antes de aceptar: 24 × (57 + 13 de `tests/auth` + D12) = 24 × 71 = **1.704 celdas** (antes, 18 × 59 = 1.062).

## 4. Cuentas
N (passed) y M (no-integ) se **miden** al aceptar grupos (su espec predice 269 y 96). Nuevos: 8 U + 4 tramposos no-integ (Z4, Z11, Z17, Z18) + 19 integ (9 A + 3 F + 4 prohibidas + 2 controles + H1) + 14 tramposos integ = 45; invitado (acuerdo con F6): 6 A + 6 tramposos, todo integ = 12. **Meta: N + 57 passed, M + 12 no-integ**, 0 failed, ruff 0, mypy 0.

## 5. Humo y réplica
- **H1** escribe `tests/_salida/humo_login.json` = `{"onboarding":201,"me_modulos":["engrama","live"],"pin_ok":200,"pin_mal":401,"bloqueo":429,"otro_colegio":403}`.
- **H2** (manual, `npx supabase start`): JWT **real** por enlace mágico (Inbucket) → `/auth/me` 200; escribe `humo_login_supabase.json` con `alg` e `iss`.
- **Réplica** (`ENGRAMA_REPLICA_LOGIN=1`): `José.P `, PIN `004821`, clase de 40, onboardings simultáneos, `valid_until = now`, CSV cp1252.

## 6. Qué NO se toca
- `src/teachers`, `src/admin`, `tests/teachers`, `integ_ayudante.py`, migraciones ≤ 031, `/core`, `/challenges`, `.venv` (argon2 con `poetry add`; ERR-11).
- **Para después:** JWKS/ES256 (**bloquea el despliegue** con signing keys, `signing-keys`), `require_module`, revocar el token al regenerar el PIN, límite por IP en el login gestionado (el del invitado sí entra, §1.4), SAML y vincular identidades.
- **Candidato a BUG:** M3 reusa perfiles entre colegios por `documento_id`.

## 7. Ley 1581 (no es concepto jurídico; lo revisa un abogado antes del primer colegio)
- **Dato mínimo del menor:** nombre, código escolar interno (no la tarjeta de identidad), usuario y hash del PIN.
- **Consentimiento:** el colegio lo declara al emitir credenciales; `audit_logs` guarda quién, cuándo y qué grupo. Ni PIN ni token en logs.

## 8. Pasos de Christiam (claves solo en el panel de Supabase, jamás en archivos ni en el chat)
**0. JWT Keys:** dile al coordinador si ves "Legacy JWT secret" o "signing keys".

**1. Correo** (el SMTP de Supabase solo envía al equipo, 2/h, `auth-smtp`): crea una cuenta SMTP y verifica tu dominio; pega sus datos en *Authentication → SMTP*; sube el límite por hora; activa *Confirm email*; pon la web en *URL Configuration*.

**2. Google** (console.cloud.google.com): proyecto "ENGRAMA"; *Branding*: nombre y correo; *Audience*: External; *Clients → Web application* con *origins* = la web y *redirect URI* = la de *Providers → Google* en Supabase (local: `http://127.0.0.1:54321/auth/v1/callback`). Copia ID y secreto en Supabase y publica.

**3. Microsoft** (portal.azure.com; `auth-azure`):
*Entra ID → App registrations → New* ("cualquier directorio y cuentas personales"); *Redirect URI* Web = la callback (local: `localhost`); *Certificates & secrets*: crea un secreto y agenda su vencimiento; *Manifest*: claims `email` y `xms_edov`. Copia ID y secreto en *Azure* de Supabase, *Tenant URL* vacía. La web pide el scope `email`.

## 9. Orden y veredicto
**Orden** (un commit cada uno): L1 la 032 · L2 `validate_jwt` (U1, U2, Z1-Z4) · L3 `/me` y onboarding · L4 licencias · L5 credenciales · L6 PIN · L6b invitado (A9-A14, Z19-Z24) · L7 humo y réplica · L8 matriz medida.

**Veredicto:**
- **FUNCIONA:** cuentas exactas, matriz = §3, H1, H2 y réplica en verde, lo previo idéntico.
- **HAY ALGO MODESTO:** H2 falla solo por llegar ES256.
- **NO:** A1-A8 dan 2xx, un tramposo queda verde, un PIN en claro o cambia algo previo.
