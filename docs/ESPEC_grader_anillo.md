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
