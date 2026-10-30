"""Deterministic sample failure reports for test suites, benchmarks, and mock demonstrations."""

from typing import Any

# Scenario 1: Healthcheck misconfiguration (app listens on /healthz, probe checks /health)
SAMPLE_HEALTHCHECK_FAILURE: dict[str, Any] = {
    "service_name": "billing-service",
    "logs": """
2026-10-26T14:00:01Z [info] Starting Uvicorn server on http://0.0.0.0:8000
2026-10-26T14:00:02Z [info] Application startup complete. Loaded 14 route handlers.
2026-10-26T14:00:05Z [info] GET /healthz 200 OK (0.8ms)
2026-10-26T14:00:15Z [warning] 127.0.0.1:45322 - "GET /health HTTP/1.1" 404 Not Found
2026-10-26T14:00:30Z [warning] 127.0.0.1:45398 - "GET /health HTTP/1.1" 404 Not Found
2026-10-26T14:00:45Z [warning] 127.0.0.1:45464 - "GET /health HTTP/1.1" 404 Not Found
""".strip(),
    "docker_inspect": {
        "Id": "c1a2b3c4d5e6f7",
        "State": {
            "Status": "running",
            "Running": True,
            "Health": {
                "Status": "unhealthy",
                "FailingStreak": 5,
                "Log": [{"ExitCode": 1, "Output": "HTTP/1.1 404 Not Found"}],
            },
        },
        "Config": {
            "Healthcheck": {
                "Test": ["CMD", "curl", "-f", "http://localhost:8000/health"],
                "Interval": 15000000000,
                "Timeout": 3000000000,
                "Retries": 3,
            }
        },
    },
    "configuration_files": {
        "docker-compose.yml": """
version: '3.8'
services:
  billing-service:
    build: .
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 15s
      timeout: 3s
      retries: 3
""".strip(),
        "app/main.py": """
from fastapi import FastAPI
app = FastAPI()

@app.get("/healthz")
def healthz():
    return {"status": "healthy", "service": "billing"}
""".strip(),
    },
    "environment_variables": {"PORT": "8000", "ENVIRONMENT": "production"},
}

# Scenario 2: Missing required environment variable causing silent crash on boot
SAMPLE_MISSING_ENV_FAILURE: dict[str, Any] = {
    "service_name": "auth-service",
    "logs": """
2026-10-26T14:05:00Z [info] Initializing auth-service engine v2.4.0
2026-10-26T14:05:01Z [error] Critical initialization error: configuration variable missing
2026-10-26T14:05:01Z [error] Database connection pool failed to initialize. Exiting with code 1.
""".strip(),
    "docker_inspect": {
        "Id": "e9f8d7c6b5a4",
        "State": {
            "Status": "exited",
            "Running": False,
            "ExitCode": 1,
            "Error": "Initialization error",
        },
    },
    "configuration_files": {
        "docker-compose.yml": """
version: '3.8'
services:
  auth-service:
    build: .
    environment:
      - PORT=8080
      - LOG_LEVEL=debug
""".strip()
    },
    "environment_variables": {"PORT": "8080", "LOG_LEVEL": "debug"},
}

# Mock model response JSON matching DiagnoseResponse schema for the healthcheck failure
MOCK_NEBIUS_HEALTHCHECK_RESPONSE: dict[str, Any] = {
    "status": "diagnosis_available",
    "summary": "The container is failing Docker health checks because docker-compose probes '/health', but the application only serves '/healthz'.",
    "hypotheses": [
        {
            "description": "Healthcheck endpoint mismatch between docker-compose.yml (/health) and FastAPI route (/healthz)",
            "supporting_evidence": [
                "docker_inspect: State.Health.Status is 'unhealthy' with 'HTTP/1.1 404 Not Found'",
                "application_logs: 'GET /healthz 200 OK' vs 'GET /health HTTP/1.1 404 Not Found'",
                "configuration_files: app/main.py defines @app.get('/healthz')",
            ],
            "contradicting_evidence": [],
            "confidence": 0.98,
            "recommended_discriminating_test": "HTTP_GET /healthz on port 8000 to verify 200 OK response",
        },
        {
            "description": "Application failed to bind to localhost inside container",
            "supporting_evidence": [],
            "contradicting_evidence": [
                "application_logs show Uvicorn running on http://0.0.0.0:8000 and answering requests with 404"
            ],
            "confidence": 0.05,
            "recommended_discriminating_test": "TCP_CONNECT 127.0.0.1:8000",
        },
    ],
    "evidence": [
        {
            "id": "ev-1",
            "source": "application_logs",
            "content": "GET /health HTTP/1.1 404 Not Found recorded at recurring 15s intervals matching Docker healthcheck interval",
            "timestamp": "2026-10-26T14:00:15Z",
        },
        {
            "id": "ev-2",
            "source": "docker_inspect",
            "content": "State.Health.Log reports ExitCode 1 and Output: HTTP/1.1 404 Not Found",
            "timestamp": None,
        },
        {
            "id": "ev-3",
            "source": "configuration_files",
            "content": "docker-compose.yml configures healthcheck test: ['CMD', 'curl', '-f', 'http://localhost:8000/health'] while app/main.py implements /healthz",
            "timestamp": None,
        },
    ],
    "recommended_tests": [
        {
            "id": "test-1",
            "test_type": "HTTP_GET",
            "target": "http://localhost:8000/healthz",
            "description": "Send GET request to /healthz to verify endpoint returns 200 OK",
            "expected_signal": "HTTP 200 OK confirming /healthz is the true health endpoint",
        }
    ],
    "missing_information": [],
    "confidence": 0.98,
    "next_action": "Update healthcheck test endpoint in docker-compose.yml from /health to /healthz",
}
