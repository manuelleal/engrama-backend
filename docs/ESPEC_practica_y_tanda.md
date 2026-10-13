# ESPEC · Nivel de práctica y la tanda de hoy, backend

F4 · Creador · 2026-10-12 · preregistro. Rama `test/fixture-integ`, sobre la racha semanal (`ESPEC_racha_semanal.md`; meta **690 passed + 23 skipped y 186 no-integ**).

Manda el dictamen `investigacion/pedagogia/04-dictamen-racha-y-reto-del-dia.md` §1.3. Bloque 2 de 5 del encargo "reto del día sin profe".

## 0. Leído (2026-10-12)
| Qué | Dónde |
|---|---|
| El feed de hoy: por grupo, sin nivel, el más nuevo primero | `challenges.list_challenges_for_student` + `foco.priorizar_feed` |
| Qué siembra el sembrador en cada reto | `engrama-web/herramientas/sembrar/mapeo.mjs:147-155`: `cefr_level = nivel de la unidad`, `topic = id de la unidad`, `skill = grammar \| vocabulary` (la lectura va sin `skill`), 2 o 3 preguntas, `max_attempts = 2`, `coins_reward = 10` |
| El nivel de SET | `confirmed_levels` (A1 a C2), por `level.read_confirmed_level`; solo lo escribe `level.record_confirmed_level` |
| Las respuestas de un intento | `challenge_attempts.answers` (`[{question_id, given_answer, is_correct}]`), escritas por `/submit` |
| La cola de repaso | `refuerzo.service.leer` (las que tocan, cada una con su forma no vista) |
| Los niveles de un reto | `challenges.cefr_level`: A1, A1+, A2, A2+, B1-, B1, B1+, B2, B2+, C1, C1+ |

## 1. Qué cambia (una cosa)
**El estudiante tiene, por institución, un NIVEL DE PRÁCTICA (que no es su nivel y nunca toca el escudo), y una ruta le arma "la tanda de hoy": hasta 3 repasos que tocan y, después, los siguientes micro-retos no ganados de ese nivel hasta sumar 6 preguntas.**

### 1.1 Nivel de práctica
- Uno por `(institución, estudiante)`: A1, A2, B1, B2 o C1. Tabla `practice_levels`. **Este módulo no importa ni llama a `record_confirmed_level` y no escribe en `confirmed_levels`.**
- **Arranque:** con nivel de SET (provisional o definitivo) → ese nivel (C2 → C1), que queda como **ancla**; sin SET → `PRACTICA_NIVEL_INICIAL` (A2).
- **Límites:** con ancla, solo `ancla − 1` a `ancla + 1`; siempre entre A1 y C1.
- Si SET confirma un nivel después (o cambia), la siguiente lectura o escritura reancla: el nivel de práctica vuelve al de SET y la ventana se vacía.
- **Escalera** (se evalúa al calificar un intento, `/submit`):
  - Ventana = las últimas `PRACTICA_VENTANA` (12) preguntas de **primeros intentos** (el primer intento completado de ese estudiante en ese reto) de retos del nivel actual, calificadas después del último cambio de nivel. El nivel de un reto es la base de su `cefr_level` (`B1+` y `B1-` son B1).
  - Con la ventana llena: ≥ `PRACTICA_SUBE` (10) correctas → sube uno; ≤ `PRACTICA_BAJA` (5) → baja uno; si el límite no deja, no cambia. **Al cambiar, la ventana se vacía.**
  - **Sin ancla de SET**, las primeras `PRACTICA_DECISIONES_RAPIDAS` (3) decisiones usan ventana de `PRACTICA_VENTANA_RAPIDA` (6): ≥ 5 sube, ≤ 2 baja. **"Decisión" = un cambio de nivel** (interpretación mía del dictamen, que no lo define: con ventana deslizante "quedarse" no es un evento; va como pregunta al pedagogo).
  - Solo cuenta el primer intento: el segundo ya vio la clave. Una pregunta en blanco cuenta como fallada.
- Nada premia velocidad: no se mira el tiempo.

### 1.2 La tanda
`POST /challenges/tanda` ("dame la tanda de hoy") y `GET /challenges/tanda` (verla; **no escribe**). Ambas responden lo mismo:
```json
{"fecha": "2026-10-14",
 "practica": {"nivel": "A2", "con_nivel_de_set": false},
 "tanda": {"numero": 1, "modo": "nuevo", "nivel": "A2", "preguntas": 7, "completa": false,
           "repaso": [{"entrada_id": 12, "etapa": "refuerzo", "nodo": {"…": "…"}, "pregunta": {"…": "…"}}],
           "retos": [{"estado": "pendiente", "paga": 10, "reto": {"id": "uuid", "title": "…", "questions": ["sin clave"]}}]},
 "tandas_hoy": 1, "tope_al_dia": 2, "puede_pedir_otra": false, "listo_por_hoy": false,
 "sin_contenido_nuevo": false}
```
- `tanda` es `null` en el `GET` si hoy no se ha pedido ninguna. El `POST`:
  - sin tanda hoy → crea la 1;
  - con la tanda de hoy **sin completar** → devuelve la misma (idempotente: no gasta el tope);
  - con la tanda completa y menos de `TANDA_MAX_AL_DIA` (2) → crea la siguiente;
  - con el tope alcanzado → la última, con `listo_por_hoy: true` (200, no es un error: la web dice "Listo por hoy. Lo que se estudia en días distintos se recuerda más. Mañana hay más.").
- **Bloque 1, `repaso`:** hasta `TANDA_REPASOS_MAX` (3) entradas de la cola que tocan al crear la tanda. Se responden por la ruta de siempre (`POST /challenges/refuerzo/{entrada_id}/respuestas`, 0 monedas). Una entrada ya respondida en esta tanda no vuelve a salir hoy en la tanda (tras fallar, la siguiente forma llega otro día: dictamen §1.4).
- **Bloque 2, `retos`:** micro-retos **activos**, que el estudiante ve (`filtro_grupo_estudiante`), del nivel de práctica, **no ganados** por él, con cupo e intentos disponibles, que no sean `open` y que no hayan salido en otra tanda de hoy. En **orden fijo**: `topic` (la unidad), después `skill` (grammar → vocabulary → lo demás, que es la lectura), después `title`, después `id`. Se toman en ese orden hasta sumar **≥ `TANDA_PREGUNTAS_MIN` (6) preguntas**, máximo `TANDA_RETOS_MAX` (4) retos. **Nada del nivel de arriba entra a la tanda.**
- Se juegan por las rutas de siempre (`/challenges/{id}/attempt` y `/submit`): **la paga es la de hoy** (10 una vez). `paga` dice cuánto pagaría ganarlo ahora (0 si ya lo cobró). `estado`: `pendiente`, `jugado` (tiene un intento completado desde que nació la tanda) o `ganado`.
- **`completa`:** todos sus retos están `jugado` o `ganado`. El repaso no bloquea (no paga y puede faltar forma).
- **Cuando el nivel se agota** (no queda ningún reto nuevo): en este orden,
  1. el repaso sigue saliendo;
  2. *segunda vuelta con gemelas:* llega con `solo_refuerzo` (bloque 3, `ESPEC_siembra_para_repaso.md`);
  3. si el límite lo deja y el nivel siguiente tiene retos no ganados, **sube de nivel** (no cuenta como decisión rápida) y la tanda sale del nivel nuevo;
  4. si no, `modo: "repetir"`: retos ya ganados con intentos disponibles (pagan 0 por la llave de BUG-13; cuentan para el día activo).
  - En `modo: repetir` la tanda lleva `sin_contenido_nuevo: true`. **El hueco** `(institución, nivel, estudiantes sin contenido nuevo)` sale de `practice_tandas.nivel_agotado`.
  - Si no hay NADA que servir (ni repaso, ni nuevo, ni ganado), no se crea tanda ni se gasta el tope: `tanda: null` con `sin_contenido_nuevo: true`.
- El feed del grupo (`GET /challenges/`) **no cambia**.

### 1.3 Migración `043_practica_y_tanda` (aditiva)
```
practice_levels (id, tenant_id, profile_id, nivel, ancla NULL, decisiones INT, ventana_desde TIMESTAMPTZ,
                 created_at, updated_at; UNIQUE (tenant_id, profile_id);
                 CHECK nivel y ancla IN ('A1','A2','B1','B2','C1'))
practice_tandas (id, tenant_id, profile_id, local_date, numero, modo, nivel, nivel_agotado NULL,
                 retos UUID[], repasos BIGINT[], repaso_desde BIGINT, preguntas INT, created_at;
                 UNIQUE (tenant_id, profile_id, local_date, numero);
                 CHECK modo IN ('nuevo','segunda_vuelta','repetir'), numero >= 1)
```
- `nivel_agotado`: el nivel que se quedó sin retos nuevos al crear la tanda (el hueco de contenido), aunque después haya subido.
- `repaso_desde`: el último `reinforcement_answers.id` al crear la tanda; "respondida en esta tanda" = una respuesta posterior a ese id (no se comparan relojes).
- `created_at` lo pone el proceso (el mismo reloj que `completed_at` de los intentos), no la base.
RLS activo y sin políticas en las dos. Bajada: las dos tablas.

### 1.4 Variables nuevas
| Variable | Por defecto | | Variable | Por defecto |
|---|---|---|---|---|
| `PRACTICA_NIVEL_INICIAL` | A2 | | `PRACTICA_DECISIONES_RAPIDAS` | 3 |
| `PRACTICA_VENTANA` | 12 | | `TANDA_REPASOS_MAX` | 3 |
| `PRACTICA_SUBE` | 10 | | `TANDA_PREGUNTAS_MIN` | 6 |
| `PRACTICA_BAJA` | 5 | | `TANDA_RETOS_MAX` | 4 |
| `PRACTICA_VENTANA_RAPIDA` | 6 | | `TANDA_MAX_AL_DIA` | 2 |
| `PRACTICA_SUBE_RAPIDA` | 5 | | | |
| `PRACTICA_BAJA_RAPIDA` | 2 | | | |

## 2. Criterios
| # | Criterio | Test |
|---|---|---|
| C1 | **Puro, el nivel:** arranque con y sin SET (C2 → C1); límites ±1 y A1 a C1; la base de `B1+`; los 11 valores por defecto | UP1 (no-integ) |
| C2 | **Puro, la escalera:** 10 de 12 sube, 5 de 12 baja, 6 a 9 no cambia, ventana sin llenar no decide; sin ancla y con menos de 3 decisiones: 5 de 6 sube y 2 de 6 baja; con ancla nunca sale de ±1; solo cuentan las ÚLTIMAS de la ventana | UP2 (no-integ) |
| C3 | **Puro, armar la tanda:** el orden fijo (unidad, gramática → vocabulario → lectura, título); hasta ≥ 6 preguntas; máximo 4 retos; con retos de 3 preguntas toma 2 | UP3 (no-integ) |
| C4 | **La tanda por HTTP:** sin SET sale del A2; trae los retos en orden, sin la clave, con `paga`; repetir el `POST` devuelve la misma; el `GET` no escribe; un reto de otro nivel, de otro grupo, inactivo o ya ganado no sale | TD1 |
| C5 | **El tope:** al completar la 1 se puede pedir la 2 (retos distintos); completa la 2 → `listo_por_hoy`; al día siguiente vuelve a haber | TD2 |
| C6 | **El repaso primero:** con cola que toca, hasta 3 entradas en `repaso`, con 0 monedas; la respondida no vuelve a salir hoy | TD3 |
| C7 | **La escalera por HTTP:** 12 primeros intentos con 10 correctas suben de A2 a B1; el segundo intento no cuenta; con SET en B1 arranca en B1 y no pasa de B2; `confirmed_levels` no cambia (0 escrituras) | TD4 |
| C8 | **Nivel agotado:** sin retos nuevos sube si puede; si no, `modo: repetir` con paga 0 y `sin_contenido_nuevo` | TD5 |
| C9 | **Por institución:** el nivel y la tanda de una institución no se ven en otra; un estudiante no recibe retos de otro grupo | TD6 |
| C10 | Migración up/down/up idéntica | MG43 |
| C11 | Regresión: el feed (`GET /challenges/`) idéntico; los previos verdes con solo las ediciones de §4 | la suite |

## 3. Tramposos (diagonal PREDICHA)
| Id | Rompe | Rojo predicho |
|---|---|---|
| ZP1 (no-integ) | Sin SET se arranca en B2 | UP1 |
| ZP2 (no-integ) | El ancla no limita (sube sin tope) | UP2 |
| ZP3 (no-integ) | La escalera cuenta todas las respuestas, no las últimas de la ventana | UP2 |
| ZP4 (no-integ) | La tanda no respeta el máximo de retos | UP3 |
| ZP5 | La tanda trae retos de cualquier nivel | TD1 |
| ZP6 | La tanda no pasa por `filtro_grupo_estudiante` | TD1 |
| ZP7 | Cada `POST` crea otra tanda (el tope no sirve) | TD1 |
| ZP8 | No hay tope diario | TD2 |
| ZP9 | La escalera cuenta también el segundo intento | TD4 |
| ZP10 | El nivel de práctica se escribe en `confirmed_levels` | TD4 |
| ZP11 | El nivel de práctica se busca sin institución | TD6 |
| ZP12 | La tanda no pone el repaso | TD3 |
| ZP13 | El nivel agotado deja la tanda vacía (ni sube ni repite) | TD5 |

## 4. Ediciones a lo existente (ERR-25)
`alembic_version` → `043_practica_y_tanda` (12 líneas); `tablas_con_rls` 43 → 45; `test_sin_acceso.py` 44 → 46; `tests/teachers/test_access.py` gana 2 rutas; `src/challenge_engine/service/attempts.py` (`submit_attempt` llama a la escalera tras guardar el intento), `src/challenge_engine/router.py` (las dos rutas, antes de `/{challenge_id}`), `src/shared/config.py` y `src/shared/models.py`.

## 5. Cuentas
UP1 a UP3 (3) + ZP1 a ZP4 (4) no-integ; TD1 a TD6 y MG43 (7) + ZP5 a ZP13 (9) integ = **16 integ y 7 no-integ**. Sobre 690 + 23 y 186: **713 passed + 23 skipped y 193 no-integ**; ruff 0.

## 6. Qué NO se toca
El feed y su orden; la paga de los retos; `/submit` (su respuesta); `confirmed_levels`; `/auth/me`; la cola de refuerzo (solo se lee).

## 7. Riesgos
- **`max_attempts = 2` del sembrador:** un reto ganado solo admite un intento más, así que `modo: repetir` se agota rápido. El pedido al sembrador lo anota.
- **El nivel es del reto entero** (`cefr_level`), no de cada pregunta.
- Retos sin `cefr_level` (los que crea un profe a mano) no entran a la tanda ni mueven la escalera; siguen en el feed.
- "Practicas en: A2" se puede leer como nivel (riesgo 6 del dictamen): el texto es de la web; el contrato trae `con_nivel_de_set` para poner "Todavía no es tu nivel…".
- Si la institución no tiene ningún reto del nivel ni ganado ni nuevo, la tanda sale vacía: la falta de contenido puede romper una racha (el dictamen dice que nunca debe; aquí no hay nada que responder). Se declara.

## 8. Para después
El hueco de contenido en el panel del profe; avisar el cambio de nivel; el nivel por pregunta; tandas de solo repaso cuando el tope ya se alcanzó.

## 9. Veredicto
- **FUNCIONA:** las cuentas de §5, la diagonal medida, MG43 y los previos verdes.
- **NO:** el nivel de práctica aparece en `confirmed_levels` o en el escudo; la tanda trae la clave, retos de otro grupo o de otro nivel; el tope no detiene; el feed cambia; un tramposo queda verde.
