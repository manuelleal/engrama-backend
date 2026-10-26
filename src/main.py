from fastapi import FastAPI

from src.auth.router import router as auth_router
from src.bolsillo.router import admin as bolsillo_admin_router
from src.bolsillo.router import economia as bolsillo_economia_router
from src.challenge_engine.router import router as challenges_router
from src.curriculo.router import router as curriculo_router
from src.datos.router import admin as datos_admin_router
from src.datos.router import usuario as datos_usuario_router
from src.engrama_core.router import router as core_router
from src.foco.router import router as foco_router
from src.grader.router import router as grader_router
from src.invitar.router import router as invitar_router
from src.refuerzo.router import router as refuerzo_router
from src.registro.router import docente as registro_docente_router
from src.registro.router import publico as registro_publico_router
from src.shared import validacion
from src.shop.router import economia as tienda_economia_router
from src.shop.router import subasta as subasta_router
from src.teachers.admin_router import router as admin_router
from src.teachers.router import router as teachers_router
from src.webhooks.router import router as events_router

app = FastAPI(
    title="Engrama 2.0 API",
    version="0.1.0",
)

# Ningún 422 de validación devuelve lo que el cliente envió (ni `input`, ni el
# detalle del analizador): un solo manejador para todas las rutas, las de hoy y
# las que vengan (docs/ESPEC_422_sin_eco.md).
validacion.instalar(app)

# Módulos de dominio — orden alfabético para evitar drift.
app.include_router(admin_router, prefix="/admin", tags=["admin"])
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(challenges_router, prefix="/challenges", tags=["challenges"])
app.include_router(core_router, prefix="/core", tags=["engrama-core"])
app.include_router(teachers_router, prefix="/teachers", tags=["teachers"])
# Autorregistro con código de grupo (docs/ESPEC_autorregistro.md): una ruta
# pública en /auth y las del profe en /teachers.
app.include_router(registro_publico_router, prefix="/auth", tags=["registro"])
app.include_router(registro_docente_router, prefix="/teachers", tags=["registro"])
# Solicitudes sobre datos personales, Ley 1581 (docs/ESPEC_solicitud_datos.md).
app.include_router(datos_usuario_router, prefix="/auth", tags=["datos"])
app.include_router(datos_admin_router, prefix="/admin", tags=["datos"])
# La puerta de entrada del anillo: EVA y SET entregan eventos firmados
# (docs/ESPEC_eventos_anillo.md). Sin JWT: la autentica la firma HMAC.
app.include_router(events_router, prefix="/events", tags=["eventos"])
# El catálogo de nodos del mapa curricular, para el selector del profe
# (docs/ESPEC_catalogo_nodos.md).
app.include_router(curriculo_router, prefix="/teachers", tags=["curriculo"])
# La puerta del Grader: lista numerada, examen impreso y hojas calificadas, con el
# Bearer del profe (docs/ESPEC_grader_anillo.md).
app.include_router(grader_router, prefix="/grader", tags=["grader"])
# El foco del grupo y las etiquetas de nodo de los retos (docs/ESPEC_foco_grupo.md).
app.include_router(foco_router, prefix="/teachers", tags=["foco"])
# La cola de refuerzo: lo que ve el profe (docs/ESPEC_refuerzo.md). Las rutas
# del estudiante viven en el router de retos.
app.include_router(refuerzo_router, prefix="/teachers", tags=["refuerzo"])
# La economía de la ola 1 (docs/ESPEC_ola1_economia.md, contrato de la ADENDA 1):
# el bolsillo del profe (Dar, Corregir y el presupuesto que recarga el admin), la
# tienda con mochila y entregas, y la subasta en vivo con retención.
app.include_router(bolsillo_economia_router, prefix="/economia", tags=["economia"])
app.include_router(tienda_economia_router, prefix="/economia", tags=["economia"])
app.include_router(bolsillo_admin_router, prefix="/admin", tags=["economia"])
app.include_router(subasta_router, prefix="/subastas", tags=["subastas"])
# El admin invita profes por correo: la cuenta la crea el backend sin contraseña
# y el profe pone la suya con el enlace (docs/ESPEC_invitar_profe.md).
app.include_router(invitar_router, prefix="/admin", tags=["invitar"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "engrama-backend"}
