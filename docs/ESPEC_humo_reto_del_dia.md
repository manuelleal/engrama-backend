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

---

## 10. Medido (2026-10-13)

### Cuentas
**768 passed + 24 skipped** (suite completa sobre `79bff7c`, 1.034 s, en un contenedor de prueba propio); **208 no-integ**; `ruff check .` 0. §6 predecía 767 + 24: el uno de más es ZL15, el tramposo que L1 ganó después (`ESPEC_l1_correccion_por_pregunta.md` §11). `mypy .`: 5 avisos, los mismos que ya tenía la rama antes de estos bloques (4 en `tests/seguridad/test_422_sin_eco.py` y 1 en `tests/tramposos/test_tramposos_practica.py`).

La réplica RRD1 pasó con la bandera, corrida aparte (dos veces).

### Criterios
| # | Resultado |
|---|---|
| H1 a H6 | Los seis en **0**, en el humo y en la réplica |
| H7 | `clases` cumplió **3 de 4** semanas. La primera no: martes y jueves asistió, y su tanda del sábado no llegó a 6 respuestas con 4 correctas (no se miró cuál de las dos cosas faltó). Gastó el protector y siguió |
| H8 | El archivo salió **idéntico** en cuatro corridas (dos antes y dos después de agregarle un dato, abajo) |
| CC1 a CC3 y RA1 | Verdes en su primera corrida, con los valores escritos antes |

Tramposos: **5 de 5 rojos por su razón** (ZK1 a ZK4 y ZH1).

### El humo (semilla 45, 4 semanas, 78 retos sembrados)
| | `clases` | `solo` | `azar` | `copia` |
|---|---|---|---|---|
| Monedas (retos + asistencia + bono) | 115 (20 + 80 + 15) | 150 (130 + 0 + 20) | 5 (0 + 0 + 5) | 15 (10 + 0 + 5) |
| Racha, mejor, semanas cumplidas, protectores | 3, 3, 3, 0 | 4, 4, 4, 1 | 1, 1, 1, 0 | 0, 1, 1, 0 |
| Días activos (solo por asistencia) | 11 (8) | 12 (0) | 8 (0) | 7 (0) |
| Días de práctica | 4 | 12 | 16 | 12 |
| Acierto de primer intento | 64,5 % | 73,1 % | 24,4 % | 29,3 % |
| Nivel de práctica al final | B1 | B2 | B1 | B1 |
| Tandas (`nuevo` / `repetir` / `segunda_vuelta`) | 4 / 0 / 0 | 23 / 1 / 0 | 26 / 3 / 0 | 12 / 0 / 0 |
| Respuestas por `/answers` | 24 | 135 | 156 | 141 |
| Reintentos con forma gemela | 3 | 19 | 26 | 23 |
| Pagas en el intento 1 y en el 2 | 1 y 1 | 9 y 4 | 0 y 0 | 1 y 0 |
| Días `sin_contenido` | 0 | 0 | 3 | 0 |

Explicaciones mostradas: 333 en español (retos A1 y A2) y 123 en inglés (B1). Huecos (`nivel_agotado` → tandas): A1 8, A2 5, B1 3, B2 22.

**Vigilancia (dictamen §2), sumando a los cuatro:**
| Riesgo | Medido | Umbral | |
|---|---|---|---|
| 1. Día activo haciendo clic | 15 de los 30 días activos por respuestas son dudosos: **50 %** (los 8 de `azar` y los 7 de `copia`) | > 5 % | **PASA EL UMBRAL** |
| 2. Cobrar copiando | con gemelas, `copia` cobró 0 de 1 pagas en el intento 2; `solo` (que no copia) 4 de 13: 30,8 % | > 30 % | ver la réplica |
| 3. Racha solo con asistencia | 0 % (dos clases no alcanzan: siempre hace falta un día de respuestas) | > 50 % | bien |
| 4. El bono pesa | `clases` 13,0 %, `solo` 13,3 %, `copia` 33,3 %, `azar` 100 % | > 15 % | pasa en quien casi no gana retos |
| 5. El repaso no se hace | 100 % (los sintéticos lo responden siempre: no mide nada) | < 50 % | — |
| 8. Racha repitiendo | 0 % | > 20 % | bien |
| El repaso revela retos del feed | 0 de 154 repasos fueron preguntas de retos del feed | — | bien |

### La réplica (semilla 46, 3 semanas, `SEGUNDO_INTENTO_PAGA = 5`, 14 retos, sin gemelas ni repasos, sin A2)
| | `clases` | `solo` | `azar` | `copia` | `con_set` (SET B1) |
|---|---|---|---|---|---|
| Monedas | 120 | 115 | 15 | **105** | 70 |
| Pagas en el intento 1 y en el 2 | 4 y 1 | 7 y 7 | 1 y 0 | **4 y 10** | 2 y 8 |
| Pagas en el intento 2 | 20 % | 50 % | 0 % | **71,4 %** | 80 % |
| Racha y protectores | 3 y 1 | 2 y 1 | 1 y 1 | 3 y 1 | 2 y 0 |
| Días `sin_contenido` | 0 | 1 | 5 | 0 | 0 |
| Repasos sobre preguntas del feed | 1 de 1 | 9 de 9 | 21 de 21 | **12 de 12** | 15 de 15 |

- `azar` y `solo` se quedaron sin nada que responder (`tanda: null`), sus semanas quedaron marcadas y **ninguna racha se rompió** (H6).
- Nadie arrancó con la tanda vacía aunque A2 no tenía retos: 10 tandas quedaron con el hueco en A2 y salieron de otro nivel (no se desglosó cuántas subiendo a B1 y cuántas prestadas).

### Predicciones
| | | |
|---|---|---|
| P1 | `azar` pasa del 5 % de días activos | **Confirmada, y por mucho:** 8 de sus 16 días de práctica fueron activos (50 %) y cumplió una semana (bono de 5). El 3,8 % del dictamen vale para 6 respuestas justas; con dos tandas y los reintentos (cada pregunta cuenta con su mejor resultado del día) responde 12 o más |
| P2 | `copia` cobra en el segundo intento donde no hay gemela | **Confirmada:** con gemelas, 0; sin gemelas, 10 de 14 (71,4 %) |
| P3 | `clases` cumple las 4 semanas | **REFUTADA:** 3 de 4 (H7) |
| P4 | `solo` ve la segunda vuelta desde el día 21 | **REFUTADA:** nunca. La escalera lo subió a B2, que no tiene retos; desde ahí todo fue prestado, y la segunda vuelta solo mira el nivel de práctica |
| P5 | Nadie queda sin tanda mientras haya retos con intentos | No refutada: las únicas tandas vacías fueron de quien ya había gastado sus dos intentos en todo |

### Hallazgos (no son defectos de estos bloques; van como preguntas)
1. **El clic al azar logra días activos la mitad de las veces** (riesgo 1).
2. **Agotar un nivel sube de nivel sin haber acertado:** `azar` terminó en B1 con 24 % de acierto. Con `max_attempts = 2`, perder dos veces cada reto "agota" el nivel y la tanda sube (regla del bloque 2).
3. **La escalera puede dejar a alguien en un nivel sin retos** (`solo` en B2): 22 tandas con hueco en B2.
4. **La segunda vuelta no se disparó ni una vez** en 4 semanas (P4).
5. **Quien tiene dos clases por semana no tiene holgura:** un solo día en casa con una tanda de 6 preguntas falla cerca de 1 de cada 6 semanas con 75 % de acierto.
6. **Con el segundo intento a 5 y sin gemelas, copiar deja 105 monedas contra 115 de quien estudia** (réplica). Y el 5 también recorta a quien se recupera de verdad: un reto de 3 preguntas se gana al primer intento el 42 % de las veces con 75 % de acierto.
7. **Sin formas de refuerzo sembradas, el repaso sirve preguntas de retos del feed y muestra su clave:** en la réplica, 12 de 12 repasos de `copia` fueron así, y ganó 4 retos al primer intento con paga completa. Con las gemelas y los repasos sembrados como `solo_refuerzo` (el humo), 0 de 154.

### Erratas del arnés (antes de fijar los números; se declaran)
- En la primera corrida `clases` cobró UNA asistencia en cuatro semanas: el reloj de la asistencia no estaba simulado y todos los check-in caían el mismo día real. Se simuló también ese reloj. Nada más cambió entre esa corrida y la siguiente.
- Después de ver la réplica se agregó un dato (`repasos_con_preguntas_del_feed`) y se volvió a fijar el archivo. No es criterio.
- CC1 a CC3 y RA1 no necesitaron ajustes.

### No medido
- Carga: los tests de concurrencia son dos hilos contra una base local.
- Más de dos pedidos a la vez; dos `/finish` o dos `/answers`+`/finish` cruzados.
- El humo con el banco real y con el sembrador real; contra el piloto y contra engrama-web.
- La segunda vuelta dentro del humo (hallazgo 4): solo la cubre SR3.
- El riesgo 5 (el repaso no se hace) y los riesgos 6, 7, 9 y 10 del dictamen: los sintéticos no los pueden medir.
- La matriz completa de tramposos de los tres bloques: solo las diagonales.
