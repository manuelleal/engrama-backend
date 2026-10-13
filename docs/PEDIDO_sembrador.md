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

## 3. Lo que cambia cuando exista `solo_refuerzo` (PENDIENTE en el backend: bloque 3, sin código)

Hoy el sembrador pone en el feed, pagando 10 cada uno, el original, la gemela y el repaso de la misma familia. El dictamen pide que **solo el `original` y las lecturas** entren al feed y a la tanda; los retos de rol `gemela` y `repaso` se sembrarán con un campo nuevo del reto:

```json
{"title": "b1-u01 · Job interview · Gramática 2 · gemela", "solo_refuerzo": true, "...": "lo demás igual"}
```

- **Ese campo todavía NO existe:** hoy `POST /challenges/` responde 422 si llega (`extra = forbid`). No mandarlo hasta que el backend lo anuncie.
- **Mientras tanto** (para el piloto del jueves): sembrar los tres roles como hoy, pero **con `nodos`, `item_ref`, `familia` y `rol`**. La cola de repaso ya funciona con eso; su límite conocido es que quien abre el reto de la gemela la "ve" y deja de servirle como repaso (`ESPEC_refuerzo.md` §12).

## 4. Recomendaciones (no bloquean)

- `max_attempts`: con 2, un reto ganado solo se puede repetir una vez, y el modo "repetir lo ganado" de la tanda (cuando el nivel se agota) se acaba pronto. Subirlo es decisión del dueño porque toca cuántas veces se puede intentar cobrar.
- Sembrar por nivel completo: la tanda solo sirve retos del nivel de práctica del estudiante (sin examen arranca en A2).

## 5. Cómo se comprueba

Después de sembrar, con un estudiante del grupo:
```
POST /challenges/tanda      → 200, `tanda.retos` con 2 a 4 retos del nivel, en el orden de las unidades
GET  /challenges/refuerzo   → tras fallar una pregunta con nodos, `pendientes` trae una forma no vista
```
