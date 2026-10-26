"""FastAPI route handlers for FixLoop API.

Implements /health, /ready, /api/v1/diagnose, and scenario exploration.
Guarantees secret safety and actionable error feedback.
"""

import shutil
import subprocess
from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException, status

from backend.app.core.config import settings
from backend.app.core.models import (
    DiagnoseRequest,
    DiagnoseResponse,
    InvestigationState,
)
from backend.app.llm.client import NebiusLLMClient
from backend.app.llm.exceptions import (
    NebiusError,
    NebiusAuthenticationError,
    NebiusModelNotFoundError,
    NebiusQuotaError,
    NebiusBillingError,
    NebiusTimeoutError,
    NebiusServiceError,
    NebiusConnectionError,
    ModelResponseValidationError,
)

router = APIRouter()

# In-memory store for investigation runs
INVESTIGATIONS_DB: Dict[str, InvestigationState] = {}

SCENARIOS = [
    {
        "id": "scenario_1_healthcheck",
        "name": "Scenario 1: Misconfigured Healthcheck Endpoint",
        "description": "Container runs normally at /healthz, but docker-compose checks /health, causing repeated unhealthy status.",
        "difficulty": "Easy",
        "requires_probe": True,
    },
    {
        "id": "scenario_2_port_mismatch",
        "name": "Scenario 2: Service Port Mapping Mismatch",
        "description": "Application listens on port 8000 internally, but compose publishes 8000:5000, causing connection refused on host.",
        "difficulty": "Easy",
        "requires_probe": True,
    },
    {
        "id": "scenario_3_missing_env",
        "name": "Scenario 3: Missing Environment Variable with Ambiguous Logs",
        "description": "App silently fails on boot without explicit missing variable name. Diagnostic probe inspects env schema to pinpoint DATABASE_URL.",
        "difficulty": "Medium",
        "requires_probe": True,
    },
    {
        "id": "scenario_4_ambiguous_failure",
        "name": "Scenario 4: Upstream Outage / Insufficient Evidence",
        "description": "Container fails due to an external network dependency. FixLoop detects insufficient evidence and honestly refuses to invent an unverified fix.",
        "difficulty": "Hard",
        "requires_probe": False,
    },
]


def check_docker_daemon() -> Dict[str, Any]:
    """Inspects Docker daemon availability safely."""
    docker_cli = shutil.which("docker")
    if not docker_cli:
        return {"available": False, "reason": "Docker CLI not found on PATH"}
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if proc.returncode == 0:
            return {"available": True, "server_version": proc.stdout.strip()}
        else:
            return {"available": False, "reason": proc.stderr.strip() or "Docker daemon not responding"}
    except subprocess.TimeoutExpired:
        return {"available": False, "reason": "Docker daemon connection timed out (service likely stopped)"}
    except Exception as exc:
        return {"available": False, "reason": str(exc)}


def get_readiness_status() -> Dict[str, Any]:
    """Evaluates readiness of application configuration without exposing secrets."""
    is_key_configured = settings.is_nebius_configured
    is_mock = settings.USE_MOCK_LLM or not is_key_configured

    issues = []
    if not is_key_configured and not settings.USE_MOCK_LLM:
        issues.append(
            "NEBIUS_API_KEY is not set. Configure NEBIUS_API_KEY in your environment or .env file, or set USE_MOCK_LLM=true for offline mode."
        )

    # The application is ready to process requests if either Nebius is configured or Mock mode is active
    is_ready = is_key_configured or settings.USE_MOCK_LLM

    return {
        "ready": is_ready,
        "service": "fixloop",
        "nebius": {
            "api_key_configured": is_key_configured,
            "base_url": settings.normalized_nebius_base_url,
            "model": settings.NEBIUS_MODEL,
            "mock_mode": is_mock,
        },
        "issues": issues,
    }


# =========================================================================
# Core Diagnostic Endpoints
# =========================================================================

@router.get("/health")
async def health():
    """Liveness health check endpoint."""
    docker_status = check_docker_daemon()
    return {
        "status": "healthy",
        "service": "fixloop",
        "version": "0.1.0",
        "docker": docker_status,
    }


@router.get("/ready")
async def ready():
    """Readiness probe reporting configuration presence without revealing secrets."""
    report = get_readiness_status()
    # If not ready and not in mock mode, return 200 with ready=false so caller can inspect issues
    return report


@router.post("/api/v1/diagnose", response_model=DiagnoseResponse)
async def diagnose(request: DiagnoseRequest) -> DiagnoseResponse:
    """Diagnose service failure from logs, Docker inspect, and configuration.

    Calls Nebius Token Factory with NVIDIA open-source model (or mock engine).
    Validates inputs, handles timeouts/retries, and returns structured diagnosis.
    """
    has_input = any([
        request.logs and request.logs.strip(),
        request.docker_inspect,
        request.configuration_files,
        request.environment_variables,
    ])
    if not has_input:
        raise HTTPException(
            status_code=422,
            detail="At least one diagnostic input (logs, docker_inspect, configuration_files, or environment_variables) must be provided."
        )

    client = NebiusLLMClient()
    try:
        diagnosis = await client.diagnose(request)
        return diagnosis
    except NebiusAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": exc.message, "actionable_advice": exc.actionable_advice}
        ) from exc
    except NebiusModelNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": exc.message, "actionable_advice": exc.actionable_advice}
        ) from exc
    except NebiusQuotaError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": exc.message, "actionable_advice": exc.actionable_advice}
        ) from exc
    except NebiusBillingError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"error": exc.message, "actionable_advice": exc.actionable_advice}
        ) from exc
    except NebiusTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={"error": exc.message, "actionable_advice": exc.actionable_advice}
        ) from exc
    except (ModelResponseValidationError, NebiusServiceError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": exc.message, "actionable_advice": exc.actionable_advice}
        ) from exc
    except NebiusConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": exc.message, "actionable_advice": exc.actionable_advice}
        ) from exc
    except NebiusError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.message, "actionable_advice": exc.actionable_advice}
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "An unexpected error occurred during diagnosis.", "actionable_advice": "Check server logs for details."}
        ) from exc


# =========================================================================
# Scenarios & Investigation Endpoints
# =========================================================================

@router.get("/scenarios")
async def list_scenarios():
    """List available reproducible test scenarios."""
    return SCENARIOS


@router.get("/investigations")
async def list_investigations() -> List[InvestigationState]:
    """List all recorded investigation runs."""
    return list(INVESTIGATIONS_DB.values())


@router.get("/investigations/{investigation_id}")
async def get_investigation(investigation_id: str) -> InvestigationState:
    """Retrieve state of an investigation run."""
    if investigation_id not in INVESTIGATIONS_DB:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return INVESTIGATIONS_DB[investigation_id]
