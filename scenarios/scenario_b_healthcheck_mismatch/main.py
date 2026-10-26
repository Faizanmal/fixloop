from fastapi import FastAPI

app = FastAPI(title="Web API Service")

@app.get("/healthz")
def healthz_probe():
    """Real service healthcheck endpoint."""
    return {"status": "ok", "uptime_seconds": 120}

@app.get("/api/v1/ping")
def ping():
    return {"message": "pong"}
