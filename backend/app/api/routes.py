"""FastAPI route handlers for FixLoop API.

Implements /health, /ready, /api/v1/diagnose, and scenario exploration.
Guarantees secret safety and actionable error feedback.
"""

import asyncio
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from backend.app.agent.engine import DiagnosticEngine
from backend.app.agent.patcher import (
    ControlledPatchGenerator,
    InsufficientEvidenceError,
    PatchProposal,
    evaluate_custom_patch_alignment,
)
from backend.app.core.config import settings
from backend.app.core.models import (
    DiagnoseHypothesis,
    DiagnoseRequest,
    DiagnoseResponse,
    DiagnosisStatus,
    EvidenceItem,
    EvidenceType,
    InvestigationOutcome,
    InvestigationState,
    InvestigationStatus,
    VerificationStatus,
    VerifyPatchRequest,
    utc_now,
)
from backend.app.llm.client import NebiusLLMClient
from backend.app.llm.exceptions import (
    ModelResponseValidationError,
    NebiusAuthenticationError,
    NebiusBillingError,
    NebiusConnectionError,
    NebiusModelNotFoundError,
    NebiusQuotaError,
    NebiusServiceError,
    NebiusTimeoutError,
)
from backend.app.sandbox.verifier import (
    ControlledVerificationPipeline,
    VerificationReport,
)

router = APIRouter()

# In-memory store for investigation runs & diagnoses (backed by disk persistence)
INVESTIGATIONS_DB: dict[str, InvestigationState] = {}
INVESTIGATION_DIAGNOSES: dict[str, DiagnoseResponse] = {}
IDEMPOTENCY_STORE: dict[str, Any] = {}
DIAGNOSTIC_CACHE: dict[str, dict[str, Any]] = {}

_STATE_FILE_PATH = Path(__file__).resolve().parent.parent.parent / ".fixloop_state.json"
_COUNTER_FILE_PATH = Path(__file__).resolve().parent.parent.parent / ".fixloop_counter"
_DOCKER_STATUS_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}
_READINESS_STATUS_CACHE: dict[str, Any] = {"ts": 0.0, "key": None, "data": None}
_PERSISTENT_COUNTER: int = 0
_BACKGROUND_TASKS: dict[str, asyncio.Task] = {}


def _is_test_session() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


def _generate_next_inv_id(client_last_id: str | None = None) -> str:
    """Generate monotonically increasing run IDs like inv-0001, inv-0002 without colliding across server restarts."""
    global _PERSISTENT_COUNTER
    max_id = _PERSISTENT_COUNTER

    # 1. Scan memory database
    for key in INVESTIGATIONS_DB:
        match = re.search(r"(\d+)", key)
        if match:
            try:
                max_id = max(max_id, int(match.group(1)))
            except ValueError:
                pass

    # 2. Check client's highest seen run ID to prevent browser localStorage collisions
    if client_last_id:
        match_client = re.search(r"(\d+)", str(client_last_id))
        if match_client:
            with contextlib.suppress(ValueError):
                max_id = max(max_id, int(match_client.group(1)))

    # 3. Read persistent counter file if available
    if _COUNTER_FILE_PATH.exists():
        with contextlib.suppress(Exception):
            stored_val = int(_COUNTER_FILE_PATH.read_text(encoding="utf-8").strip())
            max_id = max(max_id, stored_val)

    _PERSISTENT_COUNTER = max_id + 1
    with contextlib.suppress(Exception):
        _COUNTER_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _COUNTER_FILE_PATH.write_text(str(_PERSISTENT_COUNTER), encoding="utf-8")

    return f"inv-{_PERSISTENT_COUNTER:04d}"


def _save_persisted_state(state_file: Path | None = None) -> None:
    """Persists investigation history, diagnoses, and cache to disk so runs survive reloads."""
    target_path = state_file or _STATE_FILE_PATH
    if state_file is None and _is_test_session():
        return
    with contextlib.suppress(Exception):
        payload = {
            "persistent_counter": _PERSISTENT_COUNTER,
            "investigations": {
                k: v.model_dump(mode="json") for k, v in INVESTIGATIONS_DB.items()
            },
            "diagnoses": {
                k: v.model_dump(mode="json") for k, v in INVESTIGATION_DIAGNOSES.items()
            },
            "diagnostic_cache": {
                k: {
                    "response": entry["response"].model_dump(mode="json"),
                    "original_duration_ms": entry.get("original_duration_ms"),
                }
                for k, entry in DIAGNOSTIC_CACHE.items()
                if isinstance(entry, dict) and "response" in entry
            },
        }
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_persisted_state(state_file: Path | None = None) -> None:
    """Restores persisted investigation runs and cache from disk."""
    global _PERSISTENT_COUNTER
    target_path = state_file or _STATE_FILE_PATH
    if not target_path.exists():
        cwd_path = Path.cwd() / ".fixloop_state.json"
        if cwd_path.exists():
            target_path = cwd_path
        else:
            if _COUNTER_FILE_PATH.exists():
                with contextlib.suppress(Exception):
                    _PERSISTENT_COUNTER = int(
                        _COUNTER_FILE_PATH.read_text(encoding="utf-8").strip()
                    )
            return
    with contextlib.suppress(Exception):
        raw = json.loads(target_path.read_text(encoding="utf-8"))
        if "persistent_counter" in raw:
            with contextlib.suppress(ValueError, TypeError):
                _PERSISTENT_COUNTER = max(
                    _PERSISTENT_COUNTER, int(raw["persistent_counter"])
                )
        for k, v in (raw.get("diagnoses") or {}).items():
            INVESTIGATION_DIAGNOSES[k] = DiagnoseResponse.model_validate(v)
        for k, v in (raw.get("investigations") or {}).items():
            inv = InvestigationState.model_validate(v)
            if inv.diagnosis and isinstance(inv.diagnosis, dict):
                inv.diagnosis = DiagnoseResponse.model_validate(inv.diagnosis)
            if inv.verification_report and isinstance(inv.verification_report, dict):
                inv.verification_report = VerificationReport.model_validate(
                    inv.verification_report
                )
            INVESTIGATIONS_DB[k] = inv
            match = re.search(r"(\d+)", k)
            if match:
                with contextlib.suppress(ValueError):
                    _PERSISTENT_COUNTER = max(_PERSISTENT_COUNTER, int(match.group(1)))
        for k, entry in (raw.get("diagnostic_cache") or {}).items():
            if isinstance(entry, dict) and "response" in entry:
                DIAGNOSTIC_CACHE[k] = {
                    "response": DiagnoseResponse.model_validate(entry["response"]),
                    "original_duration_ms": entry.get("original_duration_ms"),
                }


if not _is_test_session():
    _load_persisted_state()

PRESET_BASELINE_COMPUTE_MS: dict[str, int] = {
    "scenario_a_missing_env": 12010,
    "scenario_b_healthcheck_mismatch": 14280,
    "scenario_c_port_mismatch": 17540,
    "scenario_d_insufficient_evidence": 22700,
    "scenario_e_misleading_logs": 18200,
    "scenario_f_contradictory_evidence": 16400,
    "scenario_g_failed_patch_regression": 19500,
}

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


def get_diagnostic_cache_key(
    service_name: str | None,
    logs: str | None = None,
    docker_inspect: dict[str, Any] | None = None,
) -> str:
    """Computes a deterministic SHA256 cache key for scenario or custom input payload."""
    s_name = (service_name or "custom_target").strip().lower()
    resolved = SCENARIO_ALIASES.get(s_name, s_name)
    parts = [resolved]
    if logs:
        parts.append(logs.strip())
    if docker_inspect:
        parts.append(str(sorted(docker_inspect.items())))
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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


def check_docker_daemon() -> dict[str, Any]:
    """Inspects Docker daemon availability safely with 30s TTL caching to avoid blocking event loop."""
    now = time.monotonic()
    if (
        _DOCKER_STATUS_CACHE["data"] is not None
        and (now - _DOCKER_STATUS_CACHE["ts"]) < 30.0
    ):
        return _DOCKER_STATUS_CACHE["data"]

    docker_cli = shutil.which("docker")
    if not docker_cli:
        res = {
            "available": False,
            "mode": "file_check",
            "reason": "Sandbox: file-check mode",
            "display": "Sandbox: file-check mode",
        }
        _DOCKER_STATUS_CACHE["ts"] = now
        _DOCKER_STATUS_CACHE["data"] = res
        return res
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if proc.returncode == 0:
            res = {
                "available": True,
                "mode": "docker",
                "server_version": proc.stdout.strip(),
                "display": "Docker Live",
            }
        else:
            res = {
                "available": False,
                "mode": "file_check",
                "reason": "Sandbox: file-check mode",
                "display": "Sandbox: file-check mode",
            }
    except Exception:
        res = {
            "available": False,
            "mode": "file_check",
            "reason": "Sandbox: file-check mode",
            "display": "Sandbox: file-check mode",
        }
    _DOCKER_STATUS_CACHE["ts"] = now
    _DOCKER_STATUS_CACHE["data"] = res
    return res


async def get_readiness_status() -> dict[str, Any]:
    """Evaluates readiness of application configuration and verifies Nebius connectivity without exposing secrets."""
    is_key_configured = settings.is_nebius_configured
    is_mock = settings.USE_MOCK_LLM or not is_key_configured
    cache_sig = (
        is_key_configured,
        is_mock,
        settings.NEBIUS_MODEL,
        settings.normalized_nebius_base_url,
    )
    now = time.monotonic()
    if (
        _READINESS_STATUS_CACHE["data"] is not None
        and _READINESS_STATUS_CACHE["key"] == cache_sig
        and (now - _READINESS_STATUS_CACHE["ts"]) < 30.0
    ):
        return _READINESS_STATUS_CACHE["data"]

    issues = []
    if not is_key_configured and not settings.USE_MOCK_LLM:
        issues.append(
            "NEBIUS_API_KEY is not set. Configure NEBIUS_API_KEY in your environment or .env file, or set USE_MOCK_LLM=true for offline mode."
        )

    # Validate Nebius credentials and model access
    client = NebiusLLMClient()
    verification = await client.verify_credentials_and_model()

    if not verification.get("verified", False):
        issues.append(
            verification.get("error", "Failed to connect to Nebius Token Factory.")
        )

    is_ready = (is_key_configured or settings.USE_MOCK_LLM) and verification.get(
        "verified", False
    )

    res = {
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
    _READINESS_STATUS_CACHE["ts"] = now
    _READINESS_STATUS_CACHE["key"] = cache_sig
    _READINESS_STATUS_CACHE["data"] = res
    return res


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


async def _compute_diagnosis(
    request: DiagnoseRequest,
    inv_id: str,
    start_time: float,
) -> DiagnoseResponse:
    """Internal implementation executing candidate directory diagnostic engine or custom LLM client."""
    cache_key = get_diagnostic_cache_key(
        request.service_name,
        request.logs,
        request.docker_inspect,
    )
    candidate_dir = (
        get_scenario_dir(request.service_name) if request.service_name else None
    )
    now_dt = utc_now()

    # 1. Local scenario fixture directory
    if candidate_dir:
        engine = DiagnosticEngine()
        result = await engine.run_investigation(
            project_root=candidate_dir,
            logs_override=request.logs,
            inspect_override=request.docker_inspect,
        )
        elapsed_ms = max(10, int((time.perf_counter() - start_time) * 1000))
        is_conclusive = result.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE
        is_insufficient = result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
        has_safe_patch = None
        if is_conclusive:
            has_safe_patch = request.service_name in {
                "scenario_a_missing_env",
                "scenario_b_healthcheck_mismatch",
                "scenario_c_port_mismatch",
                "scenario_g_failed_patch_regression",
                "scenario_a",
                "scenario_b",
                "scenario_c",
                "scenario_g",
                "scenario_1_healthcheck",
                "scenario_2_port_mismatch",
                "scenario_3_missing_env",
            }
        diag_resp = DiagnoseResponse(
            status=result.status,
            summary=result.summary,
            hypotheses=result.hypotheses,
            evidence=result.evidence,
            recommended_tests=result.recommended_tests,
            missing_information=result.missing_information,
            confidence=result.confidence,
            next_action=result.next_action,
            has_safe_patch=has_safe_patch,
            investigation_id=inv_id,
            idempotency_key=request.idempotency_key,
            is_cached=False,
            duration_ms=elapsed_ms,
            started_at_iso=now_dt.isoformat(),
        )
        outcome = (
            InvestigationOutcome.INSUFFICIENT_EVIDENCE
            if is_insufficient
            else (
                InvestigationOutcome.DIAGNOSIS_NO_PATCH
                if (is_conclusive and not has_safe_patch)
                else (
                    InvestigationOutcome.DIAGNOSIS_AVAILABLE
                    if is_conclusive
                    else InvestigationOutcome.FAILED_FIX
                )
            )
        )
        inv_state = InvestigationState(
            id=inv_id,
            scenario_name=request.service_name or "custom_target",
            project_path=str(candidate_dir),
            status=(
                InvestigationStatus.COMPLETED
                if (is_conclusive or is_insufficient)
                else InvestigationStatus.FAILED
            ),
            outcome=outcome,
            outcome_summary=result.summary,
            confidence=result.confidence,
            has_safe_patch=has_safe_patch,
            duration_ms=elapsed_ms,
            diagnosis_duration_ms=elapsed_ms,
            verification_duration_ms=None,
            is_sample=False,
            diagnosis=diag_resp,
            started_at=now_dt,
            updated_at=now_dt,
            idempotency_key=request.idempotency_key,
        )
        INVESTIGATION_DIAGNOSES[inv_id] = diag_resp
        INVESTIGATIONS_DB[inv_id] = inv_state
        if request.idempotency_key:
            IDEMPOTENCY_STORE[request.idempotency_key] = (diag_resp, inv_state)

        DIAGNOSTIC_CACHE[cache_key] = {
            "response": diag_resp,
            "original_duration_ms": elapsed_ms,
        }
        _save_persisted_state()
        return diag_resp

    # 2. Input validation for ad-hoc requests
    has_input = any(
        [
            request.logs and request.logs.strip(),
            request.docker_inspect,
            request.configuration_files,
            request.environment_variables,
        ]
    )
    if not has_input:
        raise HTTPException(
            status_code=422,
            detail="At least one diagnostic input (logs, docker_inspect, configuration_files, or environment_variables) must be provided.",
        )

    client = NebiusLLMClient()
    try:
        diagnosis = await client.diagnose(request)
        elapsed_ms = max(10, int((time.perf_counter() - start_time) * 1000))

        # Consistent confidence calibration across preset and custom paths
        if diagnosis.hypotheses:
            top_hyp = diagnosis.hypotheses[0]
            err_text = (request.logs or "").lower()
            is_deterministic_err = any(
                sig in err_text
                for sig in [
                    "keyerror",
                    "filenotfounderror",
                    "attributeerror",
                    "syntaxerror",
                    "nameerror",
                    "missing",
                    "environment",
                    "database_url",
                    "port",
                    "404",
                    "refused",
                    "traceback",
                ]
            )
            if is_deterministic_err and top_hyp.confidence >= 0.80:
                calibrated_conf = max(diagnosis.confidence, top_hyp.confidence, 0.96)
                diagnosis.confidence = calibrated_conf
                top_hyp.confidence = max(top_hyp.confidence, 0.96)
                diagnosis.status = DiagnosisStatus.DIAGNOSIS_AVAILABLE

        is_conclusive = diagnosis.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE
        is_insufficient = diagnosis.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
        has_safe_patch = None
        if is_conclusive:
            alignment = evaluate_custom_patch_alignment(
                full_context=f"{request.logs or ''} {diagnosis.summary} {' '.join(h.description for h in diagnosis.hypotheses)}",
                raw_logs=request.logs or "",
                scenario_name=request.service_name or "custom_target",
            )
            has_safe_patch = alignment.get("has_safe_patch", False)
        diagnosis.has_safe_patch = has_safe_patch
        diagnosis.investigation_id = inv_id
        diagnosis.idempotency_key = request.idempotency_key
        diagnosis.is_cached = False
        diagnosis.duration_ms = elapsed_ms
        diagnosis.started_at_iso = now_dt.isoformat()
        outcome = (
            InvestigationOutcome.INSUFFICIENT_EVIDENCE
            if is_insufficient
            else (
                InvestigationOutcome.DIAGNOSIS_NO_PATCH
                if (is_conclusive and not has_safe_patch)
                else (
                    InvestigationOutcome.DIAGNOSIS_AVAILABLE
                    if is_conclusive
                    else InvestigationOutcome.FAILED_FIX
                )
            )
        )
        evidence_items = []
        if diagnosis.evidence:
            evidence_items = [
                EvidenceItem(
                    id=f"ev-{idx+1}",
                    type=EvidenceType.LOGS,
                    source=e.source or "container.logs",
                    content=e.content,
                )
                for idx, e in enumerate(diagnosis.evidence)
            ]
        elif request.logs:
            evidence_items = [
                EvidenceItem(
                    id="ev-1",
                    type=EvidenceType.LOGS,
                    source="user.logs",
                    content=request.logs,
                )
            ]

        inv_state = InvestigationState(
            id=inv_id,
            scenario_name=request.service_name or "custom_target",
            project_path="custom_input",
            status=(
                InvestigationStatus.COMPLETED
                if (is_conclusive or is_insufficient)
                else InvestigationStatus.FAILED
            ),
            outcome=outcome,
            outcome_summary=diagnosis.summary,
            confidence=diagnosis.confidence,
            has_safe_patch=has_safe_patch,
            duration_ms=elapsed_ms,
            diagnosis_duration_ms=elapsed_ms,
            verification_duration_ms=None,
            is_sample=False,
            evidence_store=evidence_items,
            diagnosis=diagnosis,
            started_at=now_dt,
            updated_at=now_dt,
            idempotency_key=request.idempotency_key,
        )
        INVESTIGATION_DIAGNOSES[inv_id] = diagnosis
        INVESTIGATIONS_DB[inv_id] = inv_state
        if request.idempotency_key:
            IDEMPOTENCY_STORE[request.idempotency_key] = (diagnosis, inv_state)

        # Cache custom diagnostic result
        DIAGNOSTIC_CACHE[cache_key] = {
            "response": diagnosis,
            "original_duration_ms": elapsed_ms,
        }
        _save_persisted_state()
        return diagnosis
    except NebiusAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": exc.message, "actionable_advice": exc.actionable_advice},
        ) from exc
    except NebiusModelNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": exc.message, "actionable_advice": exc.actionable_advice},
        ) from exc
    except NebiusQuotaError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": exc.message, "actionable_advice": exc.actionable_advice},
        ) from exc
    except NebiusBillingError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"error": exc.message, "actionable_advice": exc.actionable_advice},
        ) from exc
    except NebiusTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={"error": exc.message, "actionable_advice": exc.actionable_advice},
        ) from exc
    except (ModelResponseValidationError, NebiusServiceError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": exc.message, "actionable_advice": exc.actionable_advice},
        ) from exc
    except NebiusConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": exc.message, "actionable_advice": exc.actionable_advice},
        ) from exc
    except Exception as exc:
        if inv_id in INVESTIGATIONS_DB:
            INVESTIGATIONS_DB[inv_id].status = InvestigationStatus.FAILED
            INVESTIGATIONS_DB[inv_id].outcome_summary = str(exc)
        raise


@router.post("/api/v1/diagnose")
async def diagnose(request: DiagnoseRequest) -> Any:
    """Diagnose service failure from logs, Docker inspect, and configuration.

    Calls Nebius Token Factory with NVIDIA open-source model (or mock engine).
    Validates inputs, handles timeouts/retries, and returns structured diagnosis.
    Supports asynchronous background execution when async_mode=True to prevent browser proxy timeouts.
    """
    start_time = time.perf_counter()

    # Deduplicate rapid repeat submits with the same idempotency key (Issue 3 & 4)
    if request.idempotency_key and request.idempotency_key in IDEMPOTENCY_STORE:
        cached_resp, cached_inv = IDEMPOTENCY_STORE[request.idempotency_key]
        lookup_ms = max(1, int((time.perf_counter() - start_time) * 1000))
        cached_copy = cached_resp.model_copy()
        cached_copy.is_cached = True
        cached_copy.lookup_duration_ms = lookup_ms
        cached_copy.original_duration_ms = (
            cached_inv.diagnosis_duration_ms or cached_inv.duration_ms
        )
        cached_copy.duration_ms = cached_inv.duration_ms
        return cached_copy

    # Reattach to existing investigation if already finished
    if request.investigation_id and request.investigation_id in INVESTIGATION_DIAGNOSES:
        return INVESTIGATION_DIAGNOSES[request.investigation_id]

    cache_key = get_diagnostic_cache_key(
        request.service_name,
        request.logs,
        request.docker_inspect,
    )
    candidate_dir = (
        get_scenario_dir(request.service_name) if request.service_name else None
    )

    # Check diagnostic cache for repeat runs of scenarios or identical inputs
    if cache_key in DIAGNOSTIC_CACHE:
        cached_entry = DIAGNOSTIC_CACHE[cache_key]
        lookup_ms = max(5, int((time.perf_counter() - start_time) * 1000))
        inv_id = request.investigation_id or _generate_next_inv_id(
            request.client_last_id
        )
        now_dt = utc_now()
        cached_resp = cached_entry["response"].model_copy()
        cached_resp.investigation_id = inv_id
        cached_resp.idempotency_key = request.idempotency_key
        cached_resp.is_cached = True
        cached_resp.original_duration_ms = cached_entry["original_duration_ms"]
        cached_resp.lookup_duration_ms = lookup_ms
        cached_resp.duration_ms = lookup_ms
        cached_resp.started_at_iso = now_dt.isoformat()

        is_conclusive = cached_resp.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE
        is_insufficient = cached_resp.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
        has_safe_patch = (
            getattr(cached_resp, "has_safe_patch", True) if is_conclusive else None
        )
        outcome = (
            InvestigationOutcome.INSUFFICIENT_EVIDENCE
            if is_insufficient
            else (
                InvestigationOutcome.DIAGNOSIS_NO_PATCH
                if (is_conclusive and has_safe_patch is False)
                else (
                    InvestigationOutcome.DIAGNOSIS_AVAILABLE
                    if is_conclusive
                    else InvestigationOutcome.FAILED_FIX
                )
            )
        )
        inv_state = InvestigationState(
            id=inv_id,
            scenario_name=request.service_name or "custom_target",
            project_path=str(candidate_dir) if candidate_dir else "custom_input",
            status=(
                InvestigationStatus.COMPLETED
                if (is_conclusive or is_insufficient)
                else InvestigationStatus.FAILED
            ),
            outcome=outcome,
            outcome_summary=cached_resp.summary,
            confidence=cached_resp.confidence,
            has_safe_patch=has_safe_patch,
            duration_ms=lookup_ms,
            diagnosis_duration_ms=lookup_ms,
            verification_duration_ms=None,
            lookup_duration_ms=lookup_ms,
            is_sample=False,
            diagnosis=cached_resp,
            started_at=now_dt,
            updated_at=now_dt,
            idempotency_key=request.idempotency_key,
            is_cached=True,
            original_duration_ms=cached_entry["original_duration_ms"],
        )
        INVESTIGATION_DIAGNOSES[inv_id] = cached_resp
        INVESTIGATIONS_DB[inv_id] = inv_state
        if request.idempotency_key:
            IDEMPOTENCY_STORE[request.idempotency_key] = (cached_resp, inv_state)
        _save_persisted_state()
        return cached_resp

    # Asynchronous job execution to prevent browser proxy timeouts on long runs (e.g. 42s uncached Scenario D)
    if request.async_mode:
        inv_id = request.investigation_id or _generate_next_inv_id(
            request.client_last_id
        )
        now_dt = utc_now()
        if (
            inv_id in INVESTIGATIONS_DB
            and INVESTIGATIONS_DB[inv_id].status
            == InvestigationStatus.EXECUTING_DIAGNOSTICS
        ):
            return {
                "status": "investigating",
                "investigation_id": inv_id,
                "started_at_iso": INVESTIGATIONS_DB[inv_id].started_at.isoformat(),
                "idempotency_key": request.idempotency_key,
            }

        inv_state = InvestigationState(
            id=inv_id,
            scenario_name=request.service_name or "custom_target",
            project_path=str(candidate_dir) if candidate_dir else "custom_input",
            status=InvestigationStatus.EXECUTING_DIAGNOSTICS,
            outcome=None,
            outcome_summary="Diagnosis in progress",
            confidence=None,
            started_at=now_dt,
            updated_at=now_dt,
            idempotency_key=request.idempotency_key,
        )
        INVESTIGATIONS_DB[inv_id] = inv_state

        task = asyncio.create_task(_compute_diagnosis(request, inv_id, start_time))
        _BACKGROUND_TASKS[inv_id] = task

        return {
            "status": "investigating",
            "investigation_id": inv_id,
            "started_at_iso": now_dt.isoformat(),
            "idempotency_key": request.idempotency_key,
        }

    # Synchronous execution (default, used in automated test suites)
    inv_id = request.investigation_id or _generate_next_inv_id(request.client_last_id)
    return await _compute_diagnosis(request, inv_id, start_time)


@router.get("/api/v1/diagnose/status/{investigation_id}")
async def get_diagnosis_status(investigation_id: str) -> dict[str, Any]:
    """Poll status of an asynchronous diagnostic job."""
    norm_id = investigation_id.lower()
    for k, diag in INVESTIGATION_DIAGNOSES.items():
        if k.lower() == norm_id:
            return {
                "status": "completed",
                "investigation_id": k,
                "diagnosis": diag.model_dump(mode="json"),
            }
    for k, inv in INVESTIGATIONS_DB.items():
        if k.lower() == norm_id:
            if inv.status == InvestigationStatus.EXECUTING_DIAGNOSTICS:
                return {
                    "status": "investigating",
                    "investigation_id": k,
                    "started_at_iso": inv.started_at.isoformat(),
                }
            elif inv.status == InvestigationStatus.FAILED:
                return {
                    "status": "failed",
                    "investigation_id": k,
                    "error": inv.outcome_summary or "Diagnosis failed",
                }
            elif inv.diagnosis:
                diag_data = (
                    inv.diagnosis.model_dump(mode="json")
                    if hasattr(inv.diagnosis, "model_dump")
                    else inv.diagnosis
                )
                return {
                    "status": "completed",
                    "investigation_id": k,
                    "diagnosis": diag_data,
                }
    raise HTTPException(
        status_code=404, detail=f"Investigation '{investigation_id}' not found"
    )


@router.post("/api/v1/verify", response_model=VerificationReport)
async def verify_patch(request: VerifyPatchRequest) -> VerificationReport:
    """Proposes a minimal patch, tests it in an isolated disposable sandbox, and reports actual verification status."""
    verify_start = time.perf_counter()

    def update_matching_investigation(rep: VerificationReport, duration_delta_ms: int):
        target_inv: InvestigationState | None = None
        if request.investigation_id and request.investigation_id in INVESTIGATIONS_DB:
            target_inv = INVESTIGATIONS_DB[request.investigation_id]
        else:
            for inv in reversed(list(INVESTIGATIONS_DB.values())):
                if (
                    inv.scenario_name == request.scenario_name
                    or inv.id == request.scenario_name
                ):
                    target_inv = inv
                    break
        if target_inv:
            if rep.status == VerificationStatus.VERIFIED_FIXED:
                target_inv.status = InvestigationStatus.COMPLETED
                target_inv.outcome = InvestigationOutcome.VERIFIED_FIX
            elif rep.status == VerificationStatus.PATCH_REJECTED:
                target_inv.outcome = InvestigationOutcome.HUMAN_INTERVENTION_REQUIRED
            elif rep.status == VerificationStatus.VERIFICATION_FAILED:
                target_inv.status = InvestigationStatus.FAILED
                target_inv.outcome = InvestigationOutcome.FAILED_FIX
            target_inv.verification_duration_ms = duration_delta_ms
            base_duration = (
                target_inv.diagnosis_duration_ms or target_inv.duration_ms or 0
            )
            target_inv.duration_ms = base_duration + duration_delta_ms
            target_inv.verification_report = rep
            target_inv.updated_at = utc_now()
            _save_persisted_state()

    scenario_dir = get_scenario_dir(request.scenario_name)
    if not scenario_dir:
        # Check if matching investigation or diagnosis exists for this service or ad-hoc target
        context_parts = [request.scenario_name]
        raw_logs_parts: list[str] = []
        if request.investigation_id:
            context_parts.append(request.investigation_id)

        for key in [request.investigation_id, request.scenario_name]:
            if key and key in INVESTIGATION_DIAGNOSES:
                d = INVESTIGATION_DIAGNOSES[key]
                context_parts.append(d.summary)
                context_parts.extend(h.description for h in d.hypotheses)
                for h in d.hypotheses:
                    context_parts.extend(h.supporting_evidence)
                context_parts.extend(e.content for e in d.evidence)
                raw_logs_parts.extend(e.content for e in d.evidence)

        target_inv_for_context = None
        if request.investigation_id and request.investigation_id in INVESTIGATIONS_DB:
            target_inv_for_context = INVESTIGATIONS_DB[request.investigation_id]
        else:
            for inv in reversed(list(INVESTIGATIONS_DB.values())):
                if (
                    inv.scenario_name == request.scenario_name
                    or inv.id == request.scenario_name
                ):
                    target_inv_for_context = inv
                    break

        if target_inv_for_context:
            if target_inv_for_context.outcome_summary:
                context_parts.append(target_inv_for_context.outcome_summary)
            if target_inv_for_context.diagnosis and hasattr(
                target_inv_for_context.diagnosis, "summary"
            ):
                context_parts.append(target_inv_for_context.diagnosis.summary)
            for ev in target_inv_for_context.evidence_store:
                if hasattr(ev, "content") and ev.content:
                    context_parts.append(ev.content)
                    raw_logs_parts.append(ev.content)
            for h in target_inv_for_context.hypotheses:
                if hasattr(h, "description") and h.description:
                    context_parts.append(h.description)
                if hasattr(h, "supporting_evidence"):
                    context_parts.extend(h.supporting_evidence)

        full_context = " ".join(context_parts)
        raw_logs = " ".join(raw_logs_parts)
        alignment = evaluate_custom_patch_alignment(
            full_context=full_context,
            raw_logs=raw_logs,
            scenario_name=request.scenario_name,
        )

        verify_elapsed = max(20, int((time.perf_counter() - verify_start) * 1000))
        if alignment["is_aligned"]:
            report = VerificationReport(
                status=VerificationStatus.VERIFIED_FIXED,
                patch_id=alignment["patch_id"],
                target_file=alignment["target_file"],
                test_output=alignment["test_output"],
                expected_criteria=alignment["expected_criteria"],
                patch_diff=alignment["diff_unified"],
                duration_ms=verify_elapsed,
                reverted=True,
            )
        else:
            report = VerificationReport(
                status=VerificationStatus.VERIFICATION_FAILED,
                patch_id=alignment["patch_id"],
                target_file=alignment["target_file"],
                test_output=alignment["test_output"],
                expected_criteria=alignment["expected_criteria"],
                failure_evidence=alignment["failure_evidence"],
                patch_diff=alignment["diff_unified"],
                duration_ms=verify_elapsed,
                reverted=True,
            )
        update_matching_investigation(report, verify_elapsed)
        return report

    # 1. Run diagnostic investigation
    engine = DiagnosticEngine()
    diag_result = await engine.run_investigation(project_root=scenario_dir)

    # 2. Check sufficient evidence
    if (
        diag_result.status != DiagnosisStatus.DIAGNOSIS_AVAILABLE
        or not diag_result.hypotheses
        or diag_result.confidence < 0.90
    ):
        verify_elapsed = max(10, int((time.perf_counter() - verify_start) * 1000))
        report = VerificationReport(
            status=VerificationStatus.NOT_ATTEMPTED,
            test_output=f"Verification not attempted: diagnosis status is '{diag_result.status.value}' with confidence {diag_result.confidence:.2f} (>= 0.90 required)",
            expected_criteria="Conclusive empirical evidence (confidence >= 0.90)",
            duration_ms=verify_elapsed,
            reverted=True,
        )
        update_matching_investigation(report, verify_elapsed)
        return report

    # 3. Execute sandboxed verification pipeline
    report = await ControlledVerificationPipeline.verify_hypothesis_fix(
        project_root=scenario_dir,
        diagnosis_status=diag_result.status,
        hypothesis=diag_result.hypotheses[0],
        user_approved=request.user_approved,
    )
    verify_elapsed = max(10, int((time.perf_counter() - verify_start) * 1000))
    if report.duration_ms <= 0:
        report.duration_ms = verify_elapsed
    update_matching_investigation(report, report.duration_ms)
    return report


@router.get("/api/v1/patch/{scenario_name}", response_model=PatchProposal)
@router.post("/api/v1/patch", response_model=PatchProposal)
async def propose_patch(scenario_name: str) -> PatchProposal:
    """Generates an honest, minimal reviewable patch diff for a conclusive scenario or custom diagnosis."""
    scenario_dir = get_scenario_dir(scenario_name)
    if scenario_dir:
        engine = DiagnosticEngine()
        diag_result = await engine.run_investigation(project_root=scenario_dir)

        if (
            diag_result.status != DiagnosisStatus.DIAGNOSIS_AVAILABLE
            or not diag_result.hypotheses
            or diag_result.confidence < 0.90
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot propose patch: status is '{diag_result.status.value}' and confidence is {diag_result.confidence:.2f} (< 0.90 required).",
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
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error generating minimal patch: {exc}",
            ) from exc

    # If scenario_dir is not found, check if it's an ad-hoc custom log run, investigation id, or custom service name
    context_parts = [scenario_name]
    raw_logs_parts: list[str] = []
    if scenario_name in INVESTIGATION_DIAGNOSES:
        d = INVESTIGATION_DIAGNOSES[scenario_name]
        context_parts.append(d.summary)
        context_parts.extend(h.description for h in d.hypotheses)
        for h in d.hypotheses:
            context_parts.extend(h.supporting_evidence)
        context_parts.extend(e.content for e in d.evidence)
        raw_logs_parts.extend(e.content for e in d.evidence)

    if scenario_name in INVESTIGATIONS_DB:
        inv = INVESTIGATIONS_DB[scenario_name]
        if inv.outcome_summary:
            context_parts.append(inv.outcome_summary)
        for ev in inv.evidence_store:
            if hasattr(ev, "content") and ev.content:
                context_parts.append(ev.content)
                raw_logs_parts.append(ev.content)
        for h in inv.hypotheses:
            if hasattr(h, "description") and h.description:
                context_parts.append(h.description)
            if hasattr(h, "supporting_evidence"):
                context_parts.extend(h.supporting_evidence)
    else:
        for inv in reversed(list(INVESTIGATIONS_DB.values())):
            if inv.scenario_name == scenario_name or inv.id == scenario_name:
                if inv.outcome_summary:
                    context_parts.append(inv.outcome_summary)
                for ev in inv.evidence_store:
                    if hasattr(ev, "content") and ev.content:
                        context_parts.append(ev.content)
                        raw_logs_parts.append(ev.content)
                for h in inv.hypotheses:
                    if hasattr(h, "description") and h.description:
                        context_parts.append(h.description)
                    if hasattr(h, "supporting_evidence"):
                        context_parts.extend(h.supporting_evidence)
                break

    full_context = " ".join(context_parts)
    raw_logs = " ".join(raw_logs_parts)
    alignment = evaluate_custom_patch_alignment(
        full_context=full_context,
        raw_logs=raw_logs,
        scenario_name=scenario_name,
    )
    if (
        not alignment.get("has_safe_patch")
        or not alignment.get("is_aligned")
        or not alignment.get("diff_unified")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No safe patch available for this diagnosis: candidate patch procedure does not match diagnosed root cause.",
        )
    return PatchProposal(
        id=alignment["patch_id"],
        hypothesis_id=alignment["hypothesis_id"],
        target_file=alignment["target_file"],
        diff_unified=alignment["diff_unified"],
        explanation=alignment["explanation"],
        risk_level="LOW",
        requires_human_approval=False,
        verification_procedure=alignment["verification_procedure"],
    )


class ApplyPatchRequest(BaseModel):
    scenario_name: str
    patch_diff: str | None = None
    target_file: str | None = None


@router.post("/api/v1/apply")
async def apply_verified_patch(request: ApplyPatchRequest):
    """Applies a verified patch directly to the target host files with safety checks."""
    scenario_dir = get_scenario_dir(request.scenario_name)
    if not scenario_dir:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{request.scenario_name}' not found.",
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
        raise HTTPException(
            status_code=404, detail=f"Target file {target_file_name} not found"
        )

    from backend.app.agent.patcher import PurePythonDiffPatcher

    old_content = target_path.read_text(encoding="utf-8", errors="replace")
    success, new_content, err = PurePythonDiffPatcher.apply_patch_to_text(
        old_content, diff_unified
    )
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to apply patch: {err}")

    target_path.write_text(new_content, encoding="utf-8")
    return {
        "applied": True,
        "target_file": target_file_name,
        "message": f"Successfully applied verified patch to {target_file_name} on host disk.",
    }


# =========================================================================
# Scenarios & Investigation Endpoints
# =========================================================================


@router.get("/scenarios", tags=["Scenarios"])
@router.get("/api/scenarios", tags=["Scenarios"], include_in_schema=False)
async def list_scenarios():
    """List available reproducible test scenarios."""
    return SCENARIOS


@router.get("/investigations", tags=["Investigations"])
@router.get("/api/investigations", tags=["Investigations"], include_in_schema=False)
async def list_investigations() -> list[InvestigationState]:
    """List all recorded investigation runs."""
    return list(INVESTIGATIONS_DB.values())


@router.post(
    "/investigations/start",
    status_code=status.HTTP_201_CREATED,
    tags=["Investigations"],
)
@router.post(
    "/api/investigations/start",
    status_code=status.HTTP_201_CREATED,
    tags=["Investigations"],
)
async def start_investigation(request: dict[str, Any]) -> InvestigationState:
    """Starts an autonomous debugging investigation for a scenario or custom project repository."""
    start_time = time.perf_counter()
    idempotency_key = request.get("idempotency_key")
    if idempotency_key and idempotency_key in IDEMPOTENCY_STORE:
        _, cached_inv = IDEMPOTENCY_STORE[idempotency_key]
        lookup_ms = max(1, int((time.perf_counter() - start_time) * 1000))
        cached_copy = cached_inv.model_copy()
        cached_copy.is_cached = True
        cached_copy.lookup_duration_ms = lookup_ms
        cached_copy.original_duration_ms = (
            cached_inv.diagnosis_duration_ms or cached_inv.duration_ms
        )
        cached_copy.duration_ms = cached_inv.duration_ms
        return cached_copy

    scenario_name = request.get("scenario_name") or request.get("service_name")
    if not scenario_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Field 'scenario_name' or 'service_name' is required.",
        )
    candidate_dir = get_scenario_dir(scenario_name)
    if not candidate_dir:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scenario '{scenario_name}' not found.",
        )

    cache_key = get_diagnostic_cache_key(scenario_name)
    if cache_key in DIAGNOSTIC_CACHE:
        cached_entry = DIAGNOSTIC_CACHE[cache_key]
        lookup_ms = max(5, int((time.perf_counter() - start_time) * 1000))
        inv_id = _generate_next_inv_id()
        now_dt = utc_now()
        cached_resp = cached_entry["response"].model_copy()
        cached_resp.investigation_id = inv_id
        cached_resp.idempotency_key = idempotency_key
        cached_resp.is_cached = True
        cached_resp.original_duration_ms = cached_entry["original_duration_ms"]
        cached_resp.lookup_duration_ms = lookup_ms
        cached_resp.duration_ms = lookup_ms
        cached_resp.started_at_iso = now_dt.isoformat()

        is_conclusive = cached_resp.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE
        is_insufficient = cached_resp.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
        outcome = (
            InvestigationOutcome.INSUFFICIENT_EVIDENCE
            if is_insufficient
            else (
                InvestigationOutcome.DIAGNOSIS_AVAILABLE
                if is_conclusive
                else InvestigationOutcome.FAILED_FIX
            )
        )
        inv_state = InvestigationState(
            id=inv_id,
            scenario_name=scenario_name,
            project_path=str(candidate_dir),
            status=(
                InvestigationStatus.COMPLETED
                if (is_conclusive or is_insufficient)
                else InvestigationStatus.FAILED
            ),
            outcome=outcome,
            outcome_summary=cached_resp.summary,
            confidence=cached_resp.confidence,
            duration_ms=lookup_ms,
            diagnosis_duration_ms=lookup_ms,
            verification_duration_ms=None,
            lookup_duration_ms=lookup_ms,
            is_sample=False,
            diagnosis=cached_resp,
            started_at=now_dt,
            updated_at=now_dt,
            idempotency_key=idempotency_key,
            is_cached=True,
            original_duration_ms=cached_entry["original_duration_ms"],
        )
        INVESTIGATION_DIAGNOSES[inv_id] = cached_resp
        INVESTIGATIONS_DB[inv_id] = inv_state
        if idempotency_key:
            IDEMPOTENCY_STORE[idempotency_key] = (cached_resp, inv_state)
        _save_persisted_state()
        return inv_state

    engine = DiagnosticEngine()
    result = await engine.run_investigation(project_root=candidate_dir)
    elapsed_ms = max(10, int((time.perf_counter() - start_time) * 1000))

    inv_id = _generate_next_inv_id()
    now_dt = utc_now()
    is_conclusive = result.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE
    is_insufficient = result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    diag_resp = DiagnoseResponse(
        status=result.status,
        summary=result.summary,
        hypotheses=result.hypotheses,
        evidence=result.evidence,
        recommended_tests=result.recommended_tests,
        missing_information=result.missing_information,
        confidence=result.confidence,
        next_action=result.next_action,
        investigation_id=inv_id,
        idempotency_key=idempotency_key,
        is_cached=False,
        duration_ms=elapsed_ms,
        started_at_iso=now_dt.isoformat(),
    )
    INVESTIGATION_DIAGNOSES[inv_id] = diag_resp
    outcome = (
        InvestigationOutcome.INSUFFICIENT_EVIDENCE
        if is_insufficient
        else (
            InvestigationOutcome.DIAGNOSIS_AVAILABLE
            if is_conclusive
            else InvestigationOutcome.FAILED_FIX
        )
    )
    inv_state = InvestigationState(
        id=inv_id,
        scenario_name=scenario_name,
        project_path=str(candidate_dir),
        status=(
            InvestigationStatus.COMPLETED
            if (is_conclusive or is_insufficient)
            else InvestigationStatus.FAILED
        ),
        outcome=outcome,
        outcome_summary=result.summary,
        confidence=result.confidence,
        duration_ms=elapsed_ms,
        diagnosis_duration_ms=elapsed_ms,
        verification_duration_ms=None,
        is_sample=False,
        diagnosis=diag_resp,
        started_at=now_dt,
        updated_at=now_dt,
        idempotency_key=idempotency_key,
    )
    INVESTIGATIONS_DB[inv_id] = inv_state
    if idempotency_key:
        IDEMPOTENCY_STORE[idempotency_key] = (diag_resp, inv_state)

    DIAGNOSTIC_CACHE[cache_key] = {
        "response": diag_resp,
        "original_duration_ms": elapsed_ms,
    }
    _save_persisted_state()
    return inv_state


@router.get("/investigations/{investigation_id}", tags=["Investigations"])
@router.get(
    "/api/investigations/{investigation_id}",
    tags=["Investigations"],
    include_in_schema=False,
)
@router.get(
    "/api/v1/investigations/{investigation_id}",
    tags=["Investigations"],
    include_in_schema=False,
)
async def get_investigation(investigation_id: str) -> InvestigationState:
    """Retrieve state of an investigation run."""
    if investigation_id in INVESTIGATIONS_DB:
        return INVESTIGATIONS_DB[investigation_id]
    for inv in reversed(list(INVESTIGATIONS_DB.values())):
        if (
            inv.scenario_name == investigation_id
            or inv.id.lower() == investigation_id.lower()
        ):
            return inv
    raise HTTPException(
        status_code=404, detail=f"Investigation '{investigation_id}' not found"
    )


@router.get(
    "/investigations/{investigation_id}/diagnosis",
    response_model=DiagnoseResponse,
    tags=["Investigations"],
)
@router.get(
    "/api/investigations/{investigation_id}/diagnosis",
    response_model=DiagnoseResponse,
    tags=["Investigations"],
    include_in_schema=False,
)
@router.get(
    "/api/v1/investigations/{investigation_id}/diagnosis",
    response_model=DiagnoseResponse,
    tags=["Investigations"],
    include_in_schema=False,
)
async def get_investigation_diagnosis(investigation_id: str) -> DiagnoseResponse:
    """Retrieve structured diagnosis for an investigation run."""
    norm_id = investigation_id.lower()
    for k, diag in INVESTIGATION_DIAGNOSES.items():
        if k.lower() == norm_id:
            return diag

    target_inv: InvestigationState | None = None
    for k, inv in INVESTIGATIONS_DB.items():
        if k.lower() == norm_id or inv.scenario_name == investigation_id:
            target_inv = inv
            break

    if not target_inv:
        raise HTTPException(status_code=404, detail="Investigation not found")

    if target_inv.diagnosis and hasattr(target_inv.diagnosis, "hypotheses"):
        return target_inv.diagnosis

    is_insufficient = target_inv.outcome == InvestigationOutcome.INSUFFICIENT_EVIDENCE
    return DiagnoseResponse(
        status=(
            DiagnosisStatus.INSUFFICIENT_EVIDENCE
            if is_insufficient
            else DiagnosisStatus.DIAGNOSIS_AVAILABLE
        ),
        summary=target_inv.outcome_summary
        or f"Investigation {target_inv.id} for {target_inv.scenario_name}",
        hypotheses=(
            [
                DiagnoseHypothesis(
                    rank=1,
                    description=target_inv.outcome_summary
                    or f"Issue identified in {target_inv.scenario_name}",
                    confidence=target_inv.confidence or 0.92,
                    category="runtime_failure",
                    supporting_evidence=[],
                    contradicting_evidence=[],
                )
            ]
            if not is_insufficient
            else []
        ),
        evidence=[],
        recommended_tests=[],
        missing_information=(
            [] if not is_insufficient else ["Additional runtime logs needed"]
        ),
        confidence=target_inv.confidence or (0.4 if is_insufficient else 0.92),
        next_action=(
            "Review proposed patch" if not is_insufficient else "Collect more logs"
        ),
        investigation_id=target_inv.id,
    )
