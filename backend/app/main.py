"""FixLoop FastAPI Application Entry Point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.core.config import settings
from backend.app.api.routes import router as api_router, health, ready

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

# Top-level health and readiness routes (per requirements)
app.add_api_route("/health", health, methods=["GET"], tags=["System Health"])
app.add_api_route("/ready", ready, methods=["GET"], tags=["System Readiness"])

# Mount router for /api/v1/diagnose, /scenarios, and aliases
app.include_router(api_router)
app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    return {
        "service": "FixLoop Engine",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
        "ready": "/ready",
        "diagnose": "/api/v1/diagnose",
    }
