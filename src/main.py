from fastapi import FastAPI

from src.auth.router import router as auth_router
from src.challenge_engine.router import router as challenges_router
from src.engrama_core.router import router as core_router
from src.leaderboard.router import router as leaderboard_router

app = FastAPI(
    title="Engrama 2.0 API",
    version="0.1.0",
)

# Módulos de dominio — orden alfabético para evitar drift.
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(challenges_router, prefix="/challenges", tags=["challenges"])
app.include_router(core_router, prefix="/core", tags=["engrama-core"])
app.include_router(leaderboard_router, prefix="/leaderboard", tags=["leaderboard"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "engrama-backend"}
