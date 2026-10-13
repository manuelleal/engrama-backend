# Pedido al sembrador (`engrama-web/herramientas/sembrar/`)

Creador (backend) · 2026-10-12. El sembrador vive en otro repo y lo escribe otro agente: este documento es el contrato, no un cambio.

**Para qué:** que la cola de repaso deje de quedar vacía y que la tanda de hoy (`POST /challenges/tanda`) tenga de dónde elegir. Origen: dictamen `investigacion/pedagogia/04-dictamen-racha-y-reto-del-dia.md` (hecho 2 y §1.3, "Qué entra al feed") y `docs/ESPEC_refuerzo.md` §6.

## 1. Lo que YA acepta el backend (desde la 041; no falta nada del lado del servidor)

`POST /challenges/` acepta, **por pregunta**, cuatro campos opcionales que el sembrador hoy no manda:

| Campo | Qué es | De dónde sale en `contenido/` |
|---|---|---|
| `nodos` | lista de hasta 8 ids VIGENTES del catálogo (`curriculum_nodes`) | `curriculo/etiquetas_unidades.json`, por familia |
| `item_ref` | el id del ítem en el banco (`b1-u01-f01-2`). Es la identidad de la pregunta | `item.id` |
| `familia` | el id de su familia (`b1-u01-f01`) | `familia.familia` |
| `rol` | `original`, `gemela` o `repaso` | `item.rol` |

Un nodo que no está en el catálogo responde **422 `nodo_desconocido`** y el reto no se crea: el catálogo se carga antes de sembrar (`python -m src.curriculo cargar --archivo curriculo/nodos.json`).

## 2. El cuerpo exacto que debe mandar (un reto de `piensalo`)

```json
{
  "title": "b1-u01 · Job interview · Gramática 1 · original",
  "description": "",
  "challenge_type": "multiple_choice",
  "cefr_level": "B1",
  "skill": "grammar",
  "topic": "b1-u01",
  "coins_reward": 10,
  "max_attempts": 2,
  "group_id": "<uuid del grupo>",
  "questions": [
    {
      "question_type": "multiple_choice",
      "question_text": "I ___ in sales for five years.",
      "options_json": [{"label": "A", "value": "have worked"}, {"label": "B", "value": "work"}],
      "correct_answer": "A",
      "order_index": 1,
      "nodos": ["gr.b1.present-perfect-duracion"],
      "item_ref": "b1-u01-f01-1",
      "familia": "b1-u01-f01",
      "rol": "original"
    }
  ]
}
```

- `cefr_level`, `topic` (el id de la unidad) y `skill` **ya los manda** y son los que usa la tanda: el nivel elige el reto y el orden fijo es `topic`, después `skill` (`grammar` → `vocabulary` → sin `skill`, que es la lectura), después `title`. **No cambiar esos tres.**
- Las lecturas (`lo_dice`) van sin `rol` y sin `familia`; `nodos` e `item_ref` si los tienen.
- Sin `max_winners`, como hoy.

## 3. `solo_refuerzo` (YA EXISTE en el backend desde la migración 044; `docs/ESPEC_solo_refuerzo.md`)

Hoy el sembrador pone en el feed, pagando 10 cada uno, el original, la gemela y el repaso de la misma familia. El dictamen pide que **solo el `original` y las lecturas** entren al feed y a la tanda; los retos de rol `gemela` y `repaso` se siembran con un campo del reto:

```json
{"title": "b1-u01 · Job interview · Gramática 2 · gemela", "solo_refuerzo": true, "...": "lo demás igual"}
```

- **Regla para el sembrador:** `solo_refuerzo: true` en todo reto cuyas preguntas sean de rol `gemela` o `repaso`; el `original` y las lecturas, sin el campo (o en `false`).
- **Un reto por rol, sin mezclar:** la segunda vuelta (a 21 días del original, paga 5) solo toma retos cuyas preguntas sean **todas** `gemela`. Un reto que mezcle `gemela` y `repaso` sirve a la cola de repaso pero nunca a la segunda vuelta.
- Cada pregunta lleva su `familia` y su `rol`: sin `familia`, la gemela no se puede emparejar con su original.
- Qué hace el backend con un reto `solo_refuerzo`: no sale en el feed ni en la tanda de retos nuevos; un estudiante recibe 404 si intenta abrirlo; sus preguntas son las formas de la cola de repaso; muestra y paga a lo sumo 5 (`SEGUNDA_VUELTA_PAGA`).
- **Requiere la migración 044 aplicada:** sin ella `POST /challenges/` responde 500 (falta la columna).
- **Lo ya sembrado no cambia solo:** los retos de rol `gemela` y `repaso` que ya están en el feed siguen ahí hasta que se resiembren (o se archiven y se vuelvan a crear con el campo).

## 4. Recomendaciones (no bloquean)

- `max_attempts`: con 2, un reto ganado solo se puede repetir una vez, y el modo "repetir lo ganado" de la tanda (cuando el nivel se agota) se acaba pronto. Subirlo es decisión del dueño porque toca cuántas veces se puede intentar cobrar.
- Sembrar por nivel completo: la tanda solo sirve retos del nivel de práctica del estudiante (sin examen arranca en A2).

## 5. Cómo se comprueba

Después de sembrar, con un estudiante del grupo:
```
POST /challenges/tanda      → 200, `tanda.retos` con 2 a 4 retos del nivel, en el orden de las unidades
GET  /challenges/refuerzo   → tras fallar una pregunta con nodos, `pendientes` trae una forma no vista
```
