# ESPEC · Registro del consentimiento (aviso de tratamiento de datos, Ley 1581), backend

F4 · Creador · 2026-10-06 · preregistro. Rama `test/fixture-integ`, HEAD `c436d59` (login del piloto y BUG-16 cerrados: **366 passed + 14 skipped y 109 no-integ**, medidos).

Origen: encargo de Christiam por ARQUITECTO (2026-10-06), antes de que entren estudiantes reales. El cliente ya trabaja contra un mock con el contrato de `ENGRAMA/engrama-web/docs/ENCARGO_backend_consentimiento.md`. **Esta espec adopta ese contrato**; las diferencias con el encargo de ARQUITECTO se concilian en §1.6.

**Esto NO es un concepto jurídico.** El backend solo registra quién aceptó qué versión y cuándo. El texto del aviso, quién es el responsable y el acuerdo de encargo los revisa un abogado (`PRODUCCION_030.md`).

## 0. Medido y leído (2026-10-06)
| Qué | Dónde |
|---|---|
| `/auth/me` y `/auth/session` comparten el cuerpo | `src/auth/router.py` (`_build_profile_payload`) |
| Rutas permitidas con contraseña temporal: 4 pares `(path, método)` | `src/auth/service.py` (`RUTAS_CON_CONTRASENA_TEMPORAL`); las fija UP3 |
| Mapa de guardas por ruta | `tests/teachers/test_access.py` (`EXPECTED_GUARDS`) |
| `audit_logs` ya existe y `/auth/logout` escribe en ella | `src/auth/router.py`; `models.py` (`AuditLog`) |
| Los clientes no tienen acceso directo a `public`, tampoco a lo que se cree después | `031_sin_acceso_directo.py` (`ALTER DEFAULT PRIVILEGES`) |
| **El reloj de la base de pruebas retrocede** (hasta 1,95 s cada 27 s) | `ESPEC_login_piloto.md` §3. Por eso "la más reciente" **no** se decide por fecha |
| `034_login_vendible` estaba reservada para la 008 | `ESPEC_login_piloto.md` §1.8 |
| **`alembic_version` fijado en los tests** (ERR-25; `git grep -n alembic_version -- tests`, corrido hoy) | `tests/integ_db.py:66`, `tests/integ/test_humo_bug11.py:35` y `tests/integ/test_humo_bug13a15.py:44` |
| Otros números que una tabla nueva mueve (`git grep -n "tablas_con_rls\\|27" -- tests`) | `tests/integ_db.py:67` (`tablas_con_rls: 26`) y `tests/seguridad/test_sin_acceso.py:85` (27 y 27) |

## 1. Qué cambia (una cosa)
**El backend registra que una persona aceptó una versión del aviso de datos, y `/auth/me` dice cuál fue la última.**

### 1.1 `POST /auth/consentimiento`
- **Guarda `user`** (JWT válido y perfil existente).
- **Cuerpo:** `{"version": "<texto>"}`, estricto y con `extra="forbid"`.
  - `version`: de 1 a 32 caracteres, sin espacios al principio ni al final. Si no, **422** sin escribir nada.
  - No se acepta ningún otro campo: ni `profile_id`, ni `accepted_at`. **La persona es siempre la del token y la fecha es siempre la del servidor.**
- **Respuesta 200:** `{"version": "<la guardada>", "accepted_at": "<ISO 8601 con zona>"}`.
- **Idempotente por (perfil, versión):** repetir la misma versión no crea otra fila, no cambia `accepted_at` (devuelve la primera) y no agrega auditoría. Responde 200 igual.
- Una versión **distinta** guarda una fila nueva: queda el historial.
- **Auditoría:** una fila en `audit_logs` por cada aceptación nueva (`action_type = 'consent_accept'`, `result = 'success'`, `metadata = {"version": …}`, `tenant_id` = la institución activa). No se guarda IP ni dispositivo (dato mínimo).
- **El servidor no conoce la versión vigente.** Acepta cualquier versión bien formada; la vigente la define el cliente (`AVISO_VERSION`). Una persona solo puede registrar aceptaciones **propias**.

### 1.2 `/auth/me` y `/auth/session`
Se **agrega** `consent_version: str | null`: la versión de la **última fila creada** para ese perfil, o `null` si nunca aceptó. Ningún campo previo cambia.
- "Última" es la de mayor `id` (identidad creciente), **no** la de mayor `accepted_at`: la fecha depende del reloj de la base, que puede retroceder (§0).
- **Límite declarado:** volver a aceptar una versión **anterior** es idempotente, así que no pasa a ser la última. Si `AVISO_VERSION` volviera a un texto ya usado, quien aceptó una posterior quedaría sin poder entrar. **Una versión nunca se reutiliza** (aviso a ARQUITECTO).

### 1.3 Por perfil, no por institución (decisión)
El consentimiento es **de la persona**: una fila por (perfil, versión), sin `tenant_id`.
- La cuenta es una sola aunque la persona esté en dos instituciones (una cédula, un perfil, un login): un docente de UIS y SENA acepta una vez.
- El cliente tiene **un** aviso y **un** responsable por despliegue (`AVISO_RESPONSABLE`).
- La institución activa al aceptar queda como contexto en `audit_logs`.
- **Si cada institución resulta ser responsable de sus propios datos** (decisión jurídica pendiente), hace falta un aviso por institución. Sin migrar nada: la versión puede llevar la institución (`uis-2026-10-v1`). Con migración: `tenant_id` en la tabla. Queda en "Para después".

### 1.4 Sin bloqueo en el servidor (decisión del piloto) y la opción
- **Sin consentimiento, el servidor no bloquea ninguna ruta.** Lo exige el cliente, que no deja entrar hasta que `consent_version == AVISO_VERSION`. Lo fija CN5.
- **Con contraseña temporal, la ruta da 403 `must_change_password`**, como todo lo que no está entre los 4 pares permitidos. El cliente la llama después de crear la contraseña. UP3 no se toca.
- **Opción que NO se implementa (para Christiam):** bloquear en el servidor con el mismo mecanismo de la contraseña temporal (403 `consent_required` salvo una lista de pares permitidos, que incluiría esta ruta).
  - Es barato en código, pero exige que **el servidor** conozca la versión vigente (una variable `CONSENT_VERSION` igual a `AVISO_VERSION`). Si las dos difieren por un error de despliegue, **nadie entra**.
  - Costo por request: una consulta más en cada ruta autenticada. **No está medido.**
  - Sin eso, quien llame a la API sin la web puede usarla sin aceptar. Para el piloto se acepta: las cuentas las crea el operador.

### 1.5 Migración `034_consentimiento`
```sql
CREATE TABLE IF NOT EXISTS consentimientos (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  profile_id  UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  version     TEXT NOT NULL,
  accepted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT consentimientos_perfil_version UNIQUE (profile_id, version),
  CONSTRAINT consentimientos_version_check
    CHECK (char_length(version) BETWEEN 1 AND 32 AND version = btrim(version))
);
ALTER TABLE consentimientos ENABLE ROW LEVEL SECURITY;
```
- **Sin políticas:** con RLS activo y sin política, ningún rol de cliente lee ni escribe (además de no tener privilegios, por la 031). El backend entra como `service_role`. Las políticas siguen en 51.
- **El CHECK repite la regla del esquema** (defensa en profundidad): una versión vacía no entra ni aunque la API la dejara pasar.
- **Bajada:** `DROP TABLE IF EXISTS consentimientos`. **Se pierde el historial de aceptaciones:** en producción no se baja; se restaura el respaldo.
- **`034_login_vendible` deja de estar reservada:** la 008 toma la siguiente libre sobre `034_consentimiento` (errata a `ESPEC_login_piloto.md` §1.8 y a `ESPEC_login_vendible.md`, en el commit de docs del cierre).

**Ediciones a lo existente, todas declaradas (ERR-25):**
- `tests/integ_db.py`: `alembic_version` → `034_consentimiento` y `tablas_con_rls` 26 → 27;
- `tests/integ/test_humo_bug11.py:35` y `tests/integ/test_humo_bug13a15.py:44`: `alembic_version`;
- `tests/seguridad/test_sin_acceso.py`: el control de D12 pasa de 27 y 27 a 28 y 28;
- `tests/teachers/test_access.py`: una entrada en el mapa de guardas (`("/auth/consentimiento", POST): "user"`);
- `tests/auth/test_login_piloto.py`: `consent_version` entra a `CLAVES_NUEVAS_RAIZ` (SP1 quita las claves nuevas antes de comparar con el snapshot);
- `src/shared/models.py`: el modelo `Consentimiento`.
- Si la medición encuentra otra, se corrige esta lista primero (regla 8).

### 1.6 Diferencias entre los dos encargos, conciliadas
| Tema | ARQUITECTO | Cliente | Queda |
|---|---|---|---|
| Respuesta | no dice | `{version, accepted_at}`, 200 | la del cliente |
| Largo de la versión | "no vacía" | 1 a 32, sin espacios al borde | la del cliente |
| Dónde se guarda | "por perfil" | tabla con historial, `UNIQUE (profile_id, version)` | tabla |
| Con contraseña temporal | "permitida aunque falte el consentimiento" | 403 `must_change_password` | **403**. No se contradicen: el servidor no bloquea por consentimiento (§1.4), así que la ruta siempre se puede usar sin él; la contraseña temporal es otra barrera |
| Por institución | "decide la espec" | por persona | por persona (§1.3) |

## 2. Criterios
| # | Criterio | Test |
|---|---|---|
| C1 | Antes de aceptar, `/auth/me` trae `consent_version: null`. `POST` con `2026-10-v1` → 200 con esa versión y un `accepted_at` con zona, igual al de la fila. Después, `/auth/me` y `/auth/session` traen `2026-10-v1`. Hay 1 fila y 1 auditoría `consent_accept` | CN1 |
| C2 | **Nadie registra por otro:** A acepta; B sigue en `null` y con 0 filas. Un cuerpo con `profile_id` de B o con `accepted_at` → 422 y 0 filas nuevas | CN2 |
| C3 | **Idempotencia e historial:** la misma versión dos veces → el mismo `accepted_at`, 1 fila y 1 auditoría. Otra versión → 2 filas y `/auth/me` trae la nueva. La primera otra vez → siguen 2 filas, su `accepted_at` original, y `/auth/me` sigue en la nueva | CN3 |
| C4 | **Versión inválida → 422 y 0 filas:** `""`, `" "`, `" v1"`, `"v1 "`, 33 caracteres, un número y el campo ausente. Control: 32 caracteres → 200 | CN4 |
| C5 | **Barreras:** con `force_password_reset`, `POST` → 403 `must_change_password` y 0 filas. Sin consentimiento, `GET /challenges/` → 200 (el servidor no bloquea) | CN5 |
| C6 | **Migración up/down/up idéntico:** tras bajar no existe la tabla; tras volver a subir coinciden, con la primera subida, las columnas (nombre, tipo, nulabilidad y default), la definición de cada restricción (`pg_get_constraintdef`), los índices y `relrowsecurity`. No se compara `ordinal_position` (ERR-24). Subir dos veces no falla | MG1 |
| C7 | Regresión: los 366 previos siguen verdes, con solo las ediciones de §1.5. D12 da 0 y 0: ningún cliente tiene privilegios sobre la tabla nueva | la suite completa |

## 3. Tests, tramposos, humo y réplica
- `tests/auth/test_consentimiento.py`: CN1-CN5 (integ), con `TestClient(app, raise_server_exceptions=False)` y lo observado en un dict comparado entero, con mensaje.
- `tests/integ/test_migracion_034.py`: MG1, con el patrón de `test_migracion_033.py` (una transacción que termina en ROLLBACK).
- `tests/integ/test_humo_consentimiento.py`: **HC1** escribe `tests/_salida/humo_consentimiento.json` antes de afirmar (va al `.gitignore`). Semilla `random.Random(34)`, que elige quién repite. Tres personas sintéticas; una está en dos instituciones.
  ```json
  {"alembic_version":"034_consentimiento","semilla":34,"antes":[null,null,null],
   "aceptan":[200,200,200],"despues":["2026-10-v1","2026-10-v1","2026-10-v1"],
   "repite":{"status":200,"misma_fecha":true},"vacia":422,"filas":3,"auditorias":3,
   "en_su_otra_institucion":"2026-10-v1","sin_bloqueo":200}
  ```
- **Réplica** (`ENGRAMA_REPLICA_CONSENTIMIENTO=1`, 1 test que se salta sin la bandera): **RC1**, con entradas nuevas: una versión con ñ y tilde, una de exactamente 32 caracteres, y 6 versiones seguidas de la misma persona (la última gana aunque las fechas se crucen).

**Tramposos** (`tests/tramposos/test_tramposos_consentimiento.py`), diagonal predicha (ERR-23: el código no existe):

| Id | Rompe | Rojo predicho | Verde predicho y por qué |
|---|---|---|---|
| XC1 | El registro se escribe a nombre de **otro** perfil | **CN2** (as: B aparece con la versión y A sin ella). CN1, CN3 y HC1 (as: quien acepta no queda registrado) | CN4 y CN5: no llegan a escribir |
| XC2 | La ruta acepta `version: str` sin límites (se reemplaza la `APIRoute`) | **CN4** (as: `""` llega a la base, el CHECK la rechaza y da 500 en vez de 422; `" v1"` igual). HC1 (as: `vacia` ≠ 422) | CN1-CN3 y CN5: mandan versiones válidas |
| XC3 | Repetir la versión **renueva** la fila (borra e inserta) | **CN3** (as: cambia `accepted_at` y hay 2 auditorías). HC1 (as: `misma_fecha` = false) | CN1, CN2, CN4 y CN5: no repiten |
| XC4 | `consent_version` es la **primera** fila, no la última | **CN3** (as: `/auth/me` sigue en la versión vieja) | CN1, CN2 y HC1: una sola versión por persona |

Matriz a medir antes de aceptar: 4 tramposos × 7 columnas (CN1-CN5, MG1 y HC1) = 28 celdas, más RC1 con la bandera.

## 4. Cuentas (ERR-10)
| Grupo | integ | no-integ |
|---|---|---|
| CN1-CN5 | 5 | — |
| MG1 | 1 | — |
| HC1 | 1 | — |
| XC1-XC4 | 4 | — |
| **Nuevos** | **11** | **0** |
| RC1 (saltado sin bandera) | 1 skipped | — |

- **passed:** 366 + 11 = **377**; **skipped:** 14 + 1 = **15**; **no-integ:** **109**; ruff 0 y mypy 0.
- Con `ENGRAMA_REPLICA_CONSENTIMIENTO=1`: 378 passed + 14 skipped.

## 5. Plan de commits
1. `docs`: esta espec.
2. `feat(auth)`: la 034, el modelo, la ruta, `consent_version`, los tests, los tramposos, el humo, la réplica y las ediciones de §1.5.
3. `docs`: la matriz medida, las erratas de la 034 en las otras especs y "Antes de aplicar la 034" en `PRODUCCION_030.md`.

## 6. Riesgo para producción
- **Aplicar la 034 en el piloto es producción:** necesita el sí de Christiam. Va **antes o junto** con el código: sin la tabla, `/auth/me` da 500 y **nadie entra**.
- Con respaldo previo (`pg_dump`). Sin downgrade en producción.
- El contrato del cliente falla cerrado: mientras `/auth/me` no traiga `consent_version`, no deja entrar.

## 7. Qué NO se toca y "para después"
- No se toca: `RUTAS_CON_CONTRASENA_TEMPORAL`, UP3, el alta del operador ni `ENGRAMA/engrama-web`.
- Para después: el bloqueo en el servidor (§1.4); el consentimiento por institución (§1.3); retirar o exportar el consentimiento (hoy, escribiendo al contacto del aviso); el consentimiento de menores (tutor), que es de la 008.

## 8. Veredicto
- **FUNCIONA:** las cuentas de §4, la matriz medida, HC1 escrito, MG1 verde y los 366 previos verdes con solo las ediciones declaradas.
- **NO:** alguien registra por otro; una versión vacía queda guardada; la fecha la pone el cliente; un cliente tiene privilegios sobre la tabla; un tramposo queda verde.
