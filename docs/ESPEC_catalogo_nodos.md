# ESPEC · El catálogo de nodos del mapa curricular, backend

F4 · Creador · 2026-10-06 · preregistro. Rama `test/fixture-integ`, sobre el generador apagado (`0e368bf`; meta **488 passed + 18 skipped y 131 no-integ**).

Origen: la decisión 012 §1 ("el mapa es la columna") y anexo B ("Nodos: `curriculo/nodos.json` → tabla de solo lectura en el backend"). Es la **pieza previa** de los tres bloques que siguen (Grader, foco del grupo y refuerzo): los tres guardan ids de nodo y necesitan una sola fuente que diga cuáles existen.

## 0. Medido y leído (2026-10-06)
| Qué | Dónde |
|---|---|
| El mapa generado | `INGLES/curriculo/nodos.json` (fuera de este repo, solo lectura): hoy `version: "nodos-0.3"`, 521 nodos vigentes en `nodos[]` y 14 en `reemplazos[]` (`{id, reemplazado_por, motivo, fecha}`). **Otro agente lo está consolidando:** los ids pueden fusionarse entre una carga y la siguiente |
| Forma de un nodo | `id` (hoy 45 caracteres el más largo; prefijos `gr`, `fn`, `lx`, `ds`, `pr`), `tipo` (5 valores), `nivel` (8 valores, con `A2+`), `nombre_es`, y campos pedagógicos que el backend no usa |
| Los reemplazados no están en `nodos[]` | medido: 0 de los 14; los 14 destinos sí están |
| No hay tabla de nodos | `grep -n "nodo\|curricul" src/shared/models.py` → 0 |
| CLI del operador | `src/onboarding/__main__.py` (`sesiones_del_entorno`): el patrón para una orden que corre contra `DATABASE_URL` sin la configuración web |
| `alembic_version` fijado en los tests (ERR-25; `git grep -n alembic_version -- tests` de hoy) | `tests/integ_db.py:66` y los `HUMO_ESPERADO` de `tests/integ/test_humo_bug11.py:35`, `_bug13a15.py:44`, `_consentimiento.py:33`, `_autorregistro.py:35`, `_solicitudes_datos.py:34` y `_eventos_anillo.py:38` |
| Otros números que una tabla mueve | `tests/integ_db.py:67` (`tablas_con_rls: 32`) y `tests/seguridad/test_sin_acceso.py:70-87` (33 y 33) |

## 1. Qué cambia (una cosa)
**El backend tiene un catálogo de nodos que el operador carga desde el mapa generado, y una sola función que traduce cualquier id a su nodo vigente.**

### 1.1 El id es texto opaco
El backend **no interpreta** el id (ni el prefijo, ni el nivel, ni los puntos): lo compara con el catálogo. Un id vale si está cargado; nada más. Así una consolidación del mapa no exige tocar código.

### 1.2 La carga (orden del operador)
```
python -m src.curriculo cargar --archivo <ruta a nodos.json>
```
Corre contra `DATABASE_URL`. Imprime un resumen JSON y sale con 0; si el archivo no cumple, sale con 2 y **no escribe nada**.

- Lee `version` (texto), `nodos[]` (`id`, `tipo`, `nivel`, `nombre_es`; lo demás se ignora) y `reemplazos[]` (`id`, `reemplazado_por`; opcional).
- **Todo o nada**, en una transacción.
- **Un nodo no se borra** (012 §1): si la tabla tiene un id que el archivo no trae ni en `nodos[]` ni en `reemplazos[]`, la carga se rechaza con `nodo_desaparecido` y la lista. Fusionar dos nodos se declara en `reemplazos[]`.
- Un reemplazo apunta a un nodo vigente. Las cadenas (A → B y B → C) se resuelven al final (A → C). Un ciclo, un destino que no existe o un id que está a la vez en `nodos[]` y en `reemplazos[]` → se rechaza (`reemplazo_invalido`).
- Otros rechazos: `sin_version`, `sin_nodos`, `id_invalido` (no es texto, vacío, con espacios o de más de 128), `id_repetido` y `campo_faltante`.
- Cargar el mismo archivo dos veces no cambia nada (`nuevos: 0, cambiados: 0`).
- **Reapuntar:** cuando un nodo pasa a reemplazado, las referencias guardadas se pasan al vigente dentro de la misma transacción. Hoy no hay ninguna tabla que guarde nodos: la lista de tablas a reapuntar (`src/curriculo/reapuntar.py`) nace vacía y **cada bloque que guarde nodos agrega su entrada y su test**.

Resumen: `{"version", "vigentes", "reemplazados", "nuevos", "cambiados", "reapuntadas": {tabla: filas}}`.

### 1.3 La función que resuelve (única fuente, ERR-26)
`src/curriculo/service.py :: canonicos(db, ids) -> list[str]`: devuelve los ids **vigentes**, en el orden de entrada y sin repetidos; un reemplazado se traduce a su destino. Si alguno no está en el catálogo → **422** `{"detail": {"code": "nodo_desconocido", "nodos": [...]}}`. Toda ruta que reciba nodos pasa por aquí; ninguna consulta la tabla por su cuenta.

Con el catálogo vacío todo id es desconocido: **cargar el catálogo va antes de usar cualquier ruta que reciba nodos.**

### 1.4 `GET /teachers/curriculo/nodos`
Para el selector de nodos del profe. `require_teacher`.
```json
200 {"version": "nodos-0.3",
     "nodos": [{"id": "gr.b1.present-perfect.for-since", "tipo": "gramatica", "nivel": "B1",
                "nombre_es": "presente perfecto con for y since"}]}
```
Solo los vigentes, ordenados por `id`. Catálogo vacío → `{"version": null, "nodos": []}`. El catálogo es el mismo para todas las instituciones: no lleva datos de nadie.

### 1.5 Migración `038_catalogo_nodos`
```sql
CREATE TABLE IF NOT EXISTS curriculum_nodes (
  id          TEXT PRIMARY KEY,
  kind        TEXT NOT NULL,
  level       TEXT NOT NULL,
  name_es     TEXT NOT NULL,
  replaced_by TEXT REFERENCES curriculum_nodes(id),
  map_version TEXT NOT NULL,
  loaded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT curriculum_nodes_id_check CHECK (char_length(id) BETWEEN 1 AND 128),
  CONSTRAINT curriculum_nodes_replaced_check CHECK (replaced_by IS NULL OR replaced_by <> id)
);
ALTER TABLE curriculum_nodes ENABLE ROW LEVEL SECURITY;
```
RLS activo y sin políticas (las políticas siguen en 51). Bajada: `DROP TABLE`. Se pierde el catálogo; se recarga con la orden.

**Ediciones a lo existente (ERR-25):** `alembic_version` → `038_catalogo_nodos` en las 7 líneas de §0; `tablas_con_rls` 32 → 33; `test_sin_acceso.py` 33 y 33 → 34 y 34; `tests/teachers/test_access.py` gana `("/teachers/curriculo/nodos", GET): "teacher"`; `src/shared/models.py` (un modelo), `src/main.py` (el router) y `.gitignore` (el humo). Si la medición encuentra otra, se corrige esta lista primero.

## 2. Criterios
| # | Criterio | Test |
|---|---|---|
| C1 | **Lectura pura del archivo:** un mapa válido se lee; cada rechazo de §1.2 que no necesita la base (`sin_version`, `sin_nodos`, `id_invalido`, `id_repetido`, `campo_faltante`, y los tres `reemplazo_invalido`) da su motivo; una cadena A → B → C queda A → C y B → C | UM1 (no-integ) |
| C2 | **Carga:** 6 vigentes y 2 reemplazados → la tabla tiene 8 filas y el resumen lo dice; cargar otra vez → `nuevos: 0, cambiados: 0` y las mismas filas. `GET` trae los 6 vigentes en orden, con su versión; el estudiante recibe 403 | MN1 |
| C3 | **Un nodo no se borra:** un archivo sin un id que la tabla tiene → `nodo_desaparecido` con ese id, y la tabla queda **idéntica** (ni los nodos nuevos de ese archivo entran). El mismo archivo con ese id declarado en `reemplazos[]` → entra, y el id queda con su destino | MN2 |
| C4 | **Resolver:** vigente → él mismo; reemplazado → su destino; repetidos y un reemplazado junto a su destino → uno solo, en orden; un desconocido → 422 `nodo_desconocido` con solo los desconocidos; con el catálogo vacío, todo es desconocido | MN3 |
| C5 | Migración up/down/up idéntica (ERR-24) | MG38 |
| C6 | Regresión: los 488 previos verdes con solo las ediciones de §1.5 | la suite |

## 3. Tramposos, humo y réplica
Diagonal PREDICHA (el código no existe; ERR-23):

| Id | Rompe | Rojo predicho | Verde predicho y por qué |
|---|---|---|---|
| ZM1 | La carga borra lo que el archivo no trae | **MN2** (as: no hay rechazo y el id desaparece) | MN1: sus dos cargas traen lo mismo |
| ZM2 | La carga escribe nodo por nodo antes de validar lo que desaparece (no es todo o nada) | **MN2** (as: los nodos nuevos del archivo rechazado quedaron) | MN1 |
| ZM3 | `canonicos` no sigue los reemplazos | **MN3** (as) | MN1 y MN2 no resuelven |
| ZM4 | `canonicos` deja pasar lo desconocido | **MN3** (as: no hay 422) | — |
| ZM5 | `GET` trae también los reemplazados | **MN1** (as: 8 nodos) | — |
| ZM6 (no-integ) | La lectura acepta un id repetido | **UM1** (as) | — |

**Matriz a medir:** 5 tramposos integ × 5 columnas (MN1, MN2, MN3, MG38 y HC1) = 25 celdas.

**Humo HC1** escribe `tests/_salida/humo_catalogo_nodos.json` antes de afirmar. Semilla `random.Random(38)`: un mapa sintético de 40 nodos (5 tipos × 8 niveles) con ids de forma `tipo.nivel.tema-N`; se carga; una segunda versión fusiona 4 al azar (reemplazos) y agrega 3; se carga; se resuelven los 4 fusionados.
```json
{"alembic_version":"038_catalogo_nodos","semilla":38,"primera":{"vigentes":40,"reemplazados":0,"nuevos":40},
 "segunda":{"vigentes":39,"reemplazados":4,"nuevos":3},"filas":43,"api_nodos":39,
 "fusionados_resuelven":true,"desconocido":422}
```

**Réplica RC1** (`ENGRAMA_REPLICA_CATALOGO=1`; saltada sin la bandera): carga **el mapa real** (`ENGRAMA_CATALOGO_NODOS` o, por defecto, `../../curriculo/nodos.json`, solo lectura) y afirma que `vigentes` y `reemplazados` son los que el propio archivo trae, que la segunda carga da `nuevos: 0`, y que cada reemplazo del archivo resuelve a un vigente. Si el archivo no está, se salta y lo dice.

## 4. Cuentas (ERR-10)
| Grupo | integ | no-integ |
|---|---|---|
| MN1, MN2, MN3 | 3 | — |
| MG38 y HC1 | 2 | — |
| UM1 | — | 1 |
| ZM1-ZM5 | 5 | — |
| ZM6 | — | 1 |
| **Nuevos** | **10** | **2** |
| RC1 (saltado sin bandera) | 1 skipped | — |

**passed:** 488 + 12 = **500**; **skipped:** 18 + 1 = **19**; **no-integ:** 131 + 2 = **133**; ruff 0 y mypy 0.

## 5. Qué NO se toca
`INGLES/curriculo/` (solo se lee, y solo en la réplica), los retos, `/auth/me`, las monedas y el nivel. No hay IA.

## 6. Riesgo para producción
- Aplicar la 038 es producción: el sí de Christiam. No rompe nada existente (tabla nueva, nadie la lee todavía).
- **El catálogo se carga a mano después de migrar**, y otra vez cada vez que el mapa cambie. Sin cargar, las rutas que reciben nodos (los bloques siguientes) responden 422.
- El mapa de hoy está **sin firma de Christiam** (`revisado_por: null`). El backend carga lo que el operador le dé: no comprueba la firma. Queda para Christiam decidir si se exige.

## 7. Veredicto
- **FUNCIONA:** las cuentas de §4, la matriz medida, HC1 escrito, MG38 verde y RC1 verde con el mapa real.
- **HAY ALGO MODESTO:** todo lo anterior sin RC1 (el mapa real no estaba o no cargó).
- **NO:** una carga borra o deja a medias el catálogo; un id desconocido pasa; un reemplazado no resuelve; un tramposo queda verde.

---

## 8. Medido (2026-10-06, sobre `8e6e277`)

### Matriz medida: 25 celdas (ERR-19 y ERR-23)
**Cómo se midió:** una corrida de pytest por tramposo, aplicado a las 5 columnas por una fixture `autouse`, en un contenedor de prueba propio (`engrama-test-pg-opus1`, puerto 55434). La fila base dio 5 verdes.

**Resultado: 9 rojas, todas por aserción; 0 por excepción; 16 verdes.**

| Id | Rojas medidas |
|---|---|
| ZM1 | MN2 |
| ZM2 | MN2, **MN1** y **HC1** |
| ZM3 | MN3 y **HC1** |
| ZM4 | MN3 y **HC1** |
| ZM5 | MN1 y **HC1** |

**Cruces que la predicción no tenía (en negrita; ningún test se tocó para que calzara):**
- **ZM2 × MN1: predicción REFUTADA** (se había predicho verde). El tramposo escribe los vigentes antes de contar, así que el resumen de la primera carga dice `nuevos: 2` en vez de 8. La predicción miró solo lo que MN1 afirma del `GET` y no el resumen.
- **ZM2, ZM3, ZM4 y ZM5 × HC1:** el humo carga, fusiona, resuelve y lee el `GET`: ejercita los cuatro caminos. §3 no predijo nada para HC1.

### Cuentas medidas
**500 passed + 19 skipped** (suite completa desde un export limpio del commit, 707 s); **133 no-integ**; `ruff check .` 0 y `mypy .` 0 (280 archivos). Igual a §4. Los 6 tramposos, rojos por su razón en la primera corrida. Las ediciones a lo existente fueron las de §1.5.

- **HC1** escribió `tests/_salida/humo_catalogo_nodos.json`, idéntico a §3.
- **RC1 pasó en su primera corrida** con el mapa real: `nodos-0.3`, **521 vigentes y 14 reemplazos**, leído de `INGLES/curriculo/nodos.json` el 2026-10-06 (el mapa sigue en consolidación: esos dos números son de ese momento).

### Lo que la medición corrigió antes del commit
`mypy` marcó que el id leído del archivo podía ser `None` donde se usaba como texto: se concentró en una función (`mapa._id_de`) que devuelve el id o lanza `id_invalido`. Los criterios no se movieron.

### No medido
- **La orden por la línea de comandos** (`python -m src.curriculo cargar --archivo …`): los tests llaman a `correr_carga`, que es lo que la orden ejecuta, pero no pasan por `main()` (argumentos, lectura del archivo, códigos de salida 0 y 2).
- La carga contra una base con miles de referencias que reapuntar (aquí, decenas).
- Dos cargas a la vez (no hay candado sobre la tabla; es una orden del operador).
- El `downgrade` por la CLI de Alembic (MG38 corre las mismas tuplas de SQL).

## 9. Antes de aplicar la 038
1. Respaldo y el sí de Christiam (es producción).
2. `alembic upgrade head`.
3. `DATABASE_URL=… python -m src.curriculo cargar --archivo <ruta>/curriculo/nodos.json`; debe imprimir `vigentes` y `reemplazados` iguales a los del archivo.
4. Repetir el paso 3 cada vez que el mapa cambie. Si responde `nodo_desaparecido`, el mapa borró un id: se corrige **el mapa** (declarándolo en `reemplazos[]`), no la base.

### Medido después, a mano y fuera de la suite (2026-10-06, sobre `0d1058b`)
La orden por su `main()`, con un test desechable fuera del repo: con el mapa real → sale con **0** y carga (`nodos-0.3`, **523 vigentes y 14 reemplazos**: el mapa ya había cambiado desde RC1); con un archivo sin nodos, uno que no es JSON y uno que no existe → sale con **2** y no escribe. Queda sin medir solo la lectura de `DATABASE_URL` del entorno (el test inyecta las sesiones).
