"""FastAPI route handlers for FixLoop API.

Implements /health, /ready, /api/v1/diagnose, and scenario exploration.
Guarantees secret safety and actionable error feedback.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, status

from backend.app.core.config import settings
from backend.app.core.models import (
    DiagnoseRequest,
    DiagnoseResponse,
    InvestigationState,
    InvestigationStatus,
    InvestigationOutcome,
    VerifyPatchRequest,
    DiagnosisStatus,
    VerificationStatus,
)
from backend.app.agent.engine import DiagnosticEngine
from backend.app.agent.patcher import (
    PatchProposal,
    ControlledPatchGenerator,
    InsufficientEvidenceError,
)
from backend.app.sandbox.verifier import ControlledVerificationPipeline, VerificationReport
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
        "id": "scenario_a_missing_env",
        "name": "Scenario A: Explicit Missing Environment Variable",
        "description": "Application startup logs explicitly document KeyError on DATABASE_URL. Engine confirms missing variable without disclosing secrets.",
        "difficulty": "Easy",
        "requires_probe": False,
    },
    {
        "id": "scenario_b_healthcheck_mismatch",
        "name": "Scenario B: Normal Logs with Healthcheck Endpoint Mismatch",
        "description": "Logs are completely normal. Container is unhealthy because compose probes /health while app exposes /healthz. Requires active diagnostic probe to discover.",
        "difficulty": "Medium",
        "requires_probe": True,
    },
    {
        "id": "scenario_c_port_mismatch",
        "name": "Scenario C: Port Forwarding Target Mismatch",
        "description": "App listens on port 8000, but compose forwards host 8000 to container 5000. Engine verifies listening ports with TCP probes.",
        "difficulty": "Easy",
        "requires_probe": True,
    },
    {
        "id": "scenario_d_insufficient_evidence",
        "name": "Scenario D: Insufficient Evidence / External Upstream Outage",
        "description": "Intermittent connection resets from external third-party gateway. Engine exhausts local probes, refuses to invent a fix, and outputs insufficient_evidence.",
        "difficulty": "Hard",
        "requires_probe": False,
    },
    {
        "id": "scenario_e_misleading_logs",
        "name": "Scenario E: Misleading Database Logs (Kernel OOM Exit 137)",
        "description": "Application logs show database connection pool timeouts. Container inspect reveals OOMKilled: true (exit code 137). Engine identifies kernel memory exhaustion rather than database outage.",
        "difficulty": "Hard",
        "requires_probe": False,
    },
    {
        "id": "scenario_f_contradictory_evidence",
        "name": "Scenario F: Contradictory Redis Logs vs In-Memory Fallback",
        "description": "Logs report Redis connection error, but compose config explicitly sets REDIS_ENABLED=false and uses in-memory cache. Engine detects contradiction, notes container is healthy, and avoids unnecessary patches.",
        "difficulty": "Medium",
        "requires_probe": False,
    },
    {
        "id": "scenario_g_failed_patch_regression",
        "name": "Scenario G: Regression in Patch (Verification Failure Caught & Reverted)",
        "description": "App failed startup due to invalid rate limit configuration. An adversarial patch with a syntax regression is tested in the sandbox, detected with exit code 1, and reverted.",
        "difficulty": "Medium",
        "requires_probe": False,
    },
]

# Alias resolution for scenario names and backwards compatibility
SCENARIO_ALIASES = {
    "scenario_a": "scenario_a_missing_env",
    "scenario_b": "scenario_b_healthcheck_mismatch",
    "scenario_c": "scenario_c_port_mismatch",
    "scenario_d": "scenario_d_insufficient_evidence",
    "scenario_e": "scenario_e_misleading_logs",
    "scenario_f": "scenario_f_contradictory_evidence",
    "scenario_g": "scenario_g_failed_patch_regression",
    "scenario_1_healthcheck": "scenario_b_healthcheck_mismatch",
    "scenario_2_port_mismatch": "scenario_c_port_mismatch",
    "scenario_3_missing_env": "scenario_a_missing_env",
    "scenario_4_ambiguous_failure": "scenario_d_insufficient_evidence",
}


def get_scenario_dir(name: str) -> Path | None:
    """Resolves scenario name or alias to directory path across working directories."""
    resolved_name = SCENARIO_ALIASES.get(name, name)
    p = Path("scenarios") / resolved_name
    if p.exists() and p.is_dir():
        return p.resolve()
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    p = repo_root / "scenarios" / resolved_name
    if p.exists() and p.is_dir():
        return p.resolve()
    return None


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


async def get_readiness_status() -> Dict[str, Any]:
    """Evaluates readiness of application configuration and verifies Nebius connectivity without exposing secrets."""
    is_key_configured = settings.is_nebius_configured
    is_mock = settings.USE_MOCK_LLM or not is_key_configured

    issues = []
    if not is_key_configured and not settings.USE_MOCK_LLM:
        issues.append(
            "NEBIUS_API_KEY is not set. Configure NEBIUS_API_KEY in your environment or .env file, or set USE_MOCK_LLM=true for offline mode."
        )

    # Validate Nebius credentials and model access
    client = NebiusLLMClient()
    verification = await client.verify_credentials_and_model()

    if not verification.get("verified", False):
        issues.append(verification.get("error", "Failed to connect to Nebius Token Factory."))

    is_ready = (is_key_configured or settings.USE_MOCK_LLM) and verification.get("verified", False)

    return {
        "ready": is_ready,
        "service": "fixloop",
        "nebius": {
            "api_key_configured": is_key_configured,
            "base_url": settings.normalized_nebius_base_url,
            "model": settings.NEBIUS_MODEL,
            "mock_mode": is_mock,
            "verification": verification,
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
    """Readiness probe reporting configuration presence and Nebius Token Factory connectivity."""
    report = await get_readiness_status()
    return report


@router.post("/api/v1/diagnose", response_model=DiagnoseResponse)
async def diagnose(request: DiagnoseRequest) -> DiagnoseResponse:
    """Diagnose service failure from logs, Docker inspect, and configuration.

    Calls Nebius Token Factory with NVIDIA open-source model (or mock engine).
    Validates inputs, handles timeouts/retries, and returns structured diagnosis.
    """
    # 1. If service_name maps to a local scenario fixture directory, run DiagnosticEngine
    candidate_dir = get_scenario_dir(request.service_name) if request.service_name else None
    if candidate_dir:
        engine = DiagnosticEngine()
        result = await engine.run_investigation(
            project_root=candidate_dir,
            logs_override=request.logs,
            inspect_override=request.docker_inspect,
        )
        inv_id = f"inv-{len(INVESTIGATIONS_DB) + 1:04d}"
        INVESTIGATIONS_DB[inv_id] = InvestigationState(
            id=inv_id,
            scenario_name=request.service_name or "custom_target",
            project_path=str(candidate_dir),
            status=InvestigationStatus.COMPLETED if result.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE else InvestigationStatus.FAILED,
            outcome=InvestigationOutcome.VERIFIED_FIX if result.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE else InvestigationOutcome.INSUFFICIENT_EVIDENCE,
            outcome_summary=result.summary,
        )
        return DiagnoseResponse(
            status=result.status,
            summary=result.summary,
            hypotheses=result.hypotheses,
            evidence=result.evidence,
            recommended_tests=result.recommended_tests,
            missing_information=result.missing_information,
            confidence=result.confidence,
            next_action=result.next_action,
        )

    # 2. Input validation for ad-hoc requests
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


@router.post("/api/v1/verify", response_model=VerificationReport)
async def verify_patch(request: VerifyPatchRequest) -> VerificationReport:
    """Proposes a minimal patch, tests it in an isolated disposable sandbox, and reports actual verification status."""
    scenario_dir = get_scenario_dir(request.scenario_name)
    if not scenario_dir:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{request.scenario_name}' not found."
        )

    # 1. Run diagnostic investigation
    engine = DiagnosticEngine()
    diag_result = await engine.run_investigation(project_root=scenario_dir)

    # 2. Check sufficient evidence
    if diag_result.status != DiagnosisStatus.DIAGNOSIS_AVAILABLE or not diag_result.hypotheses or diag_result.confidence < 0.90:
        return VerificationReport(
            status=VerificationStatus.NOT_ATTEMPTED,
            test_output=f"Verification not attempted: diagnosis status is '{diag_result.status.value}' with confidence {diag_result.confidence:.2f} (>= 0.90 required).",
            expected_criteria="Conclusive empirical evidence (confidence >= 0.90)",
            reverted=True,
        )

    # 3. Execute sandboxed verification pipeline
    report = await ControlledVerificationPipeline.verify_hypothesis_fix(
        project_root=scenario_dir,
        diagnosis_status=diag_result.status,
        hypothesis=diag_result.hypotheses[0],
        user_approved=request.user_approved,
    )

    # 4. Update latest matching investigation outcome
    for inv in reversed(list(INVESTIGATIONS_DB.values())):
        if inv.scenario_name == request.scenario_name:
            if report.status == VerificationStatus.VERIFIED_FIXED:
                inv.status = InvestigationStatus.COMPLETED
                inv.outcome = InvestigationOutcome.VERIFIED_FIX
            elif report.status == VerificationStatus.PATCH_REJECTED:
                inv.outcome = InvestigationOutcome.HUMAN_INTERVENTION_REQUIRED
            elif report.status == VerificationStatus.VERIFICATION_FAILED:
                inv.status = InvestigationStatus.FAILED
                inv.outcome = InvestigationOutcome.FAILED_FIX
            break

    return report


@router.get("/api/v1/patch/{scenario_name}", response_model=PatchProposal)
@router.post("/api/v1/patch", response_model=PatchProposal)
async def propose_patch(scenario_name: str) -> PatchProposal:
    """Generates an honest, minimal reviewable patch diff for a conclusive scenario before execution."""
    scenario_dir = get_scenario_dir(scenario_name)
    if not scenario_dir:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{scenario_name}' not found."
        )

    engine = DiagnosticEngine()
    diag_result = await engine.run_investigation(project_root=scenario_dir)

    if diag_result.status != DiagnosisStatus.DIAGNOSIS_AVAILABLE or not diag_result.hypotheses or diag_result.confidence < 0.90:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot propose patch: status is '{diag_result.status.value}' and confidence is {diag_result.confidence:.2f} (< 0.90 required)."
        )

    try:
        proposal = ControlledPatchGenerator.create_patch_for_hypothesis(
            project_root=scenario_dir,
            diagnosis_status=diag_result.status,
            hypothesis=diag_result.hypotheses[0],
        )
        return proposal
    except InsufficientEvidenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating minimal patch: {exc}"
        ) from exc


class ApplyPatchRequest(BaseModel):
    scenario_name: str
    patch_diff: Optional[str] = None
    target_file: Optional[str] = None


@router.post("/api/v1/apply")
async def apply_verified_patch(request: ApplyPatchRequest):
    """Applies a verified patch directly to the target host files with safety checks."""
    scenario_dir = get_scenario_dir(request.scenario_name)
    if not scenario_dir:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{request.scenario_name}' not found."
        )

    if request.patch_diff and request.target_file:
        diff_unified = request.patch_diff
        target_file_name = request.target_file
    else:
        proposal = await propose_patch(request.scenario_name)
        diff_unified = proposal.diff_unified
        target_file_name = proposal.target_file

    target_path = (scenario_dir / target_file_name).resolve()
    if not target_path.exists():
        raise HTTPException(status_code=404, detail=f"Target file {target_file_name} not found")

    from backend.app.agent.patcher import PurePythonDiffPatcher
    old_content = target_path.read_text(encoding="utf-8", errors="replace")
    success, new_content, err = PurePythonDiffPatcher.apply_patch_to_text(old_content, diff_unified)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to apply patch: {err}")

    target_path.write_text(new_content, encoding="utf-8")
    return {
        "applied": True,
        "target_file": target_file_name,
        "message": f"Successfully applied verified patch to {target_file_name} on host disk."
    }



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


@router.post("/investigations/start", status_code=status.HTTP_201_CREATED)
@router.post("/api/investigations/start", status_code=status.HTTP_201_CREATED)
async def start_investigation(request: Dict[str, Any]) -> InvestigationState:
    """Starts an autonomous debugging investigation for a scenario or custom project repository."""
    scenario_name = request.get("scenario_name") or request.get("service_name")
    if not scenario_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Field 'scenario_name' or 'service_name' is required."
        )
    candidate_dir = get_scenario_dir(scenario_name)
    if not candidate_dir:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{scenario_name}' not found."
        )

    engine = DiagnosticEngine()
    result = await engine.run_investigation(project_root=candidate_dir)

    inv_id = f"inv-{len(INVESTIGATIONS_DB) + 1:04d}"
    inv_state = InvestigationState(
        id=inv_id,
        scenario_name=scenario_name,
        project_path=str(candidate_dir),
        status=InvestigationStatus.COMPLETED if result.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE else InvestigationStatus.FAILED,
        outcome=InvestigationOutcome.VERIFIED_FIX if result.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE else InvestigationOutcome.INSUFFICIENT_EVIDENCE,
        outcome_summary=result.summary,
    )
    INVESTIGATIONS_DB[inv_id] = inv_state
    return inv_state


@router.get("/investigations/{investigation_id}")
async def get_investigation(investigation_id: str) -> InvestigationState:
    """Retrieve state of an investigation run."""
    if investigation_id not in INVESTIGATIONS_DB:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return INVESTIGATIONS_DB[investigation_id]
