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
