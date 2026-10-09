# ESPEC · Autorregistro con código de grupo, backend

F4 · Creador · 2026-10-06 · preregistro. Rama `test/fixture-integ`, HEAD `e421a16` (login del piloto, BUG-16 y consentimiento cerrados: **377 passed + 15 skipped y 109 no-integ**).

Origen: Christiam, 2026-10-06 ("la idea es ponerlos a registrarse") y la decisión 011 §3 y anexo B (BORRADOR). Es el encargo 2.1 de la 011.

**Esto es una puerta pública que crea cuentas.** No sale al túnel sin auditoría (011 §5). Nada de aquí es un concepto jurídico: el aviso, la declaración de mayoría de edad y el tratamiento los revisa un abogado.

## 0. Medido y leído (2026-10-06, `grep -n` sobre `e421a16`)
| Qué | Dónde |
|---|---|
| La pieza que crea cuentas con el id del perfil | `src/onboarding/cuentas.py:58-100` (`GoTrueAdmin.crear(id, correo, clave)` → `CREADA` o `CORREO_EN_USO`); no tiene `borrar` |
| La matrícula | `src/teachers/service/roster.py:108-170` (`enroll_student`): crea el perfil con `uuid4()` si falta y la membresía **activa**; si el perfil existe, lo **reusa** |
| El prefijo de la institución | `src/onboarding/csv_personas.py:63` (`con_prefijo(slug, codigo)`); la regex, `src/teachers/schemas.py` (`DOC_ID_PATRON`) |
| La política de contraseña del login piloto | `src/auth/schemas.py:95`: `nueva: str = Field(min_length=10, max_length=72)` |
| La barrera de grupo, en una sola fuente (ERR-26) | `src/teachers/service/access.py:66` (`authorize_group`): 404 si el grupo no es del tenant o no está asignado |
| Sin membresía activa → 403 | `src/auth/service.py:300-304` (`"User has no active tenant memberships"`); la lista de membresías sale de `get_memberships` (`:185`), solo las activas |
| La clave de servicio: declarada y sin uso en el proceso web | `src/shared/config.py:45`; la usa solo `src/onboarding/cuentas.py:112` (por `os.environ`) |
| "La clave de servicio solo la usa la CLI" | `docs/ESPEC_login_piloto.md:216` y `:537`; `src/auth/cuentas.py:10-11`; `src/onboarding/cuentas.py:11-12`; `src/shared/config.py:49-50` |
| El registro del consentimiento | `src/auth/consentimiento.py:25` (`registrar_consentimiento`); escribe auditoría con `user_id` |
| `audit_logs.user_id` referencia a `profiles` **sin** `ON DELETE` | `alembic/versions/026_*.py:25`: un perfil con auditoría a su nombre no se puede borrar |
| No hay límite de intentos en el backend | el único 429 es el de intentos de un reto |
| La IP del visitante | el backend no lee encabezados de IP en ningún sitio (`grep -rn "X-Forwarded\|request.client" src` → 0). El despliegue arranca uvicorn con `--proxy-headers --forwarded-allow-ips *` (`ENGRAMA/despliegue/backend/Dockerfile`, de ARQUITECTO) |
| El despliegue corre **2 procesos** | el mismo `CMD`: `--workers 2` |
| **`alembic_version` fijado en los tests** (ERR-25; `git grep -n alembic_version -- tests`, hoy) | `tests/integ_db.py:66`, `tests/integ/test_humo_bug11.py:35`, `tests/integ/test_humo_bug13a15.py:44` y `tests/integ/test_humo_consentimiento.py:33` |
| Otros números que una tabla nueva mueve | `tests/integ_db.py:67` (`tablas_con_rls: 27`) y `tests/seguridad/test_sin_acceso.py:85` (28 y 28) |
| Tramposos existentes que parchean el camino tocado (ERR-26; `git grep -n "monkeypatch\|setattr\|_parche" tests/tramposos`) | `enroll_student`: Y2, Y3 e Y4 de BUG-11. `_base_stmt` y `_requiere_asignacion`: X1 y X2 de grupos. `deps_mod.get_profile`, `get_memberships` y `build_auth_context`: ZP2, ZP4 y ZP5. Predicción en §3 |

## 1. Qué cambia (una cosa)
**Un estudiante que declara ser mayor de edad, con el código vigente de un grupo, crea su propia cuenta; queda pendiente hasta que el profe de ese grupo lo aprueba.**

### 1.1 Decisión: aprobación del profe (opción a)
| | (a) pendiente hasta aprobar | (b) entra de una y el profe expulsa |
|---|---|---|
| Código filtrado por WhatsApp | no entra nadie: el profe ve nombres que no conoce y los rechaza | entran hasta llenar el cupo; ven retos y ganan monedas de la bolsa de la institución antes de que el profe mire |
| Suplantar a un compañero | el profe ve el nombre y el código estudiantil antes de dejarlo entrar | ya está adentro con el código del compañero |
| Trabajo del profe | aprobar 40 nombres | ninguno, salvo que algo salga mal |
| Lo que hay que construir | una lista y dos botones | la expulsión, que hoy **no existe** (no hay ruta para desactivar una membresía) y tendría que deshacer monedas |

**Se elige (a).** El registro queda detrás de un túnel público: lo único que separa a internet de una cuenta con monedas es un código de 8 caracteres que 40 personas copian en un chat. Con (a), el código filtrado no da acceso a nada. Es la recomendación de la 011 (D1), que sigue siendo de Christiam: si decide (b), el cambio es una constante (`NACE_ACTIVA`) más la ruta de expulsión, en otra espec.

### 1.2 El código de inscripción
- **Formato:** 8 caracteres del alfabeto `ABCDEFGHJKMNPQRSTUVWXYZ23456789` (31 símbolos: sin `I`, `L`, `O`, `0` ni `1`), generados con `secrets`. Son 31⁸ ≈ 8,5 × 10¹¹ combinaciones. Se muestra como `XXXX-XXXX`.
- **Al leerlo se normaliza:** mayúsculas, sin espacios ni guiones. `abcd-efgh` y `ABCDEFGH` son el mismo código.
- **Solo se guarda su huella:** `HMAC-SHA256(llave, código normalizado)` en hexadecimal (64 caracteres).
  - La llave se deriva del secreto que el proceso web ya tiene: `HMAC-SHA256(SUPABASE_JWT_SECRET, "engrama:codigo-inscripcion:v1")`. No hay variable nueva.
  - **Por qué HMAC y no SHA-256 a secas:** 31⁸ se recorre en segundos; con un volcado de la base, un SHA-256 simple devolvería todos los códigos.
  - Si se rota el secreto JWT, los códigos vigentes dejan de servir (duran 48 horas; el profe genera otro).
  - La base rechaza cualquier valor que no sean 64 hexadecimales (CHECK): el código en claro **no cabe** en la columna.
- **El profe lo ve una sola vez,** en la respuesta de crearlo. Si lo pierde, genera otro.
- **Vence** (48 horas por defecto, de 1 a 168), **tiene cupo** (por defecto `groups.max_capacity`, o 40 si es nulo; de 1 a 200) y **se puede apagar**.
- **Uno activo por grupo** (índice único parcial). Generar otro apaga el anterior.
- **Sirve solo para pedir la inscripción en ese grupo.** El tenant y el grupo salen de la fila del código, nunca del cuerpo.
- **El cupo cuenta solicitudes creadas, no aprobadas, y no se devuelve al rechazar.** Si se devolviera, un código filtrado serviría para fabricarle trabajo al profe sin fin. El cupo sí se devuelve cuando la creación se deshace (§1.5).

### 1.3 `POST /auth/registro` (pública, sin JWT)
**Cuerpo** (estricto, `extra="forbid"`):

| Campo | Regla |
|---|---|
| `codigo` | texto de 1 a 20 caracteres. Lo que no sea un código vigente da 403, no 422 |
| `nombre` | 1 a 120 caracteres, sin espacios al borde |
| `correo` | 3 a 254 caracteres, `^[^@\s]+@[^@\s]+\.[^@\s]+$`. Se pasa a minúsculas. **No se guarda en la base**: solo viaja a GoTrue |
| `codigo_estudiantil` | `^[A-Za-z0-9-]{1,24}$`. El documento es `con_prefijo(tenant.slug, codigo_estudiantil)` y debe cumplir `DOC_ID_RE`; si no, 403 uniforme (depende del slug, que sale del código) |
| `contrasena` | 10 a 72 caracteres: **la misma constante** que `CambioDeClaveIn.nueva` (una sola fuente) |
| `mayor_de_edad` | `true` literal. `false`, ausente o cualquier otra cosa → 422 |
| `aviso_version` | la versión del aviso que aceptó, con la regla de `ConsentimientoIn.version` (1 a 32, sin espacios al borde). Ausente → 422 |

No se pide ni se guarda fecha de nacimiento, teléfono ni cédula.

**Orden y respuestas:**
1. **Cuerpo inválido → 422,** nada escrito, GoTrue no se llama. Depende solo del cuerpo: no revela nada.
2. **Sin configuración** (`GOTRUE_URL` o `SUPABASE_SERVICE_ROLE_KEY` vacías) → **503 `registro_no_configurado`**.
3. **Límite de intentos** (§1.6) → **429 `demasiados_intentos`** con `Retry-After`.
4. **Código** inexistente, vencido, apagado o sin cupo, o `codigo_estudiantil` que no cabe con el prefijo → **403 `{"detail": "codigo_no_valido"}`**, el mismo cuerpo en los cinco casos, 0 filas.
5. **Con código válido, la respuesta es siempre la misma: 201 `{"estado": "pendiente"}`.** No trae id, correo, nombre ni grupo. Se responde así cuando:
   - se creó la solicitud (el caso normal);
   - el `codigo_estudiantil` **ya tiene perfil** (ya se registró, ya está matriculado por lista, o es un doble envío): no se escribe ni se llama a GoTrue; la cuenta y la membresía que existan no cambian;
   - el **correo ya es de otra cuenta**: se deshace todo (§1.5) y no queda nada.
6. **GoTrue no responde o falla → 502 `registro_no_disponible`,** con todo deshecho.

**Por qué el 201 uniforme.** Con una respuesta distinta para "ese correo ya existe", quien tenga un código válido podría preguntar por cualquier correo. El costo es real y se declara: quien escribe un correo ya usado ve "espera a tu profe" y **no queda inscrito**; el profe no lo verá en su lista. El texto de la pantalla debe decirlo (aviso al cliente, §8). No hay correo de confirmación porque no hay SMTP (011 §3).

**Límites declarados del 201 uniforme:**
- Con GoTrue caído, un código estudiantil ya registrado da 201 y uno nuevo da 502: durante la caída se distingue. Se acepta.
- El tiempo de respuesta puede diferir entre "creada" y "correo en uso" (GoTrue calcula la huella de la contraseña solo al crear). **No medido.**

**Lo que escribe el caso normal:**
- el perfil (`documento_id = <slug>_<código estudiantil>`, `full_name=''`, `uuid4`) y la membresía `student` del grupo, con el nombre, por `enroll_student` (la matrícula de siempre), y enseguida la membresía pasa a `is_active = false`;
- la solicitud, en estado `creando` y después `pendiente`;
- el consentimiento (`aviso_version`), con la fecha del servidor;
- un uso del código;
- la cuenta de GoTrue con **`id = profiles.id`**, el correo confirmado y la contraseña elegida;
- una fila de auditoría `registro_solicitado`, con `user_id` nulo y `metadata = {solicitud_id, aviso_version, declara_mayor_de_edad: true}`. Sin IP, sin correo.

`profiles.force_password_reset` queda en `false`: la contraseña la eligió él.

### 1.4 El consentimiento y la mayoría de edad
- **El aviso se acepta antes de crear la cuenta** (011, anexo B): el formulario lo muestra y manda `aviso_version`. El backend lo guarda en `consentimientos` en la misma transacción que confirma la solicitud. Al entrar, `/auth/me` ya trae `consent_version`; si el cliente cambia `AVISO_VERSION`, vuelve a pedirlo como siempre. El servidor sigue sin conocer la versión vigente (`ESPEC_consentimiento.md` §1.1).
- **Mayoría de edad:** es una declaración. Se guarda que la hizo (`declaro_mayor_de_edad`, con un CHECK que impide una solicitud sin ella) y nada más. Los menores entran por la lista de la institución (011 D2).

### 1.5 Perfil primero, cuenta después, y la compensación
El mismo orden del login piloto (§1.1 de su espec), en dos transacciones cortas con la llamada a GoTrue en medio. **No se llama a GoTrue con una transacción abierta:** un GoTrue lento dejaría conexiones y el candado del código tomados, y la ruta es pública.

1. **T1:** candado sobre la fila del código (`FOR UPDATE`); se revisa que esté activo, vigente y con cupo; se revisa que el documento esté libre; se crean perfil, membresía inactiva y solicitud `creando`; `usos + 1`. **COMMIT.**
2. **GoTrue:** `crear(id = profiles.id, correo, contrasena)`.
3. **T2, si se creó:** solicitud a `pendiente`, consentimiento y auditoría. **COMMIT.** → 201.
4. **Compensación, si no se creó:**
   - `CORREO_EN_USO`: no existe cuenta con ese id. Se borra el perfil (la membresía, la solicitud y el consentimiento caen en cascada) y `usos − 1`. → 201 uniforme.
   - GoTrue falló o no respondió (**puede** haber creado la cuenta): primero `borrar(id)` en GoTrue (un 404 cuenta como borrada); si eso funciona, se borra el perfil y `usos − 1`. → 502.
   - Si `borrar` también falla: **las filas se quedan en `creando`** y se responde 502. No se puede afirmar que no haya cuenta, así que no se borra el perfil.

**El estado `creando` (el huérfano) falla cerrado:**
- la membresía está inactiva: con esa cuenta, si existiera, toda ruta da 403;
- el profe **no lo ve** (su lista trae solo `pendiente`) y no lo puede aprobar (404);
- ocupa un cupo y el código estudiantil hasta que se recoja.

**Quién lo recoge:** el siguiente `POST /auth/registro` con el mismo código estudiantil. Si encuentra una solicitud `creando` con más de **60 s** (reloj de la base), compensa (`borrar` en GoTrue y borrado del perfil) y sigue como un registro nuevo. Con menos de 60 s es un doble envío en vuelo: 201 uniforme, sin tocar nada. Esto cubre también el proceso que muere entre T1 y T2.

**Lo que no se recoge solo:** un `creando` cuyo dueño nunca reintenta. Ocupa un cupo hasta que el profe genere otro código. Un barrido periódico queda en "para después".

### 1.6 Límite de intentos
En memoria del proceso, ventana deslizante de **600 s**, sin dependencias. Todos los límites se revisan **antes** de consultar la base.

| Contador | Llave | Tope | Por qué ese número |
|---|---|---|---|
| Por IP | `request.client.host` | 150 | un salón de 40 sale por una IP y se equivoca; el número que la 008 fijó por la misma razón |
| Códigos malos por IP | la misma | 60 | cada 403 suma. Con 60 por ventana, recorrer 31⁸ no es viable; 40 estudiantes con un error cada uno caben |
| Por código | la huella del código | 200 | cualquier IP; frena martillar un código filtrado desde muchas direcciones. El cupo máximo es 200 |
| Global | — | 1000 | techo del proceso |

- Al pasarse: **429 `{"detail": "demasiados_intentos"}`** y `Retry-After` con los segundos que faltan.
- **La IP del visitante (H-3 de la auditoría `investigacion/seguridad/02`)** la calcula una función pura, `ip_del_visitante(client_host, x_forwarded_for, saltos)`, con la variable nueva **`PROXIES_DE_CONFIANZA`** (entero, 0 por defecto): cuántos proxies propios hay delante del backend.
  - **`0`** (desarrollo y pruebas): la IP es `request.client.host` y **no se lee ningún encabezado**.
  - **`n ≥ 1`:** cada proxy de confianza **agrega al final** de `X-Forwarded-For` la IP que vio. La IP del visitante es **el valor n-ésimo contando desde el final**. Todo lo que esté a su izquierda lo pudo escribir el visitante y **se ignora**. Con solo Caddy delante, `n = 1`: el último valor, que puso Caddy.
  - Si el encabezado trae menos de `n` valores, la petición no vino por la cadena esperada: la llave es `desconocida`, compartida por todas las que estén así (falla cerrado: comparten un solo cupo).
  - **Por qué no `request.client.host` en el piloto:** el despliegue arranca uvicorn con `--forwarded-allow-ips *`, y así uvicorn pone en `client.host` el **primer** valor del encabezado, que es justo el que escribe el visitante cuando la cadena agrega en vez de reemplazar. Con `n ≥ 1` este código no usa `client.host`.
  - `X-Real-IP`, `Forwarded` y `CF-Connecting-IP` no se leen nunca.
- **Memoria acotada:** como máximo 20.000 llaves por contador. Al llegar, se purgan las vencidas; si sigue lleno, responde 429 (falla cerrado).
- **Límites declarados:**
  - **Es por proceso.** El despliegue corre 2 (`--workers 2`): el tope efectivo es hasta el doble. Reiniciar el backend lo pone en cero.
  - **El valor de `PROXIES_DE_CONFIANZA` y que cada proxy agregue la IP correcta son del despliegue** (ARQUITECTO, encargo 1.4 de la 011): Caddy debe declarar al túnel como proxy de confianza para que lo que agregue sea la IP del visitante y no la del túnel. Si no, **todos los visitantes son una sola IP** y el tope por IP pasa a ser global (150 por ventana: un salón cabe, dos a la vez no). **No medido aquí.**
  - El puerto del backend no debe ser alcanzable sin pasar por el proxy: quien llegue directo escribe el encabezado entero.

### 1.7 El profe: código y solicitudes
Todas con `require_teacher` y `authorize_group(db, auth, gid)`, la única fuente de la barrera: el docente asignado al grupo o el admin de la institución. Rol equivocado → 403; grupo ajeno o inexistente → 404.

| Ruta | Qué hace |
|---|---|
| `POST /teachers/groups/{gid}/codigo-inscripcion` | Cuerpo `{"horas": 1..168 = 48, "cupo": 1..200 = max_capacity o 40}`, los dos opcionales. Apaga el código anterior y crea otro. **201** `{"codigo": "XXXX-XXXX", "vence": ISO, "cupo": n, "usos": 0}` |
| `GET /teachers/groups/{gid}/codigo-inscripcion` | **200** `{"activo": bool, "vence": ISO\|null, "cupo": n\|null, "usos": n\|null}`. Nunca trae el código. `activo` es falso si no hay, si se apagó o si venció |
| `DELETE /teachers/groups/{gid}/codigo-inscripcion` | Apaga el código. **204**, también si no había |
| `GET /teachers/groups/{gid}/solicitudes` | **200** `[{"id": n, "nombre": str, "codigo_estudiantil": str, "creada_en": ISO}]`: las `pendiente` de ese grupo, en orden de `id`. `codigo_estudiantil` es el `documento_id` (con el prefijo) |
| `POST /teachers/groups/{gid}/solicitudes/{sid}/aprobar` | La membresía pasa a activa y la solicitud a `aprobada`, con quién y cuándo. **200** `{"id": n, "estado": "aprobada"}`. Repetirlo da el mismo 200 sin cambiar nada |
| `POST /teachers/groups/{gid}/solicitudes/{sid}/rechazar` | Borra la cuenta de GoTrue y después el perfil con todo lo suyo. **200** `{"id": n, "estado": "rechazada"}` |

- Una solicitud de **otro grupo**, en `creando` o inexistente → **404** en las dos acciones (la misma respuesta).
- **Rechazar borra, no marca.** Si la cuenta quedara viva, quien se registró con el código estudiantil de un compañero conservaría la cuenta de ese documento: cuando el operador diera de alta al verdadero, el alta encontraría la cuenta y no la tocaría (`ESPEC_login_piloto.md` §1.7 paso 4), y el suplantador entraría con membresía activa. Por eso el orden es **la cuenta primero**: si GoTrue falla → 502 y nada cambia; si la base falla después, la solicitud sigue pendiente sin cuenta y el profe la vuelve a rechazar (un 404 de GoTrue cuenta como borrada).
- Rechazar una solicitud ya **aprobada** → 404. Sacar del grupo a alguien que ya entró es la expulsión, que no existe (para después).
- Queda auditoría de las dos acciones (`registro_aprobado` y `registro_rechazado`, con `user_id` = quien decidió y `metadata = {solicitud_id, group_id}`).
- Después de rechazar, el mismo código estudiantil puede volver a registrarse.

### 1.8 Mientras espera
Con membresía inactiva, hoy toda ruta da 403 `User has no active tenant memberships`. El cliente necesita distinguir "espera a tu profe".
- `get_current_user`, **solo cuando no hay membresías activas**, consulta si el perfil tiene una solicitud `pendiente` o `creando`; si la tiene → **403 `{"detail": "pending_approval"}`**.
- No agrega consultas al camino normal (con membresía activa no se entra ahí).
- No hay lista de rutas permitidas: quien espera no puede usar ninguna, ni `/auth/me`.
- Tras el rechazo, la cuenta ya no existe: el login falla en GoTrue, y un token viejo recibe 403 `Account has no ENGRAMA profile`.

### 1.9 ERRATA a `ESPEC_login_piloto.md` §1.7 (línea 216) y §7 (línea 537): la clave de servicio
**Decía:** "la clave de servicio solo la usa la CLI, nunca el proceso web" y "el proceso web no la necesita".

**Pasa a decir:** el proceso web la usa en **un solo módulo, `src/registro/cuentas.py`**, y solo para dos llamadas de la API admin de GoTrue: crear la cuenta de un autorregistro con el id de su perfil y borrarla (compensación o rechazo). `POST /auth/contrasena` sigue usando el Bearer del usuario.

- **Por qué se acepta (011, D7):** el proceso web ya tiene `SUPABASE_JWT_SECRET`, que es el secreto con que se firma esa clave. Dársela no le da un poder que no tuviera; sí agrega código que la usa, y por eso se cerca.
- **La cerca, con test (SR1):** en `src/`, el texto `supabase_service_role_key` aparece solo en `src/shared/config.py` y en `src/registro/cuentas.py`; `SUPABASE_SERVICE_ROLE_KEY`, solo en `src/onboarding/` y en comentarios de esos dos. Ningún otro módulo construye un `GoTrueAdmin`.
- La clave no sale en respuestas, en errores ni en logs (`ErrorCuenta` ya solo lleva el código de estado).
- **Sigue necesitando el sí de Christiam (D7).** Sin la variable en el entorno del backend, la ruta responde 503 y todo lo demás funciona igual.
- Los cuatro comentarios del código que repiten la frase vieja se corrigen en el commit del código.

### 1.10 Migración `035_autorregistro`
```sql
CREATE TABLE IF NOT EXISTS codigos_inscripcion (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  group_id    UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  codigo_hash TEXT NOT NULL,
  expires_at  TIMESTAMPTZ NOT NULL,
  cupo        INTEGER NOT NULL,
  usos        INTEGER NOT NULL DEFAULT 0,
  activo      BOOLEAN NOT NULL DEFAULT TRUE,
  created_by  UUID NOT NULL REFERENCES profiles(id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT codigos_inscripcion_hash_key UNIQUE (codigo_hash),
  CONSTRAINT codigos_inscripcion_hash_check CHECK (codigo_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT codigos_inscripcion_cupo_check CHECK (cupo BETWEEN 1 AND 200),
  CONSTRAINT codigos_inscripcion_usos_check CHECK (usos BETWEEN 0 AND cupo)
);
CREATE UNIQUE INDEX IF NOT EXISTS codigos_inscripcion_uno_activo
  ON codigos_inscripcion (group_id) WHERE activo;
ALTER TABLE codigos_inscripcion ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS solicitudes_inscripcion (
  id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id             UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  group_id              UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  codigo_id             BIGINT NOT NULL REFERENCES codigos_inscripcion(id) ON DELETE CASCADE,
  profile_id            UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  estado                TEXT NOT NULL DEFAULT 'creando',
  declaro_mayor_de_edad BOOLEAN NOT NULL,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  decidida_por          UUID REFERENCES profiles(id),
  decidida_en           TIMESTAMPTZ,
  CONSTRAINT solicitudes_inscripcion_perfil_key UNIQUE (profile_id),
  CONSTRAINT solicitudes_inscripcion_estado_check
    CHECK (estado IN ('creando','pendiente','aprobada')),
  CONSTRAINT solicitudes_inscripcion_mayor_check CHECK (declaro_mayor_de_edad),
  CONSTRAINT solicitudes_inscripcion_decision_check
    CHECK ((estado = 'aprobada') = (decidida_por IS NOT NULL AND decidida_en IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_solicitudes_inscripcion_grupo
  ON solicitudes_inscripcion (group_id, estado);
ALTER TABLE solicitudes_inscripcion ENABLE ROW LEVEL SECURITY;
```
- RLS activo y **sin políticas** en las dos, como la 034: ningún cliente lee ni escribe. Las políticas siguen en 51.
- `usos BETWEEN 0 AND cupo` es la barrera del cupo en la base: ni un código roto puede pasarse.
- No hay estado `rechazada`: rechazar borra la fila (§1.7).
- **Bajada:** `DROP TABLE` de las dos (solicitudes primero). Se pierde quién aprobó a quién; las membresías y las cuentas ya creadas **no se tocan**. En producción no se baja.
- **La 008** (`ESPEC_login_vendible.md`) toma la siguiente libre.

**Ediciones a lo existente, todas declaradas (ERR-25):**
- `tests/integ_db.py:66-67`: `alembic_version` → `035_autorregistro` y `tablas_con_rls` 27 → 29;
- `tests/integ/test_humo_bug11.py:35`, `test_humo_bug13a15.py:44` y `test_humo_consentimiento.py:33`: `alembic_version`;
- `tests/seguridad/test_sin_acceso.py:70-87`: el control de D12 pasa de 28 y 28 a 30 y 30;
- `tests/teachers/test_access.py`: 7 entradas en el mapa de guardas (`/auth/registro` POST `public`; las 6 de `/teachers`, `teacher`);
- `src/shared/models.py`: los modelos `CodigoInscripcion` y `SolicitudInscripcion`;
- `src/main.py`: monta los dos routers nuevos;
- `src/shared/deps.py`: el 403 `pending_approval` (§1.8);
- `src/shared/config.py`: `proxies_de_confianza` (`PROXIES_DE_CONFIANZA`, 0 por defecto);
- `src/onboarding/cuentas.py`: el método `GoTrueAdmin.borrar` y la corrección del comentario; `tests/cuentas_falsas.py`: `borrar`, y `fallar_borrar` y `fallar_crear` para los tests;
- `src/auth/schemas.py`: la política de contraseña pasa a dos constantes (`CLAVE_MIN`, `CLAVE_MAX`) que usa también el registro; el esquema de `CambioDeClaveIn` no cambia;
- los comentarios de `src/auth/cuentas.py` y `src/shared/config.py` (§1.9);
- `.gitignore`: el archivo del humo.
- Si la medición encuentra otra, se corrige esta lista primero (regla 8).

## 2. Criterios (medibles)
| # | Criterio | Test |
|---|---|---|
| C1 | **El código:** el profe lo crea (201, 8 símbolos del alfabeto con guion, `usos: 0`). En la base hay 1 fila con una huella de 64 hexadecimales y **ninguna columna contiene el código**. `GET` da `activo: true` sin el código. Crear otro apaga el primero: el primero ya no inscribe (403) y hay 1 solo activo. `DELETE` → 204 y `GET` da `activo: false`; otro `DELETE` → 204 | AR1 |
| C2 | **Registro normal:** 201 `{"estado": "pendiente"}` exacto. Queda 1 perfil con `documento_id = <slug>_<código>`, `force_password_reset = false`; 1 membresía `student` **inactiva** en el grupo del código, con el nombre; 1 solicitud `pendiente`; 1 consentimiento con la versión enviada; `usos = 1`; 1 auditoría `registro_solicitado` con `user_id` nulo. El doble recibió 1 `crear` con **`id == profiles.id`**, el correo en minúsculas y la contraseña. Ni la respuesta ni los logs capturados contienen la contraseña ni el correo; ninguna tabla guarda el correo | AR2 |
| C3 | **Código no válido, una sola respuesta:** inexistente, vencido, apagado, sin cupo y `codigo_estudiantil` que no cabe con el prefijo dan el **mismo** estado y el **mismo** cuerpo (403 `codigo_no_valido`). 0 perfiles, 0 solicitudes y 0 llamadas al doble. Control: el mismo cuerpo con un código vigente → 201 | AR3 |
| C4 | **Cupo:** con cupo 2, el tercero → 403 y `usos = 2`. **Dos registros a la vez por el último cupo** (dos hilos, barrera después de leer el código): entra exactamente uno, `usos = 1`, 1 cuenta | AR4 |
| C5 | **Pendiente no entra:** antes de aprobar, `/auth/me` y `GET /challenges/` → 403 `pending_approval`. Después de aprobar: `/auth/me` 200 con `must_change_password: false`, el `consent_version` enviado y el nombre; `GET /challenges/` 200; el roster del grupo (T2) lo trae | AR5 |
| C6 | **Aprobar y rechazar, las barreras:** el estudiante → 403; el docente de la institución sin ese grupo → 404; el docente de otra institución → 404; una solicitud del grupo G2 pedida por la ruta de G1 → 404 y sigue pendiente. El docente del grupo: aprobar → 200, y repetir → 200 con 1 sola auditoría. Rechazar a otro: 200; el doble recibió `borrar(id)`; 0 perfil, 0 membresía, 0 solicitud; el mismo código estudiantil se registra otra vez (201 y 1 solicitud nueva). Rechazar al ya aprobado → 404 y sigue activo. Si `borrar` falla → 502 y la solicitud sigue pendiente | AR6 |
| C7 | **No revela y no duplica:** (a) correo que ya es de otra cuenta → 201 con el mismo cuerpo que el normal; 0 filas quedan y `usos` vuelve a su valor. (b) Código estudiantil ya registrado (pendiente), con otro correo y otra contraseña → 201 igual; el doble **no** recibió otro `crear`; la cuenta conserva su correo y su contraseña. (c) Doble envío idéntico → 1 perfil, 1 cuenta y `usos = 1`. (d) Código estudiantil que ya está matriculado por lista (M3, membresía activa, sin cuenta) → 201 igual; la membresía sigue activa y en su grupo; 0 cuentas | AR7 |
| C8 | **Compensación:** (a) `crear` falla → 502 `registro_no_disponible`; 0 perfiles, 0 solicitudes, `usos = 0`; el doble recibió `borrar(id)`; el reintento → 201. (b) `crear` y `borrar` fallan → 502; queda 1 solicitud `creando`, la lista del profe está vacía y aprobarla da 404; con el token de ese perfil, `/auth/me` → 403. (c) Reintento antes de 60 s → 201 sin tocar nada; con la fila envejecida por SQL a 61 s → 201, 1 solicitud `pendiente` nueva, `usos = 1` y la cuenta con el id del perfil nuevo | AR8 |
| C9 | **Cuerpo inválido → 422, 0 filas, 0 llamadas al doble:** `mayor_de_edad` falso, ausente o `"true"`; `aviso_version` ausente o vacío; contraseña de 9 y de 73; correo sin `@`; nombre vacío o de 121; `codigo_estudiantil` con `:` o de 25; `codigo` ausente o vacío; y un campo de más (`tenant_id`, `group_id`, `role` o `fecha_nacimiento`). Control: contraseña de 10 y de 72 → 201 | AR9 |
| C10 | **Límite:** 60 códigos malos desde una IP dan 403 y el 61 → 429 con `Retry-After` > 0; el mismo intento con `X-Forwarded-For`, `X-Real-IP` y `Forwarded` falsos → 429 igual (con `PROXIES_DE_CONFIANZA = 0`); con `PROXIES_DE_CONFIANZA = 1` y `X-Forwarded-For: <falso que cambia cada vez>, 203.0.113.9`, el tope se alcanza igual (la llave es el último valor); un código **válido** desde esa IP → 429 también. Pasada la ventana (reloj inyectado) → 403 otra vez. Con el tope por código en 3 (parcheado), el cuarto intento con ese código → 429 aunque cambie `client.host` | AR10 |
| C11 | **El código de un grupo sirve solo en ese grupo:** dos instituciones A y B con un grupo y un código cada una. Registrarse con el código de A deja la membresía en A, en el grupo de A, con `documento_id = <slug de A>_…`; en B, 0 membresías y 0 solicitudes; el profe de B no la ve en su lista. El mismo código estudiantil con el código de B crea **otro** perfil (`<slug de B>_…`) | AR11 |
| C12 | **La clave de servicio, cercada (§1.9):** el escáner de `src/` encuentra `supabase_service_role_key` solo en `config.py` y `registro/cuentas.py`, y `GoTrueAdmin(` solo en `onboarding/cuentas.py` y `registro/cuentas.py` | SR1 |
| C13 | **El código, puro:** 200 códigos generados cumplen el formato y son distintos; `normalizar` iguala mayúsculas, guiones y espacios; la huella tiene 64 hexadecimales, es igual para las tres escrituras y **no** es el SHA-256 del código | UR1 |
| C14 | **Una sola política de contraseña:** los límites de `RegistroIn.contrasena` y de `CambioDeClaveIn.nueva` son `CLAVE_MIN` y `CLAVE_MAX` (10 y 72); `mayor_de_edad` solo admite `True` | UR2 |
| C15 | **El limitador, puro** (reloj inyectado): deja pasar hasta el tope y bloquea el siguiente con los segundos correctos; al pasar la ventana vuelve a dejar; las llaves vencidas se purgan; con el máximo de llaves lleno de vigentes, bloquea | UL1 |
| C15b | **La IP, pura:** con 0 saltos devuelve `client_host` aunque haya encabezado; con 1, el último valor; con 2, el penúltimo; con espacios y valores vacíos se limpia; con menos valores que saltos, `desconocida`; cambiar los valores de la izquierda no cambia el resultado | UL2 |
| C16 | **Migración up/down/up idéntica** de las dos tablas: columnas (nombre, tipo, nulabilidad, default), restricciones por `pg_get_constraintdef`, índices y RLS. Sin `ordinal_position` (ERR-24). Subir dos veces no falla | MG35 |
| C17 | Regresión: los 377 previos siguen verdes con solo las ediciones de §1.10. D12 da 0 y 0. `/auth/me` de quien ya tenía cuenta no cambia (SP1). AP5 sigue dando `User has no active tenant memberships` | la suite completa |

## 3. Tests y tramposos
**Archivos:**
- `tests/registro/_ayuda.py`: el cliente, el cuerpo de un registro, la siembra del código por la API y las lecturas.
- `tests/registro/test_codigo.py` (AR1, AR3, AR4), `test_registro.py` (AR2, AR7, AR8, AR9, AR11), `test_solicitudes.py` (AR5, AR6), `test_limite.py` (AR10; UL1 y UL2, no-integ), `test_unit.py` (SR1, UR1, UR2; no-integ).
- `tests/integ/test_migracion_035.py` (MG35) y `tests/integ/test_humo_autorregistro.py` (HA1 y RA1).
- Tramposos: `tests/tramposos/test_tramposos_autorregistro.py` (integ) y `test_tramposos_autorregistro_unit.py`.

**Reglas comunes** (las del login piloto): `TestClient(app, raise_server_exceptions=False)`; lo observado en un dict que se compara entero y va en el mensaje; el estado previo se siembra (ERR-9), salvo el código, que se crea por su ruta porque el código en claro solo existe en esa respuesta. El doble de GoTrue es `tests/cuentas_falsas.py`, inyectado con `dependency_overrides`. El limitador se reinicia antes de cada test.

**Tramposos: diagonal y cruces PREDICHOS** (ERR-15, 19 y 23: el código no existe; la matriz se mide antes de aceptar). **as** = aserción; **ex** = otra excepción.

| Id | Rompe | Rojo predicho (diagonal en negrita) | Verde predicho y por qué |
|---|---|---|---|
| ZR1 | El código vale aunque esté vencido o apagado | **AR3** (as: vencido y apagado → 201). AR1 (as: el código reemplazado sigue inscribiendo) | AR4: el cupo se sigue revisando. HA1: no usa códigos vencidos |
| ZR2 | No se revisa el cupo | **AR4** (as: el tercero no da 403; el CHECK de la base lo frena y sale 500). AR3 (as: "sin cupo" da 500) | los demás no llenan el cupo |
| ZR3 | El limitador nunca bloquea | **AR10** (as: el 61 da 403) | UL1 prueba la clase, no la instancia de la ruta |
| ZR4 | La IP es el **primer** valor de `X-Forwarded-For` (el que escribe el visitante) | **AR10** (as: con el encabezado falso, 403 en vez de 429) | los demás no mandan el encabezado. UL2 cruzaría (as); es no-integ y no se corre aquí |
| ZR5 | `crear` sin el id del perfil | **AR2** (as: `id ≠ profiles.id`). AR8 (as: la cuenta del reintento). HA1 (as: `cuenta_igual_perfil`) | AR6: `borrar` usa el id del perfil, y con el doble un id sin cuenta cuenta como borrada |
| ZR6 | Si el código estudiantil ya tiene perfil, sigue y crea otra cuenta | **AR7** (as: hay un segundo `crear`; en (d) aparece una cuenta para el matriculado por lista) | AR2 y AR11: documentos nuevos |
| ZR7 | Un mensaje distinto por causa (`codigo_vencido`, `sin_cupo`…) | **AR3** (as: los cuerpos difieren) | AR1 y AR4 solo miran el estado |
| ZR8 | La membresía nace activa | **AR5** (as: antes de aprobar, 200). AR2 (as: `is_active`). AR8 (as: en `creando`, `/auth/me` da 200). HA1 (as: `pendientes_bloqueados`) | AR6: mira lo que queda después de decidir |
| ZR9 | La ruta no exige `mayor_de_edad` ni `aviso_version` (se reemplaza la `APIRoute`) | **AR9** (as: 201 o 500 donde se espera 422). HA1 (as: `menor`) | los demás mandan los dos |
| ZR10 | `_requiere_asignacion` siempre falso (el tramposo X2 de grupos, la fuente única) | **AR6** (as: el docente sin ese grupo aprueba) | AR1 y AR5: el docente es el del grupo |
| ZR11 | La solicitud se busca sin filtrar por grupo | **AR6** (as: la de G2 se aprueba por la ruta de G1) | AR11: mira la lista, que sí filtra |
| ZR12 | La matrícula va al primer grupo de la institución, no al del código | **AR11** (as: el grupo). HA1 si su siembra tiene más de un grupo por institución (RA1 sí) | AR2: un solo grupo |
| ZR13 | La respuesta trae el correo | **AR2** (as: el cuerpo no es el exacto y contiene el correo). AR7 (as: los cuerpos se comparan con el exacto) | — |
| ZR14 | Sin compensación: si GoTrue falla, las filas se quedan | **AR8** (as: quedan perfil y solicitud, `usos = 1`). AR7 (as: (a) deja filas) | AR2: GoTrue no falla |
| ZR15 | Correo en uso → 409 `correo_en_uso` | **AR7** (as) | — |
| ZR16 | Guarda el código en claro en `codigo_hash` | **AR1** (as: el CHECK lo rechaza y crear da 500) | — |
| ZR17 | Sin el 403 `pending_approval` | **AR5** (as: el `detail` es el de sin membresía). AR8 (as: (b)) | — |
| ZR18 | Rechazar no borra la cuenta | **AR6** (as: el doble no recibió `borrar`). HA1 (as: `cuentas`) | — |
| ZR19 | El cupo se lee sin candado y se escribe `leído + 1` | **AR4** (as: en la carrera entran los dos) | la parte secuencial de AR4 sigue verde |
| ZR20 (no-integ) | Otro módulo usa la clave de servicio (un archivo sintético en el árbol escaneado) | **SR1** (as) | — |
| ZR21 (no-integ) | La huella es SHA-256 sin llave | **UR1** (as) | — |
| ZR22 (no-integ) | La ventana del limitador nunca vence | **UL1** (as) | — |
| ZR23 (no-integ) | `RegistroIn.contrasena` con mínimo 6 | **UR2** (as) | AR9 cruzaría (as: la de 9 da 201); no se mide en este tramposo |

**Tramposos existentes sobre el camino tocado (ERR-26), predicción:**
- Y2, Y3 e Y4 (BUG-11) parchean `roster_mod.enroll_student`: siguen midiendo M3, que no cambia. El registro llama a `enroll_student` por el módulo `roster`, así que **también** lo alcanzarían; no se corren contra los AR.
- X1 y X2 (grupos) parchean `access_mod`: siguen vivos; ZR10 reusa el de X2 a propósito.
- ZP2, ZP4 y ZP5 parchean `deps_mod.get_profile`, `get_memberships` y `build_auth_context`: el 403 nuevo va **antes** de `build_auth_context` y solo sin membresías, donde ninguno de sus tests pasa (todos tienen membresía activa, salvo AP5, que no tiene solicitud). Siguen en rojo por su razón.

**Inalcanzables (ERR-19):** ZR20-ZR23 × integ (solo corren su diagonal); ZR1-ZR19 × SR1, UR1, UR2, UL1 y UL2 (puros); todos × MG35 (SQL de la migración).

**Matriz a medir:** 19 tramposos integ × 13 columnas (AR1-AR11, MG35 y HA1) = **247 celdas**, más RA1 con la bandera.

### Matriz medida: 247 celdas, más RA1 (paso 3; ERR-19 y ERR-23)
**Cómo se midió** (2026-10-06, sobre `d5fabae`): una corrida de pytest por tramposo, con el tramposo aplicado a las 13 columnas por una fixture `autouse` que llama al mismo `aplicar` del registro `TRAMPOSOS`. La fila base (sin tramposo) dio 13 verdes. Se midió en dos contenedores de prueba propios (`engrama-test-pg-opus` y `-opus1`, puertos 55433 y 55434), porque el contenedor compartido `engrama-test-pg` lo estaban usando otras sesiones.

**Resultado: 50 rojas, todas por aserción; 0 por excepción; 197 verdes.**

| Id | Rojas medidas | RA1 (con la bandera) |
|---|---|---|
| ZR1 | AR1 y AR3 | roja (as) |
| ZR2 | AR3, AR4 y **HA1** | verde |
| ZR3 | AR10 | verde |
| ZR4 | AR10 | verde |
| ZR5 | AR2, AR8, HA1, **AR7** y **AR6** | roja (as) |
| ZR6 | AR7 y **AR8** | verde |
| ZR7 | AR3 | verde |
| ZR8 | AR2, AR5, AR8, HA1 y **AR11** | verde |
| ZR9 | AR9 y HA1 | verde |
| ZR10 | AR6 | verde |
| ZR11 | AR6 | verde |
| ZR12 | AR11 y **AR6** | roja (ex, `IndexError`) |
| ZR13 | AR2, AR7 y **AR8** | verde |
| ZR14 | AR7 y AR8 | verde |
| ZR15 | AR7 | verde |
| ZR16 | AR1 y **las otras 11 que usan un código** (todas menos MG35) | roja (ex, `IndexError`) |
| ZR17 | AR5, AR8 y **HA1** | verde |
| ZR18 | AR6 y HA1 | verde |
| ZR19 | AR4 | verde |

**Cruces que la predicción no tenía (en negrita; ERR-23; ningún test se tocó para que calzara):**
- **ZR16 × todo:** si la huella no se puede guardar, crear el código da 500 y todo test que necesita un código cae. El rojo sale de la **preparación** (el código queda vacío), aunque el arnés lo vea como aserción. La predicción solo miró el test que afirma sobre la huella (AR1), no los que dependen de ella (la regla de ERR-23).
- **ZR5 × AR7 y AR6:** sin el id del perfil, "la cuenta no cambió" (AR7) y "borrar deja sin cuenta" (AR6) miran un id que no tiene cuenta.
- **ZR6 × AR8:** el reintento antes de 60 s choca con la solicitud que ya existe (409).
- **ZR8 × AR11:** su aserción incluye `is_active` de la membresía.
- **ZR12 × AR6:** sus dos grupos son de la misma institución, así que el segundo código inscribe en el primero.
- **ZR13 × AR8, ZR2 × HA1 y ZR17 × HA1:** comparan el cuerpo exacto, el 403 del cupo y el 403 `pending_approval`.
- **ZR12 × HA1:** verde, como estaba condicionado (una sola institución con un grupo).

**Lo que la medición corrigió en el código antes del commit (regla 8; los criterios no se movieron):**
- **`mayor_de_edad`:** con `Literal[True]`, Pydantic acepta el número `1`. Quedó `bool` estricto más un validador. UR2 y AR9 lo afirman (`1` → 422), un caso más estricto que C9.
- **Solo un UNIQUE es "ocupado":** la primera versión atrapaba todo `IntegrityError` como "código estudiantil ocupado", y con ZR2 el CHECK del cupo salía como un 201 sin escribir. Ahora solo se atrapa el `23505`; lo demás se propaga (500). El mecanismo de ZR2 volvió a ser el predicho.
- **El huérfano recogido:** después del UPDATE que devuelve el uso, la fila del código se relee (`refresh`); sin eso, el registro siguiente daba 500 (`MissingGreenlet`). Lo encontró AR8.

**Erratas de §1.10 y §3 (ediciones que la espec no listó):**
- `tests/registro/conftest.py` y una fixture `autouse` igual en `test_humo_autorregistro.py` y en `test_tramposos_autorregistro.py`: sueltan el doble de GoTrue al terminar cada test. `app.dependency_overrides` es global, y el canario `test_h3_sin_overrides_de_dependencias_filtrados` falló en la primera corrida completa (417 + 1 failed) porque el doble quedaba puesto. Es la única vez que un test previo se puso rojo, y no se editó: se corrigió el arnés nuevo.
- `src/registro/` quedó con `schemas.py` y `decision.py` además de los módulos que la espec nombraba (una responsabilidad por archivo; ninguno pasa de 400 líneas y ninguna función de `src/` pasa de 40).
- SR1 vigila también el nombre de la variable de entorno (`SUPABASE_SERVICE_ROLE_KEY`), permitido solo en `src/onboarding/`.
- Varios tests nuevos pasan de 40 líneas (el estilo "lo observado en un dict"), como ya pasa con HP1 y OP5. No se partieron.

**Medido (2026-10-06, `d5fabae`): 418 passed + 16 skipped; 118 no-integ; `ruff check .` 0 y `mypy .` 0 (234 archivos).** Igual a §5. HA1 escribió el archivo con el contenido exacto de §4. **RA1 pasó en su primera corrida** (entradas que no se usaron al desarrollar).

**No medido:**
- **HA2** (GoTrue real): `DELETE /admin/users/{id}`, la respuesta a un correo repetido y los tiempos. El doble los imita según lo que supone esta espec.
- **Alembic real** `downgrade` y `upgrade`: MG35 corre las mismas tuplas de SQL, y `alembic upgrade head` desde cero corre en cada sesión de pruebas; el `downgrade` por la CLI de Alembic no se corrió.
- **La IP detrás del túnel** y el valor correcto de `PROXIES_DE_CONFIANZA`.
- **La suite con el contenedor compartido** `engrama-test-pg`: todas las corridas de esta tanda usaron un contenedor propio con otro nombre y otro puerto; el código y los tests son los mismos.

## 4. Humo y réplica
**HA1** escribe `tests/_salida/humo_autorregistro.json` **antes** de afirmar. Semilla `random.Random(35)`: elige los códigos estudiantiles y a quiénes rechaza el profe. Todo sintético, por la API y con el doble.
- una institución, un grupo, un código con cupo 40;
- 40 personas se registran; una 41 → 403; un menor (`mayor_de_edad: false`) → 422;
- los 40 pendientes prueban `/auth/me` → 403;
- el profe aprueba 38 y rechaza 2;
- los 38 entran; los 2 rechazados no tienen perfil.
```json
{"alembic_version":"035_autorregistro","semilla":35,"registros_201":40,"sin_cupo":403,"menor":422,
 "usos":40,"cuenta_igual_perfil":40,"pendientes_bloqueados":40,"aprobadas":38,"rechazadas":2,
 "entran_200":38,"perfiles":38,"membresias_activas":38,"cuentas":38,"consentimientos":38,
 "solicitudes":{"aprobada":38},"codigo_en_claro_en_la_base":false}
```
(`perfiles` cuenta solo estudiantes; el docente se siembra aparte.)

**Réplica** (`ENGRAMA_REPLICA_AUTORREGISTRO=1`; 1 test que se salta sin la bandera): **RA1**, con entradas nuevas: semilla 36; nombres con tildes y ñ ("Íñigo Peña Muñoz"); dos instituciones con dos grupos cada una y códigos distintos; códigos escritos en minúsculas y con guion; y **un código que vence a mitad de la corrida** (se envejece por SQL después del registro 5): del 6 en adelante → 403, y los 5 primeros siguen pendientes y se pueden aprobar.

**HA2, manual y no suma** (`tests/manual/humo_autorregistro_gotrue.py`, contra un GoTrue real; lo corre quien tenga el permiso de Docker, ERR-21): `crear` con id elegido, login con la contraseña, `borrar` → 200, `borrar` otra vez → 404, y qué responde `crear` con un correo repetido. **Esta espec supone que `DELETE /admin/users/{id}` responde 200 y, si no existe, 404; no está medido.**

## 5. Cuentas (ERR-10)
| Grupo | integ | no-integ |
|---|---|---|
| AR1-AR11 | 11 | — |
| MG35 | 1 | — |
| HA1 | 1 | — |
| SR1, UR1, UR2, UL1 y UL2 | — | 5 |
| ZR1-ZR19 | 19 | — |
| ZR20-ZR23 | — | 4 |
| **Nuevos** | **32** | **9** |
| RA1 (saltado sin bandera) | 1 skipped | — |

- **passed:** 377 + 32 + 9 = **418**; **skipped:** 15 + 1 = **16**; **no-integ:** 109 + 9 = **118**; ruff 0 y mypy 0; ningún archivo pasa de 400 líneas.
- Con `ENGRAMA_REPLICA_AUTORREGISTRO=1`: 419 passed + 15 skipped.

## 6. Plan de commits
1. `docs`: esta espec y la errata en `ESPEC_login_piloto.md` (§1.9).
2. `feat(registro)`: la 035, los modelos, `src/registro/`, las rutas, el 403 `pending_approval`, los tests, los tramposos, el humo, la réplica y las ediciones de §1.10.
3. `docs`: la matriz medida, las cuentas medidas y "Antes de aplicar la 035" en `PRODUCCION_030.md`.

## 7. Riesgo para producción
- **Aplicar la 035 y darle la clave de servicio al backend es producción:** necesita el sí de Christiam (D7 y D8 de la 011).
- **La 035 va antes o junto con el código.** Sin las tablas, quien no tenga membresía activa recibe 500 en vez de 403 (la consulta de §1.8), y las rutas nuevas dan 500. Quien ya entra no lo nota.
- **No sale al túnel sin:** la auditoría (011, 1.7); el criterio 1.4 de la 011 (la IP real del visitante); HA2 corrido; y el texto del aviso y de la declaración aprobados (ERR-16).
- Con respaldo previo. Sin downgrade en producción.

## 8. Contrato para el cliente (engrama-web)
```
POST /api/auth/registro            (sin Authorization)
{"codigo":"ABCD-EFGH","nombre":"Ana Pérez","correo":"ana@correo.edu.co",
 "codigo_estudiantil":"2201234","contrasena":"<10 a 72>","mayor_de_edad":true,
 "aviso_version":"2026-10-v1"}
201 {"estado":"pendiente"}
403 {"detail":"codigo_no_valido"}        código que no sirve (no dice por qué)
422 {"detail":[…]}                       algún campo mal; loc dice cuál
429 {"detail":"demasiados_intentos"}     + Retry-After: <segundos>
502 {"detail":"registro_no_disponible"}  reintentar más tarde
503 {"detail":"registro_no_configurado"}
```
- **El 201 no garantiza que quedó inscrito** (§1.3). Texto sugerido: "Listo. Tu profe debe aprobarte. Si ya tenías cuenta con ese correo, entra con ella o habla con tu profe."
- Después del 201, el cliente inicia sesión en GoTrue con el correo y la contraseña (la contraseña no se guarda en el dispositivo; 011, 2.2).
- `GET /api/auth/me` → **403 `pending_approval`**: pantalla "Esperando a tu profe"; se reintenta. 200: adentro, sin cambio de contraseña y con `consent_version` ya puesto. 403 `Account has no ENGRAMA profile` o un login que falla después de haber esperado: el profe lo rechazó.
- El código no va en la dirección de la página (011, 2.2).

```
POST   /api/teachers/groups/{gid}/codigo-inscripcion   {"horas":48,"cupo":40}  (los dos opcionales)
201 {"codigo":"ABCD-EFGH","vence":"2026-10-08T15:00:00Z","cupo":40,"usos":0}
GET    /api/teachers/groups/{gid}/codigo-inscripcion
200 {"activo":true,"vence":"…","cupo":40,"usos":12}     nunca trae el código
DELETE /api/teachers/groups/{gid}/codigo-inscripcion    204
GET    /api/teachers/groups/{gid}/solicitudes
200 [{"id":7,"nombre":"Ana Pérez","codigo_estudiantil":"uis_2201234","creada_en":"…"}]
POST   /api/teachers/groups/{gid}/solicitudes/7/aprobar    200 {"id":7,"estado":"aprobada"}
POST   /api/teachers/groups/{gid}/solicitudes/7/rechazar   200 {"id":7,"estado":"rechazada"}
```
403 rol equivocado; 404 grupo ajeno o solicitud que no es de ese grupo; 502 `registro_no_disponible` al rechazar si GoTrue no responde.

## 9. Qué NO se toca y "para después"
**No se toca:** `enroll_student`, M1-M4, T1-T7, el alta del operador (salvo el método `borrar` del adaptador), `RUTAS_CON_CONTRASENA_TEMPORAL`, `ProfileOut`, `ENGRAMA/despliegue/`, `engrama-web`, `.venv` ni Docker.

**Para después:**
- la expulsión de un estudiante ya aprobado (y qué pasa con sus monedas);
- un barrido periódico de solicitudes `creando` (§1.5);
- el límite compartido entre procesos (hoy es por proceso);
- que una persona con cuenta se inscriba en otra institución con el mismo correo (hoy entra por lista);
- el correo de confirmación y "olvidé mi contraseña" (sin SMTP no hay);
- el QR del código (es del cliente);
- avisar al profe cuando hay solicitudes nuevas;
- revocar las sesiones de GoTrue al rechazar (el token viejo ya recibe 403);
- el autorregistro de menores, con su acudiente (008).

**Para el pedagogo y para Christiam (ERR-16):** el texto del aviso y el de "soy mayor de edad"; el texto del 201 (que no promete lo que no pasó); y si el profe debe ver el correo para reconocer a su estudiante (hoy no lo ve: el backend no lo guarda).

## 10. Veredicto
- **FUNCIONA:** las cuentas de §5, la matriz medida, HA1 escrito, MG35 verde y los 377 previos verdes con solo las ediciones declaradas.
- **HAY ALGO MODESTO:** todo lo anterior, pero HA2 sin correr (GoTrue real) o la IP real sin medir detrás del túnel: sirve en local, no sale a internet.
- **NO:** entra alguien sin aprobación; un código vencido, apagado o lleno inscribe; el cupo se pasa; una respuesta distingue un correo existente; queda una cuenta sin perfil o un perfil activo sin cuenta; la clave de servicio aparece fuera de su módulo, en una respuesta o en un log; un tramposo queda verde.

## 11. Adenda 2026-10-08 · cierre de la auditoría de seguridad 03 (preregistro)
Implementador · sobre `2f174f5` (no-integ **143**; ruff 0). Origen: `investigacion/seguridad/03-auditoria-autorregistro-y-eventos-2026-10-07.md` (solo lectura, con consecuencias inferidas) y la decisión 011 (D7 aprobado: el registro se abre, primero en el piloto local con datos sintéticos). **Esta adenda se commitea antes del código.** Cada punto es un commit. **Sin migración** (la cabeza sigue en `041_refuerzo`).

### 11.0 Confirmado en el código (`2f174f5`), antes de tocar nada
| Hallazgo | Dónde | Qué se leyó |
|---|---|---|
| S-7 | `src/registro/service.py:300` | `await _confirmar(db, reserva, datos)` va sin `try`: si T2 falla después de que GoTrue creó la cuenta, la excepción sube (500) y quedan la cuenta y la solicitud en `creando` |
| S-3 (a) | `src/registro/limite.py:21-39` | `ip_del_visitante` devuelve la dirección completa: cada dirección de un /64 es una llave distinta |
| S-3 (b) | `src/registro/router.py:88` y `limite.py:115-119` | `limite.anotar` suma a `POR_IP`, `POR_CODIGO` y `GLOBAL` **antes** de consultar la base. 1.000 peticiones con cualquier código llenan `GLOBAL` (`limite.py:104`) |
| S-3 (b), **no estaba en la auditoría** | `limite.py:80-83` y `:118` | cada código inventado crea una llave en `POR_CODIGO`; al llegar a 20.000 llaves vigentes, toda llave **nueva** recibe 429 (falla cerrado). Es el mismo ataque por otra puerta |
| S-3 (c) | `limite.py:3-4` y §1.6 | el límite es por proceso (ya declarado) |
| Contraseña | `src/registro/schemas.py:34` y `src/onboarding/cuentas.py:102` | `max_length=72` cuenta **caracteres**; 40 `ñ` son 80 bytes y pasan. Si GoTrue los rechaza, `crear` lanza `ErrorCuenta` → 502. **Que GoTrue responda con error a más de 72 bytes es inferido (no medido).** |
| Aviso | `src/auth/consentimiento.py:34-37` y `router.py:78` | con `AVISO_VERSIONES_VALIDAS` vacía, `version_permitida` acepta cualquier texto bien formado |
| `documento_id` | `service.py:202-206` y `teachers/service/roster.py:101-105` | "ocupado" es `Profile.documento_id == documento`: texto exacto |

**Una premisa del encargo que el código refuta (se declara antes de implementar):** `documento_de(slug, "CODIGO", crudo)` (`src/onboarding/csv_personas.py:72-90`) **no normaliza** un código interno: solo le quita los espacios del borde y le pone el prefijo. Los puntos y espacios se quitan solo a `CC`, `TI` y `CE`. Usarla en el registro deja una sola fuente del documento, pero **no cierra las variantes** por sí sola. El diseño de §11.6 lo resuelve sin tocar lo guardado.

### 11.1 S-7 · la segunda transacción, protegida
- `registrar` llama a `_confirmar_o_deshacer`. Si `_confirmar` lanza **cualquier** excepción: `ROLLBACK`, se registra el fallo (solo el id de la solicitud y el tipo de la excepción), se compensa con `_deshacer(puede_haber_cuenta=True)` y se responde **502 `registro_no_disponible`**.
- Si la compensación tampoco puede escribir en la base (la cuenta ya se borró en GoTrue), el fallo se registra y la respuesta sigue siendo 502: las filas quedan en `creando` **sin cuenta**, y las recoge el reintento (§1.5).
- Si `borrar` falla en GoTrue, vale lo de §1.5: las filas se quedan en `creando`.

| # | Criterio | Test |
|---|---|---|
| C18 | T2 falla (un `_confirmar` que ejecuta SQL inválido y deja la transacción rota): **502**; el doble recibió `borrar(id del perfil)`; **0 cuentas**, 0 perfiles, 0 solicitudes y `usos = 0`; el reintento (ya sin el fallo) → 201 y 1 solicitud `pendiente`. Con `borrar` fallando además: 502, la solicitud queda en `creando` y la lista del profe está vacía | AR12 |

**Tramposo ZR24** (integ): `_confirmar_o_deshacer` es el código de hoy (llama a `_confirmar` a secas). Rojo predicho: **AR12** (as: la respuesta es 500 y la cuenta queda). Verde predicho: todos los demás (ninguno hace fallar T2).

### 11.2 S-3 (a) · IPv6 por /64
- `ip_del_visitante` pasa el valor elegido por `_agrupar`: una dirección **IPv6** se cuenta por su red **/64** (`2001:db8:1:2::/64`); una IPv6 que envuelve una IPv4 (`::ffff:203.0.113.9`) cuenta como esa IPv4; **IPv4 sigue por dirección completa**; lo que no es una dirección (el `testclient` de las pruebas, `desconocida`) queda igual.
- Por qué /64: es lo que un proveedor entrega a **una** casa o a un servidor; quien lo tiene dispone de 2^64 direcciones. Un salón detrás de una red IPv6 comparte normalmente un /64, como comparte una IPv4.
- **Límite declarado:** quien tenga un /48 dispone de 65.536 redes /64. No se agrupa por /48 (metería en una sola llave a clientes distintos de un mismo proveedor). Queda en "para después".

| # | Criterio | Test |
|---|---|---|
| C19 | Pura: dos direcciones del mismo /64 dan la misma llave, con 0 saltos y con 1; otro /64, otra llave; mayúsculas y forma larga no cambian la llave; `::ffff:203.0.113.9` → `203.0.113.9`; IPv4 intacta; `testclient` intacto | UL3 |

**Tramposo ZR28** (no-integ): `_agrupar` devuelve el valor tal cual (hoy). Rojo: **UL3**. UL2 sigue verde (solo usa IPv4).

### 11.3 S-3 (b) · el contador global y el contador por código cuentan solo lo que sirve
**Diseño elegido: contar solo los intentos cuyo código de grupo pasó la validación** (existe, está activo, vigente y con cupo).
- `POR_IP` sigue contando **todo** intento, antes de la base (150).
- `MALOS_POR_IP` sigue contando cada 403 (60).
- `POR_CODIGO` (200) y `GLOBAL` (1000) se anotan **después** de la reserva, y **solo si el código de grupo era válido**: los 201, el 502 y el 403 por `codigo_estudiantil` que no cabe con el prefijo (ahí el código de grupo sí servía; así AR10 no cambia). Un código inexistente, vencido, apagado o sin cupo **no los mueve**.
- Los cuatro se siguen **revisando** antes de la base.

**Por qué así y no "global por código":**
- Quien no tiene un código válido ya no puede llenar `GLOBAL` ni crear llaves en `POR_CODIGO`: sus intentos solo gastan los cupos **de su propia IP** (60 malos, 150 en total).
- Quien sí tiene un código válido queda frenado por `POR_CODIGO` (200 por ventana, cualquier IP): para llenar `GLOBAL` harían falta 5 códigos válidos martillados a la vez. `GLOBAL` deja de ser un interruptor y vuelve a ser lo que decía §1.6: el techo de cuentas que el proceso le pide a GoTrue.
- "Global por código" sería `POR_CODIGO` con otro nombre: no agrega nada.

**Lo que se pierde, declarado:**
- `GLOBAL` ya no protege a la base de una lluvia de códigos malos desde muchas IP: cada uno cuesta una consulta por índice único. Lo frena `MALOS_POR_IP` (60 por IP y ventana).
- Al anotar después, varias peticiones simultáneas pueden pasar la revisión antes de que la primera anote: el tope se puede pasar por las que estén en vuelo (pocas: el candado del código las pone en fila).
- **Sigue abierto:** `POR_IP` y `MALOS_POR_IP` también fallan cerrado con 20.000 llaves. Quien controle 20.000 direcciones IPv4 o redes /64 (un /48) todavía puede dejar sin registro a las IP nuevas durante la ventana. Es de otro tamaño (hacen falta 20.000 orígenes y no 1.000 peticiones) y se cierra en el despliegue (tabla compartida o límite en el proxy). **Para después.**

| # | Criterio | Test |
|---|---|---|
| C20 | Con `GLOBAL.tope = 3` y `PROXIES_DE_CONFIANZA = 1`: 5 códigos inventados desde 5 IP distintas → cinco 403, y `POR_CODIGO` tiene **0 llaves**; enseguida un registro con código válido desde otra IP → **201** (hoy: 429). Después, hasta completar 3 con código válido → 201, y el cuarto → **429** con `Retry-After` (el techo sigue vivo para lo que sí sirve). `POR_CODIGO` termina con 1 llave | AR13 |

**Tramposo ZR25** (integ): `limite.anotar_codigo` anota siempre, sin mirar si el código servía (hoy). Rojo predicho: **AR13** (as: tras la basura, 429). Verde: AR10 (sus topes se alcanzan igual: 60 malos por IP llegan antes que 1000).

### 11.4 S-3 (c) · documentado, sin cambio
El límite vive en la memoria de **cada proceso**. Con `--workers 2` (el `CMD` del despliegue) **cada tope vale hasta el doble** (300 por IP, 120 malos por IP, 400 por código, 2000 globales) y un reinicio lo pone en cero. Para que los números de §1.6 sean los reales hace falta **un solo worker** o una tabla compartida. **Lo decide el despliegue; el backend no lo cambia.**

### 11.5 Menores
**(a) La contraseña se acota en bytes.** bcrypt (el de GoTrue) solo mira los primeros 72 **bytes**. `RegistroIn.contrasena` conserva `CLAVE_MIN` y `CLAVE_MAX` (caracteres; UR2 no cambia) y gana un validador: si `len(contrasena.encode("utf-8")) > 72` → **422**, con un mensaje que lo dice ("no puede pasar de 72 bytes; las tildes, la ñ y los emojis ocupan más de uno"). `POST /auth/contrasena` **no** se toca (para después).

| # | Criterio | Test |
|---|---|---|
| C21 | Pura: 72 `x` → pasa; 36 `ñ` (72 bytes) → pasa; 37 `ñ` (74 bytes, 37 caracteres) → error que nombra los 72 bytes; 73 `x` → error (el de antes) | UR3 |
| C22 | En la ruta: 40 `ñ` → **422**, 0 perfiles, 0 solicitudes, 0 llamadas a `crear`; 36 `ñ` → 201 | AR14 |

**Tramposo ZR29** (no-integ): el tope en bytes no se aplica (`CLAVE_MAX_BYTES` enorme: se cuentan solo caracteres, hoy). Rojo: **UR3**. Cruce predicho, no medido en este tramposo: AR14.

**(b) Sin lista de versiones del aviso, el registro no abre.** Si el registro está encendido (hay URL de GoTrue y clave de servicio) y `AVISO_VERSIONES_VALIDAS` está vacía → **503 `{"detail": "registro_sin_aviso"}`**, sin escribir y sin llamar a GoTrue. Orden: cuerpo (422) → versión fuera de la lista (422, como hoy) → sin configuración (503 `registro_no_configurado`) → **sin lista (503 `registro_sin_aviso`)** → límite (429) → lo demás. `POST /auth/consent` no cambia (con la lista vacía sigue sin restricción: ahí hay un usuario con sesión).

| # | Criterio | Test |
|---|---|---|
| C23 | Con el doble puesto y la lista vacía → 503 `registro_sin_aviso`, 0 perfiles y 0 `crear`; con la lista puesta → 201; sin el doble (registro apagado) y la lista vacía → 503 `registro_no_configurado` | AR15 |

**Tramposo ZR26** (integ): la comprobación no hace nada (hoy). Rojo: **AR15** (as: 201 con la lista vacía).

**Edición a lo existente (ERR-25):** `tests/registro/_ayuda.py`: `preparar` pone `AVISO_VERSIONES_VALIDAS = AVISO` y `soltar` la devuelve a su valor. Sin eso, **todos** los tests del registro darían 503. CN6 (`tests/auth/test_aviso_versiones.py`) no cambia: pone su propia lista después de `preparar`, y su caso de lista vacía es del consentimiento.

### 11.6 `documento_id`: las variantes de un código ya ocupado
- **El documento se arma con `documento_de(slug, "CODIGO", codigo_estudiantil)`**, la función del CSV de alta (una sola fuente: prefijo y `DOC_ID_RE`). Lo que se **guarda** no cambia: `<slug>_<código tal como se escribió>`. Así el matriculado por lista y el que se registra siguen siendo el mismo perfil (AR7 (d)).
- **"Ocupado" deja de comparar el texto.** Se compara la **forma canónica del código** (lo que va después de `<slug>_`): minúsculas, sin guiones y sin ceros a la izquierda. `AB-0123`, `ab0123`, `00AB-0123` y `Ab-0123` son el mismo código. Se busca entre los perfiles cuyo `documento_id` empieza por `<slug>_` (los de esa institución), con la misma forma calculada en la base.
- Si alguna variante ya tiene perfil → "ocupado": **201 uniforme**, sin escribir y sin llamar a GoTrue. El huérfano (`creando` de más de 60 s) se recoge igual que antes, también si es una variante.
- **Los perfiles que ya existen no se tocan** (ni se renombran ni se fusionan). Sin migración.
- **Límites declarados:**
  - Dos personas reales de una misma institución con códigos que solo difieren en mayúsculas, guiones o ceros a la izquierda: la segunda recibe el 201 uniforme y **no queda inscrita**; entra por lista. Se acepta (el caso contrario es la suplantación).
  - Los puntos y los espacios no pueden llegar: el cuerpo los rechaza con 422 (`^[A-Za-z0-9-]{1,24}$`).
  - La búsqueda recorre los perfiles de la institución sin índice propio. En el piloto son cientos. Un índice por expresión es una migración: para después.
  - Dos registros **simultáneos** de dos variantes con códigos de **dos grupos distintos** pueden entrar los dos (el candado es por código de grupo). El profe ve los dos y rechaza uno.

| # | Criterio | Test |
|---|---|---|
| C24 | Se registra `AB-0123` (201, 1 `crear`). Las variantes `ab-0123`, `AB0123`, `ab0123` y `00AB-0123`, con otro correo → 201 uniforme cada una, **0 `crear` más**, 1 solo perfil y `usos = 1`. Un matriculado por lista con `<slug>_000457`: registrar `457` → 201, sin cuenta y sin solicitud. Control: `AB-0124` → 1 `crear` más; y `ab0123` con el código de **otra** institución → se crea (otro prefijo) | AR16 |

**Tramposo ZR27** (integ): "ocupado" compara el texto crudo (hoy). Rojo: **AR16** (as: las variantes crean perfiles y cuentas). Verde: AR7 (sus documentos son idénticos).

### 11.7 Tramposos existentes (ERR-26), predicción
- ZR3 parchea `limite.revisar(ip, huella)`: la firma no cambia. ZR4 parchea `limite.ip_del_visitante`: sigue rojo por su razón (AR10).
- ZR6 parchea `service._ocupado(db, cuentas, documento)`: la firma cambia a `(db, cuentas, slug, codigo)`; **se ajusta la firma del tramposo** (sigue devolviendo `False`) y debe seguir rojo por AR7.
- ZR14 parchea `service._deshacer`: sigue rojo por AR8.
- ZR9 llama a `router_mod.registrarse(payload, request, cuentas, db)`: la firma no cambia. Su modelo trae `aviso_version = "sin-aviso"` por defecto, que con la lista puesta por `preparar` daría 422 en el caso `sin_aviso`. **Predicción:** ZR9 sigue rojo con su mismo mensaje (`'menor': 201, 'sin_declarar': 201`: esos dos casos mandan el aviso bueno). Si no, se corrige el tramposo (su valor por defecto), no el test.
- ZH13 (aviso) y los de la solicitud de datos no pasan por lo tocado.

### 11.8 Cuentas (ERR-10)
| Grupo | integ | no-integ |
|---|---|---|
| AR12-AR16 | 5 | — |
| ZR24-ZR27 | 4 | — |
| UL3 y UR3 | — | 2 |
| ZR28 y ZR29 | — | 2 |
| UE3 y ZE20 (`ESPEC_eventos_anillo.md` §12) | — | 2 |
| **Nuevos** | **9** | **6** |

- **no-integ:** 143 + 6 = **149**. **Suite completa:** la de `2f174f5` + 15 passed; skipped sin cambio (23).
- No se mide la matriz completa de cruces (los tramposos nuevos contra todos los AR): solo la diagonal. Queda dicho.

### 11.9 Qué NO se toca y "para después"
**No se toca:** S-5 (el oráculo de tiempo; se mide en el despliegue), S-6 y S-1 (GoTrue y Caddy), S-9 (operativo), el barrido de solicitudes en `creando`, el pase acotado, `engrama-web`, `despliegue`, EVA ni SET. Ninguna migración.

**Para después:** el límite compartido entre procesos o en el proxy (y las 20.000 llaves por IP); agrupar por /48; los 72 bytes en `POST /auth/contrasena`; el índice por expresión del código canónico y la carrera entre dos grupos; fusionar perfiles viejos que ya sean variantes entre sí.

### 11.10 Qué cambia para el despliegue
- **`AVISO_VERSIONES_VALIDAS` pasa a ser obligatoria para registrar:** vacía y con la clave de servicio puesta → 503 `registro_sin_aviso`.
- **Respuestas nuevas de `POST /auth/registro`:** 503 `registro_sin_aviso`; 422 por contraseña de más de 72 bytes; 502 (antes 500) si la segunda transacción falla.
- **IPv6:** el límite cuenta por /64. `PROXIES_DE_CONFIANZA` no cambia de significado.
- **`--workers`:** cada tope vale por proceso (§11.4).

### 11.11 Medido (2026-10-08, sobre `f864e11`)
- **Suite completa: 625 passed + 23 skipped, 0 fallos** (826 s; una sola corrida, sin `WinError 10055`). **no-integ: 149. `ruff check .`: 0.** Igual a §11.8. `mypy` no se corrió en este encargo.
- **Los 7 tramposos nuevos, rojos por su razón en su primera corrida** (ZR24-ZR29 y ZE20), con el mensaje predicho. Los existentes siguen rojos: ZR3, ZR4, ZR6 (con la firma ajustada), ZR9 (con su mismo mensaje), ZR14 y ZH13.
- **Predicción refutada antes de implementar:** que `documento_de` normalizara un código interno (§11.0).
- **Errata de §11.7 (una edición que la adenda no listó):** el corredor de los tramposos puros de eventos (`tests/tramposos/test_tramposos_eventos.py`) llamaba al test sin argumentos; ahora le pasa `monkeypatch` si lo pide (UE3 lo pide).
- **No medido:** nada contra un GoTrue real (que rechace más de 72 bytes; `borrar` tras un fallo de T2); el límite con dos procesos ni detrás de Caddy con IPv6 real; la matriz completa de cruces de los tramposos nuevos (solo la diagonal); el piloto en marcha (`engrama-piloto`) no se tocó ni se reconstruyó con este código.

## 12. Adenda 2026-10-08 · lo que midió el autorregistro contra un GoTrue real (S-5 y S-6; preregistro)
Implementador · sobre `a25bde2` (no-integ **149**; ruff 0; suite 625 passed + 23 skipped). Origen: `ENGRAMA/despliegue/docs/ESPEC_anillo_docker.md` §15.22 (solo lectura) y los hallazgos S-5 y S-6 de `investigacion/seguridad/03-auditoria-autorregistro-y-eventos-2026-10-07.md`. **Esta adenda se commitea antes del código.** Cada punto es un commit. **Sin migración** (la cabeza sigue en `041_refuerzo`).

### 12.0 Lo medido en el despliegue (no se repite aquí) y lo leído en el código
| Hecho | Fuente |
|---|---|
| El autorregistro crea la cuenta por `POST /admin/users`, que **no** aplica la regla de clases: con solo letras, `POST /api/auth/registro` dio **201** | §15.22, fila SP2 |
| `POST /api/auth/contrasena` con solo letras → 422 `password_rejected`: ahí sí la aplica GoTrue | §15.22, fila SP2 |
| La regla del piloto: `GOTRUE_PASSWORD_REQUIRED_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ:0123456789-_.!@#$$%&*+"` (dos conjuntos: letras ASCII; dígitos y los símbolos `-_.!@#$%&*+`; el `$$` es un `$` escapado de compose) | `despliegue/docker-compose.yml:95` |
| Tiempos (30 repeticiones intercaladas): `creado` 131,2 ms de mediana (p10-p90 124,0-188,4; máx. 270,2), `correo_en_uso` 90,3 ms, `ocupado` 9,9 ms. `ocupado` se distingue 60 de 60 veces con un umbral | §15.22, S-5 |
| `CambioDeClaveIn.nueva` solo valida el **largo** (`Field(min_length=CLAVE_MIN, max_length=CLAVE_MAX)`); el router pasa la clave a GoTrue y convierte su 422 en `password_rejected`. **El backend no valida la composición en ese camino** | `src/auth/schemas.py:117`, `src/auth/router.py:126-157` |
| `RegistroIn.contrasena`: largo en caracteres + validador de 72 bytes | `src/registro/schemas.py:37,53-63` |
| `registrarse` devuelve: 201 (`creado`, `ocupado`, `correo_en_uso`), 403 uniforme, 429, 502, 503, y el 422 sale de FastAPI antes de entrar | `src/registro/router.py:96-123` |

### 12.1 S-6 · la regla de la contraseña también en el registro
**Qué cambia (una cosa):** `RegistroIn.contrasena` exige, además de lo de hoy (10 caracteres como mínimo, 72 **bytes** como máximo), **al menos una letra y al menos un dígito o símbolo**.

- **Una sola fuente:** un módulo nuevo, `src/auth/politica_clave.py`, con la función `cumple_composicion(clave) -> bool`, el conjunto `SIMBOLOS` y el texto del error. `RegistroIn` la llama desde un validador. Los límites de largo siguen en `CLAVE_MIN` y `CLAVE_MAX` (`auth/schemas.py`); no se mueven.
- **Qué es una letra:** cualquier carácter para el que `str.isalpha()` sea verdadero. Cuentan las tildes y la `ñ` (`é`, `Ñ`) y también las letras de otros alfabetos. **Qué es un dígito:** `0` a `9` (los dígitos ASCII, no `²` ni los árabes). **Qué es un símbolo:** exactamente los de GoTrue, `- _ . ! @ # $ % & * +`.
  - **Por qué los símbolos de GoTrue y no "cualquier carácter que no sea letra":** una contraseña como `mi clave secreta` (letras y espacios) o `clave?????` pasaría por el registro y GoTrue la **rechazaría el día que la persona la cambie** (su regla es una lista). Con la lista idéntica, la web puede explicar una sola regla y la persona no choca con la otra.
  - **Límite declarado (lo que NO queda igual a GoTrue):** GoTrue cuenta como letras solo las **ASCII** (`a-z`, `A-Z`). Aquí `ñ` cuenta como letra, como se pidió. Una contraseña como `ñññññññññ1` (ninguna letra ASCII) **pasa el registro** y GoTrue **la rechazaría al cambiarla**. Es raro (hacen falta diez letras sin ninguna ASCII) y falla del lado seguro (no se cuela nada: la persona no podría cambiarla a esa). Si se quiere cerrar, es una línea (`isalpha` pasa a `isascii and isalpha`) y la decide Christiam.
- **El 422** sale por el validador: `{"detail": [{"loc": ["body", "contrasena"], "msg": "Value error, la contraseña debe tener al menos una letra y al menos un número o un símbolo (- _ . ! @ # $ % & * +)", ...}]}`. El prefijo `Value error, ` lo pone Pydantic (igual que en el de los 72 bytes); la web puede quitarlo o mostrar el resto.
- **Orden de los errores de la contraseña** (el primero que falle): largo en caracteres → 72 bytes → composición. Una contraseña de solo letras y de 80 bytes da el de los bytes.
- **`POST /auth/contrasena` NO se toca.** Hoy no valida la composición en el backend (solo el largo, que ya comparte las constantes); la regla la aplica GoTrue y el backend ya la traduce a 422 `password_rejected` (medido, §15.22). Meterla ahí cambiaría la forma del error que la web ya sabe leer (de `password_rejected` a una lista) y dejaría dos reglas que pueden separarse cuando alguien cambie `GOTRUE_PASSWORD_REQUIRED_CHARACTERS` en el despliegue. **Aviso:** por la misma razón, la copia que esta adenda pone en el backend (la lista de símbolos) **debe actualizarse a mano** si el despliegue cambia la variable de GoTrue; el test UR4 fija la lista actual.

| # | Criterio | Test |
|---|---|---|
| C25 | **Pura:** `solo letras` (`abcdefghij`) → error; `solo dígitos` (`1234567890`) → error; `letra + dígito` (`abcdefghi1`) → pasa; `letra + símbolo` (`abcdefghi!`) → pasa; `letras con tilde o ñ + dígito` (`contraseña1`, `Ñandú-Ñoño1`) → pasa; `ñ` sin ninguna letra ASCII (`ñññññññññ1`) → pasa (límite declarado); `solo símbolos` (`-_.!@#$%&*+`) → error; símbolo fuera de la lista (`clave?????`) → error; espacios (`mi clave aa`) → error; `²` o un dígito árabe como único "número" → error; el error lleva el texto de arriba; las constantes de largo no cambian (`CLAVE_MIN`, `CLAVE_MAX` = 10, 72) y el de los bytes sigue ganando | UR4 |
| C26 | **En la ruta:** `solo letras` (`abcdefghij`) → **422** con el texto de la regla, 0 perfiles, 0 solicitudes, 0 llamadas a `crear`, `usos = 0`; `solo dígitos` → 422; `letra + dígito`, `letra + símbolo` y `ñ + dígito` → **201** | AR17 |

**Tramposos (el esquema de hoy: `cumple_composicion` siempre verdadera):**
- **ZR30** (no-integ). Rojo predicho: **UR4** (as: `solo letras` pasa).
- **ZR31** (integ). Rojo predicho: **AR17** (as: `solo letras` da 201). Verde predicho: el resto del autorregistro (todas sus contraseñas traen letra y símbolo o dígito **después** de editar los tests, ver abajo).

**Edición a lo existente (ERR-25), todas porque la regla nueva vuelve inválida una contraseña de prueba que era solo de letras:**
- `tests/registro/test_registro.py` (AR9): `clave_de_9` `x*9` pasa a `x*8 + "1"`, `clave_de_73` `x*73` a `x*72 + "1"`, `control_de_10` `x*10` a `x*9 + "1"`, `control_de_72` `x*72` a `x*71 + "1"`. Sin eso, los controles darían 422 por la regla nueva y los dos casos de largo darían 422 por otra razón.
- `tests/registro/test_unit.py`: `_acepta_mayor` (`x*10` pasa a `x*9 + "1"`) y UR3 (`x*72`, `ñ*36`, `ñ*37`, `x*73` y los emojis: cada uno gana un dígito o se acorta para seguir en el mismo número de bytes; los valores exactos quedan en el test).
- `tests/registro/test_auditoria03.py` (AR14): `ñ*40` pasa a `ñ*39 + "1"` (79 bytes) y `ñ*36` a `ñ*35 + "12"` (72 bytes).
- Ningún otro test del repo manda una contraseña de solo letras al registro: `ay.CLAVE` (`clave-sintetica-de-prueba`) trae guiones. Si una corrida encuentra otro, se corrige aquí primero.

### 12.2 S-5 · el 201 del registro no delata por tiempo
**Qué cambia (una cosa):** **toda** respuesta de `POST /auth/registro` tarda al menos un **piso común** más un pequeño componente aleatorio.

- **Dónde:** una clase de ruta, `RutaConPiso(APIRoute)`, en el módulo nuevo `src/registro/piso.py`. Envuelve el manejador de la ruta: mide desde que entra, deja que corra (también si lanza `HTTPException` o falla la validación del cuerpo) y, antes de devolver, **espera lo que falte**. Como envuelve la ruta entera, cubre las tres variantes del 201, el 403 uniforme, el 429, el 502, el 503 **y el 422**; ninguna se escapa por una rama. Solo `POST /auth/registro` (el router público) la usa; las rutas del profe no.
- **Sin bloquear el bucle:** la espera es `await asyncio.sleep(...)`. **Sin trabajo de mentira:** no se calcula ninguna huella; solo se espera.
- **El piso:** `settings.registro_piso_ms` (variable `REGISTRO_PISO_MS`), entero entre 0 y 5000, **por defecto 250** (PROVISIONAL: debe quedar por encima del camino más lento medido; en §15.22 `creado` fue 131 ms de mediana y 270 de máximo, así que 250 queda por encima de la mediana y del p90, **no del máximo**). En `0` no espera nada. Se lee **en cada petición**, no al importar (los tests lo cambian).
- **El componente aleatorio:** al piso se le suma `azar × 20 %` del piso (0 a 50 ms con 250), con `random.random()`. El tiempo total objetivo es `piso × (1 + 0,2·u)`, con `u` en `[0, 1)`. Es para que la respuesta no caiga siempre en el mismo milisegundo: **no es** un secreto y no protege contra quien promedie miles de repeticiones (el ruido de red ya es mayor).
- **Si un camino tarda más que el piso, no se acorta ni se alarga:** responde cuando termina. Ahí el piso ya no esconde nada: por eso el valor debe quedar por encima del camino más lento **real**.
- **Límites declarados:**
  - **NO se ha medido contra un GoTrue real.** Los tiempos del `creado` con el GoTrue de mentira de los tests no dicen nada del GoTrue del piloto. **Lo mide el despliegue** (§15.21/§15.22 repetido con el piso puesto): hay que correr `medir_autorregistro.mjs` otra vez, mirar que los tres caminos y el 403 queden pegados y que el máximo de `creado` quede por debajo del piso (si no, subir `REGISTRO_PISO_MS`).
  - Con una red o un GoTrue lentos, `creado` quedará por encima del piso en algunas respuestas y `ocupado` siempre en el piso: se distinguirían solo en esas colas. Subir el piso lo cierra, a costa de latencia para todos.
  - Una espera asíncrona retiene la conexión, no un hilo: 250 ms por petición. Con el límite por IP (150 por ventana) el costo está acotado.
  - **El 502 sigue distinguiéndose** (GoTrue caído: §1.3 ya lo declara). El 429 y el 503 no dependen de nada secreto; llevan el piso por uniformidad, no porque filtren.

**Cómo se mide (los números se fijan AQUÍ, antes de correr nada):**
- **Qué se compara:** cuatro caminos, **intercalados** (uno de cada, en orden, repetido): `creado` (código estudiantil nuevo, correo nuevo), `correo_en_uso` (código estudiantil nuevo, correo de una cuenta existente), `ocupado` (código estudiantil ya registrado) y `403` (código de grupo inventado). **10 repeticiones de cada uno**, con `TestClient` y el GoTrue de mentira.
- **El GoTrue de mentira tiene latencia:** `CuentasFalsas(espera_crear=0.06)` hace esperar 60 ms a `crear` (por defecto 0: nadie más lo nota). Sin eso, `creado` y `ocupado` solo difieren en las transacciones de la base y la diferencia puede quedar dentro del ruido; con 60 ms, **sin piso** `creado` debe quedar claramente por encima de `ocupado`.
- **Tiempos:** `time.perf_counter()` alrededor de `client.post`. Se compara la **mediana** de cada camino.
- **Dos bloques:** (1) **sin piso** (`registro_piso_ms = 0`): la diferencia entre la mediana mayor y la menor debe ser **mayor o igual que 25 ms** (si no, el test no puede ver la fuga y no vale como prueba); (2) **con piso** de **150 ms** (más pequeño que el de producción para no alargar la suite; el aleatorio llega a 30 ms): la diferencia entre la mediana mayor y la menor de los cuatro caminos debe ser **menor que 25 ms**, y la mediana de `creado` sin piso debe ser menor que 150 ms (el piso está por encima del camino más lento del test).
- **El umbral, 25 ms, se fijó antes de medir.** Con 10 repeticiones, la mediana de un camino al piso varía unos 3 ms (desviación) por el aleatorio; la diferencia entre dos, unos 5 ms: 25 ms son cinco desviaciones. Si la máquina está cargada y el test sale rojo por ruido, **se repite una vez y se dice**; el umbral **no se mueve** para que calce.
- **Predicción de lo que dirá la corrida sin piso** (para refutarla): `creado` ≈ 60 ms (la espera) + 20-50 ms (dos transacciones) ≈ 80-110 ms; `ocupado` ≈ 8-20 ms; `correo_en_uso` ≈ 70-100 ms; `403` ≈ 5-15 ms. Es decir, **el 403 también difiere** del `creado` (como `ocupado`), y los cuatro quedan pegados con el piso.

| # | Criterio | Test |
|---|---|---|
| C27 | **Puro** (reloj, azar y sueño inyectados): con piso 250, `azar = 0` y 0 ms gastados espera 250 ms; con `azar` casi 1 espera casi 300 (nunca más del 20 %); con 100 ms gastados espera lo que falta y nunca menos; con más gastado que el piso espera **0**; con piso 0 no espera aunque haya azar; con 50 llamadas y el azar real, las esperas **no son todas iguales** y todas caen en `[250, 300)`. El valor por defecto de `registro_piso_ms` es 250 y el máximo, 5000 | UP1 |
| C28 | **No bloquea el bucle:** mientras `esperar` espera 200 ms, otra corrutina que se despierta cada 10 ms alcanza **al menos 10 despertares** (con una espera que bloquea, 0 o 1) | UP2 |
| C29 | **En la ruta, los cuatro caminos pegados:** el bloque sin piso y el bloque con piso de arriba. Además, con piso, cada camino responde lo mismo que sin piso (201 `{"estado": "pendiente"}` los tres; 403 `codigo_no_valido`) y ninguno tarda menos que el piso | AR18 |

**Tramposos:**
- **ZR32** (integ): el piso se aplica **solo al camino `ocupado`** (la ruta general no espera; una espera suelta dentro de `service.registrar` cuando el resultado es `ocupado`). Rojo predicho: **AR18** (as: las medianas se separan más de 25 ms). Verde predicho: AR17 y el resto del autorregistro (no miden tiempo).
- **ZR33** (integ): el piso no existe (`esperar` no hace nada: el código de hoy). Rojo predicho: **AR18** (as: el bloque con piso no cierra la diferencia).
- **ZR34** (no-integ): la espera **bloquea** el bucle (`time.sleep` en vez de `asyncio.sleep`). Rojo predicho: **UP2** (as: menos de 10 despertares). Cruce: UP1 sigue verde (no mide el bucle).
- **ZR35** (no-integ): sin componente aleatorio (`azar` siempre 0). Rojo predicho: **UP1** (as: todas las esperas iguales).

**Edición a lo existente (ERR-25):**
- `src/shared/config.py`: `registro_piso_ms` (por defecto 250).
- `src/registro/router.py`: `publico = APIRouter(route_class=piso.RutaConPiso)`.
- `tests/conftest.py`: una fixture `autouse` que pone `registro_piso_ms = 0` en **todos** los tests (los que miden el tiempo lo vuelven a poner). Sin ella, cada registro de la suite (los 40 de HA1, los de AR10...) esperaría 250 ms.
- `tests/cuentas_falsas.py`: el parámetro `espera_crear` (0 por defecto).

### 12.3 Qué NO se toca y "para después"
**No se toca:** `POST /auth/contrasena` (ver 12.1), la API de administración de GoTrue ni su configuración (`despliegue`), `engrama-web`, EVA, SET, el piloto ni los stacks Docker. Ninguna migración.

**Para después:**
- Medir los tiempos contra el GoTrue real del piloto, con el piso puesto (lo hace el despliegue).
- Decidir si `ñ` y las tildes deben contar como letra también en GoTrue (hoy no: su lista es ASCII) o si el backend debe excluirlas de la regla.
- La lista de contraseñas filtradas (HIBP) y el bloqueo por cuenta (S-6, segunda mitad: del despliegue y de otra pieza).
- Un piso adaptativo (medido en vivo) en lugar de una constante.

### 12.4 Cuentas predichas (ERR-10)
| Grupo | integ | no-integ |
|---|---|---|
| UR4, ZR30 | — | 2 |
| AR17, ZR31 | 2 | — |
| UP1, UP2, ZR34, ZR35 | — | 4 |
| AR18, ZR32, ZR33 | 3 | — |
| **Nuevos** | **5** | **6** |

- **no-integ:** 149 + 2 = **151** tras S-6 y 151 + 4 = **155** tras S-5. **Suite completa:** 625 + 11 = **636 passed**; skipped sin cambio (**23**). `ruff check .` en 0.
- Solo se mide la diagonal de los tramposos nuevos (cada uno contra su test); los cruces no se miden. Queda dicho.

### 12.5 Qué cambia para el despliegue y para la web
- **Despliegue:** variable nueva `REGISTRO_PISO_MS` (opcional; 250 por defecto). Volver a medir los tiempos del registro con ella puesta (§12.2). Si el despliegue cambia `GOTRUE_PASSWORD_REQUIRED_CHARACTERS`, hay que actualizar a mano la lista de símbolos de `src/auth/politica_clave.py` (el test UR4 la fija).
- **Web:** `POST /auth/registro` responde ahora **422 por la contraseña** si no trae una letra y un número o símbolo (el texto exacto va en 12.1); y **toda respuesta del registro tarda al menos ~250 ms** (hasta ~300): la pantalla no debe tratar eso como lentitud ni reintentar sola. La regla debe mostrarse **antes** de enviar (junto al campo), no solo como error.

### 12.6 Medido (2026-10-08, sobre `7a997fc`)
- **Suite completa: 636 passed + 23 skipped, 0 fallos** (962 s; una sola corrida, sin `WinError 10055`). **no-integ: 155** (149 → 151 tras S-6 → 155 tras S-5). `ruff check .` 0; `mypy` limpio solo en los archivos nuevos (`src/registro`, `politica_clave.py`, `test_piso.py`); no se corrió sobre todo el repo. Igual a §12.4.
- **Los 6 tramposos nuevos, rojos por su razón en su primera corrida** (ZR30 a ZR35). ZR32 (piso solo en `ocupado`): con piso, `ocupado` 415 ms contra `creado` 194, `correo_en_uso` 203 y 403 47 (dispersión 369 ms). ZR33 (sin piso): dispersión 168 ms. Los tramposos existentes del autorregistro siguen rojos por su razón.
- **Predicciones refutadas (sin piso, en esta máquina, GoTrue de mentira con 60 ms de espera):** `creado` ≈ 195-218 ms (se predijo 80-110), `correo_en_uso` ≈ 193-239, `ocupado` ≈ 55-67 (se predijo 8-20) y `403` ≈ 45-52 (se predijo 5-15). Las transacciones contra el Postgres de Docker en Windows cuestan mucho más de lo supuesto. Sí se cumplió que el 403 también difiere del `creado` y que sin piso la diferencia es enorme (150-190 ms).
- **Errata del montaje de AR18 (el umbral de 25 ms NO se movió):** (1) con el piso de 150 ms que fijó §12.2, `creado` quedó por encima del piso y el test salió rojo en `creado_sin_piso_bajo_el_piso`, que es justo lo que ese criterio debía detectar; el piso del test se subió a **400 ms**. (2) Con 250 ms, una de tres corridas fue roja por carga de la máquina (medianas de `creado` de 391 ms; había otras sesiones corriendo); con 400 ms pasaron 3 de 3. (3) El componente aleatorio se **fija en 0** dentro de AR18 (se prueba en UP1): con 400 ms llegaría a 80 ms y sería más ruidoso que el umbral. (4) AR18 comprueba además que el 422 y el 503 también esperan el piso.
- **Errata de UP2 (C28):** la espec pedía "al menos 10 despertares de una corrutina que duerme 10 ms"; en Windows `sleep(0.01)` despierta cada ~15 ms y depende de la carga. UP2 cuenta los turnos que cede una corrutina con `sleep(0)` (al menos 50 en 200 ms; una espera que bloquea da 0 o 1).
- **Cambio de implementación no previsto:** `esperar` usa `time.perf_counter` (en Windows `time.monotonic` avanza a saltos de ~15 ms) y vuelve a mirar el reloj tras dormir, hasta 4 veces, porque un `sleep` puede despertar antes; así el piso es de verdad un "al menos".
- **No medido:** nada contra un GoTrue real (ni los tiempos con el piso, ni que GoTrue rechace más de 72 bytes); la matriz de cruces de los tramposos nuevos (solo la diagonal); AR18 depende de la carga de la máquina (se repite una vez y se dice); el piloto (`engrama-piloto`) no se tocó ni se reconstruyó con este código.

## 13. Adenda 2026-10-08 · el 422 no devuelve lo que se envió, y el piso del registro sube a 400 (preregistro)
Implementador · sobre `539a06a` (no-integ **155**; ruff 0; suite 636 passed + 23 skipped). Origen: lo medido contra el backend real por la web y el despliegue. **Esta adenda se commitea antes del código.** Cada punto es un commit. **Sin migración** (la cabeza sigue en `041_refuerzo`).

### 13.1 El 422 de `POST /auth/registro` (y de `POST /auth/contrasena`) no trae de vuelta valores
> **Reemplazado en el cómo (2026-10-09):** la clase `RutaSinEco` se retiró; la limpieza la hace un manejador global para toda la API (`docs/ESPEC_422_sin_eco.md`). Los criterios C36 a C38 y sus tests siguen vigentes y verdes.

**Lo medido (por quien probó contra el backend real):** el 422 del registro incluye el valor rechazado en `input`; por ejemplo `"input": "abcdefghijkl"` para la contraseña.

**Lo leído en el código (antes de tocar nada):**
- Es el formato de Pydantic v2: cada error de `RequestValidationError.errors()` trae `type`, `loc`, `msg`, `input` y, a veces, `ctx` y `url`. El manejador por defecto de FastAPI los devuelve tal cual (`{"detail": [...]}`).
- **Es peor que un campo suelto:** cuando falta un campo, el `input` de ese error es **el cuerpo entero** (con la contraseña, el código de grupo y el correo de los otros campos). Cuando sobra un campo, el `input` es su valor. Cuando el cuerpo no es un objeto, es el cuerpo crudo. Un arreglo que mirara solo el campo `contrasena` los dejaría pasar.
- `POST /auth/contrasena` tiene el mismo defecto: `CambioDeClaveIn.nueva` rechazada (menos de 10 o más de 72 caracteres) devuelve la contraseña nueva en `input`. Se cierra igual (el encargo lo pide).
- `ctx` y `url` no llevan valores enviados: `ctx` trae el límite o el patrón (`min_length`, `pattern`) o, en un `ValueError` propio, el mensaje fijo de nuestro validador; `url` es un enlace a la documentación de Pydantic. Se conservan.

**Qué cambia (una cosa):** el `input` desaparece de **todos** los errores de validación de esas dos rutas. `loc`, `msg`, `type` (y `ctx`, `url`) no cambian: la web ya lee `msg`.

**Dónde (un solo sitio que cubra todos los 422 de la ruta):** una clase de ruta, `RutaSinEco(APIRoute)`, en el módulo nuevo `src/shared/validacion.py`. Envuelve el manejador de la ruta y, si lanza `RequestValidationError` (cuerpo, parámetros o cabeceras: todo lo que valida FastAPI antes del manejador), lo vuelve a lanzar **sin el campo `input`**. Como envuelve la ruta entera, no importa cuál campo o cuál validador falló. Una función pura, `sin_valores_enviados(errores)`, hace la limpieza y es lo que se prueba sola.
- `RutaConPiso` (el piso de tiempo de §12.2) pasa a **heredar** de `RutaSinEco`: el registro lleva las dos cosas, y el 422 sigue esperando el piso (el piso envuelve por fuera).
- `POST /auth/contrasena` usa `route_class_override=RutaSinEco` (solo esa ruta; el resto de `/auth` no cambia).
- **Por qué no un manejador global de la aplicación:** quitaría `input` de todas las rutas (retos, grupos, EVA...), que son del alcance de otros y que la web puede estar leyendo; el encargo es el registro y la contraseña. Un manejador global queda en "para después" como decisión de Christiam.
- **Lo que NO cubre, declarado:** las otras rutas que reciben secretos en el cuerpo (login del piloto, PIN) y los 422 que no pasan por FastAPI. Se reportan en "para después", no se tocan.

| # | Criterio | Test |
|---|---|---|
| C36 | **Pura:** `sin_valores_enviados` quita `input` de cada error, sea texto, número, diccionario (el cuerpo entero) o lista; no toca `loc`, `msg`, `type`, `ctx` ni `url`; no modifica la lista que recibe; una lista vacía da una lista vacía | VE1 |
| C37 | **En la ruta del registro:** para **cada campo** de `RegistroIn` con un valor inválido que lleva una marca reconocible, para **cada campo** omitido (con los demás válidos y con marcas), con un campo de más, con tipos equivocados, con un cuerpo que no es un objeto y con un JSON roto: 422; ni la respuesta en texto ni ningún `input` contienen **ninguna** de las marcas enviadas (contraseña, código de grupo, correo, código estudiantil, nombre); cada error conserva `loc`, `msg` y `type`; los mensajes de la contraseña (72 bytes, composición) siguen siendo los de §11.5 y §12.1; 0 llamadas a `crear` | VE2 |
| C38 | **En `POST /auth/contrasena`:** una `nueva` demasiado corta o larga con marca, un cuerpo sin `nueva` y con un campo de más con marca, un cuerpo que no es objeto: 422 sin ninguna marca y con `loc`, `msg` y `type` | VE3 |

**Tramposos (no-integ):**
- **ZV1:** `sin_valores_enviados` devuelve la lista tal cual (el comportamiento de hoy). Rojo predicho: **VE1**, **VE2** y **VE3** (as: aparece la marca en la respuesta).
- **ZV2:** `sin_valores_enviados` quita `input` solo cuando es texto (los errores de campo) y deja pasar el diccionario del cuerpo entero (lo del campo faltante). Rojo predicho: **VE1**, **VE2** y **VE3** (as: la marca de la contraseña vuelve en el error del campo omitido).
- **ZV3:** `sin_valores_enviados` deja solo `msg` (cambia la forma del error). Rojo predicho: **VE1** (as: faltan `loc` y `type`), **VE2** y **VE3** (la forma).

**Edición a lo existente (ERR-25):** ninguna. `piso.RutaConPiso` cambia de base (hereda de `RutaSinEco`); `test_piso.py` no la nombra.

### 13.2 `REGISTRO_PISO_MS` por defecto: 250 a 400 (PROVISIONAL)
**Qué cambia (una cosa):** el valor por defecto de `registro_piso_ms` (`src/shared/config.py`) pasa de **250** a **400**. El resto de §12.2 (cómo se espera, el 20 % aleatorio, el máximo de 5000) no cambia. **Y no se toca el umbral de AR18** (25 ms): AR18 usa su propio piso de 400 ms (§12.6), no el valor por defecto.

**Por qué (medido en el piloto, no en estos tests):** con el piso en 250 ms, el tiempo de una respuesta va de 250 a 300 ms. De 60 respuestas `creado`, **1 tardó 376 ms**: se salió del techo (300) y esa sola respuesta sí delata que la cuenta se creó, porque ninguna de las otras rutas llega a 376. §12.2 lo había dicho al fijar 250: "queda por encima de la mediana y del p90, **no del máximo**". Con 400 el rango pasa a 400-480 ms: el 376 medido queda por debajo del piso, con 24 ms de margen. Es un parche a una cola larga que se vio una vez en 60.

**Lo que cuesta:** toda respuesta del registro (también el 403 y el 422) tarda 400-480 ms en vez de 250-300. El registro ocurre una vez por persona; el límite por IP (150 por ventana) acota la retención de conexiones.

**PROVISIONAL, y el despliegue lo vuelve a medir:** 400 sale de un único máximo observado (376 de 60), no de una distribución. El despliegue debe repetir la medición de §15.21/§15.22 con 400 (la escalera ya prevista en `ESPEC_anillo_docker.md`: 250, 350, 500, 750, 1000) y mirar que el máximo de `creado` quede por debajo del piso; si no, subir `REGISTRO_PISO_MS` por variable de entorno, sin tocar el código.

| # | Criterio | Test |
|---|---|---|
| C39 | El valor por defecto de `registro_piso_ms` es **400** y el máximo sigue en 5000 (5001 se rechaza) | UP1 (se edita su fila `por_defecto_y_maximo`, de `(250, ...)` a `(400, ...)`) |

**Edición a lo existente (ERR-25):** `tests/registro/test_piso.py`, UP1: la fila `por_defecto_y_maximo` pasa de `250` a `400`. Las demás filas de UP1 usan `piso_ms=250` **explícito** (pruebas de la función `esperar` con un piso cualquiera) y no dependen del valor por defecto: no cambian. Los comentarios que nombran 250 como el valor de producción (`tests/conftest.py`, `piso.py`, `config.py`) se actualizan; §12.2 y §12.5 no se reescriben: esta adenda las corrige.

**Tramposo ZR36 (no-integ):** el valor por defecto sigue en 250 (el de hoy). Rojo predicho: **UP1** (as: `por_defecto_y_maximo` dice 250, no 400). Existentes: ZR32, ZR33, ZR34 y ZR35 no dependen del valor por defecto; siguen rojos por su razón.

### 13.3 Cuentas predichas (ERR-10)
| Grupo | integ | no-integ |
|---|---|---|
| VE1, VE2, VE3 | — | 3 |
| ZV1, ZV2, ZV3 | — | 3 |
| ZR36 | — | 1 |
| **Nuevos** | **0** | **7** |

Y de `ESPEC_economia_oleada0.md` §13: 5 no-integ y 7 integ. **Total del encargo:** no-integ 155 + 5 + 7 = **167**; integ + 7; suite completa 636 + 19 = **655 passed**, skipped sin cambio (**23**). UP1 y las demás ya existentes cambian de valor, no de cuenta. `ruff check .` en 0. Solo se mide la diagonal de los tramposos.

### 13.4 Qué NO se toca y "para después"
**No se toca:** el resto de §12 y de §11, `RutaConPiso` salvo su clase base, el umbral de AR18, `engrama-web`, `despliegue`, EVA, SET, el piloto ni los stacks Docker. Ninguna migración.

**Para después:**
- Decidir si el `input` se quita en **toda** la API con un manejador global (hoy se quita solo en el registro y en el cambio de contraseña).
- Revisar las demás rutas que reciben un secreto en el cuerpo (login del piloto, PIN) con el mismo método de VE2.
- Volver a medir el piso en el despliegue con 400 (arriba) y, si la cola larga persiste, un piso adaptativo (ya anotado en §12.3).

### 13.5 Qué cambia para el despliegue y para la web
- **Despliegue:** el valor por defecto de `REGISTRO_PISO_MS` pasa a 400; si el compose no la fija, la respuesta del registro tarda 400-480 ms. Volver a medir (§13.2).
- **Web:** los 422 de `POST /auth/registro` y `POST /auth/contrasena` ya **no traen `input`**; si alguna pantalla lo leía, deja de verlo (la web real lee `msg`, según quien pidió el cambio).

### 13.6 Medido (2026-10-08, sobre `631c19d`)
- **Suite completa: 655 passed + 23 skipped, 0 fallos** (1.211 s; una sola corrida, sin `WinError 10055`). **no-integ: 167** (155 → 160 por el check-in → 166 por el 422 → 167 por el piso). `ruff check .`: 0; `mypy` limpio en los archivos nuevos y tocados de `src/shared`, `src/registro`, `src/auth/router.py` y `src/engrama_core`, no sobre todo el repo. Igual a §13.3.
- **El defecto, reproducido con el tramposo ZV1 (la función de hoy, que no quita nada):** `contrasena` de solo letras → 422 con `"input": "abcdefghijkl"`; con el campo `nombre` omitido → `input` = el cuerpo entero (código de grupo, correo, código estudiantil y contraseña). 27 casos del registro y 8 de `POST /auth/contrasena`, con marcas en cada valor: sin el arreglo ZV1 da 128 problemas en los 27 casos del registro; con él, 0. `POST /auth/contrasena` **tenía el mismo defecto** y quedó cerrado.
- **Los 4 tramposos nuevos, rojos por su razón en su primera corrida** (ZV1 a ZV3 con `loc`/`msg`/`type` y las marcas; ZR36 con `'por_defecto_y_maximo': (250, 'rechazado')`). UP1 con su fila en 400 se probó **roja contra el 250 de antes** (antes de tocar `config.py`) y verde después. Los tramposos del autorregistro (ZR1 a ZR35) siguen rojos por su razón; AR18 y UP1 a UP2 pasaron con el valor por defecto nuevo.
- **Predicciones refutadas:** (1) esta adenda dijo que `POST /auth/contrasena` se cerraba con `route_class_override=RutaSinEco` en el decorador; **el decorador `@router.post` no admite ese argumento** (solo `add_api_route`): la ruta se registra ahora con `router.add_api_route(...)`. (2) Se anticipó que ZV2 dejaría VE3 verde en un caso; se simplificó antes de implementar (rojo en los tres). (3) `RutaConPiso` no aparece en `test_piso.py`, como se predijo: la herencia no tocó ningún test existente.
- **No medido:** el valor 400 contra un GoTrue real ni su efecto sobre `creado` (es PROVISIONAL, lo mide el despliegue); que `engrama-web` ya no lea `input` en ninguna pantalla; las demás rutas con secretos en el cuerpo (login del piloto, PIN) tienen el mismo formato de 422 y **no se revisaron** (§13.4).
