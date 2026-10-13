# ESPEC · L1: la correcta y la explicación después de CADA respuesta, backend

F4 · Creador · 2026-10-06 · **preregistro SIN CÓDIGO.** Rama `test/fixture-integ`, sobre la cola de refuerzo (`0d1058b`; meta 572 passed + 22 skipped y 139 no-integ). Esta espec queda escrita para la sesión que la implemente: nada de aquí está construido ni medido.

Origen: `ENGRAMA/engrama-web/docs/ENCARGO_F4_lingo.md`, L1 (la regla de la casa, 001 §6.1: después de cada respuesta, la correcta y una explicación corta), y `TABLERO.md`, sección F4 (la normalización de respuestas escritas que pidió F8, con sus agregados 1, 2 y 3).

## 0. Leído (2026-10-06)
| Qué | Dónde |
|---|---|
| Hoy la correcta solo sale al final | `AttemptSubmitOut.correct_answers`, en `POST /challenges/attempts/{id}/submit` (`attempts.py`, `submit_attempt`) |
| La comparación de hoy | `attempts._normalize_answer`: `strip().lower()`. "don’t" (apóstrofo curvo) contra "don't" da **incorrecto** |
| No hay explicación ni respuestas alternativas | `grep -rn "explanation\|accepted_answers" src` → solo `refuerzo/schemas.py` (`explanation: null`, el campo que dejó listo `ESPEC_refuerzo.md`) |
| Las respuestas de un intento | `challenge_attempts.answers` (JSONB), que `/submit` escribe de una vez; T5, T7 y el logro por nodo lo leen |
| El gancho del refuerzo | `refuerzo.cola.desde_intento`, llamado por `submit_attempt` después de calificar |
| La paga | `award_coins` con la llave `challenge:<reto>:<estudiante>` (BUG-13) |
| Lo acordado con F8 (TABLERO, F4) | apóstrofo curvo a recto, minúsculas y espacios; además NFC y `‘ ʼ “ ”`; **(1)** quitar `. ! ?` del final; **(2)** `tolerancia: "1_letra"` (distancia ≤ 1) en 109 ítems; **(3)** pista con inicial ("c___"): se antepone la letra, con la tolerancia aplicada una sola vez. Decisión de F8 sobre (2): **no aplica si la respuesta es otra palabra válida** (fever/fewer, shift/shirt), y **una aceptada de 4 letras o menos se trata como exacta**. "Palabra válida" = el vocabulario de todo `contenido/` |

## 1. Qué cambia (una cosa)
**El estudiante responde pregunta por pregunta y, después de cada una, recibe si acertó, la correcta y la explicación; las respuestas escritas se comparan con la normalización acordada.**

### 1.1 `POST /challenges/attempts/{attempt_id}/answers`
```
{"question_id": "uuid", "answer": "don’t"}
→ 200 {"question_id": "uuid", "is_correct": true, "correct_answer": "don't",
       "explanation": {"regla": "…", "por_opcion": null, "ejemplo": "…"} | null,
       "repetida": false}
```
- `correct_answer`: en opción múltiple, la **label**. `por_opcion` es solo la de la opción elegida, y solo si fue incorrecta.
- **Idempotente:** la llave es `(attempt_id, question_id)` y **gana la primera respuesta**. Repetir, con la misma u otra, devuelve lo guardado con `repetida: true` y no cambia nada. Dos respuestas a la vez: una sentencia `ON CONFLICT DO NOTHING` y se devuelve la que quedó.
- Intento de otro estudiante o de otra institución → **404**; intento que no está `in_progress` → **409**; pregunta que no es del reto → **404**.
- **No paga, no cierra el intento y no revela nada de las otras preguntas.**

### 1.2 `POST /challenges/attempts/{attempt_id}/finish` (sin cuerpo)
Califica con las respuestas guardadas por `/answers` (las que falten cuentan como `""`, incorrectas), paga como `/submit` (la misma llave: una paga por reto y estudiante) y responde `AttemptSubmitOut`. Escribe `challenge_attempts.answers` **con la misma forma de hoy**, para que T5, T7, el logro por nodo y el gancho del refuerzo no cambien. Usa el mismo candado que `/submit` (`_tomar_intento`).

### 1.3 `/submit` queda idéntico
Regresión = identidad: sus tests no se editan. **Se declara la consecuencia:** mientras conviva, `/submit` compara con la regla vieja (`strip().lower()`) y `/answers` con la nueva. La pregunta para el coordinador está en §8.

### 1.4 La calificación (una sola función pura: `calificar(pregunta, respuesta)`)
- **Opción múltiple (y `listening`):** por **label**. Si llega el `value` de una opción, se traduce a su label antes de comparar.
- **`fill_blank`:** acierta si la respuesta normalizada coincide con `correct_answer` o con alguna de `accepted_answers`, también normalizadas.
- **`open`:** no se autocalifica aquí (queda como hoy).

**Normalización, en este orden:**
1. Unicode **NFC**.
2. Apóstrofos y comillas tipográficos a rectos: `’ ‘ ʼ` → `'`; `“ ”` → `"`.
3. Minúsculas.
4. Espacios: recortar los extremos y colapsar los internos a uno.
5. Quitar del **final** los signos `.`, `!` y `?` (uno o varios), y volver a recortar.

**Tolerancia `1_letra`** (campo de la pregunta; por defecto `exacta`). Con `1_letra`, además de la coincidencia exacta, acierta una respuesta a **distancia de edición 1** (una letra cambiada, de más o de menos) de alguna aceptada, **salvo que**:
- esa aceptada tenga **4 letras o menos** (se trata como `exacta`); o
- la respuesta sea **otra palabra válida** (está en el vocabulario cargado y no es una de las aceptadas).

**Pista con inicial** (campo `pista_inicial: true`): el cliente muestra la primera letra de la aceptada ("c___") y el estudiante puede escribir el resto o la palabra entera. El servidor compara **las dos lecturas** (lo recibido, y la inicial + lo recibido) y acierta si alguna acierta. La tolerancia se aplica **una sola vez** a cada lectura: no se suman un error por la pista y otro por el tipeo.

**El vocabulario** ("palabra válida"): una tabla `lexicon_words (word TEXT PRIMARY KEY)`, global y sin datos de nadie, que el operador carga desde `contenido/` con una orden (`python -m src.lexico cargar --archivo …`), igual que el catálogo de nodos. Con la tabla vacía, `1_letra` se comporta como si ninguna palabra fuera válida (más tolerante): **cargar el vocabulario va antes de sembrar ítems con `1_letra`**, y la orden de sembrado debe avisarlo.

### 1.5 Lo que entra por `POST /challenges/` (y por reetiquetar)
`ChallengeQuestionIn` gana, todos opcionales: `explanation` (`{regla, por_opcion: {label: texto}, ejemplo}`), `accepted_answers` (lista de hasta 10), `tolerancia` (`exacta` | `1_letra`) y `pista_inicial` (booleano). **`ChallengeQuestionOut` no expone ninguno, nunca**, salvo `pista_inicial` convertida en **la letra** (`pista: "c"`), que es justo lo que el estudiante debe ver antes de responder.

### 1.6 El refuerzo usa la misma función y la misma explicación
`refuerzo.service.responder` pasa a calificar con `calificar` y a llenar `explanation` (hoy `null`). Es el único cambio a `ESPEC_refuerzo.md`, y se declara allí cuando se implemente.

### 1.7 Migración `042_correccion_por_pregunta`
- `challenge_questions`: `explanation JSONB NULL`, `accepted_answers TEXT[] NULL`, `tolerance TEXT NOT NULL DEFAULT 'exacta'` (CHECK `exacta` | `1_letra`) y `hint_initial BOOLEAN NOT NULL DEFAULT FALSE`.
- `challenge_attempt_answers (attempt_id, question_id, tenant_id, answer, is_correct, answered_at)`: UNIQUE `(attempt_id, question_id)`; RLS activo y sin políticas.
- `lexicon_words (word)`: RLS activo y sin políticas.
- Las ediciones por la migración se enumeran con `git grep -n alembic_version -- tests` **el día que se implemente** (ERR-25): hoy serían 11 líneas.

## 2. Criterios
| # | Criterio | Test |
|---|---|---|
| C1 | **Normalización, pura:** "don’t" = "don't"; "  The   Cat. " = "the cat"; "Really?!" = "really"; NFC ("café" compuesto = descompuesto); comillas curvas = rectas; **no** se quita la puntuación interna ("it's" ≠ "its") | L1-U1 (no-integ) |
| C2 | **`1_letra`, pura:** "recive" (una letra de menos) acierta "receive"; "recieve" (dos letras cambiadas de lugar: distancia 2) **no**; "fewer" **no** acierta "fever" (es otra palabra válida); una aceptada de 4 letras ("cat") es exacta ("car" y "caat" fallan); con `exacta` nada de esto aplica | L1-U2 (no-integ) |
| C3 | **Pista con inicial, pura:** con la aceptada "castle", aciertan "astle" (el resto) y "castle" (entera); "astlee" (la inicial + lo recibido = "castlee", un error) acierta con `1_letra` y falla con `exacta`; "astl" ("castl", un error) acierta con `1_letra`; "stl" ("cstl", dos errores) no | L1-U3 (no-integ) |
| C4 | **Respuesta por pregunta:** correcta e incorrecta devuelven `is_correct`, la correcta y la explicación; en opción múltiple la `por_opcion` de la elegida solo si falló; el `value` de la opción correcta califica como correcto | L1-A1 |
| C5 | **Idempotencia:** la segunda respuesta (otra distinta) devuelve la primera con `repetida: true`; hay 1 fila; dos a la vez → 1 fila y la misma respuesta en las dos | L1-A2 |
| C6 | **Aislamiento:** intento ajeno, de otra institución o pregunta de otro reto → 404; intento ya terminado → 409 | L1-A3 |
| C7 | **Nada se filtra antes de tiempo:** `GET /challenges/{id}`, `/attempt` y el feed no traen `correct_answer`, `explanation`, `accepted_answers` ni `tolerancia` (introspección del esquema y por HTTP); `/answers` no revela las otras preguntas | L1-A4 |
| C8 | **`/finish`:** califica con lo guardado; lo que falta es incorrecto; paga una vez (la llave de BUG-13: `/finish` y `/submit` del mismo reto no pagan dos veces); `challenge_attempts.answers` queda con la forma de hoy; el gancho del refuerzo recibe lo fallado | L1-A5 |
| C9 | **`/submit` idéntico:** sus tests, sin editar | la suite |
| C10 | Migración up/down/up idéntica (ERR-24) | MG42 |

## 3. Tramposos (diagonal PREDICHA; se mide antes de aceptar)
| Id | Rompe | Rojo predicho |
|---|---|---|
| ZL1 (no-integ) | La normalización no convierte el apóstrofo curvo (el tramposo que pidió F8) | L1-U1 |
| ZL2 (no-integ) | `1_letra` acepta otra palabra válida (fever/fewer) | L1-U2 |
| ZL3 (no-integ) | `1_letra` aplica a palabras de 4 letras o menos | L1-U2 |
| ZL4 (no-integ) | La tolerancia se aplica dos veces con la pista | L1-U3 |
| ZL5 | "La última respuesta gana" | L1-A2 |
| ZL6 | `ChallengeQuestionOut` con `explanation` | L1-A4 |
| ZL7 | El intento se busca sin su dueño | L1-A3 |
| ZL8 | `/finish` paga sin la llave (dos pagas con `/submit`) | L1-A5 |
| ZL9 | `/answers` devuelve la `por_opcion` de todas las opciones | L1-A1 |
| ZL10 | `/finish` no llama al gancho del refuerzo | L1-A5 |

**Tramposos existentes sobre el camino tocado (ERR-26):** se enumeran con `git grep -n "attempts_mod\|challenges_mod" -- tests/tramposos` el día que se implemente. Hoy: Y2, Y11, A3, A4, A5, Y10, ZF1 y ZC10. `/finish` debe usar `_tomar_intento` y `is_attempt_correct` (no copiarlos), para que Y2 y A4 lo alcancen.

Humo: `tests/_salida/humo_l1.json`, con semilla fija: un reto de 6 preguntas (3 de opción múltiple y 3 escritas, una con `1_letra` y una con pista), respondido por 5 estudiantes sintéticos. Réplica: entradas nuevas (palabras con tilde, respuestas con emoji, una aceptada de exactamente 5 letras).

## 4. Cuentas (provisionales: se recalculan al implementar)
L1-U1 a U3 (3 no-integ) + L1-A1 a A5 (5 integ) + MG42 + humo + 4 tramposos no-integ + 6 integ = **13 integ y 7 no-integ**, más 1 réplica saltada. Sobre 572 + 22 y 139: **592 passed + 23 skipped y 146 no-integ**.

## 5. Qué NO se toca
`/submit` y sus tests, `award_coins`, la llave de la paga, `ChallengeOut`, T5 y T7, y `contenido/` (solo se lee, para cargar el vocabulario).

## 6. Riesgos
- **Dos reglas de comparación conviven** (`/submit` y `/answers`) hasta que se decida §8.1.
- **Un vecino real que no está en el vocabulario pasa como error de tipeo** (riesgo que ya anotó F8): el vocabulario de `contenido/` es chico. Una lista de frecuencia externa necesita el permiso de Christiam para descargarla.
- La explicación viaja al cliente **después** de responder; si el cliente la guarda, un compañero podría verla. Es del cliente (engrama-web ya descarta claves que lleguen antes de tiempo).

## 7. Para el pedagogo (ERR-16): (2) y (3) pasan por él ANTES del código
1. ¿`1_letra` con el piso de 5 letras y la excepción de "otra palabra válida" es la regla? (F8 ya dijo que sí; falta su firma.)
2. ¿Una transposición ("recieve") cuenta como 1 error? Hoy no: es distancia 2.
3. Con la pista, ¿se acepta la palabra entera además de "el resto"?
4. Una respuesta aceptada por tolerancia, ¿se le muestra al estudiante como "correcta, pero se escribe así: …"? (El contrato puede llevar `escrita_asi: "receive"`.)
5. ¿Las tildes cuentan en inglés (palabras prestadas: "café")?

## 8. Para el coordinador
1. ¿`/submit` adopta la normalización nueva (cambia su comportamiento: ERR declarado y sus tests se revisan), o se retira cuando engrama-web use `/answers` + `/finish`?
2. ¿El vocabulario se carga de `contenido/` tal cual, o lo entrega F8 como un archivo?
3. L2 (una sola paga por reto) y L3 (monedas por desempeño) tocan `/finish`: ¿van antes o después de L1? Esta espec supone la paga de hoy.

## 9. Veredicto (cuando se implemente)
- **FUNCIONA:** las cuentas medidas, la matriz medida, el humo escrito y los previos verdes (con `/submit` idéntico).
- **NO:** la correcta o la explicación salen antes de responder; la segunda respuesta cambia la primera; `/finish` paga dos veces; "don’t" no acierta "don't"; "fewer" acierta "fever"; un tramposo queda verde.

---

## 10. Adenda del 2026-10-13 (preregistro; manda sobre lo anterior donde choquen)

F4 · Creador · sobre el bloque 3 (`ESPEC_solo_refuerzo.md`; meta **731 passed + 23 skipped y 197 no-integ**). Bloque 4 de 5 del encargo "reto del día sin profe". Manda el dictamen `investigacion/pedagogia/04-dictamen-racha-y-reto-del-dia.md` §1.5 y hecho 3; el dueño confirmó el 2026-10-12: **explicación en español para A1 y A2, en inglés sencillo desde B1.**

### 10.1 Lo que cambia frente a §1 a §4
| Tema | Antes (2026-10-06) | Ahora |
|---|---|---|
| Migración | `042_correccion_por_pregunta` | **`045_correccion_por_pregunta`** |
| Vocabulario ("palabra válida") | tabla `lexicon_words` y una orden de carga | **Un archivo de texto** (una palabra por línea), en `LEXICO_ARCHIVO`; sin tabla (toda tabla nueva lleva institución, y el vocabulario no es de nadie). Vacío = ninguna palabra es "válida" |
| `ChallengeQuestionOut` | ganaba `pista` | **No cambia** (su forma está fijada por tres tests: regresión). La letra de la pista sale en la ruta nueva `GET …/answers` |
| La explicación | `{regla, por_opcion, ejemplo}` | El formato del dictamen: §10.2 |
| El segundo intento | sin tratar | §10.4 |
| Reetiquetar (`PUT /teachers/challenges/{cid}/nodos`) | aceptaba la explicación | No: se resiembra. Para después |
| Humo `humo_l1.json` | propio | Va dentro del humo del bloque 5 (`humo_reto_del_dia.json`, sección `l1`) |

`(2)` tolerancia y `(3)` pista siguen **sin la firma del pedagogo** (§7): quedan en el código, **apagadas por defecto** (`exacta`, sin pista). No sembrar ítems con `1_letra` ni con pista hasta esa firma.

### 10.2 La explicación tras cada respuesta (dictamen §1.5)
Por pregunta, `POST /challenges/` acepta `explanation` con la forma del banco (`item.explicacion` tal cual):
```json
{"regla": "…", "por_opcion": {"A": "…", "B": "…"}, "ejemplo": "…", "idioma": "es", "oracion_correcta": "…"}
```
`idioma` y `oracion_correcta` son opcionales. Lo que **sale** tras responder:

| Parte del dictamen | Campo de la respuesta | De dónde |
|---|---|---|
| 1. Veredicto, con la oración completa correcta | `is_correct` y **`oracion_correcta`** (siempre, haya o no explicación) | la que mandó el sembrador o, si no, el enunciado con el hueco (`___`) relleno con el texto de la opción correcta (en opción múltiple) o con la respuesta aceptada (escrita). Sin hueco, o con más de uno: el texto de la correcta |
| 2. Regla | `explanation.regla` | el banco |
| 3. Por qué no la suya | `explanation.por_opcion` (un **texto**, o `null`) | la línea de la opción **que eligió**, **solo si falló** |
| 4. Ejemplo | `explanation.ejemplo` | el banco |
| Idioma | `explanation.idioma` (`es` o `en`) | el del banco o, si no viene, por el nivel del reto: **A1 y A2 → `es`; B1 en adelante → `en`**; sin nivel → `es` |

- Al acertar salen 1, 2 y 4 (`por_opcion: null`). El ícono y el texto del veredicto son de la web; nunca elogio a la persona.
- El servidor **no traduce ni recorta**: el idioma dice en qué está escrito el texto. Los límites de palabras del dictamen (45 y 60) son del validador de contenido, no de esta ruta.
- Sin explicación sembrada: `explanation: null` (la `oracion_correcta` sale igual).
- El repaso (`POST /challenges/refuerzo/{id}/respuestas`) llena `explanation` con esta misma forma y gana `oracion_correcta`; califica con `calificar` (§1.6).

### 10.3 Las rutas (todas NUEVAS; `/submit` y `/attempt` no cambian de contrato)
```
POST /challenges/attempts/{attempt_id}/answers   {"question_id": "uuid", "answer": "B"}
→ 200 {"question_id": "uuid", "is_correct": false, "answer": "B", "correct_answer": "A",
       "oracion_correcta": "She goes to school every day.",
       "explanation": {"idioma": "es", "regla": "Con he, she, it el verbo lleva -s.",
                       "por_opcion": "Go es para I, you, we, they.", "ejemplo": "He plays football."},
       "repetida": false, "respondidas": 1, "total": 3}

GET  /challenges/attempts/{attempt_id}/answers   (para retomar; no escribe)
→ 200 {"status": "in_progress", "total": 3, "pistas": {"uuid": "c"},
       "respondidas": [ lo mismo que respondió cada POST, con "repetida": true ]}

POST /challenges/attempts/{attempt_id}/finish    (sin cuerpo)
→ 200 AttemptSubmitOut (la misma forma de /submit)
```
- `answer` en la respuesta es **la guardada** (gana la primera): si llega otra, la web ve cuál quedó.
- `respondidas` y `total`: cuando son iguales, la web llama a `/finish`.
- **La clave no sale antes de responder ESA pregunta:** `/answers` solo habla de la pregunta respondida; el `GET` solo de las ya respondidas; `/attempt`, el detalle, el feed y la tanda siguen sin clave ni explicación.
- 404: intento ajeno, de otra institución o inexistente; pregunta que no es de ESE intento. 409: intento que no está `in_progress`.
- **`/submit` sobre un intento que ya tiene respuestas por `/answers` → 409 `intento_con_respuestas`** (si no, "gana la primera" se salta enviando todo de nuevo). Un intento sin respuestas guardadas se envía como siempre.
- `/finish` y `/submit` cierran por el MISMO camino (`attempts.cerrar_intento`): la misma llave de paga, la racha, la cola de repaso y la escalera.
- La racha cuenta al cerrar (`/finish`), no en cada `/answers`: un intento sin terminar no cuenta.
- Cada respuesta guarda su instante (`answered_at`, reloj del servidor): es el dato del riesgo 1 ("menos de 3 s por respuesta"), que no existía.

### 10.4 El segundo intento (hecho 3 del dictamen)
- **Variable `SEGUNDO_INTENTO_PAGA`**, sin valor por defecto = **como hoy**: el segundo intento paga lo mismo que el primero. Con un número (el dictamen propone 5), del segundo intento en adelante el reto paga `min(su valor, ese número)`. **El primer intento paga siempre lo mismo.** Vale para `/submit` y `/finish`. El dueño no ha respondido si baja a 5: no se cambia.
- **Con L1 el reintento usa la forma gemela si existe.** Cuando un estudiante que ya respondió ese reto por `/answers` (ya vio sus claves) abre otro intento, cada pregunta con `familia` se reemplaza por una forma **de la misma familia que no ha visto** (gemela, después repaso), de un reto activo que su grupo ve, del mismo tipo de pregunta. `POST /challenges/{id}/attempt` devuelve esas preguntas (misma forma de siempre; cambian los ids) y el intento las recuerda (`challenge_attempts.served_questions`). `/answers`, `/finish` y `/submit` califican **las preguntas de ESE intento**: las claves copiadas del primer intento no sirven (sus ids ya no son de este intento).
- **Si una pregunta no tiene gemela sin ver, se repite la misma** y el intento paga según la variable. Se declara: con la variable sin poner y sin gemelas, copiar la clave en el segundo intento cobra lo de hoy (10). Es la pregunta 5 del dictamen, que sigue abierta; el humo del bloque 5 la mide.
- Quien nunca usó `/answers` (la web de hoy) no recibe formas distintas: su segundo intento es idéntico al de hoy.
- Una gemela servida en un reintento queda vista: no vuelve a servirse en la cola ni en la segunda vuelta.

### 10.5 Migración `045_correccion_por_pregunta` (aditiva)
- `challenge_questions`: `explanation JSONB NULL`, `accepted_answers TEXT[] NULL`, `tolerance TEXT NOT NULL DEFAULT 'exacta'` (CHECK `exacta` | `1_letra`), `hint_initial BOOLEAN NOT NULL DEFAULT FALSE`.
- `challenge_attempts`: `served_questions UUID[] NULL`.
- `challenge_attempt_answers (id, tenant_id, attempt_id, profile_id, question_id, answer, is_correct, answered_at; UNIQUE (attempt_id, question_id))`, con RLS activo y sin políticas, como las demás.
- Bajada: la tabla y las cinco columnas. En producción no se baja.

Variables: `SEGUNDO_INTENTO_PAGA` (sin valor; 0 a 50) y `LEXICO_ARCHIVO` (vacío).

### 10.6 Criterios (reemplazan la tabla de §2)
| # | Criterio | Test |
|---|---|---|
| C1 a C3 | Los de §2, sin cambio (normalización, `1_letra`, pista) | L1-U1 a L1-U3 (no-integ) |
| C4 | **Puro:** opción por label o por `value`; `por_opcion` solo de la elegida y solo si falló; la paga del intento (primero igual; segundo "como hoy" sin la variable y `min(valor, n)` con ella) | L1-U4 (no-integ) |
| C5 | **Puro:** la oración correcta (hueco relleno; sin hueco; la del sembrador manda); el idioma por nivel (A1 y A2 `es`; B1 a C1 `en`); el del banco manda | L1-U5 (no-integ) |
| C6 | **Respuesta por pregunta:** `is_correct`, la correcta, la oración y la explicación con su idioma; `por_opcion` de la elegida solo si falló; el `value` correcto acierta; sin explicación, `null`; no paga y no cierra | L1-A1 |
| C7 | **Idempotencia:** otra respuesta devuelve la primera con `repetida: true` y hay 1 fila; dos a la vez → 1 fila y la misma en las dos; el `GET` retoma | L1-A2 |
| C8 | **Aislamiento:** intento ajeno, de otra institución o pregunta de otro reto → 404; intento terminado → 409; la fila guarda su institución y su dueño | L1-A3 |
| C9 | **Nada se filtra antes de tiempo:** el detalle, `/attempt`, el feed, la tanda y el `GET …/answers` sin responder no traen la clave ni la explicación; `/answers` no revela nada de las otras preguntas; `ChallengeQuestionOut` tiene los campos de siempre | L1-A4 |
| C10 | **`/finish`:** califica con lo guardado; lo que falta es incorrecto; paga una vez (ni `/finish` + `/submit` ni dos `/finish` pagan dos veces); `answers` con la forma de hoy; lo fallado entra a la cola; cuenta para la racha; `/submit` con respuestas guardadas → 409 | L1-A5 |
| C11 | **El segundo intento:** sin gemela, las mismas preguntas y la paga de la variable (sin ponerla, 10; con 5, 5; el primer intento, 10 en los dos casos); con gemelas, preguntas distintas: las claves viejas dan 404 en `/answers` y no ganan por `/submit`; quien no usó `/answers` recibe las de siempre | L1-A6 |
| C12 | `/submit` idéntico: sus tests, sin editar | la suite |
| C13 | Migración up/down/up idéntica | MG45 |

### 10.7 Tramposos (reemplazan la tabla de §3; diagonal PREDICHA)
| Id | Rompe | Rojo predicho |
|---|---|---|
| ZL1 a ZL4 (no-integ) | Los de §3 | L1-U1, U2, U2 y U3 |
| ZL5 | "La última respuesta gana" | L1-A2 |
| ZL6 | La pregunta que ve el estudiante trae la explicación | L1-A4 |
| ZL7 | El intento se busca sin su dueño | L1-A3 |
| ZL8 | `/finish` paga sin la llave | L1-A5 |
| ZL9 | `/answers` devuelve la `por_opcion` de todas las opciones | L1-A1 |
| ZL10 | `/finish` no llama al gancho del refuerzo | L1-A5 |
| ZL11 | El reintento repite las mismas preguntas aunque haya gemelas | L1-A6 |
| ZL12 | `/submit` acepta un intento con respuestas guardadas | L1-A5 |
| ZL13 (no-integ) | El segundo intento ignora la variable | L1-U4 |
| ZL14 (no-integ) | La explicación de A2 sale marcada en inglés | L1-U5 |

**Tramposos existentes sobre el camino tocado (ERR-26):** Y2 (`_tomar_intento`), Y11 (`start_attempt`), A3 (`question_to_schema`), A4 (`is_attempt_correct`), A5 (`submit_attempt`), ZW6 (`respondidas`), ZC10 (`desde_intento`), ZP9 y ZP10. Ninguna de esas firmas cambia; `/finish` pasa por `_tomar_intento`, `is_attempt_correct`, `respondidas` y `desde_intento`.

### 10.8 Ediciones a lo existente (ERR-25)
`alembic_version` → `045_correccion_por_pregunta` (12 líneas); `tablas_con_rls` 45 → 46; `tests/seguridad/test_sin_acceso.py` 46 → 47; `tests/teachers/test_access.py` gana 3 rutas; `src/challenge_engine/schemas.py` (`ChallengeQuestionIn` gana `explanation`, `accepted_answers`, `tolerancia` y `pista_inicial`), `service/challenges.py` (los guarda), `service/attempts.py` (`submit_attempt` se parte en dos sin cambiar lo que hace: lo que cierra el intento pasa a `cerrar_intento`; califica las preguntas del intento; 409 con respuestas guardadas; la paga del intento; `start_attempt` sirve las formas del reintento), `router.py` (tres rutas); `src/refuerzo/service.py`, `schemas.py` y `formas.py` (`vistas` cuenta las formas servidas en un reintento); `src/engrama_core/service/economia.py`; `src/shared/config.py` y `models.py`; `docs/PEDIDO_sembrador.md`.

### 10.9 Cuentas
L1-U1 a U5 (5) + ZL1 a ZL4, ZL13 y ZL14 (6) no-integ; L1-A1 a A6 y MG45 (7) + ZL5 a ZL12 (8) integ = **15 integ y 11 no-integ**. Sobre 731 + 23 y 197: **757 passed + 23 skipped y 208 no-integ**; ruff 0.

### 10.10 Preguntas nuevas
- **Al dueño:** ¿el segundo intento paga 5? (Pregunta 5 del dictamen; provisional: como hoy.) ¿Y un reintento con gemelas (preguntas que no ha visto) paga completo aunque la variable esté en 5? (Provisional: no; del segundo intento en adelante manda la variable.)
- **Al pedagogo:** una gemela usada en un reintento ya no sirve a la cola de repaso ni a la segunda vuelta: ¿prioridad a cuál? (Provisional: el reintento la usa.)
- §8.1 queda respondida de hecho: `/submit` no adopta la normalización nueva y convive hasta que engrama-web use `/answers` + `/finish`.

---

## 11. Medido (2026-10-13)

### Cuentas
**208 no-integ**; `ruff check .` 0. Suite completa de este bloque en un contenedor de prueba propio (1.092 s; sin los archivos del bloque 5): **756 passed + 23 skipped y 1 rojo**, L1-A6 (abajo). Corregido, **757 passed + 23 skipped**, igual a §10.9. Después se agregó un tramposo (ZL15): **758 + 23**. La suite final, con el bloque 5, está en `ESPEC_humo_reto_del_dia.md` §10.

### Diagonal medida: 15 de 15 rojos por su razón
ZL1 a ZL4, ZL13 y ZL14 (no-integ) y ZL5 a ZL12 y ZL15 (integ), en `tests/tramposos/test_tramposos_l1.py`. **Solo la diagonal.**

### Los seis tests L1-A pasaron en su primera corrida, con los valores escritos antes
Con dos salvedades, las dos del TEST y no del código:
- **L1-A6 se puso rojo en la suite completa** (y verde suelto): comparaba las pagas de un reto en el orden del `id` del libro, que es un UUID. Ahora el ayudante las ordena por monto. Lo pagado no cambió: 10, 5 y 10.
- **L1-U5 tenía un esperado mal escrito:** el caso "sin opciones" usaba un enunciado CON hueco y esperaba la clave sola; la regla de §10.2 rellena el hueco (`x C`). Se corrigió el esperado; el código no se tocó.

### Ediciones a lo existente que §10.8 no listaba
- `tests/tramposos/test_tramposos_422_sin_eco.py`: ZE1 y ZE2 llevan escrito cuántas rutas reciben cuerpo (21 → 22 y 19 → 20), y `/answers` es una más.
- El esperado de L1-U4 del borrador gana `idioma` en la explicación.
- `ChallengeQuestionOut` quedó intacto (por eso `pista` salió por `GET …/answers`).

### Agregado después de cerrar (se declara)
§10.4 afirma que una gemela servida en un reintento queda vista. No tenía test. Se agregó la aserción a L1-A6 y su tramposo **ZL15**; con el código bueno era verdad antes y después.

### Decisiones tomadas al implementar
- `/submit` suma una consulta (¿el intento tiene respuestas guardadas?). La paga del intento solo cuenta los intentos previos cuando `SEGUNDO_INTENTO_PAGA` tiene valor: sin la variable, `/submit` paga con las mismas consultas de antes.
- `/submit` califica las preguntas DEL INTENTO (las del reto, salvo un reintento con gemelas de quien ya usó `/answers`).
- En la tanda, `paga` de un reto `jugado` muestra lo que pagaría el segundo intento (solo cambia si la variable tiene valor).
- El repaso califica ahora con `calificar`: también acepta el texto de la opción, no solo la letra.
- Módulos nuevos: `calificar.py` (puro), `explicar.py`, `intento_formas.py` y `por_pregunta.py`. `attempts.py` ya pasaba de 400 líneas (444) y quedó en 517: partirlo sin mover lo que seis tramposos reemplazan es otra espec.

### No medido
- **La tolerancia de una letra, la pista y `LEXICO_ARCHIVO` por HTTP:** solo tienen tests puros; la lectura del archivo del vocabulario no tiene ninguno. Están apagadas por defecto.
- `GET …/answers` con pistas (ningún reto de los tests lleva pista).
- Con el banco real y con engrama-web. Las explicaciones del banco pasan de 18 palabras en `por_opcion`: el servidor no las recorta.
- El `downgrade` por la CLI de Alembic.
- Dos `/finish` a la vez (pasan por el mismo candado que CC2 prueba para `/submit`; no hay test propio).
