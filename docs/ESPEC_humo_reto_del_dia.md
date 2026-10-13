# ESPEC · Humo y réplica del "reto del día sin profe", y lo que quedó sin probar

F4 · Creador · 2026-10-13 · preregistro. Rama `test/fixture-integ`, sobre L1 (`ESPEC_l1_correccion_por_pregunta.md` §10; meta **757 passed + 23 skipped y 208 no-integ**).

Bloque 5 de 5 del encargo. No cambia reglas: **mide** lo que construyeron los bloques 1 a 4 (racha semanal, nivel de práctica y tanda, `solo_refuerzo`, L1) con cuatro estudiantes sintéticos, y deja en un archivo los datos de vigilancia del dictamen `investigacion/pedagogia/04-dictamen-racha-y-reto-del-dia.md` §2. Además cierra dos "no medido" de `ESPEC_practica_y_tanda.md` §10: la concurrencia y el reancla.

## 1. Qué cambia (una cosa)
**Nada del producto. Se agregan un humo con semilla fija que escribe su archivo, su réplica con entradas nuevas, y cuatro tests de lo que ayer quedó sin probar.**

## 2. El humo HRD1 (`tests/integ/test_humo_reto_del_dia.py`)
Escribe `tests/_salida/humo_reto_del_dia.json` **antes** de afirmar. Semilla 45. Todo por HTTP, por las rutas que usará la web: `POST /challenges/tanda`, `/attempt`, `/answers`, `/finish`, el repaso y el check-in.

**El reloj es simulado** y es uno solo (la racha, la tanda, el cierre de los intentos, el repaso y el instante de cada respuesta): 4 semanas, del lunes 2026-10-12 al domingo 2026-11-08. Así el repaso a 7 días y la segunda vuelta a 21 ocurren de verdad.

**El banco sintético** (sembrado por `POST /challenges/`, como lo hará el sembrador): niveles A1 (3 unidades), A2 (6) y B1 (4); cada unidad con 2 retos del feed (gramática y vocabulario, 3 preguntas de 4 opciones) y, por cada uno, su reto de gemelas y su reto de repaso (`solo_refuerzo`); 3 nodos; `max_attempts = 2` (lo que siembra el sembrador de hoy); cada pregunta con su explicación.

**Los cuatro estudiantes** (sin examen SET: arrancan en A2):
| Quién | Qué hace cada semana | Cómo responde |
|---|---|---|
| `clases` | asiste martes y jueves; el sábado pide una tanda | acierta el 75 % de las veces; 8 a 20 s por respuesta |
| `solo` | no asiste; lunes, miércoles y viernes pide dos tandas | acierta el 75 %; 8 a 20 s |
| `azar` | lunes, martes, jueves y sábado pide dos tandas | una opción al azar; 1 a 2 s |
| `copia` | lunes, miércoles y viernes pide una tanda | al azar; si pierde, reintenta en el acto copiando la clave que le mostró `/answers` (2 s); donde le sirven una gemela no puede copiar y responde al azar |

Cada decisión sale de `Random("45|quién|día|ítem|intento")`: no depende del orden en que lleguen las cosas.

### 2.1 Lo que el archivo debe traer
Por estudiante: monedas y de dónde (retos, asistencia, bono de semana), racha, mejor racha, semanas cumplidas, protectores, días activos (y cuántos solo por asistencia), nivel de práctica final, tandas por modo, días en el tope, días `sin_contenido`, acierto de primer intento, respuestas por `/answers`, reintentos con gemela, y los **datos de vigilancia** (dictamen §2):

| Riesgo | Dato en el archivo | Umbral del dictamen |
|---|---|---|
| 1. Día activo haciendo clic | `dias_activos_dudosos_pct`: de los días activos por respuestas, los que tienen acierto de primer intento ≤ 30 % o mediana < 3 s por respuesta | > 5 % |
| 2. Cobrar copiando | `pagas_en_intento_2_pct` | > 30 % |
| 3. Racha solo con asistencia | `semanas_cumplidas_sin_respuestas_pct` | > 50 % |
| 4. El bono pesa más que acertar | `bono_sobre_monedas_pct` | > 15 % |
| 5. El repaso no se hace | `repaso_respondido_pct` (entradas que tocaron y se respondieron) | < 50 % |
| 8. Racha repitiendo | `dias_activos_solo_repetidos_pct` | > 20 % |
| Hueco de contenido | `huecos` (`nivel_agotado` → tandas) y `dias_sin_contenido` | — |

### 2.2 Criterios (lo que se afirma; fijado ANTES de medir)
| # | Criterio | Valor |
|---|---|---|
| H1 | Ninguna respuesta 5xx en toda la simulación | 0 |
| H2 | Ninguna clave ni explicación antes de responder (en cada tanda y en cada `/attempt`) | 0 fugas |
| H3 | Ningún reto `solo_refuerzo` en una tanda `nuevo` o `repetir`, ni en el feed | 0 |
| H4 | Nadie cobra dos veces el mismo reto | 0 |
| H5 | El nivel de práctica no se escribe como nivel confirmado | 0 filas |
| H6 | Ninguna semana con un día `sin_contenido` gastó protector ni rompió una racha | 0 |
| H7 | `clases` cumple las 4 semanas (2 asistencias + 1 día en casa) **si** su tanda del sábado le da 6 respuestas con 4 correctas; si no, se reporta la semana que falló y por qué | se mide |
| H8 | El archivo completo es **idéntico** al fijado con la primera medición del código bueno (la semilla manda) | identidad |

**Lo que NO es criterio y solo se reporta** (son las preguntas del dictamen, no defectos del código): los porcentajes de §2.1. Si uno pasa su umbral, va al informe como hallazgo y como pregunta al dueño.

### 2.3 Predicciones (escritas antes de correr; se refutan o no en "Medido")
- **P1:** `azar` logra días activos por respuestas en más del 5 % de sus días de práctica: el 3,8 % del dictamen supone 6 respuestas exactas, y con dos tandas responde 12 o más (4 de 12 al azar sale cerca del 35 %).
- **P2:** `copia` cobra más del 30 % de sus pagas en el segundo intento donde no hay gemela; donde la hay, no.
- **P3:** `clases` cumple las 4 semanas.
- **P4:** `solo` agota A2 en la primera semana, sube a B1 y ve la segunda vuelta desde el día 21.
- **P5:** nadie queda con una tanda vacía mientras haya retos con intentos.

## 3. La réplica RRD1 (`ENGRAMA_REPLICA_RETO_DEL_DIA=1`; saltada sin la bandera)
Entradas nuevas: semilla 46; **`SEGUNDO_INTENTO_PAGA = 5`**; 3 semanas; el banco **sin** retos de gemelas (nadie puede evitar la copia) y solo con A1 y B1 (el A2 de arranque no tiene nada: escalera del nivel agotado); un quinto estudiante con SET en B1. Afirma H1 a H6 y escribe `tests/_salida/replica_reto_del_dia.json`. Sus números se reportan junto a los del humo (sobre todo: cuánto cobra `copia` con la variable en 5 frente a sin ella).

## 4. Lo que ayer quedó sin probar
| Test | Qué mide |
|---|---|
| CC1 | Dos `POST /challenges/tanda` **a la vez** del mismo estudiante: las dos 200, la misma tanda, **una** fila |
| CC2 | Dos `/submit` **a la vez** del mismo intento: una 200 y una 409, **una** paga |
| CC3 | Una tanda y un `/submit` **a la vez** del mismo estudiante: las dos 200 (los candados se toman en el mismo orden: no hay abrazo mortal) |
| RA1 | **El reancla:** quien practicaba sin examen y subió a B1 recibe después un nivel de SET (A1): la lectura lo dice sin escribir, la siguiente tanda sale de A1, la fila queda con el ancla y la ventana vacía; si SET cambia otra vez (B2), el siguiente `/submit` reancla; `confirmed_levels` no lo escribe la práctica |

Para que "a la vez" sea de verdad y no suerte, cada test ensancha la ventana con una pausa justo DESPUÉS del punto donde el candado serializa.

### 4.1 Tramposos (diagonal PREDICHA)
| Id | Rompe | Rojo predicho |
|---|---|---|
| ZK1 | La tanda no toma ningún candado | CC1: una de las dos responde 500 (dos filas con el mismo número) |
| ZK2 | El intento se lee sin bloquear | CC2: las dos responden 200 |
| ZK3 | La tanda toma los candados al revés (nivel y después racha) | CC3: una de las dos responde 500 (abrazo mortal) |
| ZK4 | La escritura no reancla | RA1: la tanda sale del nivel viejo |
| ZH1 | El humo con un reto `solo_refuerzo` colado en el feed | HRD1: H3 |

## 5. Ediciones a lo existente
`.gitignore` (los dos archivos de salida). Ningún archivo de `src/` cambia.

## 6. Cuentas
HRD1, CC1 a CC3 y RA1 (5) + ZK1 a ZK4 y ZH1 (5) = **10 integ**, más RRD1 saltada. Sobre 757 + 23 y 208: **767 passed + 24 skipped y 208 no-integ**; ruff 0.

## 7. Qué NO se toca
`src/`. Los humos y las réplicas anteriores.

## 8. Riesgos
- El humo afirma identidad sobre muchos números: si algún orden dependiera del reloj real del contenedor, sería intermitente. Por eso cada decisión se deriva de (quién, día, ítem, intento) y el banco usa 3 nodos (el tope de 3 repasos por tanda nunca corta).
- Los cuatro estudiantes son caricaturas con probabilidades inventadas: el humo prueba que las reglas hacen lo que dicen y deja ver hacia dónde empujan; **no** predice un aula.
- CC1 a CC3 corren dos hilos contra una base local: prueban los candados, no la carga.

## 9. Veredicto
- **FUNCIONA:** las cuentas de §6, H1 a H6 y H8, los cinco tramposos rojos por su razón, la réplica verde con la bandera.
- **NO:** una clave antes de tiempo; una paga doble; una racha rota por falta de contenido; dos tandas con el mismo número o un 500 por candados; el reancla no ocurre; un tramposo queda verde.
