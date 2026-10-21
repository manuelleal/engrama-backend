"""El camino de nivel: en qué va cada unidad del nivel de práctica — `docs/ESPEC_camino_progreso.md`.

  - `reglas.py`  los estados, el bloqueo suave y la recomendada (puro, sin base).
  - `service.py` lee lo que ya existe (retos, intentos, respuestas) y arma el camino. NO escribe.
  - `schemas.py` la salida de `GET /challenges/camino`.

El camino no paga nada: completar una unidad no da monedas extra (pedagogía 06 §2.5).
Las monedas siguen saliendo solo del acierto (`/submit`, `/finish`).
"""
