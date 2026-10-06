from fastapi import FastAPI

from src.auth.router import router as auth_router
from src.challenge_engine.router import router as challenges_router
from src.engrama_core.router import router as core_router
from src.registro.router import docente as registro_docente_router
from src.registro.router import publico as registro_publico_router
from src.teachers.admin_router import router as admin_router
from src.teachers.router import router as teachers_router

app = FastAPI(
    title="Engrama 2.0 API",
    version="0.1.0",
)

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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "engrama-backend"}
