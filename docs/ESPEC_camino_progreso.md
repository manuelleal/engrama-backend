# ESPEC · El camino de nivel (progreso por unidad), backend

Creador (Opus) · 2026-10-21 · preregistro. Rama `juego/camino-progreso` sobre `f7f7aeb` (meta de partida medida en esta rama: **208 no-integ, ruff 0**; la cifra de integración se mide en §10 con la base propia antes de tocar `src/`).

Manda `investigacion/pedagogia/06-camino-de-nivel-y-temas.md` §2.1, §2.3, §2.5 y §2.7 (ola rápida) y `investigacion/producto/14-plan-recuperar-el-juego.md` punto 5. **Decisión de Christiam (21-oct): bloqueo SUAVE**: la siguiente unidad queda recomendada y se abre sola si el estudiante se atasca 7 días. La web va en `engrama-web/docs/ESPEC_camino_y_tu_palabra.md` (parte B).

## 0. Leído (2026-10-21)
| Qué | Dónde |
|---|---|
| La unidad de un reto sembrado | `challenges.topic` = id de la unidad (`engrama-web/herramientas/sembrar/mapeo.mjs`, `topic: unidad.id`); el título es `"<id> · <título de la unidad> · <bloque> · <rol>"` |
| Qué ve el estudiante | `challenges_service.filtro_grupo_estudiante` (globales + su grupo, BUG-15) y `fuera_de_refuerzo()` (sin los `solo_refuerzo`) |
| Su nivel de práctica (no escribe) | `practica.service.nivel_vigente` |
| Orden de las unidades y de los retos de una unidad | `practica.reglas.orden_fijo`: `topic`, luego gramática → vocabulario → lo demás, luego el título |
| Intentos y aciertos | `challenge_attempts` (`answers = [{question_id, given_answer, correct_answer, is_correct}]` al cerrar, `started_at`, `completed_at`, `is_correct` = ganó) |
| Respuestas pregunta por pregunta (con su hora) | `challenge_attempt_answers` (045) y `reinforcement_answers` (041) |
| Rol de la forma (original, gemela, repaso) | `challenge_questions.form_role` |
| Qué es una pregunta escrita | `calificar.TIPOS_DE_OPCION = ("multiple_choice", "listening")`: lo demás se califica como texto |
| Lo que no hay | catálogo de unidades con título y can-do en el backend; chequeo de unidad a 7 días; prueba de salto. Son de la ola media (06 §2.7) |

## 1. Qué cambia (una cosa)
**Una ruta de SOLO LECTURA, `GET /challenges/camino`, que le dice al estudiante en qué va cada unidad de su nivel de práctica: su estado, si está abierta o bloqueada (bloqueo suave) y cuál es la recomendada.** Todo se calcula al leer con lo que ya existe. **Sin migración, sin tabla nueva, sin escribir nada y sin tocar monedas.** No hace falta la 048: si un cambio posterior la necesitara, sería la **048** con `down_revision = "045_correccion_por_pregunta"` (se renumera al integrar; la 047 la usa otra rama).

### 1.1 Qué unidades entran
- El **nivel mostrado** es el nivel de práctica (`nivel_vigente`). Si ese nivel no tiene ningún reto visible, se muestra el más cercano que tenga (el orden de `reglas.otros_niveles`: abajo antes que arriba) y `prestado = true`. Sin ningún reto visible: `unidades = []`.
- Un reto es una **estación** de la unidad `topic` si: es de la institución, está `active`, lo ve el estudiante (la MISMA regla del feed), no es `solo_refuerzo`, no es `open` (no se autocalifica, `practica.service.TIPOS_FUERA`), tiene `topic` y su `cefr_level` es del nivel mostrado (`B1+` y `B1-` son B1). No importa si ya lo ganó ni si le quedan intentos: el camino muestra todo lo de la unidad.
- **Orden:** unidades por `topic`; estaciones por `orden_fijo`. **Número** de la unidad: el de `-uNN` del `topic`; si no hay, su posición (1, 2…). **Título**: el segundo segmento del título del primer reto si el primero (sin un prefijo `[…] `) es el `topic`; si no, `null` (no se inventa).

### 1.2 Por estación (reto)
`intentos` = todos los suyos (cualquier estado); `aciertos` = el mejor de sus intentos `completed` (cuenta de `is_correct` en `answers`); `jugada` = tiene al menos un intento `completed`; `ganada` = alguno con `is_correct`; `puede_jugar` = no ganada y (le quedan intentos o tiene uno `in_progress`). Un reintento con formas gemelas (L1 §10.4) cuenta igual: así "el mejor de original o gemela" de 06 §2.3 sale solo.

### 1.3 Estado de la unidad (PROVISIONAL, 06 §2.3, ola rápida)
| Estado | Regla |
|---|---|
| `sin_empezar` | ningún intento en sus estaciones |
| `en_curso` | empezó y no es Completada |
| `completada` | **todas** sus estaciones jugadas **y** `Σ aciertos / Σ preguntas ≥ 70 %` (`CAMINO_UMBRAL_COMPLETADA`) |
| `dominada` | Completada **y** evidencia demorada: respuestas a formas `gemela` o `repaso` de preguntas de esa unidad (cualquier reto con ese `topic`, también `solo_refuerzo`), dadas **≥ 7 días después de completarla** (`CAMINO_DIAS_DOMINIO`), por `/answers` o por el repaso; **al menos 3** (`CAMINO_MINIMO_DEMORADAS`), **≥ 80 %** correctas (`CAMINO_UMBRAL_DOMINADA`) y, si la unidad tiene preguntas escritas, **al menos una escrita acertada** entre ellas |

`completada_en` = el más tardío, entre sus estaciones, del primer intento que alcanzó su mejor puntaje. `empezada_en` = el primer `started_at` de sus estaciones. `porcentaje` = `round(100 · Σ aciertos / Σ preguntas)` sobre las estaciones jugadas (null sin ninguna jugada).

**Dominada es difícil a propósito en la ola 1:** sin el chequeo de unidad (ola media), la evidencia demorada solo llega por el repaso, la segunda vuelta o un reintento. Nunca se da por velocidad ni por el nivel de SET. Lo dice §7.

### 1.4 Bloqueo suave y recomendada (decisión de Christiam)
- `acceso` de la unidad *i*: `abierta` si es la primera, si ya empezó (lo empezado nunca se bloquea), o si la anterior está Completada o Dominada. `abierta_con_apoyo` si la anterior no está bloqueada, está `en_curso` y empezó hace **7 días o más** (`CAMINO_DIAS_ATASCO`, **decidido por Christiam**). Si no, `bloqueada`, con `se_abre_el` = el `empezada_en` de la anterior + 7 días cuando la anterior está abierta y en curso (si no, `null`).
- **Atascada** = `en_curso` hace 7 días o más **y** la siguiente quedó `abierta_con_apoyo`.
- `recomendada`: la primera unidad, en orden, que no está bloqueada, no está Completada ni Dominada y no está atascada. Si no hay, la primera abierta sin completar. Si todas están completas: `null`.
- **Bloqueo suave = el backend no prohíbe nada:** el feed, la tanda y `POST /{id}/attempt` siguen igual. La web solo no enlaza lo bloqueado.
- Por unidad, `siguiente_reto` = la primera estación (en orden) con `puede_jugar`; `null` si no hay.

### 1.5 Salida (`CaminoOut`, estricta)
```
{ nivel, nivel_de_practica, con_nivel_de_set, prestado,
  umbral_completada: 70, umbral_dominada: 80, dias_atasco: 7,
  recomendada: "<topic>" | null,
  unidades: [{ topic, numero, titulo|null, estado, acceso, recomendada, atascada,
               estaciones_total, estaciones_jugadas, preguntas, aciertos, porcentaje|null,
               empezada_en|null, completada_en|null, se_abre_el|null, siguiente_reto|null,
               estaciones: [{ id, title, skill|null, challenge_type, preguntas, jugada, ganada, aciertos|null }] }] }
```
**No trae ningún campo de monedas, ni la clave, ni preguntas.** El camino no paga: completar una unidad no paga extra (06 §2.5); las monedas siguen saliendo solo del acierto (`/submit`, `/finish`).

### 1.6 Variables nuevas (PROVISIONALES, las fija el pedagogo, ERR-16; la de 7 días la fijó Christiam)
`CAMINO_UMBRAL_COMPLETADA=70`, `CAMINO_UMBRAL_DOMINADA=80`, `CAMINO_DIAS_ATASCO=7`, `CAMINO_DIAS_DOMINIO=7`, `CAMINO_MINIMO_DEMORADAS=3`.

## 2. Criterios (medibles)
Puros (`tests/camino/test_unit.py`, sin base):
- **CU1** estados: sin intentos → `sin_empezar`; una estación jugada de dos → `en_curso`; todas jugadas con 7 de 10 → `completada` y con 6 de 10 → `en_curso`; el mejor intento manda (1 de 3 y luego 3 de 3 = 3).
- **CU2** dominada: completada + 3 demoradas a 7 días con 3 de 3 → `dominada`; a 6 días y 23 h → `completada`; 2 demoradas → `completada`; con escritas en la unidad y ninguna escrita acertada → `completada`; 4 de 5 (80 %) → `dominada`.
- **CU3** bloqueo suave: la primera abierta; la 2 bloqueada mientras la 1 va en curso, con `se_abre_el` = empezada + 7 días; a 6 d 23 h sigue bloqueada; a 7 días `abierta_con_apoyo` y la recomendada pasa a la 2; la 1 completada abre la 2; una unidad empezada nunca está bloqueada.
- **CU4** recomendada: la primera abierta sin completar; todo completo → `null`; si la única que queda está atascada y no tiene siguiente, es ella.
- **CU5** título y número: `"a1-u03-daily · Daily Routine · Gramática 1 · original"` → `(3, "Daily Routine")`; con `[BORRADOR] ` delante, igual; un título que no empieza por el topic → `null`; un topic sin `-uNN` → su posición.

Por HTTP contra Postgres (`tests/camino/test_camino.py`, `integ`), lo observado en un dict que se compara ENTERO:
- **CM1** forma y orden: dos unidades A2 con 3 y 2 estaciones (sembradas en desorden), un reto de otro grupo, uno `solo_refuerzo`, uno inactivo, uno `open` y uno B1 → solo salen las 5 estaciones, en orden; sin `correct_answer` ni monedas en el cuerpo; la 1 recomendada y abierta, la 2 bloqueada.
- **CM2** progreso: juega la 1 entera con ≥ 70 % → `completada`, la 2 `abierta` y recomendada; con < 70 % → `en_curso`.
- **CM3** atasco a 7 días: la 1 en curso con su intento envejecido 6 días → la 2 bloqueada con `se_abre_el`; envejecido 7 días → la 2 `abierta_con_apoyo`, recomendada, y la 1 `atascada`.
- **CM4** el GET no escribe y el camino no paga: antes y después de leerlo, las filas de `coin_ledger`, `coin_wallets`, `challenge_attempts`, `practice_levels`, `practice_tandas` y `reinforcement_queue` son las mismas; y terminar la última estación de una unidad (pasa a `completada`) paga **exactamente** el `coins_reward` de ese reto, nada más.
- **CM5** por institución y por estudiante: los intentos de otro estudiante y los retos de otra institución no cambian nada.
- **CM6** prestado: sin retos del nivel de práctica (A2) y con retos B1, sale B1 con `prestado = true`; sin nada, `unidades = []`.
- **CM7** dominada por HTTP: unidad completada; 8 días después, 3 respuestas acertadas a gemelas por el repaso o por `/answers` → `dominada`.

## 3. Tramposos (diagonal PREDICHA; `tests/tramposos/test_tramposos_camino.py`)
| Id | Versión rota | Debe ponerse rojo |
|---|---|---|
| ZC1 | `completada` sin exigir todas las estaciones jugadas | CU1 |
| ZC2 | umbral de Completada en 50 % (`>=` contra 0.5) | CU1 |
| ZC3 | dominada sin la espera de 7 días | CU2 |
| ZC4 | el atasco se abre a los 6 días | CU3 |
| ZC5 | bloqueo duro: nunca hay `abierta_con_apoyo` | CU3 |
| ZC6 | la recomendada es la primera sin completar aunque esté bloqueada o atascada | CU3 |
| ZC7 | el camino no pasa por la visibilidad del estudiante | CM1 |
| ZC8 | el camino incluye los `solo_refuerzo` | CM1 |
| ZC9 | leer el camino paga un bono por cada unidad completada | CM4 |
| ZC10 | intentos de cualquier estudiante (sin `student_id`) | CM5 |

## 4. Ediciones a lo existente (ERR-25)
- `src/main.py`: nada (la ruta vive en el router de retos, antes de `/{challenge_id}`, como `/tanda`).
- `src/challenge_engine/router.py`: la ruta `GET /camino`.
- `src/shared/config.py`: las 5 variables de §1.6.
- `tests/integ_db.py`: el nombre y el puerto del contenedor se pueden fijar con `ENGRAMA_TEST_PG_NOMBRE` y `ENGRAMA_TEST_PG_PUERTO` (por defecto, los de siempre: `engrama-test-pg`, 55432). La guarda sigue exigiendo 127.0.0.1 y ese puerto. Va en su propio commit, antes del código. Esta rama corre contra `engrama-test-pg-camino` en 55452.
- Nada más de `src/` cambia.

## 5. Cuentas (predicción)
No-integ: 208 → **208 + CU1..CU5 + los tramposos puros**. Integ: la cifra de partida + CM1..CM7 + los tramposos integ. Ruff 0. Las suites existentes, idénticas.

## 6. Qué NO se toca
La tanda (`practica/`), el feed, `/submit`, `/answers`, `/finish`, el refuerzo, la economía, el sembrador, las migraciones. El bloqueo suave no prohíbe ninguna ruta. No se escribe nada al leer.

## 7. Riesgos
1. Sin catálogo de unidades, el título se lee del título del reto; un reto creado a mano sin la convención sale con `titulo = null` (la web dice "Unidad N").
2. `dominada` casi no aparecerá en la ola 1 (§1.3): es el precio de no inflarla. El pedagogo decide si la ola media trae el chequeo a 7 días o si se afloja la regla.
3. Una unidad con todas las estaciones jugadas, sin intentos y bajo el 70 % queda `en_curso` hasta que el atasco abre la siguiente: es lo que pide la decisión.
4. Retos de la misma unidad en dos grupos del estudiante no existen hoy (un estudiante tiene un grupo).

## 8. Para después
- Can-do de la unidad y su título del banco, desde un catálogo de unidades (06 §2.7, ola media).
- `formato` y `origen` en la respuesta (06 §2.6).
- El chequeo de unidad a 7 días y la prueba de salto (ola media).
- `calificar.oracion_correcta` rellena `"f___"` como `"ffamily"` cuando el hueco lleva la inicial: el sembrador de `tu_palabra` manda la oración del banco para no tropezar (ver la espec de la web).

## 8b. Veredicto
FUNCIONA si CU1..CU5 y CM1..CM7 pasan, los 10 tramposos salen rojos por su razón, las suites existentes siguen idénticas y el humo escribe `tests/_salida/humo_camino.json`. HAY ALGO MODESTO si falta un tramposo o un criterio integ. NO si el GET escribe o paga.
