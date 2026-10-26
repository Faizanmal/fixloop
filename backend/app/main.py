"""FixLoop FastAPI Application Entry Point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.core.config import settings
from backend.app.api.routes import router as api_router

app = FastAPI(
    title="FixLoop API",
    description="Evidence-driven autonomous debugging engine for Dockerized applications.",
    version="0.1.0",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    return {
        "service": "FixLoop Engine",
        "version": "0.1.0",
        "docs": "/docs",
        "api_health": "/api/health",
        "status": "ready",
    }
