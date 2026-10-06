# ESPEC · El generador viejo con IA nace apagado (`POST /challenges/generate`)

F4 · Creador · 2026-10-06 · preregistro. Rama `test/fixture-integ`, sobre `26aa419` (485 passed + 18 skipped; 128 no-integ; ruff 0; mypy 0).

Origen: la decisión 012, D6 y anexo A. La ruta llama a un proveedor de IA dentro de la petición del profe, con el modelo fijo en el código, sin compuertas de calidad, sin revisar créditos y pegando `specific_instructions` tal cual en el mensaje; el reto queda **activo** de una vez.

## 0. Medido (2026-10-06)
| Qué | Dónde (`grep -n` de hoy) |
|---|---|
| La ruta | `src/challenge_engine/router.py:79` (`generate_challenge_endpoint`), `require_teacher` |
| Tests que la llaman | `tests/challenge_engine/test_challenges.py:84` (401 sin pase) y `:121` (403 estudiante); `test_bug16_enum.py:188` (`generar_b3`, U16-2: `B3` → 422) y `tests/integ/test_humo_bug16.py:38`. **Ninguno manda un cuerpo válido** |
| Tramposos sobre la ruta (ERR-26) | `tests/tramposos/test_tramposos_bug16.py:80` (Y16-4): reemplaza la ruta por otra con el **mismo** endpoint y un modelo roto, y exige `U16-2: /generate con B3 dio 503` |

## 1. Qué cambia (una cosa)
**`POST /challenges/generate` responde `503 {"detail": "generador_apagado"}` salvo que la variable `CHALLENGES_GENERATE_ENABLED` esté encendida.** Apagada por defecto.

- El interruptor se mira **dentro del endpoint, antes de llamar al generador**: con él apagado no hay llamada a la IA, ni reto, ni fila en `ai_usage_logs`.
- El orden de las respuestas previas no cambia: sin pase → 401; estudiante → 403; cuerpo inválido → 422. El 503 es para un profe con un cuerpo válido.
- Encendida, la ruta hace exactamente lo de hoy (no se arregla nada del generador: lo reemplaza la fábrica de la 012).
- Variable nueva: `CHALLENGES_GENERATE_ENABLED` (`true`/`false`; por defecto `false`). No es un secreto.

## 2. Criterios
| # | Criterio | Test |
|---|---|---|
| C1 | Con la variable ausente del entorno y sin `.env`, `Settings().challenges_generate_enabled` es `False` | GA1 |
| C2 | Apagado: un profe con cuerpo válido recibe 503 `generador_apagado` y el generador **no se llama** (0 llamadas a un doble que cuenta) | GA1 |
| C3 | Encendido: el mismo cuerpo llega al generador (1 llamada al doble) | GA1 |
| C4 | Regresión: 401, 403 y el 422 de U16-2 idénticos | los 4 tests de §0, sin editar |

GA1 es no-integ (`dependency_overrides` de `get_current_user`; el generador es un doble que cuenta y corta con un 418 propio, así que no se toca la base).

## 3. Tramposos
| Id | Rompe | Rojo predicho |
|---|---|---|
| ZGA1 | El endpoint no mira el interruptor | GA1 (as: apagado da 418 y 1 llamada) |
| ZGA2 | El valor por defecto es `True` | GA1 (as: `por_defecto: True`) |

**Tramposo existente (ERR-26):** Y16-4 usa el mismo endpoint, así que el interruptor queda dentro de su ruta rota. Predicción: sigue rojo con el mismo mensaje (`dio 503`), pero el 503 ahora lo produce el interruptor y no la clave vacía. Sigue midiendo lo suyo: que sin el `Literal` el `B3` pasa la validación. Se declara; no se edita.

## 4. Cuentas (ERR-10)
485 + 1 (GA1) + 2 (ZGA1, ZGA2) = **488 passed + 18 skipped**; no-integ 128 + 3 = **131**. Matriz: 2 tramposos × 1 test = 2 celdas, las dos rojas.

## 5. Qué NO se toca
`generator.py`, el esquema `ChallengeGenerateRequest`, los 4 tests de §0, Y16-4 y `tests/teachers/test_access.py` (la guarda de la ruta sigue siendo `teacher`).

## 6. Riesgo para producción
Al desplegar este commit, la generación con IA deja de funcionar hasta poner `CHALLENGES_GENERATE_ENABLED=true`. Es lo pedido (012, D6). engrama-web debe tratar el 503 `generador_apagado` como "función no disponible", no como error de red.

## 7. Veredicto
- **FUNCIONA:** las cuentas de §4, ZGA1 y ZGA2 rojos por su razón, y los 4 tests de §0 verdes sin editar.
- **NO:** con la variable ausente se llama al generador, o cambia un 401, 403 o 422 previo.
