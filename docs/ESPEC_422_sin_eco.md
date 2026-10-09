# ESPEC · Ningún 422 de validación devuelve lo que el cliente envió (toda la API)

F4 · Creador · 2026-10-09 · **preregistro** (se commitea antes del código). Rama `test/fixture-integ`, sobre `59fe08a` (no-integ **167**; ruff 0; suite 655 passed + 23 skipped). **Sin migración.**

Origen: medido hoy en el piloto. `ESPEC_autorregistro.md` §13.1 cerró el eco solo en `POST /auth/registro` y `POST /auth/contrasena`, y dejó "para después" el manejador global como decisión de Christiam. Esa decisión llegó: se cierra para toda la API.

## 0. Medido y leído (2026-10-09, sobre `59fe08a`, antes de tocar nada)
Sonda sin base de datos (`TestClient`, dependencias reemplazadas), con un centinela en cada valor enviado:

| Qué | Medido |
|---|---|
| Rutas `APIRoute` registradas en `app.routes` | **59** (más 4 de documentación, que no validan nada) |
| Rutas con cuerpo declarado | **21** |
| De esas, las que devuelven el centinela en `input` | **19** (todas menos `/auth/registro` y `/auth/contrasena`). Con un campo omitido, `input` es el cuerpo entero |
| Rutas con parámetros de ruta | **31**. Las de tipo `UUID`, `int` o `date` devuelven el valor en `input` |
| Rutas con parámetros de consulta | **4** (`limit` en tres, `estado` en una): devuelven el valor en `input` |
| Fuga parcial en `msg` y en `ctx` | `uuid_parsing`: `"msg": "Input should be a valid UUID, invalid character: found `N` at 3"` y lo mismo en `ctx.error`: un carácter del valor enviado y su posición |
| Tipos de error vistos | `missing`, `extra_forbidden`, `model_attributes_type`, `json_invalid`, `uuid_parsing`, `int_parsing`, `literal_error`, `date_from_datetime_parsing`, `value_error`, `string_too_short` y los de tipo y largo del registro |
| No hay ningún manejador de excepciones en `src/main.py` | el 422 es el de fábrica de FastAPI (`{"detail": exc.errors()}`) |
| Validadores propios (`raise ValueError` en `schemas.py`) | 8, todos con texto fijo: ninguno mete el valor enviado en su mensaje |
| `ctx` de un `value_error` | sale como `{"error": {}}` (el `ValueError` no se serializa) |
| Tests existentes que afirmen que `input` viene | **ninguno** (`git grep` de `"input"` en `tests/`: solo los de §13.1, que afirman que NO viene) |

## 1. Qué cambia (una cosa)
**Ningún 422 de validación (`RequestValidationError`) de ninguna ruta devuelve valores enviados por el cliente.** Se hace en un solo lugar: un manejador global registrado en `src/main.py`.

Por cada error de la lista `detail`:
- `input` se quita siempre.
- `loc`, `type` y `url` no se tocan.
- `ctx` conserva solo las claves que pone el servidor (los límites y lo esperado: `min_length`, `max_length`, `pattern`, `gt`, `ge`, `lt`, `le`, `multiple_of`, `expected`, `max_digits`, `max_decimal_places`, `max_whole_digits`, `field_type`, `discriminator`, `expected_tags`, `expected_schemes`, `tz_expected`, `class_name`). Las demás se quitan (`error` del analizador, `tag`, `tz_actual`, `actual_length`...).
  - Excepción: `ctx.error` se conserva en `value_error` y `assertion_error` (es el error de un validador nuestro, de texto fijo, y sale como `{}`) y en `json_invalid` (es la frase fija del decodificador de JSON de Python, sin contenido). Así las dos rutas ya cerradas no cambian ni un byte.
- `msg` no se toca, salvo cuando contiene una clave de `ctx` que se quitó y era texto: si `msg` termina en ella, se corta ahí (`"Input should be a valid UUID, invalid character: found `N` at 3"` pasa a `"Input should be a valid UUID"`); si la contiene en otra parte, `msg` pasa a un texto neutro fijo (`"Invalid value"`). El `msg` de un `value_error` (`"Value error, <texto del validador>"`) no cambia.

**Dónde:** `src/shared/validacion.py`. La función pura `sin_valores_enviados(errores)` (la de §13.1, ampliada) hace la limpieza; `responder_sin_eco(request, exc)` arma la misma respuesta que la de fábrica (`422`, `{"detail": [...]}`) con la lista limpia; `src/main.py` la registra con `app.add_exception_handler(RequestValidationError, ...)`.

**Lo de §13.1 se retira:** la clase `RutaSinEco` desaparece. `RutaConPiso` vuelve a heredar de `APIRoute` (el piso sigue envolviendo el 422: la excepción sale de la ruta, espera y la atiende el manejador global) y `POST /auth/contrasena` vuelve al decorador normal. Sus tests (VE1 a VE3) y sus tramposos (ZV1 a ZV3) no se editan y siguen verdes: reemplazan `validacion.sin_valores_enviados`, que el manejador global llama por el módulo.

## 2. Qué debe pasar, medible
Un "422 de validación" es una respuesta 422 cuyo `detail` es una lista. Sobre toda respuesta así, "limpia" quiere decir: el centinela no aparece en el texto de la respuesta; ningún error trae `input`; cada error trae `loc`, `msg` y `type`; ningún `ctx` trae una clave fuera de la lista de §1.

Cada caso se envía **dos veces**, con dos centinelas distintos del mismo largo (`CENTINELA-9f3a7c` y `ZQWXKVJYP-8b2d4e`; ver la errata de §7) en los mismos lugares. Las dos respuestas deben ser **idénticas byte a byte**: la respuesta no depende del valor enviado. Eso cubre las fugas parciales (un carácter, una posición) que buscar el centinela entero no ve.

| # | Criterio | Test |
|---|---|---|
| C1 | **Regresión = identidad (se congela antes del código):** el cuerpo exacto de los 422 de `POST /auth/registro` (los casos de VE2) y de `POST /auth/contrasena` (los de VE3) es igual, byte a byte, al congelado sobre `59fe08a` en `tests/seguridad/snapshot_422_dos_rutas.json` | SE0 |
| C2 | **Pura:** `sin_valores_enviados` quita `input`; deja `loc`, `type`, `url`; de `ctx` deja solo las claves de §1 (con la excepción de `error`); corta el `msg` de `uuid_parsing`; pone el texto neutro en un `union_tag_invalid` cuyo `tag` venía en `msg`; no cambia el `msg` de un `value_error` aunque el valor enviado sea una palabra de ese mensaje; no modifica lo que recibe | SE1 |
| C3 | **Todas las rutas con cuerpo, descubiertas de `app.routes`** (hoy 21; el test exige al menos 21): por cada una, cuerpo con un campo de más, cuerpo lista, cuerpo texto, JSON roto y, por cada campo del modelo del cuerpo, ese campo omitido (con los demás puestos con el centinela), en lista, en objeto y en texto. Los cuatro primeros casos **deben** dar 422 de validación en toda ruta; todo 422 de validación sale limpio e idéntico con los dos centinelas | SE2 |
| C4 | **Parámetros de ruta:** por cada ruta con parámetros de ruta (hoy 31) y por cada parámetro, el centinela en ese lugar. Si el parámetro no es texto (UUID, entero, fecha), **debe** dar 422 de validación; sale limpio e idéntico | SE3 |
| C5 | **Parámetros de consulta:** por cada ruta con parámetros de consulta (hoy 4) y por cada parámetro, el centinela. Si no es texto, **debe** dar 422; limpio e idéntico | SE4 |
| C6 | **La forma que la web consume no cambia:** en `/auth/registro`, la contraseña de solo letras da `loc == ["body", "contrasena"]`, `type == "value_error"` y `msg == "Value error, " + MENSAJE_COMPOSICION`, aunque la contraseña enviada sea la palabra `contraseña` (que está en ese mensaje); en `/auth/contrasena`, `nueva` corta da `loc == ["body", "nueva"]`, `type == "string_too_short"` y su `msg` de fábrica | SE5 |
| C7 | **Réplica (entradas nuevas): una ruta que hoy no existe entra sola.** Se agrega a la app, solo durante el test, una ruta sintética con cuerpo, parámetro de ruta y de consulta; sin tocar nada más, sus 422 salen limpios e idénticos con un tercer y un cuarto centinela | SE6 |

**Humo:** SE2, SE3 y SE4 escriben `tests/_salida/humo_422_sin_eco.json` **antes** de afirmar: cuántas rutas recorrió cada uno, cuántas peticiones, cuántos 422 de validación y la lista de problemas (vacía si pasa). En `.gitignore`, como los demás humos.

## 3. Cómo sabremos que falló: tramposos (no-integ)
Cada uno es una versión rota, puesta con `monkeypatch`, que debe poner rojo el test real con el mensaje de su mecanismo.

| Tramposo | Qué rompe | Rojo predicho |
|---|---|---|
| **ZE1** | No hay manejador global (el 422 de fábrica de FastAPI) | SE0 (vuelve `input` a las dos rutas), SE2, SE3, SE4, SE5 no (no mira `input`), SE6 |
| **ZE2** | El manejador limpia solo `/auth/registro` y `/auth/contrasena` (lo que hay hoy) | SE2 (nombra `/auth/consentimiento`), SE3, SE4, SE6. SE0 y SE5 verdes |
| **ZE3** | `sin_valores_enviados` quita solo `input` (la función de §13.1, tal cual) | SE1 (queda `ctx.error` del UUID), SE3 (las dos respuestas difieren: `found `N` at 3` contra `found `Z` at 1`), SE6. SE0, SE2, SE4, SE5 verdes |
| **ZE4** | `sin_valores_enviados` deja solo `msg` (rompe la forma) | SE0, SE1, SE2, SE3, SE4, SE5, SE6 (falta `loc` o `type`) |

Solo se automatiza la diagonal marcada en negrita por el mecanismo: ZE1 contra SE2; ZE2 contra SE2; ZE3 contra SE1 y SE3; ZE4 contra SE5. **El código todavía no existe:** la matriz completa de arriba es una predicción; se mide entera antes de entregar y lo refutado se escribe en §7 (ERR-10).

Los tramposos ZV1 a ZV3 de §13.1 siguen existiendo y rojos por su razón.

## 4. Cuentas predichas
| Grupo | no-integ | integ |
|---|---|---|
| SE0 (en su propio commit, verde antes y después del código) | 1 | 0 |
| SE1 a SE6 | 6 | 0 |
| ZE1 a ZE4 | 4 | 0 |
| **Nuevos** | **11** | **0** |

No-integ: 167 + 11 = **178**. Suite completa: 655 + 11 = **666 passed**, 23 skipped. `ruff check .` en 0. Ningún test existente se edita.

## 5. Qué NO se toca
- Los 422 que no son de validación: los `HTTPException(422)` del dominio (`aviso_version_no_permitida`, `password_rejected`, `nodo_desconocido`, `invalid_batch`...) y la respuesta del importador de CSV. Su `detail` no es una lista de errores y no pasan por el manejador.
- `loc`: se conserva entero. **Límite declarado:** `loc` lleva nombres, y dos de ellos los elige el cliente: el nombre de un campo de más (`extra_forbidden`) y las claves de un campo de tipo diccionario. Son nombres de clave, no valores; quitarlos dejaría a la web sin saber qué campo sobra. Los tests ponen el centinela solo en valores.
- Números derivados que no se quitan del `msg`: el largo de una lista (`... not 5`). Es una cuenta, no el valor.
- Los mensajes de los validadores propios: hoy son de texto fijo (§0). Un validador futuro que meta el valor en su `ValueError` lo devolvería en `msg`; SE2 lo atraparía solo si el centinela llega a ese validador.
- Las cabeceras: las que hay (`authorization`, `x-tenant-id`) son texto y no dan 422.
- Los esquemas, las rutas, el piso del registro (su valor y su espera), las migraciones, `engrama-web`, el piloto de Docker y los demás repos.

## 6. Qué cambia para la web
- `/auth/registro` y `/auth/contrasena`: nada (C1, byte a byte).
- Las demás rutas: sus 422 de validación dejan de traer `input`; `loc`, `msg` y `type` siguen. El `msg` de un UUID, una fecha o una hora inválidos pierde el detalle del analizador (queda `"Input should be a valid UUID"`), y `ctx.error` desaparece de esos errores.

## 7. Medido al cerrar (2026-10-09, sobre `3e45b56`)
- **No-integ:** **178 passed** (511 deselected), como se predijo (167 + 11). **Suite completa:** **666 passed + 23 skipped** en 857 s, como se predijo, en un contenedor propio (`engrama-test-pg-422eco`, puerto 45477; borrado al terminar). `ruff check .`: 0. **Ningún test existente se editó.**
- **Humo** (`tests/_salida/humo_422_sin_eco.json`): SE2 recorrió **21** rutas con cuerpo, 340 casos por dos centinelas, **330** con 422 de validación (los otros 10 son cuerpos que resultan válidos, por ejemplo un campo opcional omitido); SE3, **31** rutas y 35 parámetros de ruta, **34** con 422 (el otro es `group_code`, que es texto); SE4, **4** rutas y 4 parámetros de consulta, 4 con 422. 0 problemas.
- **Cuántas devolvían eco antes:** con ZE2 (lo que había en `59fe08a`), SE2 se pone rojo en **19 de las 21** rutas con cuerpo, SE3 en **30 de las 31** con parámetros de ruta y SE4 en las **4** con consulta.
- **SE0:** las 35 respuestas congeladas de `/auth/registro` y `/auth/contrasena` siguen idénticas byte a byte.
- **El 422 del registro sigue esperando el piso** (medido a mano, no es un test nuevo): 16 ms con piso 0 y 440 ms con piso 400.

**Matriz medida de los tramposos** (cada uno contra cada test; R = rojo, v = verde):

| | SE0 | SE1 | SE2 | SE3 | SE4 | SE5 | SE6 | VE1 | VE2 | VE3 |
|---|---|---|---|---|---|---|---|---|---|---|
| código bueno | v | v | v | v | v | v | v | v | v | v |
| ZE1 | R | v | **R** | R | R | v | R | v | R | R |
| ZE2 | v | v | **R** | R | R | v | R | v | v | v |
| ZE3 | v | **R** | R | **R** | v | v | R | v | v | v |
| ZE4 | R | R | R | R | R | **R** | R | R | R | R |

En negrita, la diagonal que se automatiza (`tests/tramposos/test_tramposos_422_sin_eco.py`).

**Predicciones refutadas:**
1. **ZE3 contra SE2: se predijo verde y es rojo** (48 problemas en 4 rutas: `POST /challenges/`, `POST /challenges/generate`, `POST /challenges/refuerzo/{entrada_id}/respuestas` y `PUT /teachers/groups/{gid}/foco`). Esos cuerpos tienen campos que pasan por un analizador de Pydantic, que también deja su detalle en `ctx.error` (no se miró cuál tipo en cada ruta). La fuga parcial no era solo de los parámetros de ruta: también estaba en el cuerpo. El código la cierra igual; solo la predicción era corta.
2. **El segundo centinela** (§7.1, errata commiteada antes del código).
3. **El descubrimiento de campos del cuerpo falló en una ruta** en la primera corrida (`POST /teachers/groups/{gid}/codigo-inscripcion`, cuyo cuerpo es opcional, `CodigoIn | None`): SE2 lo dijo con su propia guarda ("rutas cuyo cuerpo no se pudo recorrer campo a campo") y se corrigió el ayudante del test antes del commit.

**No medido:**
- Nada contra el piloto (`engrama-piloto`): no se tocó ni se reconstruyó con este código. El 422 real de `POST /auth/consentimiento` del piloto seguirá trayendo `input` hasta que se reconstruya la imagen.
- `engrama-web` contra este backend: no se abrió ninguna pantalla. Lo que se afirma de la web sale de SE0 y SE5.
- La matriz se midió una vez, fuera de la suite (un guion suelto); solo la diagonal queda automatizada.
- Los tipos de error que ninguna ruta produce hoy (`union_tag_invalid`, zonas horarias, URL): solo en la función pura (SE1), con errores sintéticos.

**Para después:**
- `loc` devuelve nombres de clave que elige el cliente (el campo de más y las claves de los campos de tipo diccionario). Declarado en §5; decidir si se recorta.
- Los 422 del dominio que sí devuelven algo enviado: `nodo_desconocido` devuelve los ids de nodo que no existen (`src/curriculo/service.py`) y el importador de CSV devuelve `[{fila, motivo}]`. No son de validación y no se tocaron; revisar con el mismo método si importa.
- Otros `detail` con texto enviado fuera de los 422 (`group_code ... already exists`, `Group '...' not found`, `Invalid or expired JWT: ...`): fuera del alcance de este cierre.

### 7.1 Errata del preregistro (2026-10-09, antes del commit del código)
- **El segundo centinela estaba mal elegido.** La espec lo fijó en `ZQWXKVJYP+8b2d4e`. Al medir SE2 con el código ya limpio, 20 casos de 4 rutas (`/admin/groups/{gid}/students`, `/auth/registro`, `/grader/examenes/{codigo}`, `/grader/resultados`) dieron respuestas distintas con los dos centinelas, y **ninguna era eco**: los campos con patrón `[A-Za-z0-9_-]` aceptan `CENTINELA-9f3a7c` y rechazan el que trae `+`, así que la lista de errores cambia. Eso mide la validez del valor, no si viaja de vuelta.
- **Corrección (al dato de prueba, no al criterio):** el segundo centinela pasa a `ZQWXKVJYP-8b2d4e`: mismo largo y, en cada posición, la misma clase de carácter que el primero. El criterio "las dos respuestas son idénticas byte a byte" no cambia. La fuga del UUID se sigue viendo (`N` en la posición 3 contra `Z` en la 1), y ZE3 lo comprueba.
- **Candidato a ERR:** un criterio de "la respuesta no depende del valor" exige valores gemelos (misma clase de carácter por posición); se validó el criterio contra el código de hoy solo para el centinela entero, no para la pareja.
