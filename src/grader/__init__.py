"""La puerta del Grader — `docs/ESPEC_grader_anillo.md`.

El profe, con su cuenta de ENGRAMA (solo su Bearer; sin secretos compartidos),
pide la lista numerada de un grupo suyo, registra un examen impreso y entrega
las hojas calificadas. El backend las guarda por ítem, sin duplicar.

  - `schemas.py` los cuerpos, estrictos y sin dónde meter una imagen.
  - `reglas.py`  PURO: qué hace que una hoja se rechace, y qué es un acierto.
  - `listas.py`  el número de lista (nace aquí; estable; no se reutiliza).
  - `service.py` registrar el examen y recibir las hojas.
  - `router.py`  las tres rutas de `/grader`.

No mueve el nivel confirmado, no acredita monedas y no guarda imágenes.
"""
