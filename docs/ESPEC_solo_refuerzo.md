# ESPEC · `solo_refuerzo`, la segunda vuelta y la escalera del nivel agotado, backend

F4 · Creador · 2026-10-13 · preregistro. Rama `test/fixture-integ`, sobre `b623ea9` (**713 passed + 23 skipped, 193 no-integ, ruff 0**).

Manda el dictamen `investigacion/pedagogia/04-dictamen-racha-y-reto-del-dia.md`: hecho 2, §1.3 ("Qué entra al feed" y "Cuando se acaba el nivel"). Es el bloque 3 de 5 del encargo "reto del día sin profe". Cierra lo que `ESPEC_practica_y_tanda.md` §10 y `ESPEC_refuerzo.md` §12 dejaron abierto. (En la espec de la práctica este documento se llamó `ESPEC_siembra_para_repaso.md`: es este.)

## 0. Leído (2026-10-13)
| Qué | Dónde |
|---|---|
| El feed | `challenges.list_challenges_for_student` (sin marca de refuerzo) |
| Los retos nuevos y ganados de la tanda | `practica.service._candidatos` y `_elegir` (nuevo → sube → repetir del MISMO nivel; si el nivel no tiene nada, tanda vacía) |
| Las candidatas del repaso | `refuerzo.formas.candidatas` (todo reto activo que el grupo ve) y `formas.vistas` |
| La paga | `attempts.submit_attempt` → `economia.recompensa_del_reto` + la llave `challenge:<reto>:<estudiante>` |
| El detalle y el arranque | `challenges.get_challenge_for` (Y12 y Y13 la reemplazan: **su firma no cambia**) y `attempts.start_attempt` (Y11: **su firma no cambia**) |
| El cierre de la racha | `racha.reglas.cerrar` (solo exenta la semana de la membresía) |
| `alembic_version` fijado (ERR-25) | `git grep -n "043_practica_y_tanda" -- tests`: 12 líneas |

## 1. Qué cambia (una cosa)
**Un reto puede marcarse `solo_refuerzo`: no sale en el feed ni en la tanda ni paga como un reto nuevo; sus preguntas alimentan la cola de repaso y, a los 21 días del original, la segunda vuelta. Y la escalera del "nivel agotado" queda completa: la falta de contenido no deja la tanda vacía mientras haya algo que responder, y cuando no hay nada, la semana no rompe la racha.**

### 1.1 La marca
- `challenges.solo_refuerzo BOOLEAN NOT NULL DEFAULT FALSE`. `POST /challenges/` acepta `solo_refuerzo` (opcional, falso por defecto). **Los retos que ya existen quedan en falso: nada cambia para ellos.**
- El sembrador marca así los retos de rol `gemela` y `repaso` (el pedido está en `docs/PEDIDO_sembrador.md` §3).
- **`ChallengeOut` no gana ningún campo** (el feed responde lo mismo, byte a byte, con los datos de hoy).

### 1.2 Dónde NO sale y dónde SÍ
| Lugar | Un reto `solo_refuerzo` |
|---|---|
| Feed (`GET /challenges/`) y foco del estudiante | **No sale** |
| Tanda, retos nuevos y "repetir lo ganado" | **No sale** |
| Detalle y arranque por un estudiante (`GET /challenges/{id}`, `POST /challenges/{id}/attempt`) | **404** (el mismo de un id que no existe), salvo que el reto esté en una tanda SUYA de segunda vuelta |
| Detalle por el personal, `GET /challenges/all` | Igual que hoy |
| Cola de repaso (`formas.candidatas`) | **Sale**: sus preguntas son las formas no vistas |
| Segunda vuelta de la tanda | **Sale** si cumple §1.3 |

### 1.3 La segunda vuelta
Un reto `solo_refuerzo` entra a la segunda vuelta de un estudiante si **todo** esto es cierto:
1. es del nivel de práctica, activo, visible para él, con cupo e intentos disponibles, no ganado y no `open`;
2. **todas** sus preguntas son de rol `gemela` (un reto de rol `repaso` nunca entra: es de la cola);
3. **ninguna** de sus preguntas la ha visto (la misma regla de "visto" de la cola: `formas.vistas`);
4. para **cada** familia de sus preguntas, el estudiante completó un intento de un reto del feed con el `original` de esa familia, y el **último** fue hace **≥ `SEGUNDA_VUELTA_DIAS` (21)** días (reloj del servidor).

- Se juega por las rutas de siempre. **Paga `min(valor del reto, SEGUNDA_VUELTA_PAGA)` = 5, una vez** (la misma llave de BUG-13) y cuenta para el día activo. `ChallengeOut.coins_reward` de un reto `solo_refuerzo` muestra eso mismo (lo que se muestra es lo que se paga).
- En la tanda: `modo: "segunda_vuelta"`, `paga: 5`, `sin_contenido_nuevo: true`.
- **Se declara el costo:** una gemela jugada en la segunda vuelta queda vista y ya no sirve a la cola de repaso de ese estudiante.

### 1.4 La escalera del nivel agotado (completa)
Al pedir una tanda, los retos salen del primer escalón que tenga algo:
| # | Escalón | `modo` | `tanda.nivel` | Mueve el nivel de práctica |
|---|---|---|---|---|
| 1 | Retos nuevos del nivel | `nuevo` | el nivel | no |
| 2 | **Segunda vuelta** del nivel (§1.3) | `segunda_vuelta` | el nivel | no |
| 3 | Sube un nivel, si el límite lo deja y arriba hay retos nuevos | `nuevo` | el de arriba | **sí** (como hoy) |
| 4 | Retos ya ganados del nivel | `repetir` | el nivel | no |
| 5 | **Prestado:** retos nuevos del nivel más cercano que tenga (primero hacia abajo, después hacia arriba) | `nuevo` | el prestado | **no** |
| 6 | **Prestado:** retos ya ganados de otro nivel, en el mismo orden | `repetir` | el prestado | no |
| 7 | Nada | sin tanda (`tanda: null`, `sin_contenido_nuevo: true`) | — | no |

- El repaso (bloque 1 de la tanda) sigue saliendo siempre, antes de todo.
- Del escalón 2 en adelante la tanda guarda `nivel_agotado` (el hueco de contenido).
- Los escalones 5 y 6 **solo** corren cuando el nivel no tiene NADA que servir. El 5 hacia arriba contradice "escalón arriba: 0 %" del dictamen; gana "la falta de contenido nunca rompe una racha". Lo prestado no mueve la escalera (`tras_intento` solo mira retos del nivel de práctica) y paga como cualquier reto nuevo. Va como pregunta al dueño.

### 1.5 Sin contenido, la semana no rompe la racha
- Si al pedir la **primera** tanda del día (`POST /challenges/tanda`) lo servible de TODA la institución para ese estudiante (preguntas de retos con intentos disponibles de cualquier nivel, más los repasos que tocan) es **menor que `RACHA_RESPUESTAS_DIA` (6)**, ese día queda marcado `sin_contenido` (`activity_days.sin_contenido`).
- **Al cerrar una semana no cumplida que tiene al menos un día `sin_contenido`, no pasa nada:** ni se gasta protector ni la racha vuelve a 0 (igual que la semana de la membresía). La racha tampoco sube.
- Solo marca quien **pidió** practicar. Quien no abre la app no queda exento.
- La respuesta de la tanda gana un campo: `racha_protegida: true` cuando hoy quedó marcado.
- Para no cruzar candados con `/submit` (racha → billeteras → nivel de práctica), `POST /challenges/tanda` toma primero el candado de la racha y después el del nivel de práctica.

### 1.6 Migración `044_solo_refuerzo` (aditiva)
```sql
ALTER TABLE challenges    ADD COLUMN IF NOT EXISTS solo_refuerzo BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE activity_days ADD COLUMN IF NOT EXISTS sin_contenido BOOLEAN NOT NULL DEFAULT FALSE;
```
Sin tablas nuevas (`tablas_con_rls` sigue en 45). Bajada: las dos columnas. En producción no se baja.

### 1.7 Variables nuevas (ninguna es secreto)
| Variable | Por defecto | Rango |
|---|---|---|
| `SEGUNDA_VUELTA_DIAS` | 21 | 1 a 365 |
| `SEGUNDA_VUELTA_PAGA` | 5 | 0 a 50 |

## 2. Criterios
| # | Criterio | Test |
|---|---|---|
| C1 | **Puro:** elegible para la segunda vuelta (todas gemelas, ninguna vista, cada familia con su original a ≥ 21 días; a 20 días no; sin original no; con una de rol `repaso` no); el orden de los niveles prestados (B1 → A2, A1, B2, C1); la paga `min(valor, 5)`; los dos valores por defecto | US1 (no-integ) |
| C2 | **Puro, el cierre:** una semana no cumplida y marcada `sin_contenido` no gasta protector ni baja la racha; la siguiente sin marca sí | US2 (no-integ) |
| C3 | **Fuera del feed y de la tanda:** con el original, la gemela y el repaso de una familia sembrados (los dos últimos `solo_refuerzo`), el feed y la tanda traen solo el original; el estudiante recibe 404 al ver y al abrir la gemela; el profe la ve; ganar todo lo del feed deja 10 monedas, no 30 | SR1 |
| C4 | **Alimenta la cola:** tras fallar el original, la cola sirve la gemela del reto `solo_refuerzo`; responderla paga 0 | SR2 |
| C5 | **Segunda vuelta:** con el nivel agotado y el original ganado hoy, NO hay segunda vuelta; con el original a 22 días, la tanda sale `segunda_vuelta` con la gemela no vista y `paga: 5`; el estudiante la abre y la gana: 5 monedas, una vez; la gemela ya vista en el repaso y el reto de rol `repaso` no salen | SR3 |
| C6 | **Sin retos del nivel:** una institución que solo tiene retos de B1 le sirve a un estudiante de A2 una tanda `nuevo` de B1, sin mover su nivel de práctica (sigue A2), con `nivel_agotado: A2`; si solo hay de A1, igual; ganados los prestados, `repetir` | SR4 |
| C7 | **La racha no se rompe por falta de contenido:** sin nada que servir, `tanda: null`, `sin_contenido_nuevo` y `racha_protegida`; al cerrar esa semana, quien pidió conserva racha y protector; quien no pidió gasta el protector | SR5 |
| C8 | Migración up/down/up idéntica | MG44 |
| C9 | Regresión: el feed, la tanda y la racha de los datos de hoy, idénticos; los previos verdes con solo las ediciones de §4 | la suite |

## 3. Tramposos (diagonal PREDICHA)
| Id | Rompe | Rojo predicho |
|---|---|---|
| ZS1 (no-integ) | La segunda vuelta no espera los días | US1 |
| ZS2 (no-integ) | El cierre ignora las semanas sin contenido | US2 |
| ZS3 | El feed no filtra `solo_refuerzo` | SR1 |
| ZS4 | La tanda no filtra `solo_refuerzo` | SR1 |
| ZS5 | El estudiante puede abrir cualquier reto `solo_refuerzo` | SR1 |
| ZS6 | La cola no usa los retos `solo_refuerzo` | SR2 |
| ZS7 | La segunda vuelta paga el valor completo | SR3 |
| ZS8 | La segunda vuelta sirve gemelas ya vistas | SR3 |
| ZS9 | Sin retos del nivel la tanda queda vacía (lo de ayer) | SR4 |
| ZS10 | El día sin contenido no se marca | SR5 |

**Tramposos existentes sobre el camino tocado (ERR-26):** Y10 a Y13 (`filtro_grupo_estudiante`, `start_attempt`, `get_challenge_for`), A3 a A5, Y2, ZP5 a ZP13 y ZW1 a ZW13. Predicción: siguen rojos por su razón; las firmas que ellos reemplazan no cambian.

## 4. Ediciones a lo existente (ERR-25)
`alembic_version` → `044_solo_refuerzo` (12 líneas); `src/challenge_engine/schemas.py` (`ChallengeCreate.solo_refuerzo`), `service/challenges.py` (lo guarda, el filtro del feed, el permiso de abrir y la paga mostrada), `service/attempts.py` (el permiso al arrancar y la paga), `router.py` (el permiso en el detalle); `src/practica/service.py`, `reglas.py` y `schemas.py` (`racha_protegida`); `src/racha/service.py` y `reglas.py` (`cerrar` gana `sin_contenido`, opcional); `src/engrama_core/service/economia.py`; `src/shared/config.py` y `models.py`; `docs/PEDIDO_sembrador.md` §3.

## 5. Cuentas
US1 y US2 (2) + ZS1 y ZS2 (2) no-integ; SR1 a SR5 y MG44 (6) + ZS3 a ZS10 (8) integ = **14 integ y 4 no-integ**. Sobre 713 + 23 y 193: **731 passed + 23 skipped y 197 no-integ**; ruff 0.

## 6. Qué NO se toca
`ChallengeOut` (su forma); la paga de los retos que no son `solo_refuerzo`; `/submit` (su respuesta); la cola de refuerzo (solo se prueba); `/auth/me`; el check-in; el nivel confirmado.

## 7. Riesgos
- **Hasta que el sembrador mande `solo_refuerzo`, nada cambia:** los retos ya sembrados siguen los tres en el feed. Resembrar es del otro repo.
- La segunda vuelta y la cola compiten por las mismas gemelas (§1.3).
- El escalón 5 puede servir retos de un nivel más alto (§1.4).
- "Servible" en §1.5 cuenta preguntas de retos con intentos disponibles; no descuenta las que ya se respondieron hoy (cuentan una vez al día para la racha). Un estudiante con 6 preguntas servibles ya respondidas hoy no queda marcado.
- Un estudiante que agotó `max_attempts` de todo queda sin nada y su racha se congela (ni sube ni baja) mientras siga pidiendo la tanda cada semana.

## 8. Para después
El hueco de contenido (y los días `sin_contenido`) en el panel del profe; que el personal vea `solo_refuerzo` en `ChallengeOut`; marcar `solo_refuerzo` al reetiquetar un reto ya sembrado.

## 9. Veredicto
- **FUNCIONA:** las cuentas de §5, la diagonal medida, MG44 y los previos verdes.
- **NO:** un reto `solo_refuerzo` sale en el feed o en la tanda de retos nuevos; un estudiante lo abre fuera de su segunda vuelta; paga 10; la segunda vuelta sirve una pregunta vista o antes de los 21 días; una institución con contenido deja la tanda vacía; una semana sin contenido rompe una racha; el feed de los datos de hoy cambia; un tramposo queda verde.
