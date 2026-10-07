"""El foco del grupo y las etiquetas de nodo de los retos — `docs/ESPEC_foco_grupo.md`.

  - `fechas.py`    PURO: qué día es "hoy" en la institución y cuándo dos periodos se solapan.
  - `service.py`   los periodos del foco, el vigente, y el feed priorizado del estudiante.
  - `etiquetas.py` leer y reemplazar los nodos de las preguntas de un reto.
  - `logro.py`     el logro del GRUPO por nodo (la regla de T5 y T7, por nodo).
  - `router.py`    las rutas del profe (`/teachers/...`).

La ruta del estudiante (`GET /challenges/foco`) vive en el router de retos,
porque debe declararse antes de `/challenges/{challenge_id}`. No hay IA.
"""
