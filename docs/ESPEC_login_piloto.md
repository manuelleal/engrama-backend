# ESPEC · Login del piloto (el subconjunto mínimo de la 008), backend

F4 · Creador · 2026-09-28 · preregistro. Rama `test/fixture-integ`, HEAD `508d568`. Origen: el despliegue del piloto de ARQUITECTO (`ENGRAMA/despliegue/docs/ESPEC_despliegue_piloto.md` §5.1, §10 y §11), medido contra `5566c47`.

**Corregido tras la auditoría (H-1, H-3 y H-4), antes de escribir código.** Es una corrección de preregistro: no hay nada medido que mover.
- H-1: el origen de cada rojo, en §3.
- H-3: el orden de la bandera y la cuenta, en §1.7 paso 4, con OP8 y ZP19.
- H-4: las rutas permitidas por `(path, método)`, en §1.5, con ZP20.
- Las cuentas se recalculan en §5 y §6.

**El piloto es multitenant real:** UIS, SENA y UNAD comparten un solo despliegue.

**Depende de BUG-13, 14 y 15.** Las cuentas parten de su meta final: **311 passed + 12 skipped y 100 no-integ** (`ESPEC_bug13a15.md` §4), que no está medida. Esta espec no toca los archivos de BUG-13: `src/challenge_engine/*`, `service/coins.py`, `service/attendance.py` ni la 033.

**Subconjunto de la 008** (`ESPEC_login_vendible.md`):
- entra solo el correo con contraseña de GoTrue, con cuentas que crea el operador y contraseña temporal con cambio obligatorio;
- no entran enlace mágico, SMTP, Google, Microsoft, PIN de menores, licencias ni `iss`.

## 0. Medido y leído (`grep -n` el 2026-09-28, sin ejecutar; ERR-10)
`src/auth`, `src/shared/deps.py`, `src/teachers` y `src/shared/config.py` no tienen cambios en el árbol (`git diff --quiet HEAD` sobre esas rutas sale 0). `src/shared/models.py` sí los tiene (BUG-13 le agrega 7 líneas), así que sus líneas se citan **en HEAD** (`git show 508d568:src/shared/models.py`).

| Qué | Dónde |
|---|---|
| El respaldo "solo desarrollo" | `src/auth/service.py:80-117` (`get_or_create_profile`). `:104` `short = str(profile_id).replace("-", "")[:8]`, `:110` `documento_id=short`, `:106` `full_name = str(email)` y `:115` `await db.commit()` |
| Quién lo llama | `src/shared/deps.py:81` (en **toda** ruta autenticada) y `src/auth/router.py:34` (`/auth/me` y `/auth/session`) |
| `documento_id` UNIQUE global | `alembic/versions/002_create_profiles.py:24`; `models.py:101` (HEAD) |
| Choque → 500 | con `sub[:8]` igual al `documento_id` de otro perfil, el INSERT de `:110` viola el UNIQUE y ningún `exception_handler` lo atrapa |
| M3 crea el perfil con `uuid4()` | `src/teachers/service/roster.py:130` (`id=uuid4(), documento_id=documento_id, full_name=""`) |
| M3 no valida el formato | `src/teachers/schemas.py:115`: `documento_id: str` |
| M4 sí lo valida | `roster.py:176` `DOC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")`, usado en `:231` después de `.strip()` |
| `roster.py` importa de `schemas.py` | `roster.py:20` (`from src.teachers.schemas import GroupCreateIn`). Por eso la regex no puede vivir en `roster.py` e importarse desde `schemas.py`: sería un ciclo |
| El colegio activo | `service.py:186-233` (`build_auth_context`). `X-Tenant-ID` **ya se valida** contra las membresías: `:206-221`, con 400 si no es UUID y 403 si no es miembro. Sin el encabezado, `:224` `chosen = memberships[0]` |
| **`memberships[0]` sin orden** | `get_memberships` (`service.py:123-139`) **no tiene `ORDER BY`**. Con dos o más membresías, el colegio por defecto no está definido |
| `MembershipOut` sin nombre | `src/auth/schemas.py:21-31`: `tenant_id`, `tenant_name`, `tenant_slug`, `role`, `group_code` e `is_active` |
| `ProfileOut.full_name` sale del perfil | `service.py:160-177` (`profile_to_schema`); `schemas.py:34-48` |
| El nombre vive en la membresía (BUG-11) | `032_nombre_por_membresia.py`; `models.py:163` (HEAD) `Membership.full_name` |
| **La bandera ya existe y nadie la usa** | `002_create_profiles.py:36` `force_password_reset BOOLEAN NOT NULL DEFAULT FALSE`; `models.py:114-116` (HEAD). `grep -rn force_password_reset src tests` solo la encuentra en `models.py` |
| Membresías con fecha | `models.py:156` (HEAD) `Membership.created_at` |
| Configuración | `src/shared/config.py:41` `supabase_url`, `:45` `supabase_service_role_key` (declarada y sin uso en `src`) y `supabase_anon_key` |
| Mapa de guardas por ruta | `tests/teachers/test_access.py:57-78` (`_PREVIAS`): toda ruta nueva debe entrar al mapa |
| Fábricas de prueba | `tests/integ_ayudante.py:115` `crear_tenant` (con billetera), `:128` `crear_perfil`, `:167` `afiliar` y `:321` `headers` (JWT HS256, sin `app_metadata`) |
| Cómo el piloto lo resuelve hoy | `despliegue/crear_cuentas.py`: el stub vía `/auth/me`, las membresías admin y teacher por SQL, el tenant y la billetera por SQL (`asegurar_colegio`), y **tokens de usuario acuñados con el secreto JWT** (`token_de_servicio_para`) |

## 1. Qué cambia (una cosa)
**Una persona que da de alta el operador entra con su correo y su contraseña de GoTrue, y el backend la reconoce por el `sub` sin crear nada, en el colegio correcto y con su nombre.**

Siete piezas de una misma cosa, en commits separados (§6).

### 1.1 El vínculo: `profiles.id = sub`, con la cuenta creada **con el id del perfil**
**Decisión:** la invariante de hoy se queda. El `sub` del JWT es `profiles.id`, y así lo suponen `SPECS/01-auth.md`, las políticas con `auth.uid()` de la 029 y el JWT propio de la 008.

Lo que cambia es el **orden**:
1. primero existe el perfil (lo crea M3, M4 o el alta del operador, con `uuid4()` como hoy);
2. después, el alta del operador (§1.7) crea la cuenta de GoTrue con `POST /admin/users {"id": <profiles.id>, "email", "password", "email_confirm": true}`.

El `sub` de esa cuenta **es** el `profiles.id`, así que no hay nada que enlazar.

**Por qué esta opción:**
- no necesita migración ni cambia M3 o M4;
- enlaza también un perfil que ya existía (creado por M3 desde la web);
- el docente que trabaja en dos instituciones tiene un perfil (misma cédula) y una cuenta;
- no abre ninguna ruta HTTP nueva para crear identidades.

**Descartadas:**
- **Tabla de identidad `(sub → profile_id)`:** rompe `profiles.id = sub`, necesita migración y agrega una consulta a cada request.
- **M3 y M4 aceptan `sub` por HTTP:** el admin de un colegio podría pre-reclamar un `sub` ajeno, porque el backend no puede verificar a quién pertenece sin la API admin de GoTrue.
- **M3 y M4 aceptan `correo` y el backend crea la cuenta:** pone la entrega de contraseñas en una ruta de admin de colegio. Eso es la invitación de la 008.
- **Mantener el stub y enlazar por correo al primer ingreso:** guarda correos (Ley 1581, dato mínimo) y conserva el choque.

**P0, precondición MEDIDA antes del código (ERR-14):** que GoTrue `v2.196.0` (la imagen del piloto) respete `id` en `POST /admin/users`.

> **P0 MEDIDO = SÍ (2026-09-28, por ARQUITECTO en el stack local `engrama-piloto`, directo contra `gotrue:9999`):**
> - `POST /admin/users` con un `id` elegido → 200, y el `id` devuelto es idéntico;
> - `POST /token?grant_type=password` → 200, y el `sub` del JWT es idéntico;
> - el usuario de prueba se borró.
>
> Va el diseño "perfil primero"; la alternativa "sub primero" no se aplica.

- Se predice que sí (`AdminUserParams.Id` en supabase/auth), pero **no se verificó**.
- La mide ARQUITECTO en su stack, con su permiso para Docker (ERR-21): una cuenta sintética con un id elegido, y después `GET /admin/users/{id}` debe dar 200.
- **Si P0 falla, la alternativa preregistrada es "sub primero":**
  - el alta crea la cuenta, lee su `id` y crea el perfil con `id = sub` mediante un parámetro de servicio `perfil_id` en `enroll_student` y en `asegurar_perfil`, que usa **solo** el alta y nunca HTTP;
  - límite declarado: un perfil que ya existía sin cuenta **no se puede vincular**. OP6 pasa a esperar el error `perfil_sin_cuenta_no_vinculable` con 0 cambios;
  - ZP1 pasa a ser "el alta ignora el `id` que devuelve GoTrue", con la misma diagonal.

### 1.2 Sin el respaldo de desarrollo
- `get_or_create_profile` se reemplaza por `get_profile(db, profile_id) -> Profile | None`, que **nunca escribe**.
- Un JWT válido cuyo `sub` no tiene perfil → **403 `{"detail": "Account has no ENGRAMA profile"}`**, con 0 filas nuevas en cualquier tabla.
- Esto cierra el 500 por choque de `sub[:8]`: ya no hay INSERT que choque.
- El 403 por falta de membresía no cambia (`service.py:200-202`, `"User has no active tenant memberships"`). El cliente distingue los dos casos por el `detail`.

### 1.3 El colegio activo con varias membresías
- **Con `X-Tenant-ID`:** el colegio pedido, validado contra las membresías activas. Ya existe (`service.py:206-221`) y no cambia: 400 si no es UUID, 403 si no es miembro.
- **Sin el encabezado:** la membresía activa **más antigua**. `get_memberships` ordena por `Membership.created_at` y luego por `Membership.id`, así que es determinista.
  - Hoy es `memberships[0]` sin `ORDER BY` (§0). El docente de UIS y SENA podía caer en cualquiera de las dos, y un reto sin `group_id` podía crearse en la institución equivocada.
- **Contrato para el cliente (aviso a ARQUITECTO, W22):**
  - si `memberships` tiene más de un elemento, el cliente manda `X-Tenant-ID` en **toda** llamada;
  - `/auth/me` dice cuál quedó activo (§1.4).
- Exigir el encabezado cuando hay más de una membresía queda en "Para después" (§10): es más seguro, pero rompe al cliente de hoy.

### 1.4 `/auth/me` (y `/auth/session`, que comparten el cuerpo)
Solo se **agregan** campos; ninguno previo desaparece:
- **`active_tenant_id: UUID`:** el tenant que resolvió `build_auth_context`.
- **`must_change_password: bool`:** `profiles.force_password_reset` (§1.5).
- **`memberships[].full_name: str | None`:** `Membership.full_name`, el nombre que escribió **esa** institución (BUG-11).
- **`full_name`** (ya existe) pasa a ser el de la **membresía activa**. Si esa membresía no tiene nombre (docente o admin creados antes de esta espec), se usa `profiles.full_name`, el nombre propio de la cuenta según la 032.
  - No reabre BUG-11: es el propio usuario viendo su nombre, y ningún colegio ve lo que escribió otro.
  - Un perfil stub ya no puede aparecer (§1.2), así que el correo deja de salir como nombre.

`role`, en la raíz, sigue siendo `profiles.role`. El rol que cuenta es el de `memberships[activa]`, como ya prueba `test_a6_rol_del_perfil_no_da_permisos`. Se documenta y no se cambia.

### 1.5 Contraseña temporal y cambio obligatorio
**Dónde vive la bandera: `profiles.force_password_reset`**, que ya existe (§0) y no necesita migración.
- **Descartado `user_metadata` de GoTrue:** el propio usuario lo puede reescribir con `PUT /user` y saltarse el cambio.
- **Descartado `app_metadata`:** solo se limpia con la clave de servicio, y el JWT viejo la conserva hasta que vence.
- En la BD, el backend la lee en cada request (el perfil ya se carga en `get_current_user`) y **nadie más** la escribe.

**Quién la pone en `true`:** el alta del operador, solo al **crear** una cuenta o al **restablecerla** (§1.7). Nunca a una cuenta que ya existía.

**Bloqueo:** con la bandera en `true`, `get_current_user` responde **403 `{"detail": "must_change_password"}`** en toda ruta menos cuatro:
- el conjunto exacto, **indexado por `(path, método)`** como `EXPECTED_GUARDS` de `test_access.py`:
  ```python
  RUTAS_CON_CONTRASENA_TEMPORAL = frozenset({
      ("/auth/me", "GET"), ("/auth/session", "POST"),
      ("/auth/logout", "POST"), ("/auth/contrasena", "POST"),
  })
  ```
- la clave es `(request.scope["route"].path, request.method)`; si falta la ruta, no se permite (falla cerrado);
- **por qué el método (H-4):** con solo el path, una ruta futura `DELETE /auth/me` o `POST /auth/me` heredaría el permiso sin que nadie lo decida;
- es una lista de permitidas: una ruta nueva queda bloqueada por defecto;
- `puede_con_contrasena_temporal(path: str, metodo: str) -> bool` es la función pura que usan `get_current_user` y UP3.

**`POST /auth/contrasena {"nueva": str}`**, con guarda `user`:
- `nueva` debe tener entre 10 y 72 caracteres (72 bytes es el límite de bcrypt); si no, 422 sin llamar a GoTrue;
- el backend llama a GoTrue `PUT /user` **con el mismo Bearer del usuario** (y `apikey: supabase_anon_key` si está configurada), con `{"password": nueva}`;
- **no usa la clave de servicio:** menor privilegio, y GoTrue valida el token por su cuenta;
- si GoTrue responde 200: `force_password_reset = false`, commit y **204**. El mismo token sigue sirviendo, porque la bandera se lee de la BD;
- si GoTrue responde 422 (clave débil o igual a la anterior): **422 `{"detail": "password_rejected"}`**, y la bandera no cambia;
- si GoTrue no responde o da 5xx: **502 `{"detail": "password_change_failed"}`**, y la bandera no cambia;
- si no hay URL de GoTrue configurada: **503 `{"detail": "password_change_not_configured"}`**;
- la configuración nueva es `gotrue_url` (`GOTRUE_URL`); si está vacía, se usa `supabase_url + "/auth/v1"`.

**Puerto:** `src/auth/cuentas.py` define `CambioDeClave` (protocolo con `async cambiar(token, nueva)`), el adaptador httpx `GoTrueCambioDeClave` y la dependencia `get_cambio_de_clave`. Los tests la reemplazan con `dependency_overrides` por un doble que registra las llamadas.

### 1.6 D1: `documento_id` (decidido por Christiam el 2026-09-28)
**Se acepta el documento nacional (CC, TI o CE) tal cual, y también un código interno con el prefijo del tenant, que ponen los scripts de alta** (p. ej. `sena_001`).
- **`documento_id` es OPACO:** el backend nunca parsea el prefijo ni infiere el tipo.
- **M3 valida con la misma regex que M4** y responde 422 si no cumple:
  - una sola fuente, `DOC_ID_PATRON = r"^[A-Za-z0-9_-]{3,32}$"` en `src/teachers/schemas.py`;
  - `StudentEnrollIn.documento_id: str = Field(pattern=DOC_ID_PATRON)`;
  - `roster.py` pasa a `DOC_ID_RE = re.compile(DOC_ID_PATRON)`, con el mismo nombre exportado en `__all__` (`roster.py:94`).
- **La regex no cambia.** Admitir `:` (para `sena:001`) queda **declarado como opción, no se hace por defecto**. Si Christiam lo pide, se cambia esa única constante y el caso `"sena:001" → 422` de AP11 pasa a 201 (un commit con su ERR, regla 8).
- **Diferencia declarada:** M4 hace `.strip()` antes de validar (`roster.py:231`) y M3 no, así que `" 123"` da 422 en M3. M3 es JSON y no se limpia a escondidas.
- **M2** (`TeacherAssignIn`) no cambia: un formato malo da 404, no 500 (§10).

**Riesgos para Christiam** (no se re-litiga D1; se anotan):
- **La cédula de extranjería no sale de la misma serie que la CC y la TI** (NUIP). Un CE y una CC con los mismos dígitos se fusionarían en un solo perfil. El alta **no** lo resuelve. La opción, si él la quiere, es que el alta escriba `ce_<número>`. Ahora no se hace.
- **Un código interno escrito en la web sin prefijo** (M3 por HTTP, p. ej. `001`) pasa la regex y puede fusionarse con el `001` de otra institución. Solo el alta pone el prefijo. Que el backend lo imponga queda en "Para después" (§10).

### 1.7 Alta de la institución y de las personas: una CLI versionada, **sin endpoint**
**Decisión: no hace falta un endpoint.** Crear un tenant, fondear su billetera (emitir monedas) y crear cuentas de GoTrue son acciones **del operador de la plataforma**, no del admin de un colegio.
- Un endpoint necesitaría un rol de plataforma que no existe y expondría la emisión de monedas por HTTP.
- La 008 traerá su propio onboarding de tenants personales.

**`python -m src.onboarding`** (paquete `src/onboarding/`: `csv_personas.py`, `alta.py` y `__main__.py`):
- **`alta --nombre "<institución>" --slug <slug> --monedas <n> --csv <ruta> --salida <ruta>`**
  1. **Valida todo el CSV antes de escribir** (`leer_csv`, función pura):
     - columnas `nombre, correo, documento, tipo_documento, grupo, rol`; UTF-8 con o sin BOM, o cp1252; separador `,` o `;`;
     - `tipo_documento` ∈ {`CC`, `TI`, `CE`, `CODIGO`}:
       - CC, TI y CE: se quitan puntos y espacios; después, solo dígitos y `DOC_ID_RE`;
       - `CODIGO`: el alta escribe `<slug>_<código>` y el resultado debe cumplir `DOC_ID_RE` (máximo 32 caracteres);
     - `rol` ∈ {`estudiante`, `profe`, `admin`}, `estudiante` si está vacío; estudiante y profe exigen `grupo`;
     - un mismo documento con dos roles, un estudiante en dos grupos o un correo con dos documentos → error;
     - un profe con dos grupos va en dos filas;
     - todos los errores salen juntos, con su número de fila, y no se escribe nada.
  2. **Institución:** tenant por `slug`. Si no existe, se crea con `coin_pool = monedas` y su billetera (`owner_type='tenant'`, `balance = monedas`), igual que `integ_ayudante.crear_tenant`.
     - Si ya existe, se reusa y **la billetera nunca se recarga**.
     - `--monedas` es **obligatorio y sin valor por defecto**: la cifra la decide Christiam (hoy 200.000 provisional).
  3. **Personas, en UNA transacción:**
     - perfil por documento (crea `uuid4`, `full_name=''`, `pin_hash=''`);
     - membresía `admin` o `teacher` con `full_name` del CSV;
     - grupos con `create_group` (M1; si ya existe, se reusa);
     - docentes con `assign_teacher` (M2) y estudiantes con `enroll_student` (M3), con los servicios de siempre.
     - Cualquier error (p. ej. un 409 de M3) → ROLLBACK de todo y se reporta la fila.
  4. **Cuentas:** una por perfil del CSV, después del commit.
     - `CuentasAdmin.buscar(profiles.id)`. Si la cuenta existe, **no se toca**: la contraseña y la bandera siguen iguales, y se reporta `cuenta_existente`, más `cuenta_con_otro_correo` si el correo difiere.
     - Si no existe:
       - `force_password_reset = true` y commit;
       - `crear(id = profiles.id, correo, clave)`;
       - si se creó, **se anota de inmediato** en `--salida`;
       - si el correo ya es de otra cuenta, error de esa fila (salida 1 al final).
     - **Orden decidido (H-3): la bandera primero y la cuenta después.** Se mantiene y se declara el estado intermedio.
       - **Estado "perfil con bandera, sin cuenta":** aparece si `crear` falla o el proceso muere entre el commit y `crear`. Queda **pendiente hasta la próxima corrida idempotente**:
         - `buscar` da `None`;
         - se vuelve a poner la bandera (ya estaba en `true`, sin efecto);
         - `crear` completa la cuenta.
         - Es **inocuo**: sin cuenta en GoTrue nadie puede entrar con ese perfil, y la bandera en `true` no bloquea nada que exista.
       - **Por qué no invertir el orden (cuenta primero, bandera después):** si el proceso muere entre `crear` y el commit, queda una cuenta **con la bandera en `false`**, es decir, una contraseña temporal que no obliga a cambiarse.
         - La próxima corrida tampoco lo arregla: `buscar` encuentra la cuenta y, por C18 y ZP18, **no toca** su bandera.
         - Ese orden falla abierto y para siempre. El elegido falla cerrado y se corrige solo.
       - **Criterio nuevo C24 (OP8)**, con su tramposo ZP19 (el orden invertido).
       - El `restablecer` sigue la misma regla: la bandera en `true` y commit, **antes** de `cambiar_clave`. Si `cambiar_clave` falla, la persona queda obligada a cambiar una contraseña que sigue siendo la suya: falla cerrado.
  5. Imprime un resumen JSON **sin contraseñas**.
- **`restablecer --slug <slug> --documento <doc> --salida <ruta>`:**
  - el documento debe tener una membresía activa en ese tenant y una cuenta; si no, error y 0 cambios;
  - clave nueva, `force_password_reset = true` y `cambiar_clave` por la API admin;
  - la anota en `--salida`.
  - Sin SMTP no hay "olvidé mi contraseña": esta es la salida.
- **Contraseña temporal:** `secrets`, 3 bloques de 4 caracteres de un alfabeto sin 0/o ni 1/l/i (14 caracteres con los guiones), como la de ARQUITECTO.
- **`--salida`:**
  - CSV `nombre, correo, rol, grupo, contrasena_temporal, creado_en`, **sin documento** (dato mínimo);
  - se abre en modo *append*;
  - si la ruta resuelta queda **dentro del repo del backend**, sale con 2 **antes de escribir nada**.
- **Credenciales:**
  - `DATABASE_URL`, `GOTRUE_URL` y `SUPABASE_SERVICE_ROLE_KEY` solo por variable de entorno;
  - **la clave de servicio solo la usa la CLI**, nunca el proceso web;
  - nunca aparece en un archivo del repo, en el resumen ni en un log.
- **Puerto:** `CuentasAdmin` (protocolo: `buscar(id) -> correo | None`, `crear(id, correo, clave) -> "creada" | "correo_en_uso"` y `cambiar_clave(id, clave)`), con el adaptador httpx `GoTrueAdmin`.
  - `main(argv, *, cuentas=None, sesiones=None) -> int` permite inyectar el doble y la sesión del fixture.
  - El doble vive en `tests/cuentas_falsas.py`:
    - rechaza un `id` repetido como GoTrue (predicho), **lanzando `ErrorCuenta("id_en_uso")`**, que la CLI atrapa por fila y convierte en salida 1;
    - genera un `uuid4` si no recibe `id` (para ZP1);
    - acepta `fallar_en: set[documento]`, para que `crear` falle en OP8;
    - acepta un observador asíncrono que, **al entrar a `crear`**, lee `force_password_reset` del perfil **desde otra conexión** (el engine `NullPool` del fixture). Así solo ve lo que ya está commiteado.

### 1.8 Migración: **ninguna**
Nada de esto cambia el esquema: `force_password_reset` existe desde la 002, `Membership.full_name` desde la 032 y `created_at` desde la 003.
- **El piloto no toma la 034.**
- **`034_login_vendible` sigue reservada para la 008** completa, sobre `033_una_paga_por_reto` (`ESPEC_bug13a15.md` §6).
- `HUMO_ESPERADO` no cambia.

## 2. Criterios (medibles)
| # | Criterio | Test que se pone rojo |
|---|---|---|
| C1 | **JWT de otro proyecto:** un usuario **con** membresía y un token firmado con otro secreto → 401 en `/auth/me` y en `GET /challenges/`. Control: los mismos claims con el secreto correcto → 200 | AP1 |
| C2 | **Vencido** (`exp` = ahora − 60 s), usuario con membresía → 401. Control → 200 | AP2 |
| C3 | **Sin perfil:** JWT válido con un `sub` sin perfil → 403 `Account has no ENGRAMA profile` en `/auth/me` y en `/auth/session`. `count(*)` de `profiles` y `memberships` no cambia; no hay fila con `id = sub` | AP3 |
| C4 | **El choque de hoy:** hay un perfil con `documento_id = "12345678"` y llega un JWT con `sub = 12345678-0000-4000-8000-000000000001`, sin perfil. Hoy da **500**; debe dar el mismo 403 de C3, con 0 filas nuevas | AP4 |
| C5 | **Perfil sin membresía activa** (sin membresías, o con una inactiva) → 403 `User has no active tenant memberships` | AP5 |
| C6 | **Tres instituciones A, B y C:**<br>- el estudiante de A con `X-Tenant-ID` de B → 403, y de C → 403;<br>- el docente de A, `GET /teachers/groups` con B → 403;<br>- el admin de A, `POST /admin/groups` con C → 403, y C sigue con 0 grupos;<br>- el admin de A, M3 sobre el `gid` de un grupo de B → 404, y B sigue con 0 membresías nuevas;<br>- `X-Tenant-ID: xyz` → 400 | AP6 |
| C7 | **Docente en dos instituciones** (un perfil y dos membresías: A creada hace un día, B ahora, **B insertada primero**):<br>- sin encabezado, 3 llamadas dan `active_tenant_id = A` y el `full_name` que escribió A;<br>- con `X-Tenant-ID: B` → B y el nombre de B;<br>- `memberships` en orden [A, B], cada una con su `full_name`;<br>- con C → 403 | AP7 |
| C8 | **Estudiante matriculado por M3** (perfil con `full_name = ''`, membresía "Ana Sintética"): `/auth/me` da `full_name = "Ana Sintética"` y `memberships[0].full_name` igual | AP8 |
| C9 | **Contraseña temporal** (`force_password_reset = true`):<br>- `/auth/me` → 200 con `must_change_password: true`; `/auth/session` → 200;<br>- `GET /challenges/` y `GET /core/coins/balance` → 403 `must_change_password`;<br>- un token con `user_metadata.must_change_password = false` sigue en 403;<br>- control: otro usuario sin la bandera → 200 | AP9 |
| C10 | **Cambio de contraseña:**<br>- `{"nueva": "corta"}` → 422, el doble no se llama y la bandera sigue;<br>- una clave válida → 204, el doble registró (el token del usuario, la clave), la bandera queda en `false` y el **mismo** token da 200 en `GET /challenges/`;<br>- el doble falla → 502 y la bandera sigue en `true` | AP10 |
| C11 | **M3 valida `documento_id`** (admin real):<br>- `"12.345.678"`, `"sena:001"` y `"ab"` → 422 con `loc == ["body","documento_id"]`, y 0 perfiles nuevos;<br>- `"1098765432"`, `"sena_001"` y `"uis-A-7"` → 201 | AP11 |
| C12 | **Identidad de `/auth/me`:** para un estudiante con una sola membresía, la respuesta es **byte a byte** el snapshot congelado antes del cambio, sin contar las claves nuevas (`active_tenant_id`, `must_change_password` y `memberships[].full_name`) y con los ids normalizados por posición | SP1 |
| C13 | **Una sola fuente de la regex:** `DOC_ID_RE.pattern == DOC_ID_PATRON`; el `pattern` de `StudentEnrollIn.documento_id` es `DOC_ID_PATRON`; `DOC_ID_RE.match("sena:001") is None` | UP1 |
| C14 | **CSV del alta** (puro): CC con puntos → solo dígitos; `CODIGO 7` en `sena` → `sena_7`; un `CODIGO` que pasa de 32 con el prefijo → error; TI con letras → error; estudiante sin grupo → error; dos roles → error; profe en dos grupos → 2 filas válidas; `;`, BOM y cp1252; varios errores → todos juntos con su fila | UP2 |
| C15 | **Lista de permitidas por `(path, método)`:**<br>- para cada `APIRoute` de la app y cada método de `route.methods`, `puede_con_contrasena_temporal(path, método)` es verdadero **solo** para los 4 pares de §1.5;<br>- además, 4 pares que hoy no existen dan falso: `("/auth/me", "POST")`, `("/auth/me", "DELETE")`, `("/auth/contrasena", "GET")` y `("/auth/session", "GET")` | UP3 |
| C16 | **Institución:**<br>- `alta` con 1000 → 1 tenant, billetera 1000 y `coin_pool` 1000;<br>- la 2.ª `alta` con `--monedas 5000` → billetera 1000, `coin_pool` 1000 y 0 filas en `coin_ledger` | OP1 |
| C17 | **Alta completa** (admin, profe y 3 estudiantes en un grupo):<br>- 5 perfiles y 5 cuentas en el doble, **cada una con `id == profiles.id`** (el vínculo);<br>- las 5 con `force_password_reset = true`;<br>- `--salida` con 5 filas, 5 claves distintas y sin documento;<br>- membresías: 1 admin, 1 teacher (y su fila en `teacher_groups`) y 3 students con el nombre del CSV;<br>- con `headers(profiles.id)`, `/auth/me` → 200 y `must_change_password: true`;<br>- el stdout no contiene ninguna clave | OP2 |
| C18 | **Idempotencia:** después de la 1.ª corrida se pone la bandera en `false` a uno; la 2.ª corrida da 0 perfiles, 0 membresías y 0 cuentas nuevas, `--salida` sigue con 5 filas y **esa bandera sigue en `false`** | OP3 |
| C19 | **Multi-institución:**<br>- el profe D (CC 7001) está en el CSV de A y en el de B con otro correo;<br>- resultado: 1 perfil, **1** cuenta (la del correo de A) y 2 membresías teacher;<br>- el resumen de B dice `cuenta_existente: 1` y `cuenta_con_otro_correo: 1`;<br>- el doble recibió 1 solo `crear` para D;<br>- **antes de la corrida de B** se pone la bandera de D en `false` (D ya cambió su clave), y después sigue en `false`;<br>- `/auth/me` de D sin encabezado → A, y con B → B | OP4 |
| C20 | **Todo o nada:**<br>- una fila mala (CC `12a`) → salida 1, con 0 tenants, 0 perfiles y 0 cuentas, y sin archivo de salida;<br>- un choque en la BD (el estudiante ya está en otro grupo de ese tenant) → ROLLBACK: 0 perfiles, 0 membresías nuevas y 0 cuentas;<br>- `--salida` dentro del repo → salida 2 y 0 escrituras | OP5 |
| C21 | **Perfil previo sin cuenta:** el admin matricula X por M3 (HTTP, `uuid4`); el alta con X crea la cuenta con `id ==` ese perfil, y la matrícula da `ya_estaba` | OP6 |
| C22 | **Restablecer:**<br>- con la bandera ya en `false`, `restablecer` del documento X → el doble registró `cambiar_clave(X.id, nueva)`, la bandera vuelve a `true` y hay 1 fila más en `--salida`;<br>- un documento de otro tenant → salida 1 y 0 cambios;<br>- un documento sin cuenta → salida 1 | OP7 |
| C24 | **La bandera antes que la cuenta (H-3):**<br>- en una corrida con 3 personas nuevas, el observador del doble ve `force_password_reset = true`, **ya commiteada**, en las 3 llamadas a `crear`;<br>- si `crear` falla para una persona: salida 1; esa persona queda con perfil y bandera en `true`, sin cuenta y sin fila en `--salida`, y las otras 2 quedan completas;<br>- una 2.ª corrida sin fallos crea **esa** cuenta (`id == profiles.id`) y agrega 1 fila, con la bandera en `true` y 0 cuentas nuevas para las otras 2 | OP8 |
| C23 | Regresión: los 311 previos siguen verdes. Única edición: una entrada en el mapa de guardas (§3). D12 da 0 y 0 | la suite completa |

## 3. Tests y tramposos
**Archivos:**
- `tests/auth/test_login_piloto.py`: AP1-AP10 y SP1 (integ); snapshot en `tests/auth/snapshot_me_antes.json`, generado en el paso 1.
- `tests/teachers/test_m3_documento.py`: AP11 (integ) y UP1 (no-integ).
- `tests/auth/test_permitidas_unit.py`: UP3 (no-integ).
- `tests/onboarding/test_csv_personas.py`: UP2 (no-integ).
- `tests/onboarding/test_alta.py`: OP1-OP8 (integ, con `tests/cuentas_falsas.py`).
- `tests/integ/test_humo_login_piloto.py`: HP1.

**Reglas comunes:**
- Todos los AP usan `TestClient(app, raise_server_exceptions=False)`, para que un 500 sea un `AssertionError`.
- Leen las claves con `.get()`, para que la falta de un campo también sea un `AssertionError`. Así corren en el paso 1 con `xfail(strict=True, raises=AssertionError)`.
- ERR-9: el estado previo se siembra en la base; cada test depende solo de la ruta que prueba.
- **AP7** fija `created_at` por SQL e inserta B antes que A, para que el orden físico no coincida con el cronológico (predicho; ver ZP4).

**Única edición a un test existente:** `tests/teachers/test_access.py` recibe un dict `_LOGIN_PILOTO = {("/auth/contrasena", frozenset({"POST"})): "user"}`, sumado a `EXPECTED_GUARDS`. `_PREVIAS` y `_NUEVAS` no se tocan.

**Tramposos:**
- Van en `tests/tramposos/test_tramposos_login_piloto.py` (integ) y en `test_tramposos_login_piloto_unit.py` (no-integ).
- Patrón de `test_tramposos_integ.py`: monkeypatch en el módulo donde se **usa** y `pytest.raises(AssertionError)` sobre el cuerpo del test real.
- Para cambiar el **esquema** de una ruta (ZP9), se reemplaza la `APIRoute` en `app.router.routes` con `monkeypatch.setitem`, como en `ESPEC_bug16.md` §3.

**Diagonal y cruces PREDICHOS** (ERR-15, ERR-19 y ERR-23: el código no existe).

Cada celda roja dice de dónde sale el rojo:
- **as:** una aserción del test;
- **ex:** una excepción que no es `AssertionError`;
- **prep:** falla la preparación antes de llegar a la aserción.

Cada fila recorre **todas** las columnas que pasan por el mismo camino de datos que rompe el tramposo. Lo que no se nombra en una fila está en "Inalcanzables".

**Ninguna celda roja sale de la preparación (predicho).** OP3, OP4, OP7 y OP8 usan la CLI en su preparación, pero ningún tramposo la hace fallar antes de la acción del test; eso se comprueba al medir.

| Id | Rompe | Rojo predicho (diagonal en negrita) | Verde predicho y por qué |
|---|---|---|---|
| ZP1 | El alta llama a `crear` sin `id` (GoTrue elige el `sub`) | **OP2** (as: `id ≠ profiles.id`).<br>OP6 (as: la cuenta no tiene el id del perfil de M3).<br>OP3 (as: en la 2.ª corrida `buscar(profiles.id)` da `None`, vuelve a crear, el correo ya está en uso y sale con 1).<br>OP4 (as: la corrida de B no encuentra la cuenta de D y crea otra: 2 `crear`).<br>OP7 (as: `restablecer` no encuentra la cuenta y sale con 1).<br>OP8 (as: la 2.ª corrida choca con los correos ya usados).<br>HP1 (as: `cuenta_igual_perfil` = 0) | OP1: no hay personas. OP5: todo o nada falla antes de las cuentas |
| ZP2 | `deps_mod.get_profile` = el `get_or_create_profile` viejo | **AP3** (as: `profiles` crece y el `detail` es el de sin membresía).<br>**AP4** (as: 500, con `raise_server_exceptions=False`) | AP1, AP2 y AP5-AP11, SP1, OP y HP1: todos llaman con un perfil que existe, y ahí la función vieja no escribe |
| ZP3 | `full_name` de `/auth/me` sale del perfil | **AP8** (as: `''`).<br>AP7 (as: el nombre del factory, no el de A ni el de B).<br>HP1 (as: `nombre_de_la_membresia` = false, porque el perfil que crea el alta tiene `full_name = ''`) | SP1: el factory pone el mismo nombre en el perfil y en la membresía (por eso SP1 no la detecta). OP2 y OP4: no miran el nombre |
| ZP4 | `get_memberships` con `ORDER BY created_at DESC` | **AP7** (as: activo = B).<br>OP4 (as: D sin encabezado → B).<br>HP1 (as: `sin_encabezado` = "B") | AP6, AP8-AP10 y SP1: una membresía por usuario. **El `memberships[0]` sin orden de hoy no es un tramposo determinista:** AP7 lo pone rojo solo si el plan de Postgres devuelve el orden físico, y eso se mide en el paso 1 (xfail) |
| ZP5 | `build_auth_context` ignora un `X-Tenant-ID` ajeno y usa la primera membresía | **AP6** (as: 200 donde se espera 403).<br>AP7 (as: C → 200).<br>HP1 (as: `otro_colegio` = [200, 200]).<br>Fuera de la matriz, predicho: `test_a7_otro_colegio_no_se_ve` (as) | AP1-AP5, AP8-AP11 y SP1: sin encabezado. OP4: pide B y D **es** miembro de B |
| ZP6 | La bandera (el bloqueo y `must_change_password` de `/auth/me`) se lee del JWT (`user_metadata`) y no de la BD | **AP9** (as: 200).<br>OP2 (as: `must_change_password` = false, porque los tokens de `headers()` no traen metadatos).<br>HP1 (as: `bloqueados_403` = 0) | AP10: afirma sobre la BD, el doble y un 200 que el tramposo también da. OP7 y OP8: afirman la columna en la BD |
| ZP7 (no-integ) | `puede_con_contrasena_temporal = lambda *_: True` | **UP3** (as: los pares no permitidos dan verdadero) | Cruces con AP9 y HP1 (as), predichos pero **no se miden** en este tramposo, porque no los corre |
| ZP8 | `/auth/contrasena` llama al doble y **no** limpia la bandera | **AP10** (as: la bandera sigue en `true` y el mismo token da 403).<br>HP1 (as: `desbloqueados_200` = 0) | AP9: no cambia la clave. OP: no llaman a la ruta |
| ZP9 | La ruta de M3 con `documento_id: str` (se reemplaza la `APIRoute`) | **AP11** (as: `"12.345.678"` → 201).<br>HP1 (as: `documento_con_puntos` = 201) | UP1: lee el esquema, no la ruta. OP6: su M3 manda un documento válido. AP6: su M3 llega al 404 de `authorize_group`, porque la ruta falsa llama al endpoint original. OP: el alta usa el servicio, no la ruta |
| ZP10 (no-integ) | `StudentEnrollIn.model_fields["documento_id"]` con un `pattern` que admite `:` | **UP1** (as) | AP11 y HP1: la validación compilada de la ruta no cambia |
| ZP11 | `asegurar_institucion` recarga la billetera en cada corrida | **OP1** (as: billetera 2000 o 6000).<br>HP1 (as: `segunda_corrida.billetera` = 2000) | OP2-OP8: no afirman el saldo de la institución (OP3, OP4 y OP8 corren dos veces, pero no lo miran) |
| ZP12 | El alta hace commit por fila, sin validar antes todo el CSV | **OP5** (as: quedan tenant y perfiles de las filas buenas; en el choque de BD quedan las filas previas al choque) | OP2-OP4 y OP6-OP8, y HP1: sus CSV son válidos y no chocan, así que el resultado final es el mismo |
| ZP13 | El alta no llama a `buscar` y siempre crea | **OP3** (as: la 2.ª corrida recibe `ErrorCuenta("id_en_uso")` del doble y sale con 1).<br>**OP4** (as: `id_en_uso` para D en B).<br>OP8 (as: la 2.ª corrida choca con las 2 cuentas ya hechas).<br>HP1 (as: la 2.ª corrida de A sale con 1) | OP2, OP6 y OP7: una sola corrida, así que cada perfil se crea una vez. **Si la CLI no atrapara el error del doble, estas celdas serían ex:** eso sería un defecto de la CLI (§1.7) y se reporta |
| ZP14 | `validate_jwt` sin verificar la firma | **AP1** (as: 200 con el token de otro proyecto).<br>`test_me_with_invalid_signature_returns_401` (as).<br>`test_invalid_signature_raises_401` (**ex:** `pytest.raises(HTTPException)` da `Failed: DID NOT RAISE`, que no es `AssertionError`) | AP2: python-jose sigue verificando `exp` sin firma (predicho). `test_malformed_jwt_raises_401`: el token malformado no se decodifica. Los demás de `tests/auth` usan tokens bien firmados |
| ZP15 | `validate_jwt` sin verificar `exp` | **AP2** (as: 200).<br>`test_me_with_expired_token_returns_401` (as).<br>`test_expired_jwt_raises_401` (**ex:** `Failed: DID NOT RAISE`) | AP1: sigue la firma. Los demás tokens están vigentes |
| ZP16 (no-integ) | `leer_csv` no antepone el prefijo a `CODIGO` | **UP2** (as: `7` en vez de `sena_7`) | Cruce con HP1 (as: `codigo_con_prefijo` = false), predicho y no medido aquí. OP2-OP8: solo usan CC |
| ZP17 | `restablecer` no pone la bandera | **OP7** (as: la bandera sigue en `false`).<br>HP1 (as: `restablecer.debe_cambiar` = false y `bloqueado` = 200) | Los demás no restablecen |
| ZP18 | El alta pone la bandera en `true` también a las cuentas existentes | **OP3** (as: la bandera puesta en `false` vuelve a `true`).<br>OP4 (as: la bandera de D, en `false` antes de B, vuelve a `true`) | OP2 y OP6: solo cuentas nuevas. OP8: las otras 2 ya tenían la bandera en `true`, así que ponerla otra vez no se ve. HP1: las dos corridas de A y la de B ocurren **antes** de cambiar las claves |
| ZP19 | Orden invertido: `crear` primero y la bandera después (H-3) | **OP8** (as: el observador ve `false` en `crear`) | OP2, OP3, OP4, OP6 y HP1: el estado **final** es el mismo, y solo OP8 mira el estado intermedio |
| ZP20 (no-integ) | `RUTAS_CON_CONTRASENA_TEMPORAL` indexada solo por path (H-4) | **UP3** (as: `("/auth/me", "POST")` da verdadero) | AP9: con las rutas de hoy, cada path permitido tiene un solo método, así que la API no lo distingue. **Por eso UP3 afirma pares que no existen** |

**Inalcanzables (se tachan, ERR-19):**
- ZP11-ZP13 y ZP17-ZP19 × AP y SP1: los AP no corren el alta.
- ZP2-ZP10, ZP14, ZP15 y ZP20 × UP2: es pura.
- ZP14 y ZP15 × OP: el alta no valida JWT; los `/auth/me` de OP usan tokens válidos.
- ZP7, ZP10, ZP16 y ZP20 × integ: son no-integ y solo corren su diagonal.

**Matriz a medir antes de aceptar:** 20 tramposos × 39 columnas = **780 celdas**. Las columnas son:
- los 24 nuevos no tramposos: AP1-AP11, SP1, UP1-UP3, OP1-OP8 y HP1 (RP1 y RP2 se tachan: van con bandera);
- los 13 de `tests/auth`;
- `test_u4_guardas_de_las_rutas_existentes`;
- `test_a1_auth_me_no_expone_pin_hash`.

Un cruce no previsto se corrige por ERR en esta espec antes de aceptar; el test no se toca (regla 8).

## 4. Humo y réplica
**HP1** (`tests/integ/test_humo_login_piloto.py`, integ) escribe `tests/_salida/humo_login_piloto.json` **antes** de afirmar (el archivo va al `.gitignore`).

**Semilla fija:** `random.Random(8)` elige:
- los documentos (8 a 10 dígitos, distintos);
- el orden de las filas (`shuffle`);
- cuál estudiante de C usa `CODIGO`.

**Siembra**, todo sintético y por la CLI con el doble:
- instituciones `inst-a`, `inst-b` e `inst-c` ("Institución Sintética A/B/C", en el papel de UIS, SENA y UNAD), con 1000 monedas cada una;
- en cada una: 1 admin, 1 profe y 4 estudiantes en un grupo;
- el profe compartido D está en A y en B con la misma CC.

**Flujo:**
1. `alta` de A, B y C, y otra vez de A.
2. Para cada una de las 19 cuentas: `/auth/me`, y después `GET /challenges/` → 403.
3. `POST /auth/contrasena` de cada una; después, `GET /challenges/` → 200.
4. El estudiante de A con `X-Tenant-ID` de B y de C.
5. D sin encabezado y con B.
6. M3 con `"12.345.678"`.
7. `restablecer` de un estudiante de B, y después `GET /challenges/`.

**Contenido exacto** (etiquetas, nunca ids ni correos):
```json
{"semilla":8,"instituciones":3,"cuentas_nuevas":[7,6,6],"cuentas_existentes":[0,1,0],
 "perfiles":19,"membresias":20,"cuenta_igual_perfil":19,"billeteras":[1000,1000,1000],
 "segunda_corrida":{"cuentas_nuevas":0,"membresias_nuevas":0,"billetera":1000},
 "primer_ingreso":{"me_200":19,"debe_cambiar":19,"bloqueados_403":19},
 "cambio":{"respuestas_204":19,"desbloqueados_200":19},
 "otro_colegio":[403,403],
 "docente_compartido":{"sin_encabezado":"A","con_B":"B","nombre_de_la_membresia":true},
 "documento_con_puntos":422,"codigo_con_prefijo":true,
 "restablecer":{"debe_cambiar":true,"bloqueado":403}}
```

Cuentas del humo:
- A = 6 + D = 7 cuentas;
- B = 6 nuevas + D existente;
- C = 6;
- perfiles 7 + 6 + 6 = **19**;
- membresías 7 + 7 + 6 = **20**.

Si no escribe el archivo, no hay corrida grande.

**Réplica** (`ENGRAMA_REPLICA_LOGIN_PILOTO=1`, 2 tests que se saltan sin la bandera; entradas que no se usaron al desarrollar):
- **RP1:**
  - semilla 9; nombres con tildes y ñ ("Íñigo Peña"); CSV con `;`, BOM y cp1252;
  - una CE con puntos (`1.234.567`) y un `CODIGO` con guion;
  - un profe en **tres** instituciones.
  - Se afirma que `cuenta_igual_perfil == perfiles` y `otro_colegio == [403,403]`, y que el profe triple tiene 1 cuenta, 3 membresías y A sin encabezado.
- **RP2:**
  - 40 estudiantes en un grupo en una sola corrida → 40 cuentas, 40 claves distintas y 40 filas;
  - `restablecer` dos veces a la misma persona → 2 filas, y la última clave es la que tiene el doble.

**HP2, manual y no suma** (contra el stack de ARQUITECTO, GoTrue real `v2.196.0`; lo corre quien tenga el permiso de Docker, ERR-21).
- Script `tests/manual/humo_login_piloto_gotrue.py`; pytest no lo recoge. URL y clave solo por variable de entorno.
- Escribe `tests/_salida/humo_login_piloto_gotrue.json` con:
  - **P0** (la cuenta con `id` elegido);
  - un login `password` → `sub == profiles.id`;
  - `/auth/me` con `must_change_password: true` y `/challenges/` → 403;
  - `POST /auth/contrasena` → 204;
  - login con la temporal → 400 y con la nueva → 200;
  - **40 logins desde una IP en menos de 5 min → cuántos 429**.
- Esto último es una medición, no un criterio: el límite por IP de GoTrue detrás de Caddy es configuración del despliegue (`ESPEC_despliegue_piloto.md` §10). Si da algún 429, es un bloqueo del piloto que se reporta a ARQUITECTO.

## 5. Cuentas (ERR-10: la suma a la vista)
**Base: la meta final de BUG-13 a 15, 311 passed + 12 skipped y 100 no-integ.** No está medida. Si cierra con N, S y M, las metas pasan a N + 44, S + 2 y M + 7. *(Antes de H-3 y H-4: N + 41 y M + 6.)*

| Grupo | integ | no-integ |
|---|---|---|
| AP1-AP11 | 11 | — |
| SP1 | 1 | — |
| OP1-OP8 | 8 | — |
| HP1 | 1 | — |
| UP1, UP2 y UP3 | — | 3 |
| ZP1-ZP6, ZP8, ZP9, ZP11-ZP15 y ZP17-ZP19 | 16 | — |
| ZP7, ZP10, ZP16 y ZP20 | — | 4 |
| **Nuevos** | **37** | **7** |
| RP1 y RP2 (saltados sin bandera) | 2 skipped | — |

- **passed:** 311 + 37 + 7 = **355**;
- **skipped:** 12 + 2 = **14**;
- **no-integ:** 100 + 7 = **107**;
- ruff 0 y mypy 0; ningún archivo nuevo pasa de 400 líneas.
- Con `ENGRAMA_REPLICA_LOGIN_PILOTO=1`: 357 passed + 12 skipped.
- **Con BUG-16** (`ESPEC_bug16.md` §4, +11 y +2 no-integ, en cualquier orden): 355 + 11 = **366 passed + 14 skipped** y 107 + 2 = **109 no-integ**. *(`ESPEC_bug16.md` §4 todavía dice 363 y 108; su errata va aparte, porque este encargo solo toca esta espec.)*

## 6. Plan de commits (cada uno con 0 failed; después de que BUG-13 a 15 estén commiteados)
0. **P0** (§1.1): medición de ARQUITECTO, sin commit en este repo. Si falla, se aplica la alternativa preregistrada **antes** del paso 6.
1. **`test(login-piloto)`:** AP1, AP2, AP5, AP6 y SP1 en verde (el snapshot se genera aquí); AP3, AP4, AP7, AP8 y AP11 con xfail estricto.
   - **Aquí se ven por la API** el 500 del choque, el stub, el nombre y el documento sin validar.
   - Esperado: 311 + 5 = **316 passed + 5 xfailed + 12 skipped**; 100 no-integ.
   - Si AP7 no queda en xfail (el plan devolvió A por casualidad), se anota como "el desorden no se reproduce" y ZP4 queda como su tramposo.
2. **`fix(auth)`, sin respaldo:** `get_profile` y 403 sin perfil; ZP2, ZP14 y ZP15. Se quita el xfail de AP3 y AP4.
   - Esperado: 316 + 2 + 3 = **321 + 3 xfailed**.
3. **`fix(auth)`, colegio activo y nombre:** el `ORDER BY`, `active_tenant_id`, `full_name` y `memberships[].full_name`; ZP3, ZP4 y ZP5. Se quita el xfail de AP7 y AP8.
   - Esperado: 321 + 2 + 3 = **326 + 1 xfailed**.
4. **`feat(auth)`, contraseña temporal:** `must_change_password`, el bloqueo en `get_current_user`, `POST /auth/contrasena`, `src/auth/cuentas.py`, `gotrue_url` en la configuración y la entrada en `test_access.py`. Tests AP9, AP10 y UP3, y tramposos ZP6, ZP7, ZP8 y ZP20.
   - Esperado: 326 + 7 = **333 + 1 xfailed**; no-integ 100 + 3 (UP3, ZP7 y ZP20) = **103**.
5. **`fix(teachers)`, D1:** `DOC_ID_PATRON` como única fuente y el `pattern` en M3; UP1, ZP9 y ZP10. Se quita el xfail de AP11.
   - Esperado: 333 + 1 + 3 = **337**; no-integ **105**.
6. **`feat(onboarding)`:** `src/onboarding/` y `tests/cuentas_falsas.py`. Tests OP1-OP8 y UP2; tramposos ZP1, ZP11, ZP12, ZP13, ZP16, ZP17, ZP18 y ZP19.
   - Suma: 8 OP + 1 UP2 + 8 tramposos = 17.
   - Esperado: 337 + 17 = **354**; no-integ 105 + 2 (UP2 y ZP16) = **107**.
7. **`test(login-piloto)`:** HP1, RP1-RP2, `tests/manual/humo_login_piloto_gotrue.py` y el `.gitignore`.
   - Esperado: 354 + 1 = **355 passed + 14 skipped**; 107 no-integ.

La suma de los pasos es 5 + 5 + 5 + 7 + 4 + 17 + 1 = **44**, igual que en §5.
8. **`docs(login-piloto)`:**
   - la matriz medida en §3;
   - la sección "Antes del piloto con estudiantes reales" en `docs/PRODUCCION_030.md` (§7);
   - las erratas de la 008 (§9).

## 7. Riesgo para producción: **el piloto con estudiantes reales ES producción**
Nada de esto se despliega en el servidor de la UIS ni se corre con datos reales sin **el sí de Christiam en esa sesión**. Eso incluye:
- construir el backend del piloto desde esta rama;
- correr `python -m src.onboarding` con el CSV real;
- fondear las billeteras.

Checklist, que va a `PRODUCCION_030.md`:
- **Ley 1581:**
  - UIS, SENA y UNAD son responsables del dato y ENGRAMA es encargado. Hace falta un acuerdo de encargo con cada una y la autorización de los titulares;
  - el dato mínimo: nombre, correo institucional y documento. El documento no sale en el archivo de credenciales;
  - lo revisa un abogado antes del primer estudiante real (como en la 008 §7).
- **Secretos:**
  - `SUPABASE_SERVICE_ROLE_KEY` solo en el entorno del operador cuando corre la CLI. **El proceso web no la necesita** (§1.5);
  - `SUPABASE_JWT_SECRET` solo en el `.env` del servidor;
  - el archivo de credenciales se genera en el servidor fuera del repo, se entrega a mano y se borra.
- **Base limpia:** el volumen de pruebas de ARQUITECTO tiene perfiles stub (`documento_id = sub[:8]`). No se migran: el piloto real arranca con un volumen nuevo.
- **Respaldo** (`pg_dump`) antes de cada alta y de cada actualización del backend.
- **Signup cerrado** en GoTrue y `/auth/v1/admin*` cerrado en Caddy: los criterios A7 y A8 del despliegue siguen en verde.
- **Límite de login por IP** (HP2): medido antes de la primera clase.
- **Ningún estudiante real antes de que cierren BUG-13, 14 y 15** (TABLERO).

## 8. Para el pedagogo y para Christiam (ERR-16: lo que ve el estudiante o toca métricas)
- **La cifra de la billetera de cada institución** (`--monedas`, hoy 200.000 provisional) limita cuánto se puede pagar. Si se agota, el check-in da 402 y el estudiante lo ve. **Decide Christiam, y la revisa el pedagogo.**
- **Pantalla de cambio obligatorio** en el primer ingreso: es el primer contacto del estudiante. El texto y el flujo van con W22 (ARQUITECTO).
- **El nombre mostrado** es el que escribió la institución activa.
- **Perfil compartido entre instituciones** (misma cédula): la racha, el XP y la billetera siguen siendo **globales por perfil** (familia BUG-12). Un estudiante de UIS y de SENA verá una sola racha y un solo saldo. No lo cambia esta espec; con el piloto multitenant **se vuelve visible**.
- **Colegio por defecto = la membresía más antigua:** el docente de dos instituciones ve primero la más antigua hasta que elija otra.

## 9. La 008: qué queda intacto y qué cambia
**Intacto, para después** (`034_login_vendible` sigue siendo suya):
- `iss` y la llave por `iss`; JWKS y ES256;
- `tenants.kind`, `tenant_modules` y licencias;
- `POST /auth/onboarding` (tenant personal);
- `class_code`, cuentas gestionadas, PIN argon2id, `pin_attempts`, bloqueo progresivo e `ip_limits`;
- el invitado del modo en vivo;
- el CSV ENGRAMA v1 (el del alta es otro, de operador);
- enlace mágico, SMTP y Mailpit, Google y Microsoft;
- H2 y H3 de la 008.

**Erratas que la 008 debe recibir antes de implementarse** (commit de docs aparte):
1. `get_or_create_profile` ya no crea perfiles. La 008 crea el perfil explícitamente en `POST /auth/onboarding`, y su `/auth/me` "sin exigir membresía" debe aceptar también "sin perfil" como `needs_onboarding`.
   - Si genera un `documento_id`, nunca `sub[:8]`. Se sugiere el `sub` completo sin guiones: 32 caracteres, cabe en `DOC_ID_RE` y solo choca con otro `sub`.
2. `/auth/me` ya trae `active_tenant_id`, `full_name` (de la membresía) y `must_change_password`. La 008 **agrega** `active_tenant {…}`, `needs_onboarding` y `modules` sin quitar esos campos.
3. Sus rutas nuevas deciden si entran en `RUTAS_CON_CONTRASENA_TEMPORAL`. Por defecto, no.
4. §6 "Qué NO se toca": el piloto sí toca `src/teachers/schemas.py` y `roster.py` (D1).
5. Base de sus cuentas: 355 (o 366 con BUG-16).
6. El "Candidato a BUG: M3 reusa perfiles entre colegios por `documento_id`" queda resuelto por D1: la identidad es global a propósito.

## 10. Qué NO se toca, avisos y "para después"
**No se toca:**
- `src/challenge_engine/*`, `service/coins.py`, `service/attendance.py` y la 033 (BUG-13);
- las migraciones: no hay ninguna nueva;
- `ENGRAMA/despliegue/` (de ARQUITECTO);
- `.venv` (no hay dependencias nuevas: httpx ya está, lo usa `generator.py`);
- Docker (ERR-21).

**Avisos a ARQUITECTO** (los aplica él):
- El backend del piloto necesita `GOTRUE_URL=http://gotrue:9999` en su entorno, para `POST /auth/contrasena`. **No** necesita la clave de servicio.
- `crear_cuentas.py` pasa a llamar a `python -m src.onboarding alta …`.
  - El CSV gana `documento` y `tipo_documento`.
  - Ya no hace falta el stub ni acuñar tokens con el secreto JWT (`token_de_servicio_para`).
- W22:
  - mandar `X-Tenant-ID` cuando haya más de una membresía;
  - ante un 403 `must_change_password`, mostrar la pantalla y llamar a `POST /api/auth/contrasena`;
  - el mensaje para `Account has no ENGRAMA profile`;
  - el nombre sale de `full_name`.

**Para después:**
- Exigir `X-Tenant-ID` cuando hay más de una membresía.
- Que el backend imponga el prefijo del tenant a los códigos internos que llegan por M3 o M4 desde la web.
- `ce_<número>` para la CE (§1.6).
- Admitir `:` en `DOC_ID_PATRON` (§1.6).
- M2 con `pattern` (hoy da 404, no 500).
- `profiles.account_locked` (existe y no se usa) para suspender una cuenta.
- Revocar las sesiones de GoTrue al restablecer.
- El límite por IP de GoTrue, si HP2 da 429.
- Mover a un estudiante de grupo (no hay ruta).

## 11. Verificación y veredicto
```
poetry run pytest -m "not integ" -q        # 107 passed
poetry run pytest -q                       # 355 passed, 14 skipped
poetry run ruff check . && poetry run mypy src
```
- **FUNCIONA:**
  - las cuentas exactas de §5;
  - la matriz medida;
  - HP1 escrito y en verde;
  - P0 medido (o la alternativa aplicada y declarada);
  - HP2 corrido por ARQUITECTO;
  - los 311 previos idénticos, con la única edición declarada.
- **HAY ALGO MODESTO:** P0 falla y queda la alternativa "sub primero", con su límite (OP6). O HP2 muestra 429 de GoTrue en 40 logins desde una IP: es un bloqueo del despliegue, no de esta espec.
- **NO:**
  - AP3 o AP4 crean filas o dan 500;
  - AP6 deja entrar a otra institución;
  - una cuenta nace con `sub ≠ profiles.id`;
  - la bandera se salta;
  - un tramposo queda verde;
  - una clave aparece en stdout o en el repo;
  - cambia algo previo.
