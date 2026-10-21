# ESPEC · El límite del registro compartido entre procesos (S-3, lo que faltaba)

Creador · 2026-10-20 · preregistro. Rama `seg/limites-registro`, desde `f7f7aeb` (la del piloto; meta de partida **768 passed + 24 skipped, 208 no-integ, ruff 0**, `ESPEC_humo_reto_del_dia.md` §6). Origen: `ENGRAMA/despliegue/LEEME_piloto.md` §12.1 punto 2 (S-3 de la auditoría `investigacion/seguridad/03`) y `TABLERO.md` ("S-3 resto"). **No se despliega antes del 22-oct. No se toca el piloto.**

## 0. Medido y leído antes de tocar nada (sobre `f7f7aeb`)
El encargo pide tres cosas (a, b, c). Dos de ellas **ya están en el código** desde el 2026-10-08 y el §12.1 del LEEME no lo refleja (es texto viejo; candidato a corregir en el despliegue, no aquí):

| Pedido | Estado en `f7f7aeb` | Dónde |
|---|---|---|
| (a) IPv6 por /64, IPv4 por dirección completa | **Hecho** (`492f076`, ESPEC_autorregistro §11.2). UL3 lo prueba y ZR28 lo pone rojo | `src/registro/limite.py:47-66` (`_agrupar`) |
| (c) que una avalancha anónima no bloquee a todos | **Hecho** (`33a0796`, §11.3): `POR_CODIGO` y `GLOBAL` solo cuentan intentos con un código de grupo **válido**; los códigos inventados solo gastan los cupos de su IP. AR13 lo prueba y ZR25 lo pone rojo | `limite.py:170-188` (`anotar_codigo`), `router.py:113-127` |
| (b) que el tope no dependa del número de procesos | **Abierto.** Los cuatro contadores (`POR_IP` 150, `MALOS_POR_IP` 60, `POR_CODIGO` 200, `GLOBAL` 1000) son `deque` en la memoria de cada proceso. El backend corre con `--workers 2` (`despliegue/backend/Dockerfile:35`): cada tope vale hasta el doble, y el guion de medición lo tolera (`autorregistro_lib.mjs:123-124` acepta el primer 429 entre el intento 61 y el 121) | `limite.py:3-4`, `:157-161`; §11.4 lo dejó "documentado, sin cambio" |
| (b') las 20.000 llaves | **Abierto** (§11.3 "Sigue abierto"): cada contador falla cerrado al llenarse de llaves vigentes; quien controle 20.000 IPv4 o redes /64 deja sin registro a toda IP nueva durante la ventana | `limite.py:105-110` |
| Login (`POST /auth/v1/token`) | **No es del backend.** Lo limita GoTrue (`GOTRUE_RATE_LIMIT_TOKEN_REFRESH`, cubo en la memoria de GoTrue), que corre en **un solo proceso** (un contenedor, sin `replicas`): no se duplica. Su llave es `X-Forwarded-For`, que Caddy sobrescribe con `{remote_host}` **completo**: una IPv6 que rota dentro de su /64 sí evade el límite del login. Eso se arregla en Caddy/GoTrue (despliegue), no aquí. §7 | `despliegue/docker-compose.yml:96-106`, `despliegue/Caddyfile` (bloque `@gotruePermitido`) |

No hay Redis en el despliegue (`config.py:192` lo declara "no usado todavía"; `docker-compose.yml` no lo trae). Lo único compartido por los dos procesos es **Postgres**.

## 1. Qué cambia (una cosa)
**Los cuatro contadores del registro guardan sus eventos en una tabla de Postgres (`limite_intentos`) en vez de en la memoria del proceso.** Mismos topes, misma ventana deslizante de 600 s, mismas llaves (IPv6 por /64, la huella del código, `todos`), mismo orden de revisión, mismo `Retry-After`. Lo que cambia es que dos procesos (o diez, o un reinicio) ven el mismo conteo.

### 1.1 Por qué una tabla en Postgres y no otra cosa
| Opción | Por qué no / por qué sí |
|---|---|
| Un solo worker (`--workers 1`) | Es del despliegue, no del backend; y deja el límite en cero en cada reinicio. Tampoco cierra las 20.000 llaves |
| Redis | No existe en el despliegue: sería un servicio nuevo que mantener, respaldar y vigilar, para un tráfico de registro que es de cientos por día |
| Límite en Caddy | Caddy no trae limitador sin un módulo de terceros; y no sabe si el código de grupo era válido (lo que pide c) |
| **Tabla en Postgres** | Ya la ven los dos procesos, ya está en el despliegue, el backend ya habla con ella por `get_db`. El costo es una transacción corta por intento, en una ruta de poco tráfico |

### 1.2 La tabla (migración `046_limite_compartido`, aditiva)
```
CREATE UNLOGGED TABLE limite_intentos (
  id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  contador TEXT NOT NULL CHECK (contador IN ('por_ip','malos_por_ip','por_codigo','global')),
  llave    TEXT NOT NULL,              -- HMAC-SHA256 en hex, nunca la IP ni el código
  momento  DOUBLE PRECISION NOT NULL   -- segundos (reloj del backend, time.time)
);
índices: (contador, llave, momento) para contar; (contador, momento) para purgar.
RLS activo y SIN políticas (como 045): nadie de afuera la lee; el backend entra como dueño.
```
- **`UNLOGGED`:** es estado efímero (10 minutos). No escribe WAL (barato bajo avalancha) y si Postgres se cae sin apagarse bien, la tabla vuelve vacía: el límite arranca en cero, lo mismo que hoy pasa con cada reinicio del backend.
- **La llave se guarda con HMAC** (`hmac(derivada del secreto JWT con la etiqueta "engrama-limite-registro-v1", "<contador>|<llave>")`). Hoy las IP viven solo en memoria; al pasarlas a una tabla entrarían en el respaldo diario (7 días de retención, §12.1 punto 3). Con la huella, ni la base ni el respaldo guardan direcciones. La misma llave en los dos procesos da la misma huella (mismo secreto).
- **Downgrade:** `DROP TABLE IF EXISTS limite_intentos`. Se prueba up/down/up (MG46).

### 1.3 El algoritmo, igual que hoy
- `espera(llave)`: cuenta los eventos de ese contador y esa llave con `momento > ahora - 600`; si son menos que el tope → 0; si no → `max(1, ceil(más_antiguo + 600 - ahora))`. Es la cuenta de `Limitador.espera` (se saca a una función pura que usan los dos, `_segundos_de_espera`; UL1 la sigue probando).
- `revisar + anotar POR_IP` van en **una sola transacción con candado por IP** (`pg_advisory_xact_lock(hashtextextended('registro:por_ip:<llave>', 0))`): dos peticiones simultáneas de la misma IP, en el mismo proceso o en dos, se ponen en fila. Hoy, en memoria, `revisar` y `anotar` no tienen un `await` entre medio y por eso son atómicos dentro de un proceso; con la base hay `await` y sin candado una ráfaga pasaría toda junta.
- `MALOS_POR_IP`, `POR_CODIGO` y `GLOBAL` se **revisan** dentro de esa transacción y se **anotan después** de consultar el código (como hoy, §11.3). Su exceso por peticiones en vuelo sigue declarado: lo acota `POR_IP` (a lo sumo 150 por IP en vuelo).
- **Candado ocupado:** `SET LOCAL lock_timeout = '2000ms'`. Si no se obtiene en 2 s → **429 `demasiados_intentos` con `Retry-After: 5`** (falla cerrado, sin 500 y sin dejar la conexión colgada).
- **Purga:** cada contador, al anotar, borra sus filas vencidas como mucho una vez por minuto por proceso (`DELETE ... WHERE contador = :c AND momento <= ahora - 600`).
- **Sin tope de llaves:** las 20.000 llaves por contador desaparecen (eran memoria, no seguridad: su "falla cerrado" era el ataque). El tamaño queda acotado por el propio límite: a lo sumo 150 filas `por_ip` + 60 `malos_por_ip` por origen y ventana, y `por_codigo`/`global` solo con códigos válidos.
- **El reloj** es `time.time()` (el de pared: los dos procesos están en el mismo anfitrión). Se inyecta por contador (`reloj`), como hoy.
- Las funciones de `limite` que tocan la base pasan a `async` y reciben el motor de la base (`db.bind` de la sesión de la ruta; cada operación del límite usa **su propia** conexión y transacción, independiente de la del registro, que hace sus propios `commit`/`rollback`).
- `reiniciar()` sigue existiendo (síncrona) y solo pone en cero lo del proceso (el calendario de purga). Vaciar la tabla es `vaciar(motor)` (pruebas y operación).

## 2. Criterios (medibles)
| # | Criterio | Test |
|---|---|---|
| C1 | **(a) en la ruta y en la tabla compartida:** con `PROXIES_DE_CONFIANZA = 1`, 61 códigos malos desde 61 direcciones DISTINTAS del mismo /64 (`2001:db8:a:b::<i>`) → sesenta 403 y el 61 **429** con `Retry-After > 0`; enseguida, desde otro /64 → 403; en la tabla: 2 llaves `por_ip` y 60 filas `malos_por_ip` | LC1 |
| C2 | **(c) avalancha:** con `GLOBAL.tope = 5`, 40 códigos inventados desde 40 orígenes distintos (20 IPv4 y 20 redes /64) → cuarenta 403, **0 filas** `global` y **0** `por_codigo`; enseguida, desde IPs nuevas, 2 registros con el código del grupo B y 2 con el del grupo C → **201** los cuatro; un quinto válido → 201; el sexto → **429** con `Retry-After` (el techo sigue vivo para lo que sirve); al final 2 llaves `por_codigo` y 5 filas `global` | LC2 |
| C3 | **(b) dos procesos:** dos procesos del sistema operativo, cada uno con su propio motor contra la misma base, hacen a la vez 30 `tomar` concurrentes desde direcciones distintas del mismo /64, con `POR_IP.tope = 10` y una pausa de 20 ms entre revisar y anotar (la misma en el bueno y en los tramposos, para que una carrera se vea): **10 admitidos en total** (no 20), 10 filas `por_ip` en la tabla; y además cada proceso anota 3 códigos válidos: 6 filas `global`, y desde el proceso de la prueba `GLOBAL` con tope 5 da espera > 0. Los dos procesos salen con 0 | DP1 |
| C4 | **Candado ocupado:** con el candado de una IP tomado desde otra conexión y `lock_timeout` de 200 ms, un registro desde esa IP → **429** `demasiados_intentos` con `Retry-After: 5` (no 500); soltado el candado → 403 (código malo) | LC3 |
| C5 | **La llave guardada (pura):** misma entrada → misma huella; otro contador → otra huella; 64 caracteres hex; ni la IP ni la red aparecen en ella | UL4 |
| C6 | **Migración:** sube, baja y vuelve a subir idéntica; la tabla es `UNLOGGED`, con RLS y 0 políticas, sus 2 restricciones (`pkey`, `contador_check`) y sus 3 índices; al bajar desaparece | MG46 |
| C7 | **Humo:** por la ruta real, un registro válido y un código malo desde el mismo /64, y uno desde una IPv4: escribe `tests/_salida/humo_limite_compartido.json` ANTES de afirmar, con las filas por contador leídas de la tabla y la confirmación de que ninguna llave contiene una IP | HLC1 |
| C8 | **Réplica** con entradas nuevas (otro /64, una IPv4 envuelta en IPv6, otro grupo y otra institución): el mismo veredicto | RLC1 |
| C9 | **Regresión = identidad:** UL1, UL2, UL3, AR10, AR13 y todo `tests/registro` dan lo mismo que en `f7f7aeb`, con sus afirmaciones intactas (solo cambia la plomería, §4) | los existentes |

## 3. Tramposos (cómo sabremos que falló)
| # | Rompe | Test que debe ponerse rojo | Rojo predicho (mensaje) |
|---|---|---|---|
| ZR37 | la llave se guarda en claro (`_llave_guardada` devuelve `"<contador>\|<llave>"`) | UL4 | la IP aparece / no es hex de 64 |
| ZR38 | `_agrupar` devuelve la dirección tal cual (sin /64) | LC1 | `'el_61': (403, ...` |
| ZR39 | `anotar_codigo` anota siempre, sin mirar si el código servía (el código de antes de `33a0796`) | LC2 | `'basura': [403, 403, 403, 403, 403, 429` |
| ZR40 | el candado ocupado no se trata (`_es_candado_ocupado` → `False`) | LC3 | `'con_candado_tomado': (500` |
| ZR41 | los contadores guardan en la memoria del proceso (el código de hoy, dentro de cada proceso hijo) | DP1 | `'admitidos': 20` |
| ZR42 | sin candado (`_candado` no hace nada) | DP1 | `'admitidos':` mayor que 10 (predicho 60: todos) |
| ZR43 | la bajada de 046 no hace nada (`SQL_BAJAR = ()`) | MG46 | `'la_tabla': {'existe': True` |

Cada tramposo se corre con su test y debe dar `AssertionError` con ese mensaje; el código bueno, verde.

## 4. Ediciones a lo existente (ERR-25), declaradas antes
- `tests/integ_db.py` `HUMO_ESPERADO`: `alembic_version` → `046_limite_compartido`; `tablas_con_rls` 46 → **47**. `politicas_public` no cambia (51).
- `tests/registro/_ayuda.py`: `preparar` vacía la tabla (`vaciar_limite(integ)`) además de `limite.reiniciar()`; ayudas nuevas `vaciar_limite(integ)` y `llaves(integ, contador)`.
- `tests/registro/test_limite.py` (AR10): los dos `limite.reiniciar()` de en medio pasan a `ay.vaciar_limite(integ)` (antes vaciaban la memoria; ahora la tabla). Las afirmaciones no cambian.
- `tests/registro/test_auditoria03.py` (AR13): `limite_mod.POR_CODIGO.llaves()` → `ay.llaves(integ, limite_mod.POR_CODIGO)`. Las afirmaciones no cambian.
- `tests/tramposos/test_tramposos_autorregistro.py`: **ZR3** (`revisar` → 0) y **ZR25** (`anotar_codigo` sin mirar) ajustan su firma a la nueva (`async`, con la conexión o el motor). Predicción: siguen rojos con su **mismo** mensaje. Si no, se corrige el tramposo (su firma), no el test.
- `src/shared/models.py`: el modelo `LimiteIntento` (para que la fixture `integ` la trunque entre tests con el resto de `Base.metadata`).
- `.gitignore`: `tests/_salida/humo_limite_compartido.json` y la réplica, como los demás humos.
- Los tramposos unitarios ZR22 (`Limitador._vigentes`) y ZR28 (`_agrupar`) no cambian: `Limitador` (en memoria) se queda como la referencia pura del algoritmo (UL1).

## 5. Cuentas predichas (ERR-10)
| Grupo | integ | no-integ |
|---|---|---|
| LC1, LC2, LC3, DP1, MG46, HLC1, RLC1 | 7 | — |
| ZR38-ZR43 | 6 | — |
| UL4 y ZR37 | — | 2 |
| **Nuevos** | **13** | **2** |

- **no-integ:** 208 + 2 = **210**. **Suite completa:** 768 + 15 = **783 passed + 24 skipped**, 0 fallos. `ruff check .` 0.

## 6. Plan de commits (uno por cambio, sin push)
1. Esta espec.
2. La migración 046, el modelo y MG46 (+ ZR43; `HUMO_ESPERADO`). La tabla existe y nadie la usa.
3. El límite usa la tabla: `limite.py`, `router.py`, las ediciones de §4, LC1-LC3, DP1, UL4 y ZR37-ZR42.
4. El humo y la réplica (HLC1, RLC1).
5. Lo medido (§9 de esta espec).

## 7. Qué NO se toca y "para después"
**No se toca:** el piloto (`engrama-piloto`, su base y su `despliegue/`), `Caddyfile`, GoTrue, los topes (150/60/200/1000), la ventana, `PROXIES_DE_CONFIANZA`, el piso de tiempo (S-5), `engrama-web`, EVA, SET.

**Para después (del despliegue, no de este backend):**
- **Login por /64:** GoTrue limita por `X-Forwarded-For` = `{remote_host}` completo. Para agrupar IPv6 por /64 hay que darle a GoTrue una llave ya agrupada: o Caddy reescribe esa cabecera con la red (no tiene función nativa para eso; haría falta un `map` con expresiones regulares que no cubre bien las formas comprimidas), o el backend ofrece una ruta `forward_auth` que Caddy consulta antes de `/auth/v1/token` y que usa esta misma tabla (contaría todo intento, buenos y malos). Requiere decisión.
- **Bloqueo por cuenta en el login** (TABLERO: "no existe bloqueo por cuenta"): GoTrue no lo trae.
- `autorregistro_lib.mjs:123-124` (`evaluarLimite`) acepta el 429 entre el intento 61 y el 121 "porque hay 2 procesos": con este cambio debe ser **exactamente 61**, y los 4 intentos con código válido tras el tope, **todos 429** (hoy basta con uno).
- `LEEME_piloto.md` §12.1 punto 2 dice que (a) y (c) faltan: ya estaban; queda (b), que cierra esta rama.
- El volumen: un 429 ahora cuesta una transacción corta en la base (antes, nada). Contra una avalancha volumétrica de muchos orígenes, el lugar es el borde (Caddy o el proveedor). Un caché local de "bloqueado hasta" por proceso ahorraría consultas; no se hace ahora.
- Agrupar por /48 (sigue en "para después" de §11.2 de ESPEC_autorregistro).

## 8. Riesgo para producción
Ninguno hoy: no se despliega. Al desplegar: la migración 046 es aditiva (`CREATE ... IF NOT EXISTS`); el backend nuevo con la base vieja falla al registrar (500: la tabla no existe), así que **la migración va antes que el backend**, como siempre en `migrar.py`. El backend viejo con la base nueva no la usa.

## 9. Medido
(Se llena al cerrar, sin mover nada de lo de arriba.)
