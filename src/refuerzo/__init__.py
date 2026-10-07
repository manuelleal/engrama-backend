"""La cola de refuerzo personalizado — `docs/ESPEC_refuerzo.md`.

Lo que entra a la cola es el NODO que el estudiante falló (en una hoja del
Grader o en un reto), no la pregunta. Se le sirve una forma paralela que no
ha visto, sin monedas, y queda superado con un acierto y un repaso espaciado.

  - `reglas.py`  PURO: estados, transiciones, identidad de una forma y cuál se sirve.
  - `cola.py`    lo que ENTRA: los ganchos del Grader y de los retos.
  - `formas.py`  las candidatas de un nodo y lo que cada estudiante ya vio.
  - `service.py` lo que ve y responde el estudiante.
  - `panel.py`   lo que ve el profe (solo él) y los huecos de contenido.
  - `router.py`  la ruta del profe; las del estudiante viven en el router de retos.

Este módulo NO llama a `award_coins` ni a `record_confirmed_level`: el
refuerzo no paga monedas y no mueve el nivel. No hay IA.
"""
