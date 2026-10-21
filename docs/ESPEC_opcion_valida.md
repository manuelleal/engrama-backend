# ESPEC · `/answers` rechaza una respuesta que no es ninguna opción de la pregunta

Creador · 2026-10-20 · **preregistro** (se commitea antes del código). Rama `seg/opcion-valida`, sobre `f7f7aeb` (no-integ **208**; ruff 0). **Sin migración.**

## 0. Medido y leído (antes de tocar nada)
- **En el piloto (lo reportó el coordinador):** en una pregunta V/F/ND, `POST /challenges/attempts/{id}/answers` con `"answer": "A"` devolvió **200** y la calificó incorrecta: quedó guardada como primera respuesta (gana la primera) y cuenta como fallada al cerrar.
- **El hueco:** `por_pregunta.responder` (`src/challenge_engine/service/por_pregunta.py`) califica con `explicar.acerto` y guarda con `_guardar_primera` sin preguntar si la respuesta es una de las opciones. `calificar.label_de` traduce un `value` a su `label`, y si no encuentra nada devuelve el texto tal cual: "A" no es igual a la clave "V" y sale incorrecta.
- **Una V/F/ND por dentro:** el sembrador (`engrama-web/herramientas/sembrar/mapeo.mjs`) la crea como `question_type: "multiple_choice"` con `options_json = [{label:"V", value:"True"}, {label:"F", value:"False"}, {label:"ND", value:"Not given"}]` y `correct_answer` = la label. La opción múltiple normal: labels "A", "B"… con su `value`.
- **Lo que manda la web:** `engrama-web/src/vistas/estudiante/reto_l1.js` manda la **label exacta** de la opción elegida (`data-testid="opcion-<label>"`); `src/ui/practica.js` solo deja jugar por `/answers` preguntas `multiple_choice` con `options_json` y `label` en cada opción. La web nunca manda texto libre a una pregunta de opciones: el cambio no la rompe.
- **Tests que hoy mandan por `/answers` algo que no es opción:** ninguno. Las respuestas "Z" y "X" de los tests van por `/submit`, que no se toca.

## 1. Qué cambia (una cosa)
En `POST /challenges/attempts/{id}/answers`, si la pregunta es **de opción cerrada** y la respuesta **no es una de sus opciones**, la ruta responde **422** con un `detail` de texto fijo (`"Answer is not one of the question's options"`, sin eco de lo enviado) y **no escribe nada**.

- **De opción cerrada** = la pregunta tiene en `options_json` al menos una opción (objeto) con `label`. No importa el `question_type`: entra la opción múltiple, la V/F/ND y cualquier otra que traiga opciones.
- **Es una de sus opciones** = la respuesta, normalizada con `calificar.normalizar` (la misma de la calificación: NFC, comillas rectas, minúsculas, espacios colapsados, sin `.` `!` `?` al final), no es vacía y es igual a la `label` normalizada o al `value` normalizado de alguna opción. Así se acepta todo lo que `label_de` ya traducía: "V", " v ", "True", "true", "Not given".
- **Dónde:** una función pura nueva `calificar.es_opcion_valida(p, respuesta) -> bool` (verdadera siempre en las preguntas sin opciones) y, en `por_pregunta.responder`, la llamada **después** de los 404/409 de hoy (intento ajeno, intento cerrado, pregunta ajena) y **antes** de calificar y guardar.
- Las de respuesta escrita (sin opciones: completar, escribir) siguen igual: cualquier texto vale.

## 2. Qué debe pasar, medible
| # | Criterio | Test |
|---|---|---|
| C1 | **Pura:** `es_opcion_valida` en V/F/ND: "V", "F", "ND", " v ", "nd.", "True", "false", "Not given" → verdadero; "A", "Verdadero", "", "   ", "VF", "T" → falso. En A/B/C: "A", "b", "goes" (value) → verdadero; "D", "V" → falso. Escrita (sin opciones): "lo que sea", "" → verdadero. Una `multiple_choice` sin opciones → verdadero (no hay contra qué validar; §5) | OV-U1 |
| C2 | **HTTP, V/F/ND:** "A" → 422 con el `detail` fijo, que no contiene "A" como palabra enviada (es el mismo texto para "A" y para "Verdadero"); tras los dos 422: **0** filas en `challenge_attempt_answers`, **0** filas en `coin_ledger`, saldo del estudiante igual, el intento sigue `in_progress` | OV-A1 |
| C3 | **La válida sigue igual:** después de los 422, "F" (incorrecta) da **200** con `is_correct=False`, `repetida=False` (los 422 no la ocuparon), `respondidas=1`, la correcta "V" y su banda (oración y explicación con `por_opcion` de "F"); "True" por su `value` en otra V/F/ND da 200 y `is_correct=True` | OV-A1 |
| C4 | **Opción múltiple A/B/C:** "D" → 422; "B" → 200 | OV-A1 |
| C5 | **Escrita sin cambio:** en un `fill_blank`, "cualquier cosa" → 200, `is_correct=False` | OV-A1 |
| C6 | **Regresión = identidad:** los tests de L1 existentes (`test_l1_calificar_unit.py`, `test_l1_por_pregunta.py`, `tramposos/test_tramposos_l1.py`) y todos los no-integ pasan **sin editarlos** | suite |

**Humo:** OV-A1 escribe `tests/_salida/humo_opcion_valida.json` (lo observado entero) **antes** de afirmar. En `.gitignore`, como los demás.

## 3. Cómo sabremos que falló: tramposos
| Tramposo | Qué rompe | Rojo predicho |
|---|---|---|
| **El código viejo** (`f7f7aeb`, sin el arreglo) | no hay validación | OV-A1 rojo con `'vfnd_A': (200, ...` (se corre de verdad antes de escribir el arreglo) |
| **ZOV1** | `es_opcion_valida` siempre verdadera (el comportamiento viejo, inyectado) | OV-U1 (`'A': True`) y OV-A1 (`'vfnd_A': (200`) |
| **ZOV2** | compara solo `label`, no `value` | OV-U1 (`'True': False`) y OV-A1 (`'vfnd_por_valor_True': (422`) |
| **ZOV3** | compara sin normalizar (texto exacto) | OV-U1 (`' v ': False`) |
| **ZOV4** | toda pregunta es cerrada (la escrita sin opciones también se rechaza) | OV-U1 (`'lo que sea': False`) y OV-A1 (`'escrita': (422`) |

ZOV1 a ZOV4 viven en `tests/tramposos/test_tramposos_opcion_valida.py` con el patrón de `test_tramposos_l1.py` (monkeypatch en el módulo donde se usa; se exige `AssertionError` con el mensaje predicho). Los de OV-U1 son no-integ.

## 4. Qué NO se toca
- `/submit` (`attempts.grade_answers`) y el repaso (`src/refuerzo/service.py`, que también califica con `explicar.acerto`): tienen el mismo hueco, quedan **para después** (§6).
- `calificar.calificar`, `label_de`, la explicación, los esquemas, la web, las migraciones, el piloto (nada se despliega).
- El orden y el texto de los 404/409 de hoy.

## 5. Réplica
OV-U1 se corre también con un juego de opciones que no está en ningún banco (labels "Yes"/"No"/"Maybe" con values en español) generado en el test: las labels y values pasan, una label de V/F/ND ("V") no.

## 6. Para después
- `/submit` y el repaso aceptan igual una respuesta fuera de opciones (la califican incorrecta). Cerrarlos es otro encargo.
- Una `multiple_choice` sin `options_json` no se puede validar (no hay opciones): hoy el sembrador nunca la crea; se podría exigir opciones al crear.
