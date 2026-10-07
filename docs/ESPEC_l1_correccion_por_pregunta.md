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
