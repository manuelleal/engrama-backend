# ESPEC · S-7 hasta el final: ningún fallo del registro deja una cuenta de GoTrue huérfana

F4 · Creador · 2026-10-20 · **preregistro** (se commitea antes del código). Rama `seg/confirmar` (worktree propio), sobre `f7f7aeb` (no-integ **208**; ruff 0; suite 768 passed + 24 skipped según su commit). **Sin migración. No se despliega antes del 22-oct.**

Origen: `investigacion/seguridad/03-auditoria-autorregistro-y-eventos-2026-10-07.md` S-7 y `ENGRAMA/despliegue/LEEME_piloto.md` §12.1 punto 9, que lo dan por **abierto**.

## 0. Leído y medido antes de tocar nada (2026-10-20, sobre `f7f7aeb`)

### 0.1 Lo que S-7 decía ya está cerrado desde `656b2f0` (2026-10-08)
- **Qué es `_confirmar`** (`src/registro/service.py:274-295`): la **segunda transacción (T2)** del registro público `POST /auth/registro`. La llama `registrar` después de que GoTrue creó la cuenta con `id = profiles.id`. Escribe: la solicitud de `creando` a `pendiente`, el consentimiento del aviso y una fila de `audit_logs` (`registro_solicitado`). COMMIT.
- **El hueco que describía la auditoría:** `await _confirmar(...)` iba sin `try`. Si T2 fallaba, la cuenta quedaba creada y el perfil en `creando`: el estudiante entra a "espera a tu profe" y el profe nunca lo ve (`decision.listar` solo muestra `pendiente`). Respuesta 500.
- **Cerrado en `656b2f0`** (`ESPEC_autorregistro.md` §11.1): `registrar` llama a `_confirmar_o_deshacer` (`service.py:298-329`), que ante **cualquier** excepción hace ROLLBACK, borra la cuenta, borra el perfil, devuelve el uso y responde 502. Test **AR12** y tramposo **ZR24** (el código de antes). `f7f7aeb` lo trae y es el backend del piloto.
- **Corrido hoy en este worktree, contra una base propia** (`engrama-test-pg-s7`, 127.0.0.1:55437): AR12 **verde**, ZR24 **rojo por su razón** (el tramposo pone 500 y deja la cuenta), ZR14 rojo. **El LEEME está desactualizado en ese punto** (candidato a ERR: un documento de despliegue dice abierto lo que el código cerró hace 12 días).

### 0.2 Lo que sigue abierto de la MISMA promesa ("no queda una cuenta sin solicitud visible")
Sonda exploratoria fuera del repo, con el doble `CuentasFalsas` y la base propia:

| # | Camino | Medido hoy | ¿Síntoma de S-7? |
|---|---|---|---|
| R1 | `crear` falla con algo que **no** es `ErrorCuenta` después de que GoTrue creó la cuenta (un 2xx con cuerpo ilegible: `r.json()` lanza `ValueError`; un defecto del adaptador) | **500**; cuenta viva; perfil en `creando`; usos 1; lista del profe `[]`. Reintento inmediato: **201 "pendiente"** y la lista sigue `[]` | **Sí, exacto** |
| R3 | T2 falla **y** GoTrue no deja borrar (doble fallo), o el proceso muere entre `crear` y T2 | 502; cuenta viva; `creando`. Reintento antes de 60 s: **201** y lista `[]`. Se recoge solo si alguien reintenta ese documento después de `HUERFANO_S` | Sí, pero es la regla "falla cerrado" de §1.5, hecha a propósito |
| R4 | GoTrue ignora el `id` pedido (P0 roto, p. ej. al cambiar de versión) | 502; la compensación borra el id pedido (404 = ok) y la cuenta **real**, con otro id, queda con el correo. Reintento: 201 (por "correo en uso") y lista `[]` | Sí |
| R5 | `CancelledError` en la ventana | No alcanzable con el despliegue de hoy: uvicorn sin `--timeout-graceful-shutdown` no cancela peticiones en vuelo y no hay middleware que cancele al desconectarse el cliente (`src/main.py` no registra ninguno) | — |

**No es un ataque**: ningún camino lo dispara un visitante a voluntad. Es integridad ante fallos: el riesgo al abrir a internet es que un fallo raro deje a un estudiante esperando para siempre sin que nadie lo vea.

## 1. Qué cambia (una cosa)
**El paso de GoTrue del registro (`crear` la cuenta) se compensa ante CUALQUIER excepción, no solo ante `ErrorCuenta`** (cierra R1). Es la misma regla que `656b2f0` puso a T2 ("cualquier fallo aquí deja la misma cuenta huérfana"), llevada al paso anterior.

- `src/registro/service.py`: nueva `_crear_cuenta_o_deshacer(db, cuentas, reserva, datos) -> str`, gemela de `_confirmar_o_deshacer`. Llama a `_crear_cuenta`; si sale **cualquier** `Exception`: registra el fallo, `_deshacer(puede_haber_cuenta=True)` (borrar es idempotente: un 404 cuenta como borrada) y lanza `RegistroNoDisponible` (502). `registrar` la llama en lugar del `try/except ErrorCuenta` de hoy.
- El log: con `ErrorCuenta`, el mensaje de siempre (no lleva claves ni contraseñas, `onboarding/cuentas.py`); con cualquier otra, **solo el nombre del tipo** (el texto de una excepción ajena puede traer el correo).
- `CancelledError` y demás `BaseException` no se atrapan (R5).

## 2. Qué debe pasar, medible

| # | Criterio | Test |
|---|---|---|
| C50 | Con un doble cuyo `crear` **crea la cuenta y luego lanza `ValueError`** (con el correo dentro del mensaje): **502 `registro_no_disponible`**; el doble recibió `borrar(id del perfil)`; 0 cuentas, 0 perfiles, 0 solicitudes, `usos = 0`; **el correo no aparece en los logs**. Reintento ya sin el fallo: **201** y una solicitud `pendiente` que **sí** está en la lista del profe. Y si además `borrar` falla: 502, la cuenta queda, la solicitud queda en `creando`, `usos = 1` y la lista del profe vacía (falla cerrado, §1.5) | **AR30** |

**Cómo sabremos que FALLÓ:** AR30 rojo. Con el código de hoy la primera respuesta es `(500, None)` y la cuenta queda.

**Tramposo ZR50** (integ): `_crear_cuenta_o_deshacer` protege solo `ErrorCuenta` (el código de hoy). Rojo predicho: **AR30**, con `AR30: {'inesperado': {'respuesta': (500, None), 'borrar_la_cuenta_del_perfil': False, 'cuenta': True`. Verde predicho: el resto (AR8, que usa `ErrorCuenta`, no cambia).

Los números saltan a AR30, C50 y ZR50 a propósito: la rama paralela `seg/limites-registro` ya reservó ZR37 a ZR43 y otra (`seg/pase-acotado`) está abierta; así no chocan al juntarlas. Test y tramposo van en archivos nuevos (`tests/registro/test_confirmar_protegido.py`, `tests/tramposos/test_tramposos_confirmar.py`) por la misma razón.

## 3. Qué NO se toca
- `_confirmar`, `_confirmar_o_deshacer`, `_deshacer`, `_recoger_huerfano`, `HUERFANO_S`, el router, el piso de tiempo, el límite (lo lleva `seg/limites-registro`), `onboarding/cuentas.py`, la base y las migraciones.
- La respuesta pública: 502 `registro_no_disponible` ya existe (AR8, AR12); no hay código ni texto nuevo para la web.
- Ningún test existente se edita.

## 4. Humo, réplica y cuentas predichas (ERR-10)
- **Humo:** no hay corrida grande nueva. El humo de la pieza, **HA1** (`tests/integ/test_humo_autorregistro.py`), se corre como regresión y debe escribir `tests/_salida/humo_autorregistro.json` con su contenido exacto de siempre.
- **Réplica** (fuera del repo, entradas nuevas): `crear` revienta con `KeyError` y con `AttributeError` (no `ValueError`), en otra institución, con la persona 7 y el correo en mayúsculas: 502, 0 cuentas, `usos = 0` y reintento 201.
- **Cuentas predichas:** no-integ **208** (sin cambio: los dos tests nuevos son integ); suite completa **770 passed + 24 skipped** (768 + AR30 + ZR50); ruff 0. Rojo predicho con el tramposo: solo AR30.

## 5. Para después (no se toca ahora)
- **R4:** en `GoTrueAdmin.crear`, si GoTrue devolvió otro id, borrar ESE id antes de lanzar. Hoy lo frena que GoTrue va fijado en `v2.196.0` (P0 medido); quien suba GoTrue debe repetir P0.
- **R3:** un reintento antes de `HUERFANO_S` recibe 201 aunque el registro anterior murió; el estudiante deja de reintentar y nadie lo recoge. Opciones: recolector periódico de `creando` viejos, o mostrárselos al profe. Es diseño (toca la respuesta uniforme de S-5): decisión del arquitecto.
- La compensación del paso de GoTrue, si la base falla al borrar el perfil, sigue respondiendo 500 (la cuenta ya se borró: no hay huérfana, solo el código de estado). `_confirmar_o_deshacer` sí la convierte en 502.
- `LEEME_piloto.md` §12.1 punto 9 y §14.12 punto 3: corregir "S-7 abierto".

## 6. Medido (2026-10-20/21, código en `cd0f362`)
Todo con la base propia `engrama-test-pg-s7` (127.0.0.1:55437): un plugin local, fuera del repo, cambia el nombre y el puerto de `tests/integ_db.py` para no borrar `engrama-test-pg`, que usaba la rama paralela. Nunca contra el piloto.

| Qué | Predicho | Medido |
|---|---|---|
| Suite completa antes (`f7f7aeb` + espec) | 768 + 24 | **768 passed + 24 skipped** (56 min) |
| AR30 con el código de antes | rojo, `(500, None)` y la cuenta viva | **rojo**: `(500, None)`, cuenta viva, `creando`, usos 1; reintento 201 y lista del profe **0**. Con `borrar` fallando, también 500 |
| AR30 con el código nuevo | verde | **verde** |
| ZR50 (tramposo) | AR30 rojo con su mensaje | **rojo por su razón** (el test del tramposo pasa) |
| AR12, ZR24, ZR14, AR8 | sin cambio | verdes / rojos como siempre |
| Réplica (`KeyError`, `AttributeError`; otra institución, persona 7, correo en mayúsculas, nombre con tildes) | 502, 0 cuentas, usos 0, reintento 201 | **2/2**: exactamente eso, y la lista del profe con 1 |
| Humo HA1 | escribe su archivo con el contenido de siempre | escrito, **idéntico** a `HUMO_ESPERADO` |
| No-integ | 208 | **208** |
| ruff | 0 | **0** |
| Suite completa después | 770 + 24 | **769 passed + 1 failed + 24 skipped** (48 min). El que falló: **AR18** (medición de tiempo del piso) |

**AR18 no lo rompió este cambio**, es la carga de la máquina: durante la corrida había al menos cuatro worktrees del backend con agentes en paralelo (`limites-registro`, `lote`, `opcion`, `pase`). Las medianas sin piso salieron de 322 a 759 ms para `creado` (lo normal es unos 70). **El código de antes (`78cc159`, en un worktree temporal) falló AR18 igual en ese momento** (dispersión con piso: 352,7 ms). Con menos carga, `test_piso.py` entero pasa con el código nuevo (**3 passed**). Cuenta real: 770 de 770 con la máquina tranquila; no se repitió la suite entera en ese estado.

Candidatos a ERR, para el coordinador: (1) `LEEME_piloto.md` da S-7 por abierto 12 días después de cerrarlo; (2) `tests/integ_db.py` fija el nombre y el puerto del contenedor: dos agentes que corran integración a la vez se borran la base el uno al otro (aquí se esquivó con el plugin local); (3) AR18 es un test de tiempo que se pone rojo con la máquina cargada.
