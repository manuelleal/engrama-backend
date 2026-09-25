# ESPEC · Grupos y panel docente (MVP para un grupo real)

F4 · Creador · 2026-09-25 · preregistro. Rama `test/fixture-integ`, base `d77dcb4`. Brechas 1, 2 y 8 de `investigacion/paridad/01`, y la 4 solo en inscripción.

**Corregido por ERR-16 (2026-09-25)** sobre `f4d930b`, con la validación del pedagogo (`investigacion/pedagogia/01-panel-docente.md`). Cambian §0 (hechos nuevos), §1, T2, T5, la ruta nueva T7, §2.1-§2.4, §3, §4, §5, §6, §7 y §8. **T5 y T7 no se implementan hasta que el coordinador anote en §2.4 la respuesta del pedagogo.** El resto (T1-T4, T6, M1-M4) sigue su curso.

**Corregido por ERR-19 (2026-09-25)** con lo MEDIDO (regla 8): la matriz de `tests/_salida/matriz_tramposos_grupos.json` y los hallazgos H-1, H-2, H-3 y H-5 del auditor. Cambian §2 (nota en M3), §3 (la diagonal pasa a tener una columna medida), §4 (cuentas), §6 (BUG-11, **bloqueante para producción**) y §8. Ninguna regla de negocio cambia; lo que se corrige es la predicción y la cuenta.

## 0. Medido (contenedor propio desechable, puerto 55499, `.venv` oficial)
- **163 passed**, **76** no-integ, ruff 0, mypy 0; **20** rutas APIRoute.
- Ningún router usa `require_admin` (`src/shared/deps.py:98`); `src/teachers/*.py` tienen 0 líneas.
- Estudiante ↔ grupo por `memberships.group_code` (`003_create_memberships.py:26`), con `UNIQUE (tenant_id, profile_id)` (`:31`): un grupo por colegio.
- `attendance_sessions.status` ∈ {active, expired, cancelled} (`008:34`). Un check-in sobre una sesión no `active` da 410 (`attendance.py:248`).
- `weak_skills` nunca se escribe: `grep weak src/` solo encuentra `models.py:512` y `:625`.
- `profiles.id` no tiene FK a `auth.users`. `python-multipart` no está instalado.
- **Hueco existente:** un docente del mismo colegio sin `teacher_groups` recibe 201 en `POST /core/attendance/sessions` y en `POST /challenges/` con el `group_id` de otro grupo. Desde otro colegio: 404 y `[]`.

**Hechos nuevos. Corregido por ERR-16 (2026-09-25).** Salen de leer el código con `grep -n` en `f4d930b`, sin ejecutarlo:
- **El acierto por ítem sí existe.** `submit_attempt` guarda en `challenge_attempts.answers` (`attempts.py:253`) la lista de `grade_answers` (`:64`), con una entrada por pregunta: `{question_id, given_answer, correct_answer, is_correct}` (`:93`, `:95`). Un envío trae todas las preguntas (`:212`).
- **No existe nivel MCER por estudiante ni por grupo.** `profiles.level` es un entero de XP (`models.py:109`). `memberships` (`:137`) y `groups` (`:173`) no tienen nivel. `student_progress.cefr_level` (`:614`) nunca se escribe: `grep -rn "student_progress|StudentProgress" src` sin `models.py` da 0. Solo el reto tiene nivel: `challenges.cefr_level` (`:404`, nullable). Las preguntas no lo tienen.
- **La skill es del reto, no del ítem:** `challenges.skill` (`:405`) es texto libre y nullable. El generador documenta `grammar | vocabulary | reading | listening | writing` (`schemas.py:84`).
- **`require_teacher` deja pasar al admin** (`deps.py:90`). Con `visible_groups`, un admin ve todos los grupos del colegio.
- **`correct_answer` mezcla dos convenciones:** el generador guarda el *value* de la opción (`generator.py:86`) y `tests/challenge_engine/test_challenges.py:195` guarda la *label* (`"B"`). `grade_answers` compara el texto sin traducir de una a otra.
- **El ayudante de integ no siembra lo que T5 y T7 necesitan:** `crear_challenge` (`integ_ayudante.py:230`) no recibe `skill` ni `cefr_level`, y `crear_intento` (`:276`) deja `answers=[]` y `completed_at=now()`.

## 1. Qué cambia (una cosa)
Nacen `/teachers` (**7 rutas**) y `/admin` (4 rutas) en `src/teachers/`, con `router.py`, `admin_router.py`, `schemas.py` y `service/{access,panel,roster,achievement,item_errors}.py`, montados en `main.py`. *(Corregido por ERR-16 (2026-09-25): eran 6 rutas y 3 servicios.)*

Toda la autorización pasa por **un solo punto**, `visible_groups(auth, only_assigned=False)`: grupos de `auth.tenant_id`, todos si `is_admin`, y si no, solo los que `teacher_groups` asigna a `auth.profile_id`. `authorize_group(db, auth, gid, only_assigned=False)` = ese filtro más `id = gid`; sin resultado, 404.

**Con `only_assigned=True`, el filtro de `teacher_groups` se aplica también al admin.** Lo usan T5 y T7, que muestran aprendizaje: solo los ve el docente del grupo (pedagogo, Riesgos). *Corregido por ERR-16 (2026-09-25).*

**Sin migración:** las tablas y el status `expired` ya existen, y el backend escribe como `service_role` (decisión 005). El filtro MCER de T5 **sí** necesitaría una migración, y por eso queda fuera (§2.1).

## 2. Qué debe pasar
| # | Ruta | Contrato |
|---|---|---|
| T1 | `GET /teachers/groups` | `visible_groups`: id, group_code, n.º de estudiantes |
| T2 | `GET …/groups/{gid}/students` | *Corregido por ERR-16 (2026-09-25).* Estudiantes del grupo (membresía `student` activa con el `group_code` del grupo), **ordenados por `full_name` y luego por `profile_id`**. Por estudiante: `profile_id`, `full_name`, `consistency: {"label": "constancia", "current_streak": n}` y la última asistencia a sesiones de **ese** grupo. **Sin saldo** (§2.2). Sin `documento_id` ni `pin_hash`. No escribe nada |
| T3 | `POST …/{gid}/attendance-sessions` | `{duration_minutes}` → 201; reusa `create_session` sin tocarla |
| T4 | `POST …/attendance-sessions/{sid}/close` | `status='expired'`, `expires_at=now()`. Sesión de otro grupo → 404. El check-in posterior da 410 |
| T5 | `GET …/{gid}/achievement` | *Corregido por ERR-16 (2026-09-25).* Logro por eje de cada estudiante del grupo, con la regla de §2.1. Usa `only_assigned=True`. Sin `answers`, sin monedas, sin `weak_skills` |
| T6 | `PUT …/{gid}/challenges/{cid}` | fija `group_id`. El reto debe ser del colegio y estar sin grupo o en un grupo visible; si no, 404 |
| T7 | `GET …/{gid}/item-errors` | *Nueva, por ERR-16 (2026-09-25).* Indicador n.º 1 del pedagogo: los ítems con más error del grupo y su distractor más elegido, en agregado (§2.3). Usa `only_assigned=True` |
| M1 | `POST /admin/groups` | `{group_code, max_capacity?}` → 201; código repetido → 409 |
| M2 | `POST /admin/groups/{gid}/teachers` | `{documento_id}` con membresía `teacher` activa en el colegio → 201 (200 si ya estaba); si no, 404 |
| M3 | `POST …/{gid}/students` | `{documento_id, nombre_completo}`. Crea el perfil si falta (uuid4, `pin_hash=''`); si existe, lo reusa sin pisar el nombre (*ERR-19: esto, con `documento_id` UNIQUE global, es BUG-11, §6*). 201 inscrito · 200 ya estaba · 409 si está en otro grupo, con otro rol o inactivo. Solo devuelve profile_id, documento_id y resultado |
| M4 | `POST …/{gid}/students/import` | cuerpo `text/csv` UTF-8, BOM opcional, separador `,` o `;`. Cabecera `documento_id,nombre_completo` (`coins-mvp/app.js:3538`); el resto se ignora y `pin` nunca se guarda. ≤ 500 filas. **Todo o nada:** documento fuera de `^[A-Za-z0-9_-]{3,32}$` (`app.js:300-305`), nombre vacío, fila repetida o en otro grupo → 422 `[{fila, motivo}]` y 0 escrituras. Reimportar da `creados 0` |

T usa `require_teacher` más `authorize_group`; M usa `require_admin` más `authorize_group`. Rol equivocado → **403 exacto**; recurso de otro grupo o colegio → **404 exacto**.

### 2.1 Regla de logro de T5 (Corregido por ERR-16, 2026-09-25)
Reemplaza a `weak_skills = [skill] si el intento completo falló`. Aquel campo no sale en la API y la columna no se escribe. Todo se calcula con los datos que ya existen (§0), en funciones puras de `service/achievement.py` que reciben `now` como parámetro.

1. **Unidad: el ítem en primer intento.** El primer intento de un estudiante en un reto es su intento `completed` con el `completed_at` más antiguo; si empatan, gana el menor `started_at` y luego el menor `id`. Se elige **sobre toda la historia, antes de aplicar la ventana**.
   - `in_progress` y `abandoned` no cuentan. La retroalimentación solo se revela al enviar (`attempts.py:282`), así que un intento sin envío no la vio.
   - Cada entrada de `answers` de ese intento es un ítem, y `is_correct` es su acierto.
2. **Ventana de 28 días:** cuenta el ítem si ese primer intento tiene `completed_at >= now - 28 días` (el borde entra). Si el primer intento es más viejo, ese reto no aporta ítems, **aunque haya un reintento reciente**.
3. **Alcance:**
   - retos con `group_id = gid`: los de todo el colegio (`group_id NULL`) no cuentan;
   - estudiantes del roster de T2;
   - se excluyen los retos `challenge_type = 'open'`, porque su acierto por ítem es una coincidencia exacta de texto libre (`attempts.py:64-95`) y no mide dominio.
4. **Paso de skill a eje: un mapeo fijo, declarado.** La skill del reto se pasa a minúsculas y sin espacios, y se aplica esta tabla:

   | skill | eje |
   |---|---|
   | `reading`, `listening` | Comprehension |
   | `writing`, `speaking` | Expression |
   | `grammar`, `vocabulary` | Accuracy |

   Cualquier otra skill, o `NULL`, no entra en ningún eje: se cuenta en `unmapped_items`. La respuesta lo dice en `method.axis_mapping`: "fijo por la skill del reto".
5. **Mínimo por eje:** 8 ítems o más, de 3 retos distintos o más. Si no se cumple, `status = "datos_insuficientes"`.
6. **Umbrales,** calculados con enteros (`100*correct` contra `80*items` y `60*items`), nunca con float:
   - 80 % o más → `logrado`;
   - de 60 % a menos de 80 % → `en_desarrollo`;
   - menos de 60 % → `a_reforzar`.
7. **Filtro MCER (recortado).** El pedagogo pide contar solo los ítems de nivel igual o menor que el asignado, pero **ese campo no existe** (§0). Hoy no se aplica, y queda explícito:
   - `method.cefr_filter = "no_aplicado: no existe nivel MCER asignado por estudiante"`;
   - cada eje lleva `cefr_levels`, el conteo de sus ítems por `challenges.cefr_level` (`"sin_nivel"` si es NULL), para que el docente vea contra qué se midió.

   Aplicar el filtro exige una migración (p. ej., `memberships.cefr_assigned` con el CHECK de los 11 niveles), y va a "para después".

**Respuesta de T5:**
- **`method`,** una constante: `window_days 28`, `first_attempt_only true`, `min_items 8`, `min_challenges 3`, `thresholds {logrado 80, en_desarrollo 60}`, `excluded_types ["open"]`, `axis_mapping` y `cefr_filter`.
- **`students`,** en el orden de T2. Cada estudiante trae:
  - `profile_id` y `full_name`;
  - `axes`: siempre 3, en el orden Comprehension, Expression, Accuracy. Cada uno con `axis`, `status`, `label`, `items`, `correct`, `challenges` y `cefr_levels`;
  - `skills` (detalle): `skill`, `axis` o null, `items` y `correct`, ordenadas por `skill`;
  - `unmapped_items`;
  - `attempts` (detalle): los intentos `completed` del alcance dentro de la ventana, ordenados por `completed_at`, con `challenge_id`, `title`, `skill`, `score_percent`, `is_correct`, `completed_at` y `first_attempt`.

### 2.2 Decisiones de T2 (Corregido por ERR-16, 2026-09-25)
- **El saldo se quita del roster y no se abre ahora un bloque "Economía".** Las razones:
  - El saldo no es desempeño: incluye la asistencia, y `max_winners` premia la velocidad (pedagogo; constitución §5).
  - En esta espec ninguna acción del docente depende del saldo: la tienda, las subastas y las monedas manuales están fuera de alcance (§6).
  - Ley 1581: con menores, el acceso es mínimo y no se expone lo que no tiene uso.
  - Se quita un camino de código (`get_balance`) y el riesgo de crear wallets al leer.

  "Economía" entra con la espec de la tienda, en su propia ruta. Es reversible.
- **La racha va dentro de `consistency`, con `label = "constancia"`,** para que la interfaz no la presente como desempeño.
- **El orden es alfabético,** nunca por racha ni por ninguna métrica. Lo mismo vale para T5.

### 2.3 Indicador n.º 1: T7 (Nuevo por ERR-16, 2026-09-25)
**Se puede calcular hoy:** `answers` guarda `given_answer` y `is_correct` por ítem (§0), y `challenge_questions.options_json` guarda las opciones `[{label, value}]`.

- **Alcance:** el mismo de §2.1, puntos 1 a 3 (primer intento, 28 días, retos del grupo, roster de T2, sin `open`). Se agrupa por `question_id`, uniendo con `challenge_questions`; un ítem cuya pregunta ya no existe se omite.
- **Por ítem:** `challenge_id`, `title`, `question_id`, `order_index`, `question_text`, `skill`, `axis`, `respondents` (estudiantes distintos), `errors` y `top_distractor`.
- **Distractor:**
  1. Se normaliza la respuesta (`strip().lower()`) y se compara primero con el `value` de cada opción y después con su `label`.
  2. Solo cuentan las respuestas incorrectas que caen en una opción. La vacía no cuenta, y la que no coincide con ninguna opción tampoco.
  3. **Nunca cuenta la opción que coincide con `correct_answer`** (por `value` o por `label`): por la mezcla de convenciones de §0, una respuesta calificada incorrecta puede señalar a la correcta.
  4. Gana la opción más elegida; si empatan, la primera en `options_json`. Sin opciones o sin coincidencias → `null`. Se devuelve `{label, value, count}`.
- **Agregado, sin exponer a nadie:** un ítem con menos de **5** respondientes no se muestra y se cuenta en `suppressed_items`. No sale ningún `profile_id` ni ninguna respuesta individual.
- **Orden:** tasa de error descendente, comparada como fracción exacta (`errors/respondents`), luego `errors` descendente, luego `title` y luego `order_index`. Los ítems se ordenan; los estudiantes no aparecen.
- **Respuesta:** `{method: {window_days 28, first_attempt_only true, min_respondents 5, excluded_types ["open"]}, items: [...], suppressed_items: n}`.

### 2.4 Lenguaje y preguntas al pedagogo (Corregido por ERR-16, 2026-09-25)
- **Lenguaje:**
  - En ninguna respuesta de `/teachers` aparece `weak`, `débil` ni `debil`, ni en claves ni en valores.
  - La etiqueta la arma el servidor: `label = "a reforzar: <eje>"`. Por simetría, las demás son `"logrado: <eje>"`, `"en desarrollo: <eje>"` y `"datos insuficientes: <eje>"`.
  - No hay campos de posición, ranking ni percentil.
- **Bloqueo de T5 y T7.** Son recortes del Creador y, por la regla de ERR-16, el pedagogo los valida antes de implementar. El coordinador anota aquí cada respuesta (sí / no + nota):
  - **P1:** sin nivel asignado, ¿se da el estado por eje sin el filtro MCER y con `cefr_levels` a la vista? Si la respuesta es no, T5 devuelve `items`, `correct` y `cefr_levels` sin `status` ni `label` hasta la migración.
    → **Pedagogo (2026-09-25): SÍ CON CAMBIO.**
      - T5 agrega `method.status_scope = "desempeño en los retos asignados al grupo; no es nivel MCER del estudiante"`, constante; F5 lo afirma.
      - Ninguna vista muestra `status` ni `label` de un eje sin su `cefr_levels` al lado.
  - **P2:** ¿el mínimo de 8 ítems y 3 retos se aplica por eje?
    → **Pedagogo: SÍ.** Es una señal formativa, no una nota: con n = 8 el intervalo de Wilson al 95 % es de ±26 puntos. La banda de confianza, o subir el mínimo a 12, va a "para después".
  - **P3:** ¿se excluyen los retos `open`?
    → **Pedagogo: SÍ.** El acierto es texto exacto. `fill_blank` entra, pero con el mismo sesgo hacia "a reforzar"; va a "para después".
  - **P4:** ¿basta un mínimo de 5 respondientes por ítem en T7?
    → **Pedagogo: SÍ CON CAMBIO.**
      - T7 agrega por ítem `blank_answers` (primeros intentos con `given_answer` vacía). `errors` los sigue incluyendo.
      - La interfaz muestra `errors - blank_answers` como "errores con respuesta".
      - U6 o F13 afirman el conteo.
  - **P5:** ¿quedan fuera los retos de todo el colegio (`group_id NULL`)?
    → **Pedagogo: SÍ.** Que el reto esté asignado al grupo es la única señal de calibración mientras no exista el nivel MCER asignado. Se reabre junto con P1.

  **Resultado:** T5 y T7 quedan **DESBLOQUEADOS** con los cambios de P1 y P4. No requieren migración ni cambian la matriz de tramposos.

  **Condición antes del primer grupo real, no bloqueante hoy:** la mezcla de *label* y *value* en `correct_answer` contamina `is_correct` en T5 y `errors` en T7. Hay que fijar el contrato de envío por *label* o recalcular el acierto por opción al leer.

  Si una respuesta cambia la regla, se corrige esta espec **antes** de implementar (regla 8), no después.

## 3. Matriz rol × ruta (tests A por la API)
Actores:
- **D**: docente dueño de GA (colegio A);
- **E**: estudiante de GA;
- **DO**: docente de A sin GA;
- **DT**: docente de B;
- **DM**: D con membresía también en B, llamando con `X-Tenant-ID: B`;
- **AA** y **AB**: admin de A y de B.

*Corregido por ERR-16 (2026-09-25): se agregan T7 y la fila de AA en T5 y T7.*

| Ruta | Prohibidas (1 test cada una) | Control |
|---|---|---|
| T1 | E 403 · DO, DT, DM, AB: 200 **sin GA** | D |
| T2, T3, T4, T6 | E 403 · DO, DT, DM, AB 404 | D; AA en T2 |
| T5, T7 | E 403 · DO, DT, DM, AB, **AA** 404 | D |
| M1 | E 403 · D 403 | AA |
| M2-M4 | E 403 · D 403 · AB 404 | AA |

Son **48 prohibidas** (5 + 5×4 + 6×2 + 2 + 3×3 = 5 + 20 + 12 + 2 + 9 = 48) y **12 controles** (T1 1 + T2 2 + T3, T4, T5, T6 y T7 1 cada una + M1 1 + M2-M4 3 = 1 + 2 + 5 + 1 + 3 = 12). Cada escritura prohibida afirma además que no escribió nada.

**Cómo quedaron escritos (medido; corregido por ERR-19, 2026-09-25).** Las 48 prohibidas son 48 funciones. De los 12 controles, **10 se fusionaron** dentro del test F de su ruta (D en F1, F2, F3, F4, F5 y F13; AA en F7, F8, F9 y F10) y **2 quedaron aparte** (`test_t2_control_aa` y `test_t6_control_d_reasigna_reto_sin_grupo`). Además nació **1 test fuera de la espec**, `test_m2_documento_sin_membresia_docente_404` (la rama "si no, 404" de M2). Cuenta: `grep "def test_" tests/teachers tests/integ/test_humo_grupos.py`. *El auditor (H-5) habló de 8 controles fusionados; con 8 la suma da 78 integ y no los 77 medidos. Con 10 + 1 extra cierra exacto (§4).*

**Tramposos y diagonal PREDICHA** (ERR-15). Al escribir esta corrección, el implementador iba en el paso 2 de §7: `service/access.py` y `service/panel.py`, sin `only_assigned` y sin T2, T5 ni T7. Ninguna celda de las reglas nuevas se pudo medir. *Corregido por ERR-16 (2026-09-25): X9 se redefine, se agregan X10-X21 y cambia el rojo de X1 y X2.*

*Corregido por ERR-19 (2026-09-25): la columna "Rojo predicho" se conserva tal cual se escribió antes de medir (no se mueve el criterio); solo se tachan las celdas **inalcanzables** por mecanismo. La columna "Rojo medido" copia `tests/_salida/matriz_tramposos_grupos.json`. En **negrita**, lo que difiere de la predicción.*

| Tramposo | Rojo predicho | Rojo medido (ERR-19) | Archivo |
|---|---|---|---|
| X1 `visible_groups` sin colegio | DM×T1-T7; AB×{T1, T2, T3, T4, T6}; AB×M2-M4; F1. **No** AB×T5 ni AB×T7: `only_assigned` los sigue protegiendo | DM×{T1, T2, T5, T7}; AB×{T1, T2, M3, M4}. **No se ponen rojos: DM y AB × {T3, T4, T6}** (defensa en profundidad, nota 1); **AB×M2** (test defectuoso, H-1; se re-mide, nota 2); **F1** (nota 3) | integ |
| X2 sin `teacher_groups` (también anula `only_assigned`) | DO×T1-T7, AA×T5, AA×T7, F1 | DO×T1-T7, AA×T5, AA×T7, **F6** (no previsto, nota 4). **F1 no** (nota 3) | integ |
| X3 `/teachers` con `get_current_user` | E×T1-T7, ~~U4~~ (inalcanzable, nota 5) | E×T1-T7 | integ |
| X4 `/admin` con `require_teacher` | D×M1-M4, ~~U4~~ (inalcanzable, nota 5) | D×M1-M4 | integ |
| X5 `close` no cambia el status | F4, F12 | F4, F12 | integ |
| X6 T5 sin filtro de grupo | F5 | F5, **F13** (no previsto, nota 6) | integ |
| X7 T6 no revisa el grupo actual | F6 | F6 | integ |
| X8 CSV escribe antes de fallar | F11 | F11 | integ |
| X9 T2 incluye `balance` | F2 | F2 | integ |
| X10 T5 y T7 con `only_assigned=False` | AA×T5, AA×T7 | AA×T5, AA×T7 | integ |
| X11 usa el último intento, no el primero | U3a, F5 | U3a, **U3b** (no previsto, nota 7). F5: **no medido** (nota 8) | no-integ |
| X12 aplica la ventana antes de elegir el primer intento | U3b · F5? | U3b. F5: no medido (nota 8) | no-integ |
| X13 mínimo sin la condición de 3 retos | U3c · F5? | U3c. F5: no medido | no-integ |
| X14 umbral de 80 exclusivo (`>`) | U3d · F5? | U3d. F5: no medido | no-integ |
| X15 una skill desconocida cae en Accuracy | U3e · F5? | U3e. F5: no medido | no-integ |
| X16 incluye los retos `open` | U3g · F5? · F13? | U3g. F5 y F13: no medidos | no-integ |
| X17 T5 serializa `weak_skills` | F5, ~~U3f~~ (inalcanzable, nota 5) | F5 | integ |
| X18 T5 ordena por logro | F5 | F5 | integ |
| X19 el distractor cuenta la opción correcta | U5 · F13? | U5. F13: no medido | no-integ |
| X20 T7 sin la supresión de menos de 5 | U6, F13 | U6. F13: **no medido** (nota 8) | no-integ |
| X21 T7 sin filtro de grupo | F13 | F13, **F5** (no previsto, nota 6) | integ |

`F5?` y `F13?` marcan un cruce **posible**: X12-X16, X19 y X20 alteran funciones que F5 o F13 comparten, y según ERR-15 se dan por cruzados hasta que la matriz demuestre lo contrario. Que crucen depende de la siembra de F5 y F13 (§4).

**Notas de la medición (ERR-19, 2026-09-25):**
1. **X1 en T3, T4 y T6 es defensa en profundidad, no un hueco.** Aunque `visible_groups` pierda el filtro de colegio y `authorize_group` deje pasar GA a DM o a AB, cada una de esas rutas tiene una verificación de tenant **independiente y redundante** que devuelve 404:
   - T3: `create_session` recibe `tenant_id=auth.tenant_id` (`router.py:89-92`, `panel.py:103-107`) y resuelve el grupo por `(tenant_id, group_code)` (`attendance.py:132-141`); no encuentra "GA" en B. **Ojo:** esta segunda barrera es por *código*, no por id. Si B tuviera un grupo con el mismo código que GA (el caso de la réplica), con X1 el POST daría 201 y abriría la sesión en el grupo homónimo de B: no filtra datos de A, pero tampoco es un 404. Solo ocurre con `visible_groups` roto;
   - T4: la sesión se busca con `AttendanceSession.tenant_id == auth.tenant_id` (`panel.py:124-127`) **antes** de `authorize_group`;
   - T6: `get_challenge(db, cid, auth.tenant_id)` (`panel.py:154`) no encuentra en B un reto de A.

   Los tests de esas celdas están bien; lo que estaba mal era la predicción. T2, T5 y T7 sí se ponen rojos porque, pasado `authorize_group`, leen con `group.tenant_id`, que es el de A. Así, `visible_groups` es la única barrera de tenant en T1, T2, T5, T7 y M2-M4, y una de dos en T3, T4 y T6.
2. **AB×M2:** el test de la espec original mandaba `documento_id: "x"`, que da 404 en la búsqueda de `assign_teacher` sin llegar a probar el aislamiento. H-1 lo cambia por el `documento_id` real de DT. La celda X1 × AB×M2 **se re-mide** tras H-1: `<pendiente>`.
3. **F1 no puede ponerse rojo con X1 ni con X2 dada su siembra.** `armar` (`tests/teachers/_actores.py`) crea un solo grupo por colegio y asigna a D solo a GA. Con X1, el filtro de `teacher_groups` sigue dejando a D solo con GA; con X2, el colegio A no tiene otro grupo que ver. Lo que F1 iba a vigilar lo vigilan ya las celdas DM×T1, AB×T1 (X1) y DO×T1 (X2), que sí se pusieron rojas. Candidato para después: sembrar un segundo grupo en A si se quiere que F1 discrimine.
4. **X2 → F6:** F6 siembra un reto en GC, un grupo de A que D no tiene asignado. Sin `teacher_groups`, GC pasa a ser visible para D y el PUT reasigna el reto (200 en vez de 404). Es la misma regla que X7 ataca desde otro punto.
5. **Celdas inalcanzables:** U4 (`test_u4_*`) y U3f son introspección **estática** (la tabla de guardas de `app.routes` y los `model_fields` de los esquemas). X3 y X4 rompen con `app.dependency_overrides`, y X17 reemplaza el endpoint con `_reemplazar_ruta`: ninguno de los dos mecanismos cambia lo que U4 o U3f inspeccionan. En lugar de U4, H-3 agrega `test_h3_sin_overrides_de_dependencias_filtrados` (`tests/teachers/test_access.py`), no-integ, que afirma `app.dependency_overrides == {}`: vigila que un tramposo no deje una guarda anulada para el resto de la suite. No es una celda de X3 ni de X4: es la condición para que su matriz sea válida.
6. **X6 y X21 son el mismo parche** (`achievement_mod.intentos_del_grupo` sin filtro de `group_id`). `item_errors.build_response` llama a esa función, así que el hueco se ve por T5 (F5) y por T7 (F13). Los dos tramposos tienen la misma diagonal medida; se conservan porque cada uno declara un test real distinto.
7. **X11 → U3b:** la segunda mitad de U3b siembra un primer intento fuera de la ventana y un reintento dentro. Con el último intento, entra el reintento: U3b se pone rojo por la misma razón que U3a.
8. **No medido no es "no cruza".** La sección `no_integ` del JSON solo registra tests no-integ. F5 afirma `correct == 0` para el estudiante con el primer intento fallado y el reintento acertado, así que con X11 **tendría** que ponerse rojo; que el JSON no lo registre indica que F5 y F13 no se corrieron bajo X11-X20. Esas celdas quedan como **no medidas**, y las `?` de ERR-15 siguen dándose por cruzadas.

Los 163 previos no importan código nuevo. **Antes de aceptar** se mide la matriz completa y se escribe aquí: 21 tramposos × 85 tests nuevos (12 U + 13 F + 48 prohibidas + 12 controles) = **1.785 celdas**. Un cruce no previsto se corrige por ERR (regla 8).

*Corregido por ERR-19 (2026-09-25):* los tests nuevos no tramposos son **77 hoy** (13 no-integ: U1, U2, U3a-U3g, U4 en 2 funciones, U5 y U6; 64 integ: 13 F, 48 prohibidas, 2 controles aparte y 1 extra), más 1 de H-3. La matriz completa es **21 × <tests nuevos no tramposos tras H-1 y H-3>** = `<pendiente>` celdas, y **no está medida entera**: faltan las celdas de la nota 8 y la de la nota 2.

## 4. Tests y cuentas (Corregido por ERR-16, 2026-09-25)
- **no-integ (12 tests):**
  - U1: CSV válido (`,`, `;`, BOM);
  - U2: CSV con errores;
  - U3a: el primer intento manda y el reintento no cuenta;
  - U3b: la ventana, en el borde exacto de 28 días (entra) y 28 días + 1 s (sale); un primer intento fuera de la ventana no deja entrar al reintento;
  - U3c: el mínimo: 7 ítems de 3 retos y 8 ítems de 2 retos dan `datos_insuficientes`, y 8 ítems de 3 retos dan un estado;
  - U3d: los umbrales, con n = 10: 8 → logrado, 7 y 6 → en desarrollo, 5 → a reforzar;
  - U3e: el mapeo: `" Reading "` y `"GRAMMAR"` se normalizan; `"pronunciation"` y NULL van a `unmapped_items`;
  - U3f: el lenguaje: ningún campo de los esquemas de T2, T5 ni T7 contiene `weak`, `débil` ni `debil`, y la etiqueta es `"a reforzar: Expression"`;
  - U3g: un reto `open` no aporta ítems;
  - U4: las 20 rutas previas idénticas, más las **11** nuevas con su guarda;
  - U5: el distractor: gana el más elegido; empate por el orden de las opciones; la opción correcta (por label) no cuenta; la respuesta vacía o fuera de las opciones no cuenta; sin opciones da `null`;
  - U6: la supresión: 4 respondientes → suprimido; 5 → visible.
- **Tramposos no-integ (8):** X11-X16, X19 y X20, en `tests/tramposos/test_tramposos_logro.py`, sin `pytestmark`, con el patrón de `test_tramposos_como.py`.
- **integ:**
  - F1-F6: T1-T6;
  - F7-F11: M1, M2, M3, M4 en lote idempotente y M4 inválido sin escrituras;
  - F12: humo;
  - F13: T7;
  - 48 prohibidas, 12 controles y 13 tramposos (X1-X10, X17, X18 y X21).
- **Siembra obligatoria:**
  - **F5** siembra:
    - un estudiante con un primer intento fallado y un reintento acertado (X11);
    - un reto de otro grupo del mismo colegio (X6);
    - dos estudiantes cuyo orden alfabético es el inverso de su logro (X18).

    Afirma el orden alfabético, `method` constante, la ausencia de monedas y la ausencia de `weak`, `débil` y `debil` en el cuerpo (X17). **No** siembra bordes de ventana, de mínimo, de umbral, skills desconocidas ni `open`: así se predice que X12-X16 no cruzan F5.
  - **F13** siembra:
    - un ítem con 5 respondientes y 3 errores, 2 de ellos en la misma opción incorrecta;
    - un ítem con 4 respondientes (X20);
    - un reto de otro grupo con 5 o más respondientes (X21).

Cuentas: **163 + 12 + 8 + (13 + 48 + 12 + 13) = 163 + 12 + 8 + 86 = 269 passed**, 0 failed, 0 xfail. No-integ: **76 + 12 + 8 = 96**. ruff 0, mypy 0, ningún archivo pasa de 400 líneas. *(Antes: 240 y 80.)*

**Cuentas medidas (corregido por ERR-19, 2026-09-25).** Las de arriba quedan como predicción. Lo medido antes de H-1 y H-3 fue **261 passed + 6 skipped** y **97 no-integ**. Las diferencias:
- U4 quedó en **2 funciones** (`test_u4_guardas_de_las_rutas_existentes` y `test_u4_al_final_estan_las_11`): +1 no-integ.
- **10 de los 12 controles** se fusionaron en el test F de su ruta (§3): −10 integ.
- **1 test fuera de la espec** (`test_m2_documento_sin_membresia_docente_404`): +1 integ.
- Los **6 skipped** son la réplica (`tests/teachers/test_replica_grupos.py`), que solo corre con `ENGRAMA_REPLICA_GRUPOS=1`. No cuentan como passed.

Fórmula a la vista:
- no-integ: 76 + (2 U1-U2 + 7 U3a-U3g + **2** U4 + 2 U5-U6) + 8 tramposos = 76 + 13 + 8 = **97** ✓ medido.
- integ nuevos: 13 F + 48 prohibidas + **2** controles aparte + **1** extra + 13 tramposos = **77**.
- passed: 163 + 21 + 77 = **261** ✓ medido; skipped: **6**.

H-3 agrega `test_h3_sin_overrides_de_dependencias_filtrados`, no-integ (+1 predicho). H-1 reescribe `test_m2_ab_404` sin cambiar la cuenta (predicho).
- **Cuentas finales tras H-1 y H-3: `<N passed>` + `<N skipped>`; no-integ: `<N>`.** Predicción: 262 + 6 y 98. Las completa el implementador con la salida real; si no coinciden, se corrige aquí antes de aceptar.

**Regla desde ERR-19:** fusionar un control dentro de un test F, partir un test en dos o agregar uno fuera de la espec **actualiza esta cuenta en el mismo commit**.

Ubicación: `tests/teachers/`, `tests/integ/test_humo_grupos.py`, `tests/tramposos/test_tramposos_grupos.py` (integ) y `tests/tramposos/test_tramposos_logro.py` (no-integ).

En `integ_ayudante.py` se agregan:
- `afiliar(perfil, tenant, rol)`;
- los kwargs opcionales `skill=None` y `cefr_level=None` en `crear_challenge`;
- los kwargs opcionales `answers=None` y `completed_at=None` en `crear_intento`.

Los valores por defecto dejan idéntico el comportamiento actual, así que los 163 no cambian.

## 5. Humo y réplica
- **Humo (F12):** AA crea el grupo, asigna a D e importa 3 filas; D abre una sesión, un estudiante hace check-in y D la cierra. Escribe `tests/_salida/humo_grupos.json` = `{"inscritos":3,"docentes":1,"checkin":200,"checkin_tras_cierre":410,"con_asistencia":1}`, y el archivo va al `.gitignore`.
- **Réplica** (`ENGRAMA_REPLICA_GRUPOS=1`, entradas nuevas):
  - códigos de grupo con tilde y espacio;
  - un CSV de 40 filas con `;` y BOM;
  - D con 2 grupos;
  - **B con un grupo de código idéntico a GA**: T2 de GA no puede listar a los estudiantes de B;
  - *(Corregido por ERR-16, 2026-09-25)* T5 con skills `"Listening"` y `"vocabulary "`, y un eje con exactamente 8 ítems de 3 retos y 60 % (→ en desarrollo). T7 con un ítem de exactamente 5 respondientes y la respuesta dada como *label*.

## 6. Qué NO se toca
- `alembic/` (`git diff d77dcb4 -- alembic/` vacío), los 163 tests, `integ_db.py`, `models.py`, `/auth`, `/core`, `/challenges` y sus servicios, `pyproject.toml`, `poetry.lock` y `.venv` (ERR-11). La columna `challenge_attempts.weak_skills` no se lee, no se escribe y no se renombra.
- **Fuera de alcance:** tienda, apuestas, anuncios, badges, panel web, IA, super admin, monedas manuales, mover o borrar grupos y `max_capacity`.
- **Para después:**
  - **BUG-11 · BLOQUEANTE PARA PRODUCCIÓN** *(Corregido por ERR-19, 2026-09-25; confirmado por el auditor)*. `profiles.documento_id` es UNIQUE **global** (`models.py:101`), y M3 y M4 (`roster.py:101-124`, `get_profile_by_documento` + `enroll_student`) reutilizan el perfil que ya creó otro colegio y **descartan en silencio** el `nombre_completo` que envía el segundo. Resultado: T2, T5 y T7 le muestran a un colegio el nombre que escribió otro, y el segundo colegio no recibe ningún aviso de que su dato no se guardó.
    - **Dirección decidida por el coordinador:** el nombre se guarda **por membresía o por colegio** (cada colegio ve lo que escribió) y la **identidad sigue siendo global** (`documento_id` único, un solo `profile_id`).
    - Exige migración, así que va en **su propia espec**, no en esta. Ningún grupo real se matricula en producción mientras BUG-11 siga abierto.
  - BUG-10: el hueco de §0, más `/challenges/all` y `/core/attendance/sessions/active`, que muestran todo el colegio;
  - **la cuenta de acceso** (Supabase Auth con `id = profile_id`). Sin ella, un inscrito no entra: esta espec **no basta sola** para usar el sistema en clase;
  - *(Corregido por ERR-16, 2026-09-25; lo que sigue reemplaza a "que el pedagogo valide la regla de `weak_skills`")*
  - **el nivel MCER asignado:** una migración (p. ej., `memberships.cefr_assigned`), escrita por el docente o por SET, que active el filtro de §2.1.7;
  - **el bloque "Economía"** (saldo), con la espec de la tienda;
  - **candidato a BUG:** `correct_answer` mezcla *label* y *value* (§0), así que un estudiante que responde con el *value* de la opción correcta puede quedar calificado incorrecto. Afecta a `/challenges`, que aquí no se toca;
  - los retos `open` en el logro, cuando exista calificación por ítem que no sea coincidencia exacta;
  - los retos de todo el colegio (`group_id NULL`) en el logro del grupo;
  - los indicadores 2-5 del pedagogo que no cubre T5: la recuperación tras el feedback (calculable hoy con los reintentos), la participación, y el nivel externo frente al juego;
  - Ley 1581: declarar la finalidad formativa y la retención;
  - `max_winners` contra la constitución §5;
  - `skill` como texto libre, sin `speaking` en el generador y con un solo valor por reto.

## 7. Orden de commits (cada uno con 0 failed y los previos idénticos)
*Corregido por ERR-16 (2026-09-25).*
1. `test`: `afiliar` + los kwargs del ayudante + U4 con las 20 rutas.
2. `feat`: `access.py` (con `only_assigned`) + T1 + F1 + sus celdas + X1, X2 y X3.
3. T2 + F2 + celdas + X9.
4. T3 y T4 + F3 y F4 + celdas + X5.
5. T6 + F6 + celdas + X7.
6. M1 y M2 + F7 y F8 + celdas + X4.
7. M3 + F9 + celdas.
8. M4 + U1 y U2 + F10 y F11 + celdas + X8.
9. F12 + `.gitignore`.
10. **(Tras §2.4 respondida)** `achievement.py` + T5 + U3a-U3g + F5 + celdas + X6, X10, X11-X18.
11. **(Tras §2.4 respondida)** `item_errors.py` + T7 + U5 y U6 + F13 + celdas + X19, X20 y X21.
12. Un commit de docs con la matriz medida.

Si el paso 10 o el 11 no llega en esta tanda, las cuentas intermedias se escriben aquí antes de aceptar, con la suma a la vista.

## 8. Verificación y veredicto
```
poetry run pytest -m "not integ"   # 96 passed  (predicho; medido 97, final tras H-1/H-3: <N>)
poetry run pytest                  # 269 passed (predicho; medido 261 + 6 skipped, final tras H-1/H-3: <N> + <N> skipped)
ENGRAMA_REPLICA_GRUPOS=1 poetry run pytest tests/teachers tests/integ/test_humo_grupos.py
poetry run ruff check . ; poetry run mypy .
```
*Corregido por ERR-19 (2026-09-25):* las cuentas que valen son las de §4, "Cuentas medidas". "Matriz medida = §3" se lee contra la columna "Rojo medido", y **las celdas no medidas (notas 2 y 8 de §3) se miden antes de aceptar**.
- **FUNCIONA:** cuentas exactas, matriz medida = §3, réplica y humo en verde, `alembic/` y los 163 intactos, §2.4 respondida antes de T5 y T7.
- **HAY ALGO MODESTO:** la réplica falla solo en tests F.
- **NO:**
  - una celda prohibida da 2xx o datos ajenos;
  - cambia algo previo;
  - aparece una migración;
  - un tramposo queda en verde;
  - T5 o T7 exponen `weak`, `débil` o `debil`, o un orden de estudiantes por desempeño;
  - T7 muestra un ítem con menos de 5 respondientes o algún `profile_id`;
  - T5 o T7 se implementan antes de responder §2.4.
