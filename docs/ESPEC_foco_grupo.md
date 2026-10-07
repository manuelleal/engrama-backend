# ESPEC · El foco del grupo y las etiquetas de nodo de los retos, backend

F4 · Creador · 2026-10-06 · preregistro. Rama `test/fixture-integ`, sobre la puerta del Grader (`55397a3`; meta **525 passed + 20 skipped y 135 no-integ**).

Origen: la decisión 012 §3 (foco del grupo) y §10, oleada 2. **No usa IA.** Necesita el catálogo de nodos cargado (`ESPEC_catalogo_nodos.md`).

## 0. Medido y leído (2026-10-06)
| Qué | Dónde (`grep -n` de hoy) |
|---|---|
| El feed del estudiante | `src/challenge_engine/router.py` (`list_challenges`) → `challenges.list_challenges_for_student`: del colegio, activos, globales o de su grupo (`filtro_grupo_estudiante`, la única fuente; BUG-15), con cupo y con intentos; orden `created_at DESC` |
| Las preguntas no llevan nodos | `challenge_questions` (011): `question_type, question_text, options_json, correct_answer, order_index`. `ChallengeQuestionIn` (`schemas.py`) tampoco |
| Cómo se siembran los retos | por `POST /challenges/` (el guion vive en `ENGRAMA/despliegue`, fuera de este repo). **Aquí solo se define el contrato de la API** |
| El logro que ya validó el pedagogo (ERR-16) | `src/teachers/service/achievement.py`: primer intento por reto, ventana de 28 días, sin `open` (`primeros_en_ventana`), y por eje: mínimo 8 ítems de 3 retos, 80 y 60 %. `item_errors.py`: mínimo 5 estudiantes por ítem. Etiquetas: logrado, en desarrollo, a reforzar, datos insuficientes; nunca "débil" |
| La barrera de grupo | `access.authorize_group` (`only_assigned=True` en T5 y T7: ni el admin ve el aprendizaje de un grupo que no tiene asignado) |
| No hay zona horaria en la configuración | `grep -n "zona\|tz\|offset" src/shared/config.py` → 0 |
| **`alembic_version` fijado en los tests** (ERR-25) | `tests/integ_db.py:66` y los `HUMO_ESPERADO` de `tests/integ/test_humo_bug11.py`, `_bug13a15.py`, `_consentimiento.py`, `_autorregistro.py`, `_solicitudes_datos.py`, `_eventos_anillo.py`, `_catalogo_nodos.py` y `_grader.py` (9 líneas) |
| Tramposos existentes sobre el camino tocado (ERR-26) | Y10 (`test_tramposos_bug15.py:85`) parchea `challenges.filtro_grupo_estudiante`; A3 (`test_tramposos_seguridad.py:192`) parchea `challenges.question_to_schema`; Y16-1 a Y16-3 (`test_tramposos_bug16.py:75`) reemplazan la ruta `POST /challenges/` con el endpoint original; X12 y X16 (`test_tramposos_logro.py:112` y `:120`) parchean `achievement.primeros_en_ventana`; los de `test_tramposos_grupos.py:295` y `:325` parchean `achievement.intentos_del_grupo`. Predicción en §3 |

## 1. Qué cambia (una cosa)
**El profe fija, con vigencia, los nodos del mapa que su grupo trabaja; el estudiante recibe primero los retos de esos nodos; y el profe ve el logro del grupo por nodo.** Para eso cada pregunta de un reto puede llevar sus nodos.

### 1.1 Las preguntas de los retos llevan nodos (el contrato para el guion de sembrado)
- `ChallengeQuestionIn` gana **`nodos`**: lista de 0 a 8 ids del mapa, opcional (si falta, `[]`). Vale para `POST /challenges/`, que es lo que usa el guion.
- Pasan por `curriculo.service.canonicos`: se guardan los vigentes; un desconocido → **422 `nodo_desconocido`** y **el reto no se crea**.
- Se guardan en `challenge_questions.nodes TEXT[] NOT NULL DEFAULT '{}'`.
- **Lo que ve el estudiante no cambia:** `ChallengeQuestionOut` y `ChallengeOut` quedan idénticos (no llevan nodos).
- **Reetiquetar un reto que ya existe** (los ya sembrados):
  ```
  PUT /teachers/challenges/{cid}/nodos
  {"preguntas": [{"question_id": "uuid", "nodos": ["gr.b1.present-perfect.for-since"]}]}
  → 200 {"challenge_id": "uuid", "preguntas": [{"question_id": "uuid", "order_index": 1, "nodos": ["…"]}]}
  ```
  Reemplaza los nodos de las preguntas nombradas (las demás no cambian). Todo o nada: una pregunta que no es de ese reto → 422 `pregunta_ajena`; un nodo desconocido → 422. La respuesta trae **todas** las preguntas del reto.
  `GET /teachers/challenges/{cid}/nodos` → lo mismo, sin escribir.
- **Quién puede:** el admin de la institución, cualquier reto de ella; el docente, solo los retos de un grupo que tiene asignado (`access.visible_groups`). Un reto global, de otro grupo, de otra institución o inexistente → **404** para el docente (la misma respuesta). Estudiante → 403.
- No hay IA: los nodos los pone quien siembra (el guion, desde las unidades ya etiquetadas por el pedagogo).

### 1.2 El foco: nodos activos de un grupo, con vigencia
```
PUT /teachers/groups/{gid}/foco
{"desde": "2026-10-05", "hasta": "2026-10-11", "nodos": ["gr.b1.present-perfect.for-since", "lx.b1.work"]}
→ 200 {"desde": "2026-10-05", "hasta": "2026-10-11", "vigente": true,
       "nodos": [{"id": "…", "tipo": "gramatica", "nivel": "B1", "nombre_es": "…"}]}
```
- Un **periodo** es `(grupo, desde, hasta, nodos)`. `PUT` crea el periodo que empieza en `desde`, o **reemplaza** el que ya empezaba ese día.
- `hasta` es opcional: si falta, `desde + 6 días` (una semana). `hasta >= desde` y a lo sumo **62 días** → si no, 422.
- `nodos`: de 1 a 12, por `canonicos` (422 `nodo_desconocido`).
- **Dos periodos del mismo grupo no se solapan:** si el nuevo se cruza con otro (que empiece otro día) → **409 `foco_solapado`**, y nada cambia. Se comprueba con un candado sobre la fila del grupo.
- `GET /teachers/groups/{gid}/foco` → `{"hoy": "2026-10-06", "vigente": {…}|null, "periodos": [{…}]}` (los periodos del grupo, del más nuevo al más viejo; a lo sumo 50).
- `DELETE /teachers/groups/{gid}/foco/{desde}` → 204; si no existe, 404.
- **Vigente** = el periodo con `desde <= hoy <= hasta`. Como no se solapan, hay a lo sumo uno.
- **"Hoy"** es la fecha en la hora de la institución: `ahora en UTC + ENGRAMA_UTC_OFFSET_HOURS` (por defecto **−5**, Colombia). Es una sola para toda la instalación; una zona por institución queda en "para después".
- **Quién puede:** `access.authorize_group` (el docente del grupo y el admin de la institución). Lo demás, 404; estudiante, 403.
- **Reapuntar:** `challenge_questions` y `group_focus` entran a `src/curriculo/reapuntar.py`.

### 1.3 El feed del estudiante prioriza
- `GET /challenges/` devuelve **los mismos retos que hoy** (ni uno más, ni uno menos), pero **primero los que tienen alguna pregunta con un nodo del foco vigente de su grupo**. Dentro de cada mitad, el orden de hoy (`created_at DESC`).
- **Sin foco vigente, la respuesta es idéntica a la de hoy** (regresión = identidad).
- El foco es del grupo del estudiante (`auth.group_code` en `auth.tenant_id`): el foco de otro grupo no lo toca. Un estudiante sin grupo no tiene foco.
- `GET /challenges/foco` (nuevo, para que el cliente pinte "esta semana"):
  ```json
  200 {"vigente": {"desde": "2026-10-05", "hasta": "2026-10-11",
                   "nodos": [{"id": "…", "tipo": "…", "nivel": "…", "nombre_es": "…"}]},
       "retos_en_foco": ["uuid", "uuid"]}
  ```
  `vigente: null` y `retos_en_foco: []` si no hay. `retos_en_foco` sale **del mismo feed**: nunca trae un reto que el estudiante no vería.
- Cuesta, en el feed, una consulta del foco y, si hay foco, una de las preguntas con esos nodos.

### 1.4 El panel: logro del grupo por nodo
```
GET /teachers/groups/{gid}/foco/logro
→ 200 {"method": {"window_days": 28, "first_attempt_only": true, "min_students": 5, "min_items": 8,
                  "thresholds": {"logrado": 80, "en_desarrollo": 60}, "excluded_types": ["open"],
                  "scope": "retos asignados al grupo; es el logro del GRUPO, no el nivel de nadie"},
       "foco": {"desde": "…", "hasta": "…"} | null,
       "group_students": 28,
       "nodos": [{"nodo": {"id": "…", "tipo": "…", "nivel": "…", "nombre_es": "…"},
                  "students": 14, "items": 40, "correct": 31, "challenges": 3,
                  "status": "en_desarrollo", "label": "en desarrollo"}]}
```
- Trae **los nodos del foco vigente**, en el orden en que el profe los puso. Sin foco vigente: `foco: null` y `nodos: []`.
- **El alcance es el de T5 y T7, sin copiarlo** (`achievement.intentos_del_grupo` y `achievement.primeros_en_ventana`): intentos terminados de retos **asignados al grupo**, el **primer** intento de cada estudiante en cada reto, dentro de los últimos 28 días, sin los `open`.
- Una respuesta cuenta para un nodo si **su pregunta** lleva ese nodo. Por nodo: `students` (estudiantes distintos con al menos una respuesta), `items` (respuestas), `correct` y `challenges` (retos distintos).
- **Estado**, con enteros: si `students >= 5` y `items >= 8`: `logrado` (≥ 80 %), `en_desarrollo` (≥ 60 %) o `a_reforzar`; si no, `datos_insuficientes`. Nunca "débil".
- **Es un dato del grupo:** no nombra ni ordena estudiantes. `only_assigned=True`, igual que T5 y T7: ni el admin lo ve sin tener el grupo asignado.
- **Pendiente del pedagogo (ERR-16):** los mínimos (5 estudiantes y 8 ítems) y los cortes (80 y 60) **se toman tal cual** de T5 y T7, que él validó para ejes e ítems, no para nodos. Quedan como constantes nombradas; las preguntas van en §9. La ruta nace con ellos porque el encargo la pide; si el pedagogo los cambia, cambia una constante y su test.

### 1.5 Migración `040_foco_grupo`
```sql
ALTER TABLE challenge_questions ADD COLUMN IF NOT EXISTS nodes TEXT[] NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_challenge_questions_nodes ON challenge_questions USING GIN (nodes);

CREATE TABLE IF NOT EXISTS group_focus (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  group_id   UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  starts_on  DATE NOT NULL,
  ends_on    DATE NOT NULL,
  nodes      TEXT[] NOT NULL,
  set_by     UUID NOT NULL REFERENCES profiles(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT group_focus_group_start_key UNIQUE (group_id, starts_on),
  CONSTRAINT group_focus_dates_check CHECK (ends_on >= starts_on AND ends_on - starts_on <= 62),
  CONSTRAINT group_focus_nodes_check CHECK (cardinality(nodes) BETWEEN 1 AND 12)
);
ALTER TABLE group_focus ENABLE ROW LEVEL SECURITY;
```
RLS activo y sin políticas en `group_focus`; `challenge_questions` conserva las suyas. Bajada: `DROP TABLE group_focus`, el índice y la columna (**se pierden las etiquetas y los focos**).

**Ediciones a lo existente (ERR-25):** `alembic_version` → `040_foco_grupo` en las 9 líneas de §0; `tablas_con_rls` 38 → 39; `tests/seguridad/test_sin_acceso.py` 39 y 39 → 40 y 40; `tests/teachers/test_access.py` gana 7 rutas; `src/challenge_engine/schemas.py` (`ChallengeQuestionIn.nodos`), `service/challenges.py` (`create_challenge` guarda los nodos) y `router.py` (el feed prioriza, y `GET /challenges/foco`, declarado **antes** de `/{challenge_id}`); `src/shared/config.py` (`engrama_utc_offset_hours`), `src/shared/models.py`, `src/main.py`, `src/curriculo/reapuntar.py` y `.gitignore`. Si la medición encuentra otra, se corrige esta lista primero.

## 2. Criterios
| # | Criterio | Test |
|---|---|---|
| C1 | **Puro:** el estado de un nodo en los bordes (4 y 5 estudiantes; 7 y 8 ítems; 79, 80, 59 y 60 %); dos periodos se solapan o no (bordes incluidos); "hoy" con el desfase (las 23:30 en Bogotá siguen siendo el mismo día aunque en UTC ya sea mañana); priorizar es estable y no pierde ni repite; y `ChallengeQuestionOut` tiene **exactamente** sus 5 campos de hoy | UF1 (no-integ) |
| C2 | **Etiquetas:** `POST /challenges/` con nodos los guarda vigentes (un reemplazado, como su destino); un desconocido → 422 y 0 retos; sin `nodos`, igual que hoy. Reetiquetar reemplaza solo lo nombrado; una pregunta de otro reto → 422 y nada cambia. El docente sin el grupo, el de otra institución y el reto global → 404; el admin puede; el estudiante, 403. Una fusión del mapa reapunta la pregunta. **El JSON del reto que ve el estudiante tiene las mismas claves que antes** | FG1 |
| C3 | **Foco:** crear; `hasta` por defecto; el mismo `desde` reemplaza; solapado → 409 y nada cambia; `hasta < desde`, 63 días, 0 o 13 nodos, nodo desconocido → 422; `vigente` según "hoy" (antes, durante el primer y el último día, y después); borrar; una fusión del mapa reapunta el foco | FG2 |
| C4 | **Feed:** sin foco, el orden de hoy; con foco, primero los retos con un nodo del foco y después el resto, cada mitad en su orden; son **los mismos** retos. El foco vencido y el foco de **otro** grupo no cambian nada. `GET /challenges/foco` trae el vigente y solo retos del feed del estudiante | FG3 |
| C5 | **Aislamiento del foco:** E 403; DO, DT, DM y AB 404 en `PUT`, `GET`, `DELETE` y `logro`; AA puede `PUT` y `GET`, y recibe 404 en `logro`. 0 filas escritas por quien no puede | FG4 |
| C6 | **Logro por nodo:** con respuestas sembradas: un nodo `logrado`, uno `a_reforzar` y uno con 4 estudiantes en `datos_insuficientes`; el segundo intento, el intento de hace 29 días, el reto de otro grupo y la pregunta sin ese nodo **no cuentan**; los conteos son exactos | FG5 |
| C7 | Migración up/down/up idéntica (ERR-24) | MG40 |
| C8 | Regresión: los 525 previos verdes con solo las ediciones de §1.5 | la suite |

## 3. Tramposos, humo y réplica
Diagonal PREDICHA (el código no existe; ERR-23):

| Id | Rompe | Rojo predicho | Verde predicho y por qué |
|---|---|---|---|
| ZF1 | Los nodos de una pregunta se guardan sin resolver | **FG1** (as: entra el desconocido) | FG3 y FG5 siembran nodos vigentes |
| ZF2 (no-integ) | `ChallengeQuestionOut` gana `nodos` | **UF1** (as) | — |
| ZF3 | Reetiquetar no mira el grupo del reto | **FG1** (as: el docente sin el grupo recibe 200) | — |
| ZF4 | Reetiquetar acepta una pregunta de otro reto | **FG1** (as) | — |
| ZF5 | Los periodos se pueden solapar | **FG2** (as: 200 en vez de 409) | FG3: un solo periodo por grupo |
| ZF6 | Cualquier periodo cuenta como vigente (no mira las fechas) | **FG3** (as: el vencido prioriza). FG2 (as: `vigente` antes y después) | FG5: su foco es de hoy |
| ZF7 | El foco del feed se busca sin el grupo (cualquiera de la institución) | **FG3** (as: el foco de otro grupo prioriza) | FG2, FG4 y FG5 van por `gid` |
| ZF8 | Priorizar reordena aunque no haya foco | **FG3** (as: sin foco cambia el orden) | — |
| ZF9 | El logro cuenta todos los intentos, no el primero | **FG5** (as) | — |
| ZF10 | El logro no exige el mínimo de evidencia | **FG5** (as: el nodo con 4 estudiantes recibe etiqueta) | — |
| ZF11 | La barrera de grupo no exige asignación (`access._requiere_asignacion`, la fuente) | **FG4** (as: DO recibe 200). FG1 (as: el docente sin el grupo reetiqueta) | los que usan al dueño |
| ZF12 | `retos_en_foco` no pasa por el feed del estudiante | **FG3** (as: aparece el reto de otro grupo) | — |
| ZF13 | La carga del mapa no reapunta retos ni focos | **FG1** (as). FG2 (as) | MN1-MN3 y GR10: su tabla sigue reapuntando solo si no se la quita; **se predice GR10 rojo también** si el tramposo vacía la lista entera (se mide) |

**Tramposos existentes (ERR-26), predicción:** Y10 sigue rojo (el feed sigue usando `filtro_grupo_estudiante`; priorizar ordena lo que ese filtro deja pasar, no agrega retos). A3 sigue rojo (`question_to_schema` no cambia). Y16-1 a Y16-3 siguen rojos (el endpoint original sigue creando el reto; los nodos son opcionales). X12, X16 y los dos de `intentos_del_grupo` siguen rojos en T5 y T7; **además alcanzarían a FG5**, que usa las mismas dos funciones (es lo que se quiere: una sola fuente). No se corren contra FG5 aquí; se declara.

**Matriz a medir:** 12 tramposos integ × 7 columnas (FG1-FG5, MG40 y HF1) = **84 celdas**, más RF1 con la bandera.

**Humo HF1** escribe `tests/_salida/humo_foco_grupo.json` antes de afirmar. Semilla `random.Random(40)`: un grupo de 12 estudiantes y 8 retos de 3 preguntas, cada pregunta con un nodo al azar del catálogo sintético; el profe fija el foco de la semana con 2 nodos; cada estudiante responde 5 retos al azar con acierto al azar.
```json
{"alembic_version":"040_foco_grupo","semilla":40,"retos":8,"preguntas_con_nodo":24,"foco":200,
 "feed_sin_foco_igual_al_de_antes":true,"retos_en_foco":"K","primeros_del_feed_en_foco":true,
 "mismos_retos":true,"logro":{"nodos":2,"items":"I","correct":"A"},"estudiante_ve_nodos":false}
```
`K`, `I` y `A` salen de la semilla: se fijan al medir el humo por primera vez con el código bueno.

**Réplica RF1** (`ENGRAMA_REPLICA_FOCO=1`): dos grupos de la misma institución con focos distintos la misma semana; un periodo de un solo día; un foco de 12 nodos; un reto global con nodos del foco (entra a la prioridad, no al logro); y "hoy" en el cambio de día de Bogotá.

## 4. Cuentas (ERR-10)
| Grupo | integ | no-integ |
|---|---|---|
| FG1-FG5 | 5 | — |
| MG40 y HF1 | 2 | — |
| UF1 | — | 1 |
| ZF1 y ZF3-ZF13 | 12 | — |
| ZF2 | — | 1 |
| **Nuevos** | **19** | **2** |
| RF1 (saltado sin bandera) | 1 skipped | — |

**passed:** 525 + 21 = **546**; **skipped:** 20 + 1 = **21**; **no-integ:** 135 + 2 = **137**; ruff 0 y mypy 0.

## 5. Variables nuevas
`ENGRAMA_UTC_OFFSET_HOURS`: entero de −12 a 14; por defecto −5. No es un secreto.

## 6. Contrato para el guion de sembrado (vive en `ENGRAMA/despliegue`; aquí no se escribe)
1. Cargar el catálogo: `python -m src.curriculo cargar --archivo curriculo/nodos.json`.
2. Retos nuevos: `POST /challenges/` con `questions[].nodos`.
3. Retos ya sembrados: `GET /teachers/challenges/{cid}/nodos` para leer los `question_id`, y `PUT` con los nodos de cada pregunta (con el pase de un admin de la institución).
4. Los nodos de cada pregunta salen del etiquetado de las unidades de `contenido/` que hizo el pedagogo (familia → nodos). **Sin IA y sin adivinar:** una pregunta sin etiqueta se siembra con `nodos: []` y no entra a la prioridad ni al logro.

## 7. Qué NO se toca
`filtro_grupo_estudiante`, `question_to_schema`, `ChallengeOut`, `ChallengeQuestionOut`, T1-T7, `access.py`, las monedas, el nivel, el Grader y `INGLES/curriculo/`.

## 8. Riesgo para producción
- Aplicar la 040 es producción: el sí de Christiam. Agrega una columna con valor por defecto a `challenge_questions` (rápido en PostgreSQL 11 o más; no reescribe la tabla).
- **La 040 va antes o junto con el código:** sin la columna, crear o leer un reto da 500.
- Sin el catálogo cargado, etiquetar o fijar un foco da 422; el feed y todo lo demás siguen igual.

## 9. Para el pedagogo (ERR-16)
1. ¿El mínimo para etiquetar un nodo del grupo es 5 estudiantes y 8 respuestas, o pide otro (por ejemplo, la mitad del grupo)?
2. ¿Los cortes de 80 y 60 % valen también por nodo?
3. ¿La ventana es la de siempre (28 días) o **la vigencia del foco**?
4. ¿Los retos globales con nodos del foco deben contar en el logro del grupo? Hoy no cuentan (el alcance de T5).
5. ¿El estudiante ve el nombre del nodo del foco ("esta semana: presente perfecto"), o solo los retos marcados?

## 10. Para después
Una zona horaria por institución; elegir el foco desde una unidad de la alineación de un libro (012 §2) y desde el plan de clase (012 §8); el logro por nodo **por estudiante** (pasa antes por el pedagogo); avisar al profe cuando un nodo del foco no tiene retos (el hueco, para la fábrica).

## 11. Veredicto
- **FUNCIONA:** las cuentas de §4, la matriz medida, HF1 escrito, MG40 verde, RF1 verde y los previos verdes con solo las ediciones declaradas.
- **NO:** el feed pierde, gana o repite un reto; sin foco cambia el orden; el foco de un grupo toca a otro; un docente fija el foco de un grupo ajeno; el estudiante recibe nodos donde antes no; un tramposo queda verde.

---

## 12. Medido (2026-10-06, sobre `9231656`)

### Matriz medida: 84 celdas, más RF1 (ERR-19 y ERR-23)
**Cómo se midió:** una corrida de pytest por tramposo, aplicado a las 7 columnas por una fixture `autouse`, sobre un export limpio del commit, en un contenedor de prueba propio. La fila base dio 7 verdes.

**Resultado: 16 rojas, todas por aserción; 0 por excepción; 68 verdes.**

| Id | Rojas medidas | RF1 (con la bandera) |
|---|---|---|
| ZF1 | FG1 | verde |
| ZF3 | FG1 | verde |
| ZF4 | FG1 | verde |
| ZF5 | FG2 | verde |
| ZF6 | FG3 y FG2 | roja (as) |
| ZF7 | FG3 | roja (as) |
| ZF8 | FG3 y **HF1** | roja (as) |
| ZF9 | FG5 | verde |
| ZF10 | FG5 | verde |
| ZF11 | FG4 y FG1 | verde |
| ZF12 | FG3 | verde |
| ZF13 | FG1 y FG2 | verde |

- **Cruce que la predicción no tenía: ZF8 × HF1** (el humo compara el feed sin foco con el orden de creación).
- Fuera de las 7 columnas: ZF5 y ZF10 también ponen rojo a **UF1** (el test puro), porque parchean la función y las constantes que UF1 mide.
- Lo demás salió como se predijo (incluidos ZF6 × FG2, ZF11 × FG1 y ZF13 × FG2).

### Lo que la medición corrigió en el código antes del commit (regla 8; los criterios no se movieron)
**`PUT /teachers/challenges/{cid}/nodos` escribía y después respondía 500.** La primera versión olvidaba toda la sesión tras escribir y luego leía un atributo del reto ya expirado. Lo encontró FG1 en su primera corrida. Ahora la lectura de la respuesta vuelve a consultar las preguntas (`populate_existing`) y no toca el reto.

### Cuentas medidas
**546 passed + 21 skipped** (suite completa desde un export limpio del commit, 967 s); **137 no-integ**; `ruff check .` 0 y `mypy .` 0 (310 archivos). Igual a §4. Los 13 tramposos, rojos por su razón. Las ediciones a lo existente fueron las de §1.5.

- **HF1** escribió su archivo. Sus números (fijados con la primera medición, como decía §3): **`retos_en_foco` = 5, `items` = 35 y `correct` = 25**.
- **RF1 pasó en su primera corrida** (dos grupos con focos distintos, un periodo de un día, 12 nodos y el cambio de día de Bogotá).
- Los tramposos existentes del camino tocado (Y10, A3, Y16-1 a Y16-3, X12, X16 y los de `intentos_del_grupo`) siguieron rojos por su razón (corridos antes del commit, dentro de `tests/tramposos`).

### Se declara
- **Tras una fusión del mapa, los nodos de un foco quedan en orden alfabético** (el reapuntado quita repetidos ordenando): se pierde el orden en que el profe los puso, solo en los periodos que tenían el nodo fusionado.
- El logro por nodo **no cuenta los retos globales** (el alcance de T5). RF1 lo afirma; es la pregunta 4 de §9.

### No medido
- **Contra engrama-web y contra el guion de sembrado** (`ENGRAMA/despliegue`): el contrato de §6 se probó con un sembrador simulado en los tests.
- Dos `PUT` del foco a la vez (hay un candado sobre el grupo; no hay test con dos hilos).
- El costo del feed con miles de retos (una consulta más, con índice GIN).
- El `downgrade` por la CLI de Alembic.

## 13. Antes de aplicar la 040
Respaldo y el sí de Christiam. **La 040 va antes o junto con el código** (sin `challenge_questions.nodes`, crear o leer un reto da 500). Después: cargar el catálogo y etiquetar los retos (§6).
