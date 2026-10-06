# ESPEC · BUG-16: un `challenge_type` o `cefr_level` fuera del enum da 500, y debe dar 422

F4 · Creador · 2026-09-28 · preregistro. Rama `test/fixture-integ`, HEAD `508d568`. Origen: `ENGRAMA/despliegue/docs/ESPEC_despliegue_piloto.md` §11.2 (ARQUITECTO lo midió: `challenge_type: 'practice'` da **500**).

**Se implementa después de BUG-13, 14 y 15.** Toca `src/challenge_engine/schemas.py`, y ese árbol lo está editando el implementador de BUG-13. Parte de su meta final: **311 passed + 12 skipped y 100 no-integ** (`ESPEC_bug13a15.md` §4). Esa meta no está medida.

## 0. Leído con `grep -n` (2026-09-28, sin ejecutar)
Las líneas de `src/challenge_engine/*` y de `src/shared/models.py` se leyeron **en HEAD** (`git show 508d568:<ruta>`), porque en el árbol de trabajo BUG-13 las está moviendo.

| Qué | Dónde |
|---|---|
| CHECK de la BD, tipo | `alembic/versions/010_create_challenges.py:30`: `CHECK (challenge_type IN ('multiple_choice','open','fill_blank','listening'))` |
| CHECK de la BD, nivel | `010:32`: `CHECK (cefr_level IN ('A1','A1+','A2','A2+','B1-','B1','B1+','B2','B2+','C1','C1+'))` |
| CHECK de la BD, estado | `010:42`: `CHECK (status IN ('active','inactive','archived'))` |
| Espejo en el modelo | `models.py:441-447` (HEAD), con los nombres `challenges_type_check` y `challenges_cefr_check`. **El CHECK de la 010 es de columna y en línea, así que Postgres lo nombra `challenges_challenge_type_check`.** Es una predicción sin medir, y por eso ningún test busca el CHECK por nombre |
| Las tuplas existen, pero nadie las usa para validar | `schemas.py:32-36` (`_CEFR_LEVELS`, `_CHALLENGE_TYPES`, `_CHALLENGE_STATUSES`). Solo `_CHALLENGE_STATUSES` se usa, en `service/challenges.py:223` (da **400**, no 500) |
| El hueco | `schemas.py:65` `challenge_type: str = "multiple_choice"` y `:66` `cefr_level: str \| None = None` en `ChallengeCreate`; `:83` `cefr_level: str` en `ChallengeGenerateRequest` |
| Por qué da 500 | `service/challenges.py:69-84` inserta y hace `flush` sin validar; ningún `exception_handler` atrapa el `IntegrityError` (`grep -rn "exception_handler\|IntegrityError" src` sale vacío) |
| `/generate` | `service/generator.py:205-209` arma un `ChallengeCreate` con el `cefr_level` del cliente **después** de llamar a Anthropic, y `:216` convierte `ValueError` en 502. Hoy, un nivel malo gasta la llamada a la IA y termina en 500. Si solo se arregla `ChallengeCreate`, terminaría en 502, también **después** de gastar la llamada |

## 1. Qué cambia (una cosa)
**Los valores con CHECK de enum en `challenges` se validan en el esquema de entrada, con el mismo enum de la BD.** Un valor fuera del enum da 422 antes de tocar la base o la IA.

En `src/challenge_engine/schemas.py`:
- `ChallengeType = Literal["multiple_choice", "open", "fill_blank", "listening"]` y `CefrLevel = Literal["A1", "A1+", "A2", "A2+", "B1-", "B1", "B1+", "B2", "B2+", "C1", "C1+"]`, en el mismo orden que la 010.
- Las tuplas salen del Literal (`_CHALLENGE_TYPES = get_args(ChallengeType)` y `_CEFR_LEVELS = get_args(CefrLevel)`): una sola fuente, con los mismos valores y el mismo orden que hoy (identidad de `CHALLENGE_TYPES` y `CEFR_LEVELS`).
- En `ChallengeCreate`: `challenge_type: ChallengeType = "multiple_choice"` y `cefr_level: CefrLevel | None = None`.
- En `ChallengeGenerateRequest`: `cefr_level: CefrLevel`.

**Incluido por ser de la misma clase y trivial (declarado):**
- `cefr_level` en los dos esquemas: mismo archivo, mismo tipo de hueco (CHECK sin validar) y la misma tabla.
- Arreglar solo `challenge_type` dejaría el 500 de `cefr_level` a un campo de distancia.

**Solo anotaciones de tipo:** `service/generator.py` (`generate_challenge(cefr_level: CefrLevel, …)`), para que mypy acepte pasarle el Literal a `ChallengeCreate`. No cambia ninguna lógica.

## 2. Criterios
| # | Criterio | Test que se pone rojo |
|---|---|---|
| C1 | Un docente real hace `POST /challenges/` con `challenge_type: "practice"`: **422**, con un error de `type == "literal_error"` y `loc == ["body","challenge_type"]`. `challenges` y `challenge_questions` quedan con 0 filas nuevas | A16-1 |
| C2 | Lo mismo con `cefr_level: "B3"`: 422, con `loc == ["body","cefr_level"]` y 0 filas | A16-2 |
| C3 | **Identidad:** los 4 tipos válidos y los 11 niveles, más `cefr_level` ausente, dan 201. La respuesta trae el valor tal cual | S16 |
| C4 | **Mismo enum que la BD:** los argumentos del Literal de `challenge_type` y de `cefr_level` son iguales, como conjunto y en orden, a los valores del CHECK leídos de la base viva. Se leen con `pg_get_constraintdef` en `pg_constraint`, con `conrelid = 'challenges'::regclass` y `contype = 'c'`, filtrando por el nombre de la columna en la definición; los valores se sacan con la regex `'([^']+)'::text` | U16-1 |
| C5 | `POST /challenges/generate` con `cefr_level: "B3"` da **422 sin llamar a la IA** | U16-2 |
| C6 | Regresión: los 311 previos siguen verdes y no se edita ningún test existente | la suite completa |

## 3. Tests y tramposos
**Tests:**
- **A16-1, A16-2, S16 y U16-1** (integ) van en `tests/challenge_engine/test_bug16_enum.py`.
  - Siembra: `crear_tenant` y un docente con `crear_perfil(rol="teacher")`.
  - Usan `TestClient(app, raise_server_exceptions=False)`: así, el 500 de hoy es un `AssertionError` y no una excepción que se escapa. Eso permite el xfail estricto del paso 1.
- **U16-2** (no-integ) va en el mismo archivo, marcado aparte, o en `test_challenges.py`.
  - Usa `dependency_overrides[get_current_user]` con un `AuthContext` de docente, como `_student_auth_context` en `test_challenges.py:31`.
  - Hace `monkeypatch.setattr(generator_mod.settings, "anthropic_api_key", "")`: así, si el 422 no llega, el resultado es un 503 local y **nunca** una llamada real a la IA, aunque haya una clave en el `.env` de quien corre la prueba.
- **H16** (integ, humo) escribe `tests/_salida/humo_bug16.json` **antes** de afirmar:
  ```json
  {"practice":422,"B3":422,"generate_B3":422,"tipos_validos":[201,201,201,201],"niveles_validos":11,"filas_con_valor_invalido":0}
  ```
  El archivo se agrega a `.gitignore`.

**Tramposos:** `tests/tramposos/test_tramposos_bug16.py`, con `pytest.raises(AssertionError)` sobre el cuerpo del test real.

**Mecanismo:** el modelo del cuerpo queda fijado al decorar la ruta, así que parchear el módulo no sirve. El tramposo reemplaza la ruta en `app.router.routes` con `monkeypatch.setitem`, por una `APIRoute` con el mismo path, los mismos métodos, el mismo `status_code` y el mismo `response_model`. Su endpoint llama a la función original del router con un modelo derivado: `create_model("Roto", __base__=ChallengeCreate, challenge_type=(str, "multiple_choice"))`.

| Id | Rompe | Rojo predicho | Verde predicho y por qué |
|---|---|---|---|
| Y16-1 | La ruta `POST /challenges/` con `challenge_type: str` | **A16-1** (as: 500) y H16 (as) | A16-2: el nivel sigue siendo Literal. S16: los valores válidos pasan. U16-1: lee el esquema, no la ruta |
| Y16-2 | La ruta con `Literal` **sin** `"listening"` | **S16** (as: 422 en `listening`) | A16-1: `practice` sigue dando 422 |
| Y16-3 | La ruta con `cefr_level: str \| None` | **A16-2** (as: 500) y H16 | A16-1 y S16 |
| Y16-4 | La ruta `/challenges/generate` con `cefr_level: str` (no-integ) | **U16-2** (as: 503) | los demás no llaman a `/generate` |
| Y16-5 | `monkeypatch.setitem(ChallengeCreate.model_fields, "challenge_type", …)` con un `FieldInfo` cuyo Literal tiene 3 valores | **U16-1** (as) | A16-* y S16: la validación compilada no cambia (**por eso Y16-5 no sirve de tramposo para la API, solo para la paridad**) |

La matriz se mide completa antes de aceptar: 5 tramposos × 6 tests (A16-1, A16-2, S16, U16-1, U16-2 y H16) = **30 celdas**. Lo no medido no es "no cruza" (ERR-15 y ERR-19).

### Matriz medida: 30 celdas (paso 3; ERR-19 y ERR-23)
**Cómo se midió** (2026-10-06, sobre el código del paso 2): una corrida de pytest por tramposo, con el tramposo aplicado a las 6 columnas por una fixture `autouse` que llama al mismo `aplicar` del registro `TRAMPOSOS`. La fila base dio 6 verdes.

**Resultado: 9 rojas, todas por aserción; 0 por excepción y 0 por preparación.**

| Id | Rojas medidas |
|---|---|
| Y16-1 | A16-1 y H16 |
| Y16-2 | S16 y **H16** |
| Y16-3 | A16-2 y H16 |
| Y16-4 | U16-2 y **H16** |
| Y16-5 | U16-1 |

**Dos cruces que la predicción no tenía (en negrita; ERR-23). Los tests no se tocaron.**
- **Y16-2 × H16:** el humo crea un reto de cada tipo válido, y sin `"listening"` su `tipos_validos` sale `[201, 201, 201, 422]`. La predicción solo miró a S16.
- **Y16-4 × H16:** el humo también llama a `/challenges/generate` con `B3`; con la ruta rota llega al generador y `generate_B3` sale 503. La predicción decía "los demás no llaman a `/generate`", y H16 sí.

**Precisiones del paso 2 (ningún criterio cambia):**
- **El mecanismo del tramposo:** `monkeypatch.setitem` no sirve para una lista. Se reemplaza `app.router.routes` entera por una copia con la ruta cambiada (`setattr`), y la `APIRoute` nueva lleva `dependency_overrides_provider`; sin él ignoraría el `get_db` del fixture. Es lo mismo que ZP9 del login piloto.
- **U16-1** compara, además de los dos campos de `ChallengeCreate`, el `cefr_level` de `ChallengeGenerateRequest` y las tuplas exportadas `CHALLENGE_TYPES` y `CEFR_LEVELS`.
- **S16** afirma también que, sin `challenge_type`, el reto nace `multiple_choice`.
- **Medido en la base viva:** `challenges` tiene exactamente un CHECK que nombra `challenge_type` y uno que nombra `cefr_level`, con los valores y el orden de la 010.
- **U16-2 y H16 nunca llaman a la red:** vacían `anthropic_api_key` antes de pedir.

## 4. Cuentas (ERR-10: la suma a la vista)
**Base:** la meta final de BUG-13 a 15, **311 passed + 12 skipped y 100 no-integ**. No está medida; si cierra con N, S y M, las metas pasan a N + 11, S y M + 2.

| Grupo | integ | no-integ |
|---|---|---|
| A16-1, A16-2, S16 y U16-1 | 4 | — |
| U16-2 | — | 1 |
| H16 | 1 | — |
| Y16-1, Y16-2, Y16-3 y Y16-5 | 4 | — |
| Y16-4 | — | 1 |
| **Nuevos** | **9** | **2** |

- **passed:** 311 + 9 + 2 = **322**;
- **skipped:** 12 (no hay réplica con bandera: esta espec no tiene estado ni concurrencia, y la réplica con entradas nuevas es S16, que recorre **todos** los valores válidos);
- **no-integ:** 100 + 2 = **102**;
- ruff 0 y mypy 0.
- **Medido (2026-10-06), con el login del piloto ya adentro: 366 passed + 14 skipped y 109 no-integ; `ruff check .` 0 y `mypy .` 0 (205 archivos).** Es la suma prevista abajo. El paso 1 se midió en su archivo (2 passed + 3 xfailed) y en no-integ (107 passed + 1 xfailed); la suite completa de ese paso no se corrió.

Si `ESPEC_login_piloto.md` entra antes, las dos metas se suman: 355 + 11 = **366 passed**, 14 skipped y 107 + 2 = **109 no-integ** (§5 de esa espec, corregida en 73dbbfd).

## 5. Orden de commits (cada uno con 0 failed)
1. **`test(bug16)`:** A16-1, A16-2 y U16-2 con `xfail(strict=True, raises=AssertionError)`; S16 y U16-1 en verde (hoy el esquema no tiene Literal, así que U16-1 compara las **tuplas** `CHALLENGE_TYPES` y `CEFR_LEVELS` con la BD, y en el paso 2 pasa a leer el Literal).
   - Esperado: 311 + 2 = **313 passed + 3 xfailed + 12 skipped**; no-integ 100 + 0 = 100 passed + 1 xfailed.
   - **Aquí se ve el 500 por la API.**
2. **`fix(bug16)`:** los Literal, `generator.py` (solo tipos), H16, Y16-1..5 y `.gitignore`. Se quitan los 3 xfail.
   - Esperado: 313 + 3 + 1 + 5 = **322 passed + 12 skipped**; no-integ **102**.
3. **`docs(bug16)`:** la matriz medida en §3.

## 6. Impacto en el cliente y para el pedagogo (ERR-16)
- **Contrato:** un 500 pasa a 422, sin cambios en el camino feliz. engrama-web ya dejó de mandar `'practice'` (`engrama-web/herramientas/sembrar/mapeo.mjs:145`), y `despliegue/sembrar.mjs` lo mapea a `multiple_choice`. **Aviso a ARQUITECTO:** con BUG-16, cualquier `challenge_type` que quede mal mapeado se ve como 422 con el campo exacto.
- **Para el pedagogo (ERR-16):** el tipo decide cómo se califica. `service/attempts.py`: `_PARTIAL_CREDIT_TYPES = {"open", "fill_blank"}` gana con ≥ 70 %; `multiple_choice` y `listening` exigen el 100 %. Mapear `'practice'` a `multiple_choice` hace que un reto de práctica sea **todo o nada**, y eso lo ve el estudiante.
  - BUG-16 no cambia esto. Solo impide que un valor inválido llegue a la base.
  - Qué tipo corresponde a cada unidad del piloto lo decide el pedagogo.

## 7. Otros CHECK o enum que el esquema no valida (inventario; solo las rutas montadas en `src/main.py:15-19`)
| Campo | CHECK de la BD | Hoy | Decisión |
|---|---|---|---|
| `ChallengeCreate.challenge_type` | `010:30` | 500 | **BUG-16** |
| `ChallengeCreate.cefr_level` | `010:32` | 500 | **incluido** (misma clase, trivial) |
| `ChallengeGenerateRequest.cefr_level` | `010:32`, vía el generador | 500 después de gastar la IA | **incluido** (si no, pasa a 502 después de gastar la IA) |
| `ChallengeStatusUpdate.status` | `010:42` | **400** (validado en `service/challenges.py:223`) | Para después: no es un 500. Pasarlo a 422 cambia el contrato |

**Para después (no son de la clase CHECK/enum, o no son triviales; todos predichos, sin medir):**
- **Enteros sin tope** (`INTEGER` de 32 bits): `coins_reward`, `xp_reward`, `max_attempts` y `max_winners` (`ChallengeCreate`, solo `ge`), `order_index` (`ChallengeQuestionIn`) y `max_capacity` (`GroupCreateIn`). Con un valor > 2.147.483.647 se predice un `DataError` de asyncpg, es decir, un 500.
- **Texto con el carácter NUL (`\u0000`)** en cualquier campo `str`: Postgres rechaza 0x00 en `text`, y se predice un 500.
- **`coins_reward = 0`** (lo permite `ge=0`): `award_coins` rechaza `amount <= 0` con **400** (`service/coins.py:108` en HEAD). Se predice que **toda victoria de ese reto responde 400** y el estudiante no puede completarlo. **Candidato a BUG y para el pedagogo (ERR-16),** porque lo ve el estudiante. Ese código lo está editando BUG-13, así que se mide cuando cierre.
- `ChallengeQuestionIn.question_type` no tiene CHECK en la BD (`011`): se acepta texto libre. Calidad de datos, no un 500.
- `TeacherAssignIn.documento_id` (M2) no valida el formato. Da 404, no 500. Va junto con `ESPEC_login_piloto.md` §2 (D1), que valida M3.

## 8. Qué NO se toca
- La lógica de `service/challenges.py`, `service/attempts.py` y `router.py`: BUG-13 los está editando.
- Las migraciones: los CHECK ya existen y **no hace falta migración**.
- `ChallengeOut`: la salida sigue siendo `str`, porque la BD ya garantiza el valor.

## 9. Veredicto
- **FUNCIONA:** las cuentas exactas de §4, la matriz medida, H16 escrito y los 311 previos idénticos.
- **NO:** A16-1 o A16-2 dan algo distinto de 422, un tramposo queda verde, U16-2 llama a la red o cambia un test previo.
