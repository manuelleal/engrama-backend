"""Alta de instituciones y personas por el OPERADOR — `docs/ESPEC_login_piloto.md` §1.7.

No es un módulo HTTP: es una CLI (`python -m src.onboarding alta|restablecer`).
Crear un tenant, fondear su billetera y crear cuentas de GoTrue son acciones
del operador de la plataforma, no del admin de un colegio; por eso no hay
endpoint ni rol nuevo.
"""
