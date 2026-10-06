"""Autorregistro con código de grupo — `docs/ESPEC_autorregistro.md`.

  - `codigos.py`  : el código de inscripción (generar, normalizar, huella) y su ciclo de vida.
  - `limite.py`   : el límite de intentos en memoria y la IP del visitante.
  - `cuentas.py`  : el ÚNICO módulo del proceso web que usa la clave de servicio.
  - `service.py`  : registrar (perfil primero, cuenta después, compensación).
  - `decision.py` : la lista del profe, aprobar y rechazar.
  - `pendiente.py`: ¿este perfil espera aprobación? (lo usa `get_current_user`).
  - `router.py`   : `POST /auth/registro` y las rutas del profe.
"""
