# ESPEC · La puerta del Grader (`/grader`), backend

F4 · Creador · 2026-10-06 · **preregistro SIN CÓDIGO.** Rama `test/fixture-integ`. Esta espec queda escrita para la sesión que la implemente; nada de aquí está construido ni medido.

Origen: `TESDER/docs/ENCARGO_backend_grader.md` (solo lectura) y la decisión 011, encargo 3.5. El Grader imprimible califica una foto sin IA y devuelve, por hoja, qué marcó cada estudiante en cada ítem.

**Va después de `ESPEC_eventos_anillo.md`** (usa su regla "una sola función escribe el nivel" y su numeración de migraciones). Las cuentas parten de la cifra con que cierre esa espec (meta: 491 passed + 18 skipped y 129 no-integ).

## 0. Leído (2026-10-06, sin ejecutar)
| Qué | Dónde |
|---|---|
| El Grader entra con el Bearer del profe y pregunta `/auth/me` | su encargo, "Lo que ya usa"; lee `id`, `full_name`, `active_tenant_id`, `memberships[].tenant_id/.role/.is_active` y `must_change_password` |
| **El número de lista no existe en el backend** | ninguna columna ni tabla lo guarda (`grep -rn "numero\|list_number" src` → 0). El "número de lista" de EVA vive en EVA |
| `group_code` es único por institución | `groups_tenant_code_key UNIQUE (tenant_id, group_code)` (`src/shared/models.py`) |
| La barrera de grupo es por `id`, en una fuente | `access.authorize_group` y `access.visible_groups` (ERR-26) |
| Grupo ajeno → **404**, nunca 403 | la convención de `/teachers` y `/admin` (no delata si el grupo existe) |
| Los errores por ítem del panel (T7) salen de los intentos de retos | `src/teachers/service/item_errors.py`; su regla la validó el pedagogo (ERR-16) |

## 1. Qué cambia (una cosa)
**El profe, con su cuenta de ENGRAMA, obtiene la lista numerada de un grupo suyo, registra un examen impreso y entrega las hojas calificadas; el backend las guarda por ítem, sin duplicar y sin mover el nivel.**

Sin secretos compartidos: solo el Bearer del profe. Todas las rutas: `require_teacher`, Pydantic estricto con `extra="forbid"`, y el grupo resuelto por **la misma barrera de siempre** (`access.visible_groups`, filtrando por `group_code`).

### 1.1 `GET /grader/grupos/{group_code}/lista`
```json
200 {"group_code": "11A", "estudiantes": [{"numero": 7, "student_id": "uuid", "full_name": "…"}]}
```
- **El número de lista nace aquí** (tabla nueva, §1.5): la primera vez que se pide la lista, cada estudiante activo del grupo recibe el siguiente número libre, en orden de `(memberships.created_at, memberships.id)`. Desde ahí es **estable**: quien entra después recibe el siguiente, y un número **no se reutiliza** aunque el estudiante salga del grupo.
- `full_name` es el de la membresía (BUG-11). Solo salen los estudiantes **activos**; el número de quien salió queda reservado.
- Grupo de otra institución, no asignado al docente o inexistente → **404** (la misma respuesta). El admin de la institución ve todos sus grupos.
- Es un `GET` que puede escribir (asigna números). Se declara; la alternativa (asignar al matricular) toca M3, M4 y el autorregistro, y queda en "para después".

### 1.2 `PUT /grader/examenes/{codigo}`
Cuerpo como en el encargo: `{codigo, huella, titulo, nivel, group_code, n_items, items: [{item_id, origen, nivel, destreza, tema, enunciado, correcta_texto, explicacion}]}`.
- `codigo` del cuerpo = el de la ruta; `huella` = 64 hexadecimales; `n_items` = `len(items)` (1 a 200); `item_id` sin repetir; `origen` ∈ oficial, docente; `nivel` ∈ A1…C2. Si no → 422.
- **201** la primera vez; **200** si llega con la misma `huella` (no cambia nada); **409 `examen_con_otra_huella`** si el `codigo` existe con otra.
- El examen es de la institución activa y del grupo (`UNIQUE (tenant_id, codigo)`). Un `codigo` de otra institución no choca ni se ve.
- **Una pregunta de origen `docente` no sale de su institución:** vive en la fila del examen de ese `tenant_id`; ninguna ruta la lee desde otro.

### 1.3 `POST /grader/resultados`
Cuerpo como en el encargo: `{codigo, huella, group_code, hojas: [{event_id, numero, forma, calificado_en, items: [{item_id, estado, correcta, elegida_texto, resuelta_por}], aciertos, total}]}` (1 a 200 hojas).
- Del lote: examen no registrado → **404**; `huella` distinta → **409**; grupo que no es del profe o no es el del examen → **404**.
- **Por hoja, todo o nada** (el lote no): cada hoja en su transacción.
  - `event_id` debe ser `grd:{codigo}:{numero}`;
  - `estado` ∈ marcada, vacia, doble. **`dudosa` → la hoja se rechaza** (`estado_invalido`);
  - los `item_id` son exactamente los del examen; `total` = cuántos son;
  - **`aciertos` se recalcula** contando `correcta: true` en ítems `marcada`; si no coincide → `aciertos_no_coinciden`. `vacia` y `doble` nunca cuentan como acierto, digan lo que digan;
  - `numero` sin estudiante en la lista del grupo → `numero_sin_estudiante`;
  - `resuelta_por`, si viene, es el propio profe del token.
  - **Reenviar la misma hoja REEMPLAZA** (el profe corrigió una dudosa): una fila por `(examen, numero)`.
- **200** `{"recibidas": 28, "reemplazadas": 2, "rechazadas": [{"numero": 41, "motivo": "numero_sin_estudiante"}]}`. `recibidas` incluye las reemplazadas.
- **Diferencia con el encargo:** una hoja con `dudosa` no tumba el lote con 422; se rechaza esa hoja. El 422 queda para un cuerpo que no cumple el esquema (incluido cualquier campo de más: no hay dónde meter una imagen).

### 1.4 Lo que NO hace
- **No mueve el nivel confirmado.** Guarda evidencia; `confirmed_levels` solo se escribe por su función (`ESPEC_eventos_anillo.md` §1.7), y este módulo no la llama.
- No acredita monedas ni XP.
- No recibe ni guarda imágenes.
- **No alimenta todavía los errores por ítem del panel (T7).** Mezclar hojas de papel con intentos de retos cambia una métrica que el profe ve sobre sus estudiantes: pasa primero por el pedagogo (ERR-16). Lo que sí queda es el dato, por ítem y por estudiante, listo para esa regla. Preguntas concretas para él en §7.

### 1.5 Migración (la siguiente libre; hoy sería la 038)
- `grader_list_numbers (tenant_id, group_id, profile_id, numero)`: UNIQUE `(group_id, numero)` y UNIQUE `(group_id, profile_id)`; `numero` de 1 a 9999.
- `grader_exams (id, tenant_id, group_id, codigo, huella, titulo, nivel, n_items, created_by, created_at)`: UNIQUE `(tenant_id, codigo)`.
- `grader_exam_items (exam_id, posicion, item_id, origen, nivel, destreza, tema, enunciado, correcta_texto, explicacion)`: UNIQUE `(exam_id, item_id)`.
- `grader_sheets (id, exam_id, tenant_id, profile_id, numero, forma, calificado_en, aciertos, total, enviada_por, recibida_en)`: UNIQUE `(exam_id, numero)`.
- `grader_sheet_items (sheet_id, item_id, estado, correcta, elegida_texto, resuelta_por)`: UNIQUE `(sheet_id, item_id)`; CHECK `estado IN ('marcada','vacia','doble')`.
- RLS activo y sin políticas en las cinco. Bajada: `DROP` de las cinco (se pierden exámenes y hojas).
- Las ediciones por la migración se enumeran con `git grep -n alembic_version -- tests` **el día que se implemente** (ERR-25).

## 2. Criterios
| # | Criterio | Test |
|---|---|---|
| C1 | **Contrato de `/auth/me`:** los 7 campos que lee el Grader existen con ese nombre y tipo (test de contrato, no-integ, sobre el esquema) | GR1 |
| C2 | **Lista:** 3 estudiantes → números 1, 2 y 3 en orden de matrícula; pedirla otra vez da los mismos; entra un cuarto → recibe el 4; sale el 2 → la lista trae 1, 3 y 4, y un quinto recibe el 5 (el 2 no vuelve) | GR2 |
| C3 | **Examen:** 201; otra vez igual → 200 y las mismas filas; otra `huella` → 409 y nada cambia; `n_items` que no coincide o un `item_id` repetido → 422 | GR3 |
| C4 | **Punta a punta:** un examen de 15 ítems y una hoja con 11 aciertos → `recibidas: 1`; hay 15 filas de ítems y la hoja dice 11 de 15 | GR4 |
| C5 | **Idempotencia:** la misma hoja 2 veces → 1 fila y `reemplazadas: 1`; corregida (un ítem cambia) → la fila refleja la corrección y sigue siendo 1 | GR5 |
| C6 | **Aislamiento, 3 instituciones:** el profe de X recibe 404 en la lista, el examen y los resultados de Y y de Z; el docente de X sin ese grupo, 404; el estudiante, 403. 0 filas escritas | GR6 |
| C7 | **No se confía en el cliente:** `aciertos: 15` con 3 errores → la hoja se rechaza; `dudosa` → se rechaza; `numero` sin estudiante → se rechaza; el resto del lote entra | GR7 |
| C8 | **Sin imágenes:** un campo de más en la raíz, en la hoja o en el ítem (con base64) → 422 y 0 filas | GR8 |
| C9 | **El nivel no se mueve:** `confirmed_level` idéntico antes y después de recibir resultados, con y sin nivel previo | GR9 |
| C10 | Migración up/down/up idéntica (ERR-24) | MG |

## 3. Tramposos (cada uno debe poner rojo su test)
| Id | Rompe | Test |
|---|---|---|
| ZG1 | Acepta resultados de un profe que no dicta el grupo | GR6 |
| ZG2 | Inserta en vez de reemplazar al reenviar | GR5 |
| ZG3 | Confía en `aciertos` sin recalcular | GR7 |
| ZG4 | Acepta `estado: dudosa` | GR7 |
| ZG5 | Recibir resultados escribe el nivel confirmado | GR9 |
| ZG6 | Acepta el mismo `codigo` con otra `huella` | GR3 |
| ZG7 | El número de quien salió se reutiliza | GR2 |
| ZG8 | El examen se busca sin la institución | GR6 |
| ZG9 | Un `doble` con `correcta: true` cuenta como acierto | GR7 |
| ZG10 | Lote todo o nada | GR7 |

La diagonal es PREDICHA; la matriz se mide antes de aceptar (ERR-15, 19 y 23). Humo: un grupo sintético de 28, un examen de 15 ítems, 28 hojas y 2 reenviadas, con semilla fija, que escribe `tests/_salida/humo_grader.json`. Réplica: 3 instituciones, formas A y B, una hoja con todo `vacia` y un examen de 1 ítem.

## 4. Cuentas (provisionales: se recalculan al implementar)
GR1 (no-integ) + GR2-GR9 (8 integ) + MG + humo + 10 tramposos = **20 integ y 1 no-integ**, más 1 réplica saltada.

## 5. Diferencias con el encargo de TESDER: qué debe ajustar el Grader
| Tema | Su encargo | Queda | Qué ajusta |
|---|---|---|---|
| Grupo que el profe no dicta | 403 | **404** (igual que "no existe") | tratar 404 como "sin acceso" |
| Hoja con `dudosa` | 422 del lote | la hoja va a `rechazadas` con `estado_invalido` | leer `rechazadas` |
| `numero` | "estable; confirmar dónde vive" | **no existía**: lo asigna el backend al pedir la lista | pedir la lista **antes** de imprimir, y no inventar números |
| `event_id` | `grd:{codigo}:{numero}` | igual; se valida | nada |
| Panel con % por ítem | "qué hace el backend" | **no en esta espec** (ERR-16) | nada; el dato queda guardado |
| Importar preguntas del profe por CSV | "para después" | para después | nada |
| Contrato de `/auth/me` | pide un test | GR1 | nada |

## 6. Qué NO se toca
`/auth/me` (solo se congela su contrato), T1-T7, `access.py`, el nivel confirmado, las monedas y `TESDER/`.

## 7. Para el pedagogo (ERR-16), antes de mostrar nada de esto en el panel
1. ¿Las hojas de papel entran al mismo indicador de errores por ítem que los retos, o van en uno aparte por examen?
2. ¿Un ítem `vacia` cuenta como error, o se muestra aparte?
3. ¿Qué mínimo de hojas hace falta para mostrar "la opción equivocada más elegida"?
4. ¿El estudiante ve su hoja con las explicaciones, o solo el profe?

## 8. Veredicto (cuando se implemente)
- **FUNCIONA:** las cuentas medidas, la matriz medida, el humo escrito y los previos verdes.
- **NO:** un profe ve o escribe en un grupo que no es suyo; una hoja queda dos veces; entra un `aciertos` falso o una `dudosa`; el nivel se mueve; un tramposo queda verde.

---

## 9. Ajuste del preregistro, escrito ANTES del código (2026-10-06, la sesión que implementa)
Nada medido se mueve: el código no existe. Donde esta sección y las anteriores difieran, vale esta.

### 9.1 De dónde parte
Sobre `8e6e277` (el generador apagado y el catálogo de nodos, `ESPEC_catalogo_nodos.md`): **500 passed + 19 skipped y 133 no-integ**. La migración es la **`039_grader`** (la 038 es el catálogo).

### 9.2 Cada ítem del examen lleva sus nodos (decisión 012 §6)
- `items[].nodos`: lista de 0 a 8 ids del mapa. **Opcional** (si falta, `[]`): un Grader que todavía no los manda sigue funcionando.
- Pasan por `curriculo.service.canonicos` (la única fuente): se guardan **los vigentes**; un reemplazado se guarda como su destino. Un id desconocido → **422 `nodo_desconocido`** con la lista, y **el examen no se registra** (0 filas). Con el catálogo sin cargar, un examen con nodos da 422; uno sin nodos entra.
- Se guardan en `grader_exam_items.nodos TEXT[] NOT NULL DEFAULT '{}'`.
- **Reapuntar:** `grader_exam_items` entra a `src/curriculo/reapuntar.py`. Si una carga posterior fusiona un nodo, los ítems ya guardados pasan al vigente en esa misma transacción.
- Un ítem sin nodos se guarda y se califica igual; solo no alimentará el refuerzo (`ESPEC_refuerzo.md`).

### 9.3 Precisiones del contrato
- `codigo`: `^[A-Za-z0-9_-]{1,32}$`. El de la ruta y el del cuerpo deben ser iguales; si no, 422 `codigo_no_coincide`.
- `huella`: 64 hexadecimales **en minúscula**.
- `nivel` (del examen y de cada ítem) ∈ A1, A2, B1, B2, C1, C2. `destreza` 1 a 64 caracteres; `tema` hasta 256; `enunciado` 1 a 4.000; `correcta_texto` y `explicacion` hasta 4.000; `titulo` 1 a 200; `forma` 1 a 8; `elegida_texto` hasta 1.000 o `null`.
- **Motivos de rechazo de una hoja**, en este orden (el primero que falle): `event_id_invalido`, `estado_invalido`, `items_no_coinciden` (los `item_id` no son exactamente los del examen), `total_no_coincide`, `aciertos_no_coinciden`, `resuelta_por_invalido` y `numero_sin_estudiante`.
- **`numero_sin_estudiante`** = ese número no está asignado en la lista del grupo. Un estudiante que salió del grupo **después** de recibir su número conserva la hoja (el examen se presentó): su número sigue reservado y la hoja entra.
- `correcta` se guarda como **acierto real**: `true` solo si `estado == "marcada"` y `correcta == true`. Un `doble` o `vacia` con `correcta: true` se guarda `false`.
- La misma hoja dos veces **en el mismo lote**: la segunda reemplaza a la primera (cuenta en `reemplazadas`).
- Lista: si el siguiente número pasaría de 9999, 409 `lista_llena`.
- El `GET` de la lista toma un candado sobre la fila del grupo: dos peticiones a la vez no reparten el mismo número.

### 9.4 Migración `039_grader`
Las cinco tablas de §1.5, con `grader_exam_items.nodos` (§9.2), `ON DELETE CASCADE` desde el examen y la hoja hacia sus ítems, y un índice GIN sobre `grader_exam_items.nodos`. RLS activo y sin políticas en las cinco.

**Ediciones a lo existente (ERR-25; `git grep -n alembic_version -- tests` de hoy):** `alembic_version` → `039_grader` en `tests/integ_db.py:66` y en los `HUMO_ESPERADO` de `tests/integ/test_humo_bug11.py:35`, `_bug13a15.py:44`, `_consentimiento.py:33`, `_autorregistro.py:35`, `_solicitudes_datos.py:34`, `_eventos_anillo.py:38` y `_catalogo_nodos.py:38`; `tablas_con_rls` 33 → 38; `tests/seguridad/test_sin_acceso.py` 34 y 34 → 39 y 39; `tests/teachers/test_access.py` gana las 3 rutas (`teacher`); `src/shared/models.py` (cinco modelos), `src/main.py` (el router), `src/curriculo/reapuntar.py` (una entrada) y `.gitignore` (el humo).

### 9.5 Tests (reemplaza la tabla de §2 donde difiera)
| Test | Criterios | Qué agrega este ajuste |
|---|---|---|
| GR1 (no-integ) | C1 | — |
| GR2 | C2 | — |
| GR3 | C3 | el `codigo` de la ruta distinto al del cuerpo → 422 |
| GR4 | C4 | `correcta` guardada como acierto real |
| GR5 | C5 | la misma hoja dos veces en un lote |
| GR6 | C6 | **el mismo `codigo` registrado en Y → 201 y no choca con el de X** |
| GR7 | C7 | cada motivo de §9.3 con su hoja; un `doble` con `correcta: true` no suma |
| GR8 | C8 | — |
| GR9 | C9 | — |
| GR10 | **C11 (nuevo):** los nodos de cada ítem se guardan vigentes; el reemplazado, como su destino; un desconocido → 422 y 0 filas; sin nodos, entra; una carga que fusiona un nodo reapunta el ítem | todo |
| MG39 | C10 | — |
| HG1 / RG1 | humo y réplica | — |

### 9.6 Tramposos (reemplaza la tabla de §3 donde difiera). Diagonal PREDICHA (ERR-23)
| Id | Rompe | Parche | Rojo predicho | Verde predicho y por qué |
|---|---|---|---|---|
| ZG1 | Acepta al profe que no dicta el grupo | `access._requiere_asignacion` → nunca (la fuente de la barrera, ERR-26) | **GR6** (as: DO recibe 200) | los demás usan al dueño del grupo o al admin |
| ZG2 | Inserta en vez de reemplazar | `service._guardar_hoja` con INSERT llano | **GR5** (as: 500, el UNIQUE lo frena) | GR4: una sola hoja |
| ZG3 | Confía en `aciertos` | `reglas.aciertos_de` devuelve lo declarado | **GR7** (as) | GR4 y GR5: sus `aciertos` son honestos |
| ZG4 | Acepta `dudosa` | `reglas.ESTADOS` con `dudosa` | **GR7** (as: 500; el CHECK de la base lo frena después) | — |
| ZG5 | Recibir resultados escribe el nivel | `service._guardar_hoja` llama además a `record_confirmed_level` | **GR9** (as) | — |
| ZG6 | Acepta otra `huella` | `service.misma_huella` → siempre | **GR3** (as: 200 en vez de 409) | — |
| ZG7 | El número de quien salió se reutiliza | `listas.siguiente_numero` = el menor libre entre los activos | **GR2** (as) | — |
| ZG8 | El examen se busca sin la institución | `service._examen` sin `tenant_id` | **GR6** (as: el mismo `codigo` en Y da 409 o 200 en vez de 201) | las hojas de Y contra el examen de X siguen en 404 por la barrera del grupo (segunda barrera; se declara) |
| ZG9 | Un `doble` con `correcta: true` cuenta | `reglas.es_acierto` = `correcta` | **GR7** (as) | GR4: sin dobles marcados correctos |
| ZG10 | Lote todo o nada | `service.recibir` rechaza el lote si hay una hoja mala | **GR7** (as) | los lotes sin rechazos |
| ZG11 | Los nodos se guardan sin resolver | el servicio guarda `item.nodos` tal cual | **GR10** (as: queda el reemplazado y entra el desconocido) | GR3-GR9: sus ítems no llevan nodos |
| ZG12 (no-integ) | `/auth/me` renombra `must_change_password` | `ProfileOut` sin ese campo | **GR1** (as) | — |
| ZG13 | La carga no reapunta los ítems del examen | la entrada de `reapuntar.TABLAS` no hace nada | **GR10** (as) | MN1-MN3: sin exámenes |

**Tramposos existentes sobre el camino tocado (ERR-26; `git grep -n "access_mod\|level_mod" -- tests/tramposos` de hoy):** ZR10 (`test_tramposos_autorregistro.py:218`) y los dos de `test_tramposos_grupos.py:252` y `:257` parchean `access` (`_requiere_asignacion` y `_base_stmt`); ZE11 y ZE13 (`test_tramposos_eventos.py:229` y `:235`) parchean `level`. Este bloque **no edita** `access.py` ni `level.py`: los usa. Predicción: los cinco siguen rojos por su razón; sus tests no llaman a `/grader`.

**Matriz a medir:** 12 tramposos integ × 11 columnas (GR2-GR10, MG39 y HG1) = **132 celdas**, más RG1 con la bandera.

### 9.7 Cuentas (reemplaza §4)
| Grupo | integ | no-integ |
|---|---|---|
| GR2-GR10 | 9 | — |
| MG39 y HG1 | 2 | — |
| GR1 | — | 1 |
| ZG1-ZG11 y ZG13 | 12 | — |
| ZG12 | — | 1 |
| **Nuevos** | **23** | **2** |
| RG1 (saltado sin bandera) | 1 skipped | — |

**passed:** 500 + 25 = **525**; **skipped:** 19 + 1 = **20**; **no-integ:** 133 + 2 = **135**; ruff 0 y mypy 0.

### 9.8 Humo y réplica (precisa §3)
**HG1** escribe `tests/_salida/humo_grader.json` antes de afirmar. Semilla `random.Random(39)`: 28 estudiantes, un examen de 15 ítems (5 con nodos del catálogo sintético), 28 hojas con respuestas al azar y 2 reenviadas con una corrección.
```json
{"alembic_version":"039_grader","semilla":39,"lista":28,"examen":201,"examen_otra_vez":200,
 "primer_envio":{"recibidas":28,"reemplazadas":0,"rechazadas":0},
 "reenvio":{"recibidas":2,"reemplazadas":2,"rechazadas":0},
 "hojas":28,"items":420,"aciertos_totales":"A","con_nodos":5,"nivel_escrito":0,"monedas_movidas":0}
```
`A` sale de la semilla: se fija al medir el humo por primera vez con el código bueno, y desde ahí no se mueve.

**RG1** (`ENGRAMA_REPLICA_GRADER=1`): tres instituciones con el mismo `group_code` y el mismo `codigo`; formas A y B; una hoja con todo `vacia`; un examen de 1 ítem; y un examen de 200 ítems.
