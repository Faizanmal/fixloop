"""FastAPI route handlers for FixLoop API."""

import shutil
import subprocess
from typing import Dict, List
from fastapi import APIRouter, HTTPException, BackgroundTasks
from backend.app.core.config import settings
from backend.app.core.models import (
    InvestigationState,
    StartInvestigationRequest,
    HumanApprovalRequest,
    InvestigationStatus,
)

router = APIRouter()

# In-memory store for MVP investigation runs
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


def check_docker_daemon() -> Dict[str, any]:
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


@router.get("/health")
async def health_check():
    """System health check and diagnostic connectivity report."""
    docker_status = check_docker_daemon()
    return {
        "status": "online",
        "nebius": {
            "configured": settings.is_nebius_configured,
            "base_url": settings.NEBIUS_BASE_URL,
            "model": settings.NEBIUS_MODEL,
            "mock_mode": settings.USE_MOCK_LLM or not settings.is_nebius_configured,
        },
        "docker": docker_status,
        "active_investigations_count": len(INVESTIGATIONS_DB),
    }


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
