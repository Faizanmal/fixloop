"""FixLoop FastAPI Application Entry Point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes import router as api_router
from backend.app.core.config import settings

app = FastAPI(
    title="FixLoop API",
    description="Evidence-driven autonomous debugging engine for Dockerized applications.",
    version="0.1.0",
)

# CORS configuration: dynamically handle Vercel origins, wildcards, and credentials safely
cors_kwargs: dict = {
    "allow_methods": ["*"],
    "allow_headers": ["*"],
}
if "*" in settings.cors_origins_list:
    cors_kwargs["allow_origins"] = ["*"]
    cors_kwargs["allow_credentials"] = False
else:
    cors_kwargs["allow_origins"] = settings.cors_origins_list
    cors_kwargs["allow_credentials"] = True
    if settings.CORS_ORIGIN_REGEX:
        cors_kwargs["allow_origin_regex"] = settings.CORS_ORIGIN_REGEX

app.add_middleware(CORSMiddleware, **cors_kwargs)

# Mount router for canonical routes (/health, /ready, /api/v1/diagnose, /scenarios, /investigations)
app.include_router(api_router)


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
