# ESPEC · Endurecimiento del piloto antes del túnel, backend

F4 · Creador · 2026-10-06 · preregistro. Rama `test/fixture-integ`, sobre el autorregistro y las solicitudes de datos (meta **435 passed + 17 skipped y 118 no-integ**).

Origen: la auditoría `investigacion/seguridad/02-auditoria-piloto-antes-del-tunel.md` (2026-10-06), en lo que toca al backend: H-7, H-8, H-10, H-11, H-12, H-13 y H-19, más el intermitente del reloj. Lo de integración y web (H-1 a H-6, H-9 y H-14 a H-18) no es de esta espec.

**Un commit por punto** (§5). Cada punto es una cosa; van juntos en una espec porque comparten origen y son chicos.

## 0. Medido y leído (2026-10-06)
| Qué | Dónde |
|---|---|
| `jwt.decode` sin exigir claims | `src/auth/service.py:59-64`: `algorithms` y `audience`, sin `options`. La auditoría midió que acepta un token sin `aud` ni `exp` |
| `profiles.is_active` existe y nadie lo consulta | `src/shared/models.py` (`Profile.is_active`); `get_current_user` (`src/shared/deps.py`) no lo mira |
| El archivo de credenciales | `src/onboarding/salida.py:42-56`: `ruta.open("a")` y después `os.chmod(0o600)`; la guarda `dentro_del_repo` (`:37`) solo mira el repo del backend |
| La CLI exige `--salida` y GoTrue para toda orden | `src/onboarding/__main__.py:107` y `:115` |
| La versión del aviso es texto libre | `src/auth/consentimiento.py:25`; `ConsentimientoIn.version` solo acota la forma |
| El bloqueo por contraseña temporal | UP3 (`tests/auth/test_permitidas_unit.py`) prueba la función; AP9 prueba por HTTP dos rutas |
| El backend entra a la base como `postgres` | `src/shared/db.py:4` ("service_role, bypass RLS"); el despliegue le da el usuario `postgres` |
| El intermitente del reloj | `ESPEC_login_piloto.md` §3: el colegio por defecto es la membresía con el `created_at` más antiguo, y el reloj del contenedor de pruebas retrocede hasta 1,95 s |
| Quiénes crean dos membresías seguidas sin fijar la fecha | `tests/teachers/_actores.py` (`armar`: D en A y en B), OP4 (`tests/onboarding/test_alta.py`), HP1 y RP1 (`tests/integ/_login_piloto.py`) |

## 1. Los puntos

### H-10 · El JWT debe traer `exp`, `aud` y `sub`
- `validate_jwt` pasa a `jwt.decode(..., options={"require_exp": True, "require_aud": True, "require_sub": True})`.
- Un token bien firmado al que le falte cualquiera de los tres → **401**. Hoy, sin `exp` no vence nunca.
- **Criterio (UJ1, no-integ):** cuatro tokens firmados con el secreto correcto: completo → pasa; sin `exp` → 401; sin `aud` → 401; sin `sub` → 401. **Tramposo ZH10:** el `jwt.decode` de hoy (sin `options`) → UJ1 rojo (el token sin `exp` pasa).
- Los 13 tests de `tests/auth` y `integ.headers()` ya mandan los tres: no cambian.

### H-8 · Suspender una cuenta
- **`get_current_user`:** si `profiles.is_active` es falso → **403 `{"detail": "account_suspended"}`** en **toda** ruta, también `/auth/me`. Va después de "sin perfil" y antes de la contraseña temporal. Se lee de la base en cada petición: corta **al instante**, sin esperar a que venza el token.
- **`python -m src.onboarding suspender --slug <slug> --documento <doc>`:**
  - el documento debe tener una membresía en esa institución (activa o no); si no, salida 1 y 0 cambios, con el mismo mensaje para "no existe" y "es de otra" (como `restablecer`);
  - pone `profiles.is_active = false` **y** `memberships.is_active = false` en esa institución, en una transacción, con una auditoría `cuenta_suspendida`;
  - es idempotente; imprime `{"institucion", "suspendidas": 1}`;
  - **no necesita GoTrue ni `--salida`**: solo `DATABASE_URL`.
- **`reactivar --slug --documento`**, la inversa (auditoría `cuenta_reactivada`). Sin ella, deshacer una suspensión equivocada sería SQL a mano en producción.
- **Decisión: NO se bloquea la cuenta en GoTrue.**
  - La bandera de la base ya corta todo: el backend la lee en cada petición, y EVA, SET y el Grader preguntan `/auth/me` (011 §4), que da 403.
  - Un bloqueo en GoTrue (`ban_duration`) **no** invalida el token vigente (hasta 1 hora), así que por sí solo es más lento que la bandera; y su comportamiento en `v2.196.0` no está medido.
  - Queda en "para después" como segunda barrera.
- **Límite declarado: el perfil es global.** Suspender a una persona en una institución le corta el acceso en **todas** (una cuenta, una persona). Para sacarla solo de una institución sin tocar las otras hace falta desactivar solo la membresía: `--solo-institucion`, que deja `profiles.is_active` como está.
- **Criterios:** **AH8** (integ): suspendido → 403 `account_suspended` en `/auth/me`, `/auth/session` y `GET /challenges/`; otro usuario, 200; reactivado por SQL, 200. **OH8** (integ): `suspender` deja perfil y membresía inactivos y 1 auditoría, sin variables de GoTrue; un documento de otra institución → salida 1 y 0 cambios; `--solo-institucion` deja el perfil activo; `reactivar` los devuelve.
- **Tramposos:** **ZH8a** (`get_current_user` no mira `is_active`) → AH8. **ZH8b** (`suspender` no desactiva la membresía) → OH8.

### H-11 · El archivo de credenciales nace cerrado y nunca dentro de un repo
- **Permisos:** el archivo se crea con `os.open(ruta, O_WRONLY | O_APPEND | O_CREAT, 0o600)`: nace con el permiso restringido, en vez de nacer con el umask y cerrarse después. (En Windows el modo no restringe; en el servidor, sí.)
- **`--salida` se rechaza si cae dentro de CUALQUIER repositorio git** (se busca `.git` desde la carpeta del archivo hacia arriba), además del repo del backend. Salida 2 antes de escribir nada.
- **Decisión: sin excepción para rutas ignoradas.** Saber si una ruta está ignorada exige ejecutar git y confiar en un `.gitignore` que puede cambiar mañana. Lo simple y seguro es que las contraseñas nunca vivan dentro de un repo. **Consecuencia para el operador:** `ENGRAMA/despliegue/salida/` deja de servir como destino desde el equipo (toda `INGLES/` es un repo); dentro del contenedor del despliegue no hay `.git`, así que su volumen sigue sirviendo. Aviso a ARQUITECTO.
- **Criterio (UH11, no-integ):** `anotar` crea el archivo llamando a `os.open` con modo `0o600` y, donde el sistema lo respeta (POSIX), el archivo queda en `0o600`; `dentro_de_un_repo` es verdadero para una ruta bajo una carpeta con `.git` (en un directorio temporal), para una dentro del backend y para una subcarpeta ignorada, y falso para una ruta sin `.git` arriba.
- **Tramposos:** **ZH11a** (el `open("a")` de hoy) y **ZH11b** (la guarda de hoy, solo el backend) → UH11.
- OP5 (`--salida` dentro del repo → 2) no cambia.

### H-12 · Fórmulas en el CSV de credenciales
- Al escribir, todo campo que empiece por `=`, `+`, `-`, `@`, tabulador o retorno de carro recibe un `'` delante. Un nombre como `=HYPERLINK(…)` ya no se ejecuta al abrir el archivo en Excel.
- La contraseña temporal nunca empieza por esos caracteres (su alfabeto son letras y dígitos).
- **Criterio (UH12, no-integ):** nombres y correos que empiezan por cada uno de los seis quedan con `'`; uno normal queda igual; la contraseña queda igual. **Tramposo ZH12:** sin neutralizar → UH12.

### H-13 · Versiones del aviso permitidas
- Configuración nueva **`AVISO_VERSIONES_VALIDAS`**: lista separada por comas (p. ej. `2026-10-v1`).
- Con la lista puesta, `POST /auth/consentimiento` y `POST /auth/registro` (`aviso_version`) aceptan **solo** una versión de la lista; cualquier otra → **422 `{"detail": "aviso_version_no_permitida"}`**, sin escribir. En el registro va antes del límite de intentos y del código: depende solo del cuerpo y de la configuración.
- **Con la lista vacía no hay restricción** (lo de hoy): así el desarrollo y los tests existentes no cambian. **El despliegue debe ponerla**; sin ella, H-13 sigue abierto. Va al checklist de `PRODUCCION_030.md`.
- **Aviso a ARQUITECTO:** la lista debe contener el `AVISO_VERSION` del cliente. Si no la contiene, **nadie puede aceptar el aviso y nadie entra**. Al cambiar de versión: primero se agrega la nueva a la lista del backend y después se cambia el cliente.
- **Criterio (CN6, integ):** con la lista `v-a, v-b`: `v-a` → 200; `v-c` → 422 y 0 filas; el registro con `v-c` → 422 y 0 perfiles, y con `v-b` → 201. Con la lista vacía, `v-c` → 200. **Tramposo ZH13:** la validación siempre dice que sí → CN6.

### H-19 · El bloqueo por contraseña temporal, en TODAS las rutas
- **Criterio (AH19, integ):** un usuario con `force_password_reset = true` llama por HTTP a **cada** `(ruta, método)` registrado en la app, con los parámetros de ruta rellenados con valores sintéticos y sin cuerpo:
  - las rutas **sin** `get_current_user` (públicas) se listan y se comparan con el conjunto exacto esperado (`/health` y `POST /auth/registro`);
  - los 4 pares permitidos **no** dan 403 `must_change_password`;
  - **todas las demás** dan exactamente 403 `must_change_password`.
- El test recorre `app.routes`: una ruta nueva entra sola. Si una ruta nueva no pasa por `get_current_user`, el test falla hasta que alguien la declare pública a propósito.
- **Tramposos:** **ZH19a** (`puede_con_contrasena_temporal` siempre verdadero) y **ZH19b** (una ruta autenticada sin `get_current_user`: se agrega una `APIRoute` sintética) → AH19.
- No cambia código de `src/`.

### H-7 · El backend entra con un rol que se salta la RLS (solo documento)
- **Qué pasa:** el backend se conecta como `postgres`, que tiene `BYPASSRLS`. Las 51 políticas y la 031 protegen el acceso **directo** de clientes; el aislamiento entre instituciones **dentro del backend** depende solo de los `WHERE tenant_id = …` de cada consulta. Un `WHERE` olvidado es una fuga, y la RLS no la detendría.
- **Lo que lo cubre hoy:** los tests de aislamiento por ruta (A7, AP6, los `*_ab_404`, y en esta tanda AR6, AR11 y SD5) y la barrera de grupo en una sola fuente (`access.py`, ERR-26).
- **Plan (deuda, sin fecha; va a `PRODUCCION_030.md`):**
  1. un rol `engrama_app` con `NOBYPASSRLS` y sin ser dueño de las tablas;
  2. `get_db` fija por transacción `SET LOCAL app.tenant_id` y `app.profile_id` con lo que resolvió `get_current_user`;
  3. políticas para ese rol sobre esas variables (las de hoy usan `auth.uid()`, pensado para clientes);
  4. las rutas sin usuario (registro, eventos del anillo) y las migraciones siguen con un rol aparte;
  5. se mide con la suite entera corriendo como `engrama_app`: lo que falle es un `WHERE` que hoy sostiene solo.
- Es la ADR-003, que sigue sin decidir. **No bloquea el piloto** (la auditoría lo marca MEDIO y "después").

### El intermitente del reloj
- Los actores de prueba que tienen dos membresías fijan `created_at` **explícito**: la de la primera institución, un día antes. Así "la más antigua" no depende de que dos `now()` seguidos salgan en orden.
  - `integ.afiliar` y `integ.crear_perfil` ganan un parámetro opcional `creada_hace`; `_actores.armar` lo usa para D;
  - OP4, HP1 y RP1 envejecen por SQL las membresías de la primera institución antes de dar de alta la segunda (`tests/integ/_login_piloto.py` y `tests/onboarding/test_alta.py`).
- **Criterio (UR-reloj, integ):** después de `armar`, la membresía de D en A es al menos 1 hora más antigua que la de B, y `/auth/me` de D sin encabezado da A en 5 llamadas. **Tramposo ZH-reloj:** `afiliar` ignora `creada_hace` → rojo (la diferencia es de milisegundos).
- **No cambia código de `src/`.** El orden de producción sigue dependiendo del reloj de la base, lo que queda como deuda declarada en `ESPEC_login_piloto.md` §10.

## 2. Qué NO se toca
`RUTAS_CON_CONTRASENA_TEMPORAL`, UP3, `ProfileOut`, las migraciones (no hay ninguna nueva), `ENGRAMA/despliegue/`, `.venv` ni Docker.

## 3. Tests y tramposos
| Punto | Tests | Tramposos | Archivo |
|---|---|---|---|
| H-10 | UJ1 (no-integ) | ZH10 (no-integ) | `tests/auth/test_jwt_requeridos.py` |
| H-8 | AH8 y OH8 (integ) | ZH8a y ZH8b (integ) | `tests/auth/test_suspension.py` |
| H-11 | UH11 (no-integ) | ZH11a y ZH11b (no-integ) | `tests/onboarding/test_salida_unit.py` |
| H-12 | UH12 (no-integ) | ZH12 (no-integ) | el mismo |
| H-13 | CN6 (integ) | ZH13 (integ) | `tests/auth/test_aviso_versiones.py` |
| H-19 | AH19 (integ) | ZH19a y ZH19b (integ) | `tests/auth/test_todas_las_rutas.py` |
| Reloj | UR-reloj (integ) | ZH-reloj (integ) | `tests/teachers/test_actores_reloj.py` |

Cada tramposo vive en el archivo de su test (son pocos por punto) y sigue el patrón de siempre: se rompe la pieza en el módulo donde se usa y se exige `AssertionError` con el mecanismo.

**Cruces predichos** (ERR-23):
- ZH8a × AH19: verde (AH19 no suspende a nadie). ZH19a × AP9 y HP1: rojos por aserción (es el ZP7 del login piloto); no se corren aquí.
- H-10 × los 13 de `tests/auth`: verdes (sus tokens traen los tres claims). Si alguno fabrica un token sin `aud`, es una edición a declarar.
- H-11 × OP1-OP8, HP1 y RP1: verdes **si** `tmp_path` no cuelga de un repo git. **Se mide antes del commit**; si cuelga, se corrige esta espec primero.
- H-13 × CN1-CN5, HC1, RC1 y los AR: verdes (lista vacía en los tests).

## 4. Cuentas (ERR-10)
| Punto | integ | no-integ |
|---|---|---|
| H-10 | — | 1 + 1 |
| H-8 | 2 + 2 | — |
| H-11 | — | 1 + 2 |
| H-12 | — | 1 + 1 |
| H-13 | 1 + 1 | — |
| H-19 | 1 + 2 | — |
| Reloj | 1 + 1 | — |
| **Nuevos** | **11** | **7** |

- **passed:** 435 + 11 + 7 = **453**; **skipped:** **17**; **no-integ:** 118 + 7 = **125**; ruff 0 y mypy 0.
- Por commit, en el orden de §5: 437 (H-10), 441 (H-8), 444 (H-11), 446 (H-12), 448 (H-13), 451 (H-19) y 453 (reloj).

### Medido (2026-10-06)
- **Cada tramposo, rojo por su razón** (la diagonal de §3, automatizada): ZH10, ZH8a, ZH8b, ZH11a, ZH11b, ZH12, ZH13, ZH19a, ZH19b y ZH-reloj.
- **H-10, antes del arreglo:** UJ1 dio `{'completo': 200, 'sin_exp': 200, 'sin_aud': 200, 'sin_sub': 401}`: el token sin `exp` y el token sin `aud` entraban, como midió la auditoría.
- **H-19:** con contraseña temporal, **todas** las rutas autenticadas dan 403 `must_change_password` salvo los 4 pares; las públicas son exactamente `/health` y `POST /auth/registro`. No apareció ninguna ruta sin bloquear.
- **H-11:** `tmp_path` no cuelga de un repo git en esta máquina; OP1-OP8 y HP1 siguen verdes, como estaba condicionado.
- **Suite completa** (un contenedor de pruebas propio, como en el autorregistro): **452 passed + 1 failed + 17 skipped**, y 125 no-integ; `ruff` 0 y `mypy` 0. El fallo era el tramposo existente ZP15 (abajo). Con su corrección, el archivo de tramposos del login piloto pasa entero; **la cifra 453 sale de 452 más ese test, y la suite completa se vuelve a medir al cerrar la tanda** (`ESPEC_eventos_anillo.md`).
- **Las cifras por commit de §4 (437, 441…) NO se midieron una por una:** en cada commit se corrieron los tests del punto, los que comparten archivos y la suite no-integ.

**Errata (ERR-26, reincidencia; candidato a ERR): H-10 dejó sin efecto a un tramposo existente.**
- **Qué pasó:** ZP15 del login piloto ("`validate_jwt` sin verificar `exp`") apaga `verify_exp` en el `jwt` de python-jose. Con `require_exp`, python-jose **vuelve a encender** `verify_exp` (un claim obligatorio siempre se verifica), así que el tramposo ya no rompía nada y dio `DID NOT RAISE`.
- **Por qué no lo previó esta espec:** §3 cruzó H-10 con los 13 tests de `tests/auth`, pero no enumeró con `git grep` los tramposos que parchean `validate_jwt` o su `jwt` (la regla 2 de ERR-26).
- **Qué se editó:** ZP15 apaga también `require_exp` (`fix(test)`, commit aparte). El criterio no cambió: AP2 debe ponerse rojo si `exp` no se verifica, y se pone. ZP14 (sin firma) no se vio afectado.

**Otra precisión:** el `suspender` de la CLI audita también cuando se repite (3 filas `cuenta_suspendida` en OH8: dos de la misma persona y una de `--solo-institucion`). Es idempotente en el estado, no en la auditoría.

## 5. Plan de commits
1. `docs`: esta espec.
2. `fix(auth)`: H-10.
3. `feat(auth)`: H-8 (el 403 y las órdenes `suspender` y `reactivar`).
4. `fix(onboarding)`: H-11.
5. `fix(onboarding)`: H-12.
6. `feat(auth)`: H-13.
7. `test(auth)`: H-19.
8. `test`: el reloj.
9. `docs`: H-7 y el checklist en `PRODUCCION_030.md`, y lo medido.

## 6. Variables y avisos
- **Nueva:** `AVISO_VERSIONES_VALIDAS` (backend).
- **Para ARQUITECTO:** ponerla igual al `AVISO_VERSION` del cliente; `--salida` fuera de cualquier repo; el cliente debe mostrar un mensaje para 403 `account_suspended`.

## 7. Para después
El bloqueo en GoTrue al suspender; revocar sesiones; una ruta HTTP para que el admin suspenda (hoy es del operador); el rol sin `BYPASSRLS` (H-7); un tope de versiones del aviso por persona cuando la lista está vacía.

## 8. Veredicto
- **FUNCIONA:** las cuentas de §4, cada tramposo en rojo por su razón y los previos verdes.
- **NO:** un token sin `exp` entra; un suspendido entra a alguna ruta; el archivo de credenciales se puede escribir dentro de un repo; una fórmula llega intacta al CSV; con la lista puesta entra otra versión; una ruta autenticada responde con contraseña temporal fuera de las 4; un tramposo queda verde.
