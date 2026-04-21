from fastapi import FastAPI

from src.auth.router import router as auth_router

app = FastAPI(
    title="Engrama 2.0 API",
    version="0.1.0",
)

# Módulos de dominio — orden alfabético para evitar drift.
app.include_router(auth_router, prefix="/auth", tags=["auth"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "engrama-backend"}
