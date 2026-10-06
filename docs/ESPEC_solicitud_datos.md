# ESPEC · Solicitudes sobre datos personales dentro de la app (Ley 1581), backend

F4 · Creador · 2026-10-06 · preregistro. Rama `test/fixture-integ`, sobre el autorregistro (`ESPEC_autorregistro.md`; meta **418 passed + 16 skipped y 118 no-integ**).

Origen: encargo de Christiam por el coordinador (2026-10-06). No hay un correo de contacto para el aviso de datos: el canal para ejercer los derechos (conocer, actualizar, rectificar, suprimir) es una solicitud dentro de la app.

**Esto NO es un concepto jurídico.** El backend solo registra la solicitud y deja traza de quién la respondió y cuándo. Los plazos, quién es el responsable y si una solicitud procede los revisa un abogado.

## 0. Medido y leído (2026-10-06)
| Qué | Dónde |
|---|---|
| El servidor no bloquea por consentimiento | `ESPEC_consentimiento.md` §1.4; lo fija CN5 |
| Rutas permitidas con contraseña temporal: 4 pares, fijados por UP3 | `src/auth/service.py` (`RUTAS_CON_CONTRASENA_TEMPORAL`) |
| `require_admin`: solo admin de la institución activa | `src/shared/deps.py` |
| El nombre que ve una institución es el de **su** membresía (BUG-11) | `Membership.full_name` |
| **`alembic_version` fijado en los tests** (ERR-25; `git grep -n alembic_version -- tests`, después del autorregistro) | `tests/integ_db.py:66`; `tests/integ/test_humo_bug11.py:35`, `test_humo_bug13a15.py:44`, `test_humo_consentimiento.py:33` y `test_humo_autorregistro.py` (`HUMO_ESPERADO`) |
| Otros números que una tabla nueva mueve | `tests/integ_db.py:67` (`tablas_con_rls: 29`) y `tests/seguridad/test_sin_acceso.py` (30 y 30) |

## 1. Qué cambia (una cosa)
**Una persona autenticada registra una solicitud sobre sus datos personales y ve su estado; el admin de la institución la responde. Nada se ejecuta solo.**

### 1.1 `POST /auth/solicitudes-datos` (guarda `user`)
- **Cuerpo** (estricto, `extra="forbid"`): `{"tipo": "conocer"|"actualizar"|"rectificar"|"suprimir", "mensaje": str}`.
  - `mensaje`: de 1 a 1000 caracteres, con algo que no sea espacio. 1001 → 422.
  - Ningún otro campo: ni `profile_id`, ni `tenant_id`, ni `estado`, ni fecha. **La persona es la del token, la institución es la activa y la fecha es la del servidor.**
- **201** con la solicitud (§1.5), en estado `abierta`.
- **Tope: 5 solicitudes sin cerrar por persona** (`abierta` o `en_tramite`, en todas sus instituciones). La sexta → **409 `{"detail": "demasiadas_solicitudes_abiertas"}`** y nada escrito. Cuando el admin cierra una, cabe otra. El conteo se hace con el perfil bloqueado (`FOR UPDATE`): dos envíos a la vez no lo pasan.
- Auditoría: `datos_solicitud_creada`, con `metadata = {solicitud_id, tipo}`. El mensaje no va a la auditoría ni a los logs.

### 1.2 `GET /auth/solicitudes-datos` (guarda `user`)
**200** con la lista de **sus** solicitudes, de la más nueva a la más vieja (por `id`), de todas sus instituciones: el derecho es de la persona. Nunca trae las de otro.

### 1.3 `GET /admin/solicitudes-datos` y `PUT /admin/solicitudes-datos/{id}` (guarda `admin`)
- **`GET`**: las solicitudes cuya institución es la **activa del admin**, de la más nueva a la más vieja. Con `?estado=` filtra (un estado que no existe → 422). Cada una trae además al solicitante: `{"profile_id", "nombre", "documento_id"}`; `nombre` es el de la membresía en **esa** institución (BUG-11), o `null`.
- **`PUT`** con `{"estado": "en_tramite"|"resuelta"|"rechazada", "respuesta": str}` (`respuesta` de 1 a 1000 caracteres; `abierta` no se puede volver a poner → 422).
  - **200** con la solicitud. Guarda el estado, la respuesta, **quién respondió** (el admin del token) y **cuándo** (reloj del servidor).
  - Una solicitud de **otra institución** o inexistente → **404** (la misma respuesta), y no cambia.
  - Una solicitud ya **cerrada** (`resuelta` o `rechazada`) → **409 `{"detail": "solicitud_cerrada"}`**: una respuesta dada no se reescribe.
  - `en_tramite` se puede actualizar las veces que haga falta; la última respuesta es la que se ve, y **cada cambio queda en `audit_logs`** (`datos_solicitud_respondida`, con `{solicitud_id, estado}` y el admin en `user_id`).
- El docente no las ve ni las responde (403): son datos personales, no asunto del aula.

### 1.4 No ejecuta nada
Resolver una solicitud de `suprimir` **no borra ni cambia ningún dato**: suprimir es un trámite manual del operador, y aquí solo queda documentado que se pidió, quién lo respondió y cuándo. Lo fija SD6.

**Si el operador borra el perfil,** la solicitud **se conserva sin la persona** (`profile_id` pasa a nulo, `ON DELETE SET NULL`): queda la prueba de que se atendió. El texto del mensaje lo escribió la persona y puede traer datos suyos: el procedimiento manual incluye vaciarlo (`PRODUCCION_030.md`).

### 1.5 La solicitud, como la ve cada uno
```json
{"id": 12, "tipo": "rectificar", "mensaje": "Mi nombre está mal escrito.",
 "estado": "abierta", "creada_en": "2026-10-06T15:04:05.123456Z",
 "respuesta": null, "respondida_en": null}
```
El admin recibe lo mismo más `"solicitante": {"profile_id", "nombre", "documento_id"}` (o `null` si el perfil ya no existe). **Ninguna respuesta trae `respondida_por`:** quién respondió queda en la base, para el operador.

### 1.6 Las dos barreras de entrada (decisión)
- **Sin consentimiento, se puede.** Negarse al aviso no quita el derecho a preguntar por los datos o a pedir que se borren. El servidor no bloquea por consentimiento en ninguna ruta (`ESPEC_consentimiento.md` §1.4), así que hoy no hay nada que exceptuar; SD6 lo deja fijado para que un bloqueo futuro tenga que exceptuar estas dos rutas.
- **Con contraseña temporal, NO se puede: 403 `must_change_password`,** como toda ruta fuera de los 4 pares. Por qué:
  - una contraseña temporal la conoce alguien más (el operador que la generó y quien la entregó). Una solicitud hecha con ella **no prueba que la hizo el titular**, y entre los tipos está `suprimir`;
  - cambiarla es un paso y no exige aceptar el aviso;
  - mantiene la lista de permitidas en 4 pares exactos (UP3 y el recorrido completo que pide la auditoría, H-19).
  - **Límite declarado:** quien no pueda o no quiera cambiar la contraseña no tiene canal dentro de la app; le queda el admin de su institución.
- **Otros límites declarados:** tampoco tiene canal quien no tiene membresía activa (espera aprobación, fue rechazado o su institución lo desactivó): toda ruta le da 403. Y el `GET` del usuario exige lo mismo.

### 1.7 Migración `036_solicitudes_datos`
```sql
CREATE TABLE IF NOT EXISTS solicitudes_datos (
  id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  profile_id     UUID REFERENCES profiles(id) ON DELETE SET NULL,
  tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  tipo           TEXT NOT NULL,
  mensaje        TEXT NOT NULL,
  estado         TEXT NOT NULL DEFAULT 'abierta',
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  respuesta      TEXT,
  respondida_por UUID REFERENCES profiles(id) ON DELETE SET NULL,
  respondida_en  TIMESTAMPTZ,
  CONSTRAINT solicitudes_datos_tipo_check
    CHECK (tipo IN ('conocer','actualizar','rectificar','suprimir')),
  CONSTRAINT solicitudes_datos_estado_check
    CHECK (estado IN ('abierta','en_tramite','resuelta','rechazada')),
  CONSTRAINT solicitudes_datos_mensaje_check CHECK (char_length(mensaje) BETWEEN 1 AND 1000),
  CONSTRAINT solicitudes_datos_respuesta_check
    CHECK (respuesta IS NULL OR char_length(respuesta) BETWEEN 1 AND 1000),
  CONSTRAINT solicitudes_datos_traza_check
    CHECK ((estado = 'abierta') = (respondida_en IS NULL AND respuesta IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_solicitudes_datos_perfil ON solicitudes_datos (profile_id);
CREATE INDEX IF NOT EXISTS idx_solicitudes_datos_tenant ON solicitudes_datos (tenant_id, estado);
ALTER TABLE solicitudes_datos ENABLE ROW LEVEL SECURITY;
```
- RLS activo y sin políticas (como la 034 y la 035). Las políticas siguen en 51.
- Los CHECK repiten las reglas de la API: un mensaje de 1001 o un tipo inventado no entran ni aunque la API los dejara pasar.
- **Bajada:** `DROP TABLE`. **Se pierden las solicitudes y su traza:** en producción no se baja.

**Ediciones a lo existente, todas declaradas (ERR-25):**
- `tests/integ_db.py`: `alembic_version` → `036_solicitudes_datos` y `tablas_con_rls` 29 → 30;
- `alembic_version` en los 4 humos de §0;
- `tests/seguridad/test_sin_acceso.py`: 30 y 30 → 31 y 31;
- `tests/teachers/test_access.py`: 4 entradas (`/auth/solicitudes-datos` POST y GET, `user`; `/admin/solicitudes-datos` GET y `/admin/solicitudes-datos/{sid}` PUT, `admin`);
- `src/shared/models.py` (`SolicitudDatos`), `src/main.py` (dos routers) y `.gitignore` (el humo).
- Si la medición encuentra otra, se corrige esta lista primero (regla 8).

## 2. Criterios
| # | Criterio | Test |
|---|---|---|
| C1 | **Crear y ver:** `POST` → 201 con `estado: abierta`, `respuesta` y `respondida_en` nulos y un `creada_en` con zona igual al de la fila. La fila tiene el perfil del token y la institución activa (con `X-Tenant-ID`, la pedida). `GET` la trae. 1 auditoría `datos_solicitud_creada` cuyo `metadata` no contiene el mensaje | SD1 |
| C2 | **Nadie lee ni crea por otro:** A crea 2; el `GET` de B da `[]` y el de A, 2. Un cuerpo con `profile_id` de B, con `tenant_id`, con `estado` o con `created_at` → 422 y 0 filas nuevas. Todas las filas son de A | SD2 |
| C3 | **Validación → 422 y 0 filas:** tipo `borrar`, tipo ausente, tipo `SUPRIMIR`, mensaje de 1001, vacío, solo espacios, numérico y ausente. Control: mensaje de 1000 → 201 | SD3 |
| C4 | **Tope de 5:** cinco → 201; la sexta → 409 `demasiadas_solicitudes_abiertas` y siguen 5 filas. El admin pasa una a `en_tramite`: sigue en 409. La cierra (`resuelta`): la siguiente → 201 | SD4 |
| C5 | **El admin, solo su institución y con traza:** A1 (de A) y B1 (de B) crean una cada uno. El admin de A lista 1 (la de A1, con su nombre de A y su documento); el de B, la de B1. El admin de B hace `PUT` sobre la de A → 404 y la fila no cambia. Estudiante y docente en `GET` y `PUT` → 403. `PUT` con `estado: abierta`, con respuesta vacía o de 1001 → 422. El admin de A responde `en_tramite` y después `resuelta`: 200 las dos; la fila tiene `respondida_por` = el admin y `respondida_en`; hay 2 auditorías `datos_solicitud_respondida`; otro `PUT` → 409 `solicitud_cerrada` y la respuesta no cambia. A1 ve en su `GET` el estado y la respuesta, y la respuesta no trae `respondida_por` | SD5 |
| C6 | **Barreras y "no ejecuta":** con `force_password_reset`, `POST` y `GET` → 403 `must_change_password` y 0 filas. Sin consentimiento (`consent_version: null`), `POST` → 201. Una solicitud `suprimir` resuelta deja el perfil, la membresía, el consentimiento y el saldo **idénticos** | SD6 |
| C7 | Migración up/down/up idéntica, con los campos de ERR-24. Subir dos veces no falla | MG36 |
| C8 | Regresión: los 418 previos verdes con solo las ediciones de §1.7. D12 da 0 y 0. UP3 no se toca | la suite completa |

## 3. Tests, tramposos, humo y réplica
- `tests/datos/test_solicitudes_datos.py`: SD1-SD6 (integ), con las reglas del login piloto (`raise_server_exceptions=False`, lo observado en un dict comparado entero).
- `tests/integ/test_migracion_036.py`: MG36, con las funciones de `test_migracion_035.py`.
- `tests/integ/test_humo_solicitudes_datos.py`: **HS1** escribe `tests/_salida/humo_solicitudes_datos.json` antes de afirmar. Semilla `random.Random(36)`: elige el tipo de cada solicitud y cuál responde el admin. Dos instituciones; 4 personas crean 6 solicitudes; un admin responde 2.
  ```json
  {"alembic_version":"036_solicitudes_datos","semilla":36,"creadas_201":6,"de_1001":422,
   "tipo_invalido":422,"del_usuario":[2,2,1,1],"del_admin":[4,2],"cruce_de_institucion":404,
   "respondidas":2,"con_traza":2,"auditorias":{"creada":6,"respondida":2},"perfiles_borrados":0}
  ```
- **Réplica** (`ENGRAMA_REPLICA_SOLICITUD_DATOS=1`; 1 test que se salta sin la bandera): **RS1**, con entradas nuevas: un mensaje con tildes, ñ, emoji y saltos de línea de exactamente 1000 caracteres; una persona en dos instituciones que crea una solicitud en cada una (cada admin ve solo la suya, ella ve las dos); y el tope de 5 repartido entre las dos instituciones.

**Tramposos** (`tests/tramposos/test_tramposos_solicitud_datos.py`), diagonal predicha (ERR-23: el código no existe):

| Id | Rompe | Rojo predicho | Verde predicho y por qué |
|---|---|---|---|
| XS1 | La lista del usuario no filtra por perfil | **SD2** (as: B ve las de A). HS1 (as: `del_usuario`) | SD1: una sola persona |
| XS2 | La solicitud se crea a nombre de **otro** perfil | **SD2** (as: las filas no son de A). SD1 (as: el perfil de la fila; si no hay otro perfil, 500). SD4 (as: el tope no cuenta) | SD3: no llega a escribir, salvo su control |
| XS3 | La lista del admin no filtra por institución | **SD5** (as: el admin de A ve 2). HS1 (as: `del_admin`) | — |
| XS4 | El `PUT` busca la solicitud sin la institución | **SD5** (as: el admin de B responde la de A, 200). HS1 (as: `cruce_de_institucion`) | — |
| XS5 | La ruta acepta `mensaje: str` sin tope (se reemplaza la `APIRoute`) | **SD3** (as: el CHECK de la base lo frena y da 500 en vez de 422). HS1 (as: `de_1001`) | — |
| XS6 | La ruta acepta `tipo: str` libre (ídem) | **SD3** (as: 500 por el CHECK). HS1 (as: `tipo_invalido`) | — |
| XS7 | Sin el tope de 5 | **SD4** (as: la sexta → 201) | — |
| XS8 | Resolver un `suprimir` borra el perfil | **SD6** (as: el perfil ya no está). HS1 (as: `perfiles_borrados`, si el azar eligió un `suprimir`) | SD5: su solicitud no es `suprimir` |
| XS9 | El `PUT` no guarda quién respondió | **SD5** (as: `respondida_por`). HS1 (as: `con_traza`) | — |

Matriz a medir antes de aceptar: 9 tramposos × 8 columnas (SD1-SD6, MG36 y HS1) = **72 celdas**, más RS1 con la bandera.

### Matriz medida: 72 celdas, más RS1 (paso 3; ERR-19 y ERR-23)
**Cómo se midió** (2026-10-06, sobre el código del paso 2): una corrida de pytest por tramposo, aplicado a las 8 columnas por una fixture `autouse`. La fila base dio 8 verdes.

**Resultado: 20 rojas, todas por aserción; 0 por excepción; 52 verdes.**

| Id | Rojas medidas | RS1 (con la bandera) |
|---|---|---|
| XS1 | SD2, HS1 y **SD5** | verde |
| XS2 | SD1, SD2, **SD3**, **SD5** y **HS1** | roja (as) |
| XS3 | SD5 y HS1 | roja (as) |
| XS4 | SD5 y HS1 | verde |
| XS5 | SD3 y HS1 | verde |
| XS6 | SD3 y HS1 | verde |
| XS7 | SD4 | roja (as) |
| XS8 | SD6 | verde |
| XS9 | SD5 y HS1 | verde |

**Contra la predicción (ERR-23; ningún test se tocó para que calzara):**
- **XS2 × SD4 salió verde** (se predijo roja): el tramposo cuenta y bloquea con el mismo perfil equivocado, así que el tope sigue cortando en la sexta.
- **XS2 × SD3, SD5 y HS1, y XS1 × SD5,** no estaban: el control de SD3 (1000 caracteres) sí escribe, y sin otro perfil da 500; SD5 y HS1 leen la lista del usuario.
- **XS8 cambió de mecanismo antes del commit.** Borrar el perfil no se puede: `audit_logs.user_id` referencia a `profiles` sin `ON DELETE`, y la persona tiene la auditoría de su propia solicitud, así que la base responde 500. El tramposo quedó como "resolver un `suprimir` **desactiva** el perfil", que sí llega a la aserción de SD6. **Hallazgo para el operador:** hoy un perfil con auditoría a su nombre no se borra con un `DELETE` simple (abajo, en `PRODUCCION_030.md`).
- XS8 × HS1: verde, como estaba condicionado.

**Medido (2026-10-06): 435 passed + 17 skipped; 118 no-integ; `ruff check .` 0 y `mypy .` 0 (244 archivos).** Igual a §4. HS1 escribió el archivo con el contenido exacto de §3. **RS1 pasó en su primera corrida.** Las ediciones a lo existente fueron exactamente las de §1.7.

**No medido:** el `downgrade` por la CLI de Alembic (MG36 corre las mismas tuplas de SQL); dos envíos realmente simultáneos contra el tope de 5 (el candado está, sin test de concurrencia).

## 4. Cuentas (ERR-10)
| Grupo | integ | no-integ |
|---|---|---|
| SD1-SD6 | 6 | — |
| MG36 | 1 | — |
| HS1 | 1 | — |
| XS1-XS9 | 9 | — |
| **Nuevos** | **17** | **0** |
| RS1 (saltado sin bandera) | 1 skipped | — |

- **passed:** 418 + 17 = **435**; **skipped:** 16 + 1 = **17**; **no-integ:** **118**; ruff 0 y mypy 0.
- Si el autorregistro cierra con otras cifras N, S y M, las metas pasan a N + 17, S + 1 y M.

## 5. Plan de commits
1. `docs`: esta espec.
2. `feat(datos)`: la 036, el modelo, `src/datos/`, las 4 rutas, los tests, los tramposos, el humo, la réplica y las ediciones de §1.7.
3. `docs`: la matriz medida y "Antes de aplicar la 036", con el procedimiento manual de supresión, en `PRODUCCION_030.md`.

## 6. Contrato para el cliente (engrama-web)
```
POST /api/auth/solicitudes-datos      {"tipo":"suprimir","mensaje":"Quiero que borren mi cuenta."}
201 {"id":12,"tipo":"suprimir","mensaje":"…","estado":"abierta","creada_en":"…","respuesta":null,"respondida_en":null}
409 {"detail":"demasiadas_solicitudes_abiertas"}     ya tiene 5 sin cerrar
422 {"detail":[…]}                                   tipo o mensaje mal (loc dice cuál)
403 {"detail":"must_change_password"}                primero cambia la contraseña

GET  /api/auth/solicitudes-datos
200 [ {…la más nueva…}, … ]

GET  /api/admin/solicitudes-datos[?estado=abierta]
200 [ {…, "solicitante":{"profile_id":"…","nombre":"Ana Pérez","documento_id":"uis_2201234"}} ]
PUT  /api/admin/solicitudes-datos/12   {"estado":"resuelta","respuesta":"Se corrigió el nombre."}
200 {…la solicitud…}   404 no es de su institución   409 {"detail":"solicitud_cerrada"}
```
- El cliente muestra estas rutas **antes** de exigir el aviso (el servidor las deja).
- Estados: `abierta` → `en_tramite` → `resuelta` o `rechazada`.

## 7. Riesgo para producción, qué NO se toca y "para después"
- **Aplicar la 036 es producción:** el sí de Christiam, con respaldo. Va antes o junto con el código (sin la tabla, las 4 rutas dan 500; lo demás no lo nota).
- **No se toca:** `RUTAS_CON_CONTRASENA_TEMPORAL`, UP3, el consentimiento ni `engrama-web`.
- **Para después:** avisar al admin de que hay solicitudes; plazos y vencimientos (la ley los fija; aquí no se miden); adjuntos; que el solicitante retire su solicitud; exportar los datos de una persona (`conocer`) con una herramienta; un canal para quien no puede entrar; el operador de plataforma viendo las de todas las instituciones.
- **Para el pedagogo y para Christiam (ERR-16):** los textos de los 4 tipos y de los estados que ve el estudiante.

## 8. Veredicto
- **FUNCIONA:** las cuentas de §4, la matriz medida, HS1 escrito, MG36 verde y los previos verdes con solo las ediciones declaradas.
- **NO:** alguien lee o crea la solicitud de otro; un admin ve o responde la de otra institución; entra un mensaje de 1001 o un tipo inventado; responder borra o cambia datos; una respuesta queda sin quién ni cuándo; un tramposo queda verde.
