# ESPEC · La cola de refuerzo personalizado, backend

F4 · Creador · 2026-10-06 · preregistro. Rama `test/fixture-integ`, sobre el foco del grupo (`9231656`; meta **546 passed + 21 skipped y 137 no-integ**).

Origen: la decisión 012 §6 (mejoramiento personalizado) y §10, oleada 3; `investigacion/pedagogia/02` (dentro de la familia: original → gemela → repaso a 7 días, "es recuperación, no reconocimiento"). Cierra el ciclo que pidió Christiam: **examen → resultados → refuerzo**. No usa IA. Necesita el catálogo cargado y las preguntas etiquetadas (`ESPEC_catalogo_nodos.md` y `ESPEC_foco_grupo.md`).

## 0. Medido y leído (2026-10-06)
| Qué | Dónde (`grep -n` de hoy) |
|---|---|
| Dónde se guarda una hoja del Grader | `src/grader/service.py` (`recibir` → `_guardar_hoja`); los nodos de cada ítem, en `grader_exam_items.nodos` |
| Dónde se califica un reto | `src/challenge_engine/service/attempts.py` (`submit_attempt` → `grade_answers`): compara por `strip().lower()`; `details` trae `question_id` e `is_correct` |
| Cómo paga un reto (BUG-13) | `award_coins` con la llave `challenge:<reto>:<estudiante>`: una paga por (reto, estudiante). **El refuerzo no llama a `award_coins`** |
| Qué retos ve un estudiante | `challenges.filtro_grupo_estudiante` (la única fuente; BUG-15) |
| Una pregunta no sabe de qué familia es | `challenge_questions` no tiene `item_ref`, familia ni rol (`grep -n "item_ref\|family" src/shared/models.py` → solo `learning_events.item_ref`) |
| No hay explicación por pregunta todavía | `grep -rn "explanation" src` → 0. Llega con L1 (`ENCARGO_F4_lingo.md`) |
| `alembic_version` fijado en los tests (ERR-25) | 10 líneas: `tests/integ_db.py:66` y los `HUMO_ESPERADO` de `tests/integ/test_humo_bug11.py`, `_bug13a15.py`, `_consentimiento.py`, `_autorregistro.py`, `_solicitudes_datos.py`, `_eventos_anillo.py`, `_catalogo_nodos.py`, `_grader.py` y `_foco_grupo.py` |
| Tramposos existentes sobre el camino tocado (ERR-26) | sobre `attempts`: Y2 (`test_tramposos_bug13.py:168`, `_tomar_intento`), Y11 (`test_tramposos_bug15.py:89`, `start_attempt`), A4 y A5 (`test_tramposos_seguridad.py:194` y `:196`, `is_attempt_correct` y `submit_attempt`). Sobre el Grader: ZG2 y ZG5 (`_guardar_hoja`) y ZG10 (`recibir`). Predicción en §3 |

## 1. Qué cambia (una cosa)
**Cuando un estudiante falla un ítem (en una hoja del Grader o en un reto), el NODO de ese ítem entra a su cola de refuerzo; la plataforma le sirve una forma paralela que no ha visto, sin monedas; y el nodo queda superado cuando acierta una forma no vista y otra en un repaso espaciado.**

### 1.1 Lo que entra a la cola es el nodo, no la pregunta
Una fila por `(institución, estudiante, nodo)`.
- **Desde el Grader:** al guardar una hoja, cada ítem que **no** fue acierto (`marcada` incorrecta, `vacia` o `doble`) mete los nodos de ese ítem. Un ítem sin nodos no mete nada. Va en la misma transacción que la hoja.
- **Desde un reto:** al calificar un intento (`/submit`), cada pregunta fallada mete sus nodos. Un reto sin nodos no cuesta ni una consulta.
- **Reenviar la misma hoja no cuenta dos veces** (la fila recuerda de qué hoja o intento vino). Si la hoja **corregida** ya no falla un ítem, la entrada que esa hoja creó se retira **solo si está intacta** (nadie la ha respondido); si el estudiante ya trabajó en ella, se queda.
- Fallar otra vez un nodo que ya estaba: `en_refuerzo` suma un fallo; `por_repasar` vuelve a `en_refuerzo`; `superado` **se reabre**.
- Fallar una forma **del propio refuerzo** no crea otra entrada: es la misma.

### 1.2 Qué es "la misma pregunta" y qué es una forma paralela
Las preguntas de los retos ganan tres datos opcionales (los pone el guion de sembrado, sin IA):

| Campo | Qué es |
|---|---|
| `item_ref` | el id del ítem en el banco (`b1-u01-f01-2`). **Es la identidad:** el mismo ítem sembrado en dos retos, o impreso en un examen, es la misma pregunta |
| `familia` | el id de su familia (`b1-u01-f01`). Texto opaco |
| `rol` | `original`, `gemela` o `repaso` |

- Sin `item_ref`, la identidad de una pregunta es ella misma.
- **Visto** por un estudiante = (a) toda pregunta de un reto que abrió (con o sin enviar); (b) toda forma que respondió en el refuerzo; (c) todo ítem de un examen suyo del Grader (`item_id` = `item_ref`).
- **Candidatas** para un nodo = preguntas con ese nodo, de retos **activos** que el estudiante puede ver (`filtro_grupo_estudiante`), que no sean `open`, y cuya identidad **no ha visto**.
- **Cuál se sirve** (determinista): primero las de **la misma familia** del ítem que falló; dentro de eso, en el refuerzo la `gemela` y después el `repaso`, y en el repaso espaciado al revés; después las de otras familias del mismo nodo; a igualdad, por identidad. **Nunca la misma pregunta.**
- El nivel no se filtra aparte: el nodo ya lleva su nivel.

### 1.3 Las rutas del estudiante
```
GET /challenges/refuerzo
→ 200 {"pendientes": [{"entrada_id": 12, "etapa": "refuerzo",
                       "nodo": {"id": "…", "tipo": "…", "nivel": "…", "nombre_es": "…"},
                       "pregunta": {"id": "uuid", "question_type": "multiple_choice",
                                    "question_text": "…", "options_json": [...], "order_index": 1}}],
       "por_repasar": 2, "en_espera_de_contenido": 1, "superados": 3}
```
- Trae a lo sumo `REFUERZO_MAX_POR_VEZ` (5) entradas **que tocan**: las `en_refuerzo` y las `por_repasar` cuya fecha ya llegó, de la más vieja a la más nueva. Cada una con **su** forma. Dos entradas no reciben la misma pregunta.
- La pregunta sale con el esquema de siempre (`ChallengeQuestionOut`): **sin clave y sin nodos**.
- No escribe nada: pedirla dos veces da lo mismo.

```
POST /challenges/refuerzo/{entrada_id}/respuestas   {"question_id": "uuid", "answer": "B"}
→ 200 {"entrada_id": 12, "question_id": "uuid", "is_correct": true, "correct_answer": "B",
       "explanation": null, "estado": "por_repasar", "proxima_fecha": "2026-10-13T15:04:05Z",
       "repetida": false, "coins_earned": 0}
```
- Se califica con **la misma función** que `/submit` (`attempts.grade_answers`).
- **Idempotente:** la llave es `(entrada, pregunta)` y gana la primera respuesta. Repetir, con la misma u otra respuesta, devuelve lo guardado con `repetida: true` y no cambia nada.
- Entrada de otro estudiante, de otra institución o inexistente → **404**. La entrada no toca todavía (repaso con fecha futura, o ya superada) → **409 `no_toca_todavia`**. La pregunta no es la forma que el servidor serviría ahora → **409 `forma_no_vigente`** (no se puede "responder" una pregunta vista ni elegir cuál).
- `explanation` va en `null` hasta que exista la explicación por pregunta (L1); el campo ya está en el contrato.
- **`coins_earned` es siempre 0.** El refuerzo no llama a `award_coins`, no da XP y no cuenta como ganador de ningún reto (la regla de la casa: se premia el dominio una vez, no repetir; BUG-13).
- Ambas rutas se declaran antes de `/challenges/{challenge_id}`.

### 1.4 Cuándo queda superado (LO FIJA EL PEDAGOGO; ERR-16)
Propuesta de la 012 §6, **como configuración**:
1. `en_refuerzo` → acierta `REFUERZO_ACIERTOS_PARA_REPASO` formas no vistas (por defecto **1**; un fallo pone la cuenta en 0) → `por_repasar`, con fecha `ahora + REFUERZO_DIAS_REPASO` días (por defecto **7**).
2. `por_repasar`, llegada la fecha → acierta **otra** forma no vista → `superado`. Si la falla → vuelve a `en_refuerzo`.

Los dos números son variables de entorno; **el valor por defecto es una propuesta**, no una decisión. Cambiarlos no toca código. Las preguntas concretas van en §9. **Esto no mueve el nivel MCER del escudo** (010 y 011): este módulo no llama a `record_confirmed_level`.

### 1.5 Sin forma no vista: "en espera de contenido"
Si a una entrada que toca no le queda ninguna candidata, **no se le sirve nada** (no se repite una pregunta para rellenar). No es un estado guardado: se calcula al leer, con la misma función que sirve. En cuanto exista una forma nueva, se sirve sola.
- El estudiante lo ve como un número (`en_espera_de_contenido`).
- El profe lo ve por estudiante y, agregado, como **hueco**: `huecos: [{nodo, estudiantes_en_espera}]`. Ese dato es el que después se le pide a la fábrica (012 §7).

### 1.6 Lo que ve el profe
```
GET /teachers/groups/{gid}/refuerzo
→ 200 {"method": {"aciertos_para_repaso": 1, "dias_para_repaso": 7, "pendiente_del_pedagogo": true,
                  "regla": "superado = acierta una forma no vista y otra en un repaso espaciado"},
       "estudiantes": [{"profile_id": "uuid", "full_name": "…",
                        "nodos": [{"nodo": {…}, "estado": "en_refuerzo", "etiqueta": "en refuerzo",
                                   "origen": "grader", "fallos": 1, "desde": "…", "proxima_fecha": null}]}],
       "por_nodo": [{"nodo": {…}, "en_refuerzo": 4, "por_repasar": 2, "superado": 1,
                     "en_espera_de_contenido": 3}],
       "huecos": [{"nodo": {…}, "estudiantes_en_espera": 3}]}
```
- Estados: `en_refuerzo`, `por_repasar`, `superado` y `en_espera_de_contenido`. Las etiquetas no califican a nadie ("débil" no existe): dicen qué está practicando.
- Solo los estudiantes **activos** del grupo; el nombre, el de la membresía (BUG-11).
- **Es solo del panel del profe:** `only_assigned=True` (ni el admin lo ve sin tener el grupo), y la respuesta lleva `Cache-Control: no-store`. **No hay ninguna ruta que lo exponga a estudiantes ni a la clase en vivo.** Para engrama-web y EVA: esta vista nunca va en una pantalla proyectable.

### 1.7 Migración `041_refuerzo`
```sql
ALTER TABLE challenge_questions ADD COLUMN IF NOT EXISTS item_ref TEXT;
ALTER TABLE challenge_questions ADD COLUMN IF NOT EXISTS family_ref TEXT;
ALTER TABLE challenge_questions ADD COLUMN IF NOT EXISTS form_role TEXT;
-- CHECK form_role IN ('original','gemela','repaso'), y un índice por item_ref

CREATE TABLE IF NOT EXISTS reinforcement_queue (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  node_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'en_refuerzo',
  hits INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 1,
  reopened INTEGER NOT NULL DEFAULT 0, family_ref TEXT,
  origin TEXT NOT NULL, origin_ref TEXT NOT NULL,
  next_due_at TIMESTAMPTZ, mastered_at TIMESTAMPTZ,
  entered_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, profile_id, node_id),
  CHECK (status IN ('en_refuerzo','por_repasar','superado')),
  CHECK (origin IN ('grader','reto')),
  CHECK ((status = 'por_repasar') = (next_due_at IS NOT NULL)),
  CHECK ((status = 'superado') = (mastered_at IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS reinforcement_answers (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  queue_id BIGINT NOT NULL REFERENCES reinforcement_queue(id) ON DELETE CASCADE,
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  question_id UUID NOT NULL REFERENCES challenge_questions(id) ON DELETE CASCADE,
  form_key TEXT NOT NULL, stage TEXT NOT NULL, answer TEXT NOT NULL, is_correct BOOLEAN NOT NULL,
  status_after TEXT NOT NULL, due_after TIMESTAMPTZ, answered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (queue_id, question_id), CHECK (stage IN ('refuerzo','repaso'))
);
```
RLS activo y sin políticas en las dos tablas nuevas. Bajada: las dos tablas y las tres columnas (**se pierde la cola**).

**Ediciones a lo existente (ERR-25):** `alembic_version` → `041_refuerzo` en las 10 líneas de §0; `tablas_con_rls` 39 → 41; `tests/seguridad/test_sin_acceso.py` 40 y 40 → 42 y 42; `tests/teachers/test_access.py` gana 3 rutas; `src/grader/service.py` (`recibir` llama al gancho después de guardar la hoja), `src/challenge_engine/service/attempts.py` (`submit_attempt` llama al gancho después de calificar), `src/challenge_engine/schemas.py` (`ChallengeQuestionIn` gana `item_ref`, `familia` y `rol`), `service/challenges.py` (los guarda), `router.py` (las dos rutas del estudiante), `src/foco/schemas.py` y `etiquetas.py` (reetiquetar acepta y devuelve esos tres datos, opcionales), `src/shared/config.py` (tres variables), `src/shared/models.py`, `src/main.py`, `src/curriculo/reapuntar.py` y `.gitignore`.

**Reapuntar:** `reinforcement_queue` entra a la lista. Si una fusión del mapa deja a un estudiante con el nodo viejo y el nuevo, se conserva la fila del nuevo y se borra la del viejo (se declara: se pierde el avance de esa fila).

## 2. Criterios
| # | Criterio | Test |
|---|---|---|
| C1 | **Puro:** la tabla de transiciones (acierto y fallo en cada estado; con 2 aciertos exigidos; con otra cantidad de días); el orden de las candidatas (familia, rol según la etapa, identidad); la identidad con y sin `item_ref`; y los valores por defecto (1 acierto, 7 días, 5 por vez) | UR1 (no-integ) |
| C2 | **Desde el Grader:** una hoja con fallos en ítems con nodos mete exactamente esos nodos (una fila por nodo, `origen: grader`); el acierto y el ítem sin nodos no meten nada; reenviar la misma hoja no suma fallos; la hoja corregida retira la entrada intacta y deja la que ya se trabajó | CR1 |
| C3 | **Desde un reto:** la pregunta fallada mete sus nodos (`origen: reto`); la acertada no; fallar otra vez en otro intento suma un fallo; las monedas y el resultado de `/submit` son los de antes | CR2 |
| C4 | **El ciclo:** se sirve la gemela de la familia, **nunca** el ítem del examen ni el de otro grupo; fallarla revela la correcta y sirve otra forma; acertar → `por_repasar` a 7 días y **no se sirve nada** hasta entonces; llegada la fecha se sirve otra forma no vista; acertarla → `superado`. Repetir una respuesta devuelve lo guardado; una pregunta que no es la vigente → 409; antes de tiempo → 409. **0 filas en el libro de monedas y el saldo idéntico** | CR3 |
| C5 | **Sin forma no vista:** la entrada no se sirve, cuenta en `en_espera_de_contenido`, el profe la ve con ese estado y en `huecos`; al aparecer una forma nueva, se sirve | CR4 |
| C6 | **Retrocesos y configuración:** fallar el repaso → `en_refuerzo`; fallar un nodo `superado` lo reabre; con `REFUERZO_ACIERTOS_PARA_REPASO=2` hacen falta dos aciertos seguidos; con `REFUERZO_DIAS_REPASO=3` la fecha es a 3 días | CR5 |
| C7 | **Quién ve qué:** el profe del grupo ve por estudiante y por nodo, con `Cache-Control: no-store`; E 403; DO, DT, DM, AB **y AA** 404; un estudiante no lee ni responde la entrada de otro (404), ni la suya desde otra institución | CR6 |
| C8 | **Fusión del mapa:** la cola se reapunta; con las dos filas, queda la del nodo nuevo | CR7 |
| C9 | Migración up/down/up idéntica (ERR-24) | MG41 |
| C10 | Regresión: los 546 previos verdes con solo las ediciones de §1.7 | la suite |

## 3. Tramposos, humo y réplica
Diagonal PREDICHA (el código no existe; ERR-23):

| Id | Rompe | Rojo predicho | Verde predicho y por qué |
|---|---|---|---|
| ZC1 | Se sirven también las formas ya vistas | **CR3** (as: en el repaso sale el ítem del examen). CR4 (as) | CR1 y CR2 no sirven |
| ZC2 | Responder el refuerzo paga monedas | **CR3** (as: filas en el libro) | — |
| ZC3 | Superado al primer acierto | **CR3** (as). CR5 (as) | CR4 |
| ZC4 | El repaso no se espacia (toca de inmediato) | **CR3** (as: se sirve antes de la fecha) | — |
| ZC5 | Responder no es idempotente (la segunda respuesta cuenta) | **CR3** (as) | — |
| ZC6 | Se acepta cualquier pregunta como la forma | **CR3** (as: 200 con el ítem del examen) | — |
| ZC7 | La entrada se busca sin su dueño | **CR6** (as: otro estudiante la responde) | — |
| ZC8 | El Grader mete también los ítems acertados | **CR1** (as) | — |
| ZC9 | Reenviar la hoja suma fallos | **CR1** (as: `fallos: 2`) | CR2: sus fallos vienen de intentos distintos |
| ZC10 | El reto no mete nada | **CR2** (as) | CR1 |
| ZC11 | Sin forma no vista se repite una vista | **CR4** (as) | CR3: siempre hay otra |
| ZC12 | El panel no exige asignación (`access._requiere_asignacion`) | **CR6** (as: DO y AA reciben 200) | — |
| ZC13 | Las candidatas no pasan por `filtro_grupo_estudiante` | **CR3** (as: sale la pregunta del otro grupo) | — |
| ZC14 | La carga del mapa no reapunta la cola | **CR7** (as) | — |
| ZC15 | Fallar el repaso no devuelve a `en_refuerzo` | **CR5** (as) | CR3: su repaso se acierta |
| ZC16 (no-integ) | El repaso por defecto es a 0 días | **UR1** (as) | — |

**Tramposos existentes (ERR-26), predicción:** Y2, Y11, A4 y A5 siguen rojos por su razón: el gancho va **después** de calificar y no cambia el resultado ni la paga; con retos sin nodos (los de esos tests) no hace ni una consulta. ZG2, ZG5 y ZG10 siguen rojos: el gancho va en `recibir`, después de `_guardar_hoja`; sus exámenes no llevan nodos salvo HG1 y GR10.

**Matriz a medir:** 15 tramposos integ × 9 columnas (CR1-CR7, MG41 y HR1) = **135 celdas**, más RR1 con la bandera.

**Humo HR1** escribe `tests/_salida/humo_refuerzo.json` antes de afirmar. Semilla `random.Random(41)`: 10 estudiantes; un banco sintético de 4 nodos × 2 familias × 3 formas sembrado en retos; un examen de 8 ítems (los originales) calificado con fallos al azar; cada estudiante responde su refuerzo (acierta con probabilidad 0,7), el reloj avanza 7 días y responde el repaso.
```json
{"alembic_version":"041_refuerzo","semilla":41,"hojas":10,"entradas":"E","servidas_ya_vistas":0,
 "tras_el_refuerzo":{"en_refuerzo":"a","por_repasar":"b"},"tras_el_repaso":{"superado":"s","en_refuerzo":"r","por_repasar":"p"},
 "en_espera_de_contenido":"w","huecos":"h","filas_en_el_libro":0,"saldo_movido":0,"nivel_escrito":0}
```
Las letras salen de la semilla y se fijan con la primera medición del código bueno. `servidas_ya_vistas`, `filas_en_el_libro`, `saldo_movido` y `nivel_escrito` son **0 por criterio**.

**Réplica RR1** (`ENGRAMA_REPLICA_REFUERZO=1`): un estudiante en dos instituciones con el mismo nodo en las dos colas; un ítem con 3 nodos; preguntas sin `item_ref`; un nodo cuya única forma es `open` (queda en espera); y 6 entradas con `REFUERZO_MAX_POR_VEZ=5`.

## 4. Cuentas (ERR-10)
| Grupo | integ | no-integ |
|---|---|---|
| CR1-CR7 | 7 | — |
| MG41 y HR1 | 2 | — |
| UR1 | — | 1 |
| ZC1-ZC15 | 15 | — |
| ZC16 | — | 1 |
| **Nuevos** | **24** | **2** |
| RR1 (saltado sin bandera) | 1 skipped | — |

**passed:** 546 + 26 = **572**; **skipped:** 21 + 1 = **22**; **no-integ:** 137 + 2 = **139**; ruff 0 y mypy 0.

## 5. Variables nuevas (ninguna es secreto)
| Variable | Por defecto | Rango | Quién la fija |
|---|---|---|---|
| `REFUERZO_ACIERTOS_PARA_REPASO` | 1 | 1 a 5 | el pedagogo |
| `REFUERZO_DIAS_REPASO` | 7 | 1 a 60 | el pedagogo |
| `REFUERZO_MAX_POR_VEZ` | 5 | 1 a 20 | producto |

## 6. Contrato para el guion de sembrado
`POST /challenges/` y `PUT /teachers/challenges/{cid}/nodos` aceptan, por pregunta, `item_ref`, `familia` y `rol` (opcionales). **Para que el refuerzo tenga qué servir, las gemelas y los repasos de cada familia deben estar sembrados en retos activos que el grupo vea**, con su `item_ref`. El examen del Grader usa esos mismos ids como `item_id`.

## 7. Qué NO se toca
`grade_answers`, `award_coins`, la paga de los retos, `/submit` (su respuesta es idéntica), `_guardar_hoja`, `filtro_grupo_estudiante`, `access.py`, el nivel confirmado y `/auth/me`.

## 8. Riesgo para producción
- Aplicar la 041 es producción: el sí de Christiam. Va **antes o junto con el código**: sin las columnas, crear o leer un reto da 500.
- Desde este commit, cada `/submit` con preguntas etiquetadas escribe en la cola: unas pocas sentencias más por intento.
- **Si el banco no tiene formas paralelas sembradas, todo quedará "en espera de contenido".** No rompe nada, pero el refuerzo no sirve hasta que se siembren (riesgo ya declarado en la 012 §12).

## 9. Para el pedagogo (ERR-16), antes de mostrarlo en un aula
1. ¿"Superado" = 1 acierto en una forma no vista + 1 acierto en el repaso a 7 días? ¿O 2 aciertos antes del repaso?
2. ¿7 días, o el repaso a 21 días con la gemela no vista que propone el informe 02 para el grupo?
3. ¿Un ítem `vacia` del examen entra a la cola igual que uno fallado? (Hoy sí.)
4. Acertar en un reto normal una pregunta de un nodo que está en la cola, ¿debe contar como acierto del refuerzo? (Hoy no: solo cuenta el refuerzo.)
5. Tras fallar una forma del refuerzo, ¿se sirve otra de inmediato o al día siguiente? (Hoy, de inmediato, después de ver la correcta.)
6. ¿Qué texto ve el estudiante por "en espera de contenido"? ¿Y ve el nombre del nodo?
7. Para el profe: ¿"en refuerzo", "por repasar", "superado" y "en espera de contenido" son las etiquetas correctas?
8. Si no hay gemela de la familia, ¿vale cualquier otro ítem del mismo nodo, o debe ser del mismo tipo de pregunta?

## 10. Para después
Que un acierto en un reto cuente para la cola; el repaso de grupo a 21 días con la gemela no vista (informe 02); la explicación por pregunta (L1); pedir los huecos a la fábrica (012 §7); purgar la cola de quien sale de la institución; avisar al estudiante cuándo le toca el repaso.

## 11. Veredicto
- **FUNCIONA:** las cuentas de §4, la matriz medida, HR1 escrito con sus cuatro ceros, MG41 verde, RR1 verde y los previos verdes con solo las ediciones declaradas.
- **HAY ALGO MODESTO:** todo lo anterior, pero la regla de "superado" sigue siendo una propuesta sin el sí del pedagogo, y no se probó con un banco real sembrado.
- **NO:** se sirve una pregunta ya vista; el refuerzo paga monedas; un nodo queda superado sin el repaso; un estudiante ve o responde la cola de otro; el `/submit` o la hoja del Grader cambian de resultado; un tramposo queda verde.
