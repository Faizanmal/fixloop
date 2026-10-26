"""Core domain models and schema definitions for FixLoop.

All models adhere to strict Pydantic v2 validation.
Separates observations, hypotheses, diagnostic actions, patches, and verification results.
"""

from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EvidenceType(str, Enum):
    LOGS = "LOGS"
    DOCKER_INSPECT = "DOCKER_INSPECT"
    COMPOSE_CONFIG = "COMPOSE_CONFIG"
    DOCKERFILE = "DOCKERFILE"
    ENVIRONMENT = "ENVIRONMENT"
    DIAGNOSTIC_OUTPUT = "DIAGNOSTIC_OUTPUT"
    SOURCE_CODE = "SOURCE_CODE"


class EvidenceItem(BaseModel):
    """An immutable atomic piece of evidence gathered from the system."""
    id: str = Field(..., description="Unique ID for this evidence item, e.g. ev-1")
    type: EvidenceType
    source: str = Field(..., description="Origin of evidence: e.g. docker.logs, probe.http_get")
    timestamp: datetime = Field(default_factory=utc_now)
    content: str = Field(..., description="Raw text or structured JSON string of the evidence")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    is_initial: bool = Field(default=False, description="True if collected before hypothesis generation")


class HypothesisCategory(str, Enum):
    HEALTHCHECK_MISCONFIG = "HEALTHCHECK_MISCONFIG"
    PORT_MISMATCH = "PORT_MISMATCH"
    MISSING_ENV = "MISSING_ENV"
    CODE_DEFECT = "CODE_DEFECT"
    EXTERNAL_DEPENDENCY = "EXTERNAL_DEPENDENCY"
    RESOURCE_EXHAUSTION = "RESOURCE_EXHAUSTION"
    UNKNOWN = "UNKNOWN"


class Hypothesis(BaseModel):
    """A plausible root-cause explanation for the observed system failure."""
    id: str = Field(..., description="Hypothesis identifier, e.g. hyp-1")
    title: str = Field(..., max_length=150)
    description: str
    category: HypothesisCategory
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Confidence between 0.0 and 1.0")
    supporting_evidence_ids: List[str] = Field(default_factory=list)
    contradicting_evidence_ids: List[str] = Field(default_factory=list)
    suggested_probe_rationale: Optional[str] = None


class DiagnosticProbeType(str, Enum):
    """Strict allowlist of permitted safe diagnostic probe actions."""
    HTTP_GET = "HTTP_GET"
    TCP_CONNECT = "TCP_CONNECT"
    INSPECT_CONTAINER_CONFIG = "INSPECT_CONTAINER_CONFIG"
    READ_TARGET_FILE = "READ_TARGET_FILE"
    CHECK_ENV_KEY_EXISTS = "CHECK_ENV_KEY_EXISTS"
    INSPECT_PROCESS_LIST = "INSPECT_PROCESS_LIST"
    CHECK_CONTAINER_LOGS_TAIL = "CHECK_CONTAINER_LOGS_TAIL"


class DiagnosticActionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


class DiagnosticAction(BaseModel):
    """A targeted diagnostic test explicitly selected from the controlled allowlist."""
    id: str = Field(..., description="Action ID, e.g. act-1")
    probe_type: DiagnosticProbeType
    target: str = Field(..., description="Target identifier (container name, URL path, file path)")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(..., description="Why this probe distinguishes competing hypotheses")
    tested_hypothesis_id: Optional[str] = None
    requires_human_approval: bool = Field(default=False)
    status: DiagnosticActionStatus = Field(default=DiagnosticActionStatus.PENDING)
    output: Optional[str] = None
    executed_at: Optional[datetime] = None


class Patch(BaseModel):
    """A minimal unified diff proposed to resolve the identified root cause."""
    id: str = Field(..., description="Patch identifier, e.g. patch-1")
    hypothesis_id: str
    target_file: str = Field(..., description="Relative path of file to patch, e.g. docker-compose.yml")
    diff_unified: str = Field(..., description="Unified diff format patch")
    explanation: str
    is_minimal: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now)


class VerificationStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"


class VerificationResult(BaseModel):
    """Honest test execution results validating whether the proposed patch resolves the issue."""
    status: VerificationStatus
    exit_code: Optional[int] = None
    test_output: str
    duration_ms: int = 0
    verified_at: Optional[datetime] = None


class InvestigationOutcome(str, Enum):
    VERIFIED_FIX = "VERIFIED_FIX"
    FAILED_FIX = "FAILED_FIX"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    HUMAN_INTERVENTION_REQUIRED = "HUMAN_INTERVENTION_REQUIRED"


class InvestigationStatus(str, Enum):
    INITIALIZING = "INITIALIZING"
    COLLECTING_INITIAL_EVIDENCE = "COLLECTING_INITIAL_EVIDENCE"
    FORMULATING_HYPOTHESES = "FORMULATING_HYPOTHESES"
    EXECUTING_DIAGNOSTICS = "EXECUTING_DIAGNOSTICS"
    AWAITING_HUMAN_APPROVAL = "AWAITING_HUMAN_APPROVAL"
    GENERATING_PATCH = "GENERATING_PATCH"
    VERIFYING_PATCH = "VERIFYING_PATCH"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class InvestigationState(BaseModel):
    """State machine container capturing the entire lifecycle of an active investigation."""
    id: str
    scenario_name: str
    project_path: str
    status: InvestigationStatus = InvestigationStatus.INITIALIZING
    iteration: int = 0
    max_iterations: int = 5
    evidence_store: List[EvidenceItem] = Field(default_factory=list)
    hypotheses: List[Hypothesis] = Field(default_factory=list)
    diagnostic_history: List[DiagnosticAction] = Field(default_factory=list)
    candidate_patch: Optional[Patch] = None
    verification_result: Optional[VerificationResult] = None
    outcome: Optional[InvestigationOutcome] = None
    outcome_summary: Optional[str] = None
    started_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


# Request & Response Contracts for REST API

class StartInvestigationRequest(BaseModel):
    scenario_name: Optional[str] = Field(default=None, description="Preset scenario name, or custom repo path")
    custom_repo_path: Optional[str] = Field(default=None)
    max_iterations: int = Field(default=5, ge=1, le=10)


class HumanApprovalRequest(BaseModel):
    action_id: str
    approved: bool
    comments: Optional[str] = None


class LLMHypothesisResponse(BaseModel):
    """Structured format expected from Nebius / Nemotron model when reasoning over evidence."""
    reasoning: str
    hypotheses: List[Hypothesis]
    needs_diagnostic_probe: bool
    recommended_probe: Optional[DiagnosticAction] = None
    is_evidence_sufficient: bool = False
    refusal_reason: Optional[str] = None


class LLMPatchResponse(BaseModel):
    """Structured format expected from Nebius / Nemotron model when synthesizing a minimal patch."""
    target_file: str
    diff_unified: str
    explanation: str
    verification_command: str


# =========================================================================
# V1 Diagnostic Request & Response Schemas (Required by API v1 Diagnose)
# =========================================================================

class DiagnosisStatus(str, Enum):
    DIAGNOSIS_AVAILABLE = "diagnosis_available"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    HUMAN_INTERVENTION_REQUIRED = "human_intervention_required"


class DiagnoseHypothesis(BaseModel):
    """Individual root-cause hypothesis with evidence references and confidence."""
    description: str = Field(..., description="Description of the proposed root cause hypothesis")
    supporting_evidence: List[str] = Field(default_factory=list, description="References to supporting evidence")
    contradicting_evidence: List[str] = Field(default_factory=list, description="References to contradicting evidence")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence level between 0.0 and 1.0")
    recommended_discriminating_test: Optional[str] = Field(default=None, description="Recommended discriminating test")


class EvidenceRecord(BaseModel):
    """Record of observed system evidence."""
    id: str = Field(..., description="Unique ID for this evidence record, e.g. ev-1")
    source: str = Field(..., description="Source of evidence: logs, inspect, env, config, etc.")
    content: str = Field(..., description="Content or summary of observed evidence")
    timestamp: Optional[str] = Field(default=None, description="ISO timestamp if available")


class RecommendTest(BaseModel):
    """Controlled discriminating test recommended to isolate competing hypotheses."""
    id: str = Field(..., description="Identifier for recommended test probe, e.g. test-1")
    test_type: str = Field(..., description="Type of probe: HTTP_GET, TCP_CONNECT, CHECK_ENV, READ_FILE")
    target: str = Field(..., description="Target endpoint, port, variable, or file")
    description: str = Field(..., description="Explanation of what this test verifies")
    expected_signal: str = Field(..., description="Signal indicating positive or negative outcome")


class DiagnoseResponse(BaseModel):
    """Complete structured diagnosis response matching FixLoop API specification."""
    status: DiagnosisStatus
    summary: str
    hypotheses: List[DiagnoseHypothesis] = Field(default_factory=list)
    evidence: List[EvidenceRecord] = Field(default_factory=list)
    recommended_tests: List[RecommendTest] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0, description="Overall confidence level between 0.0 and 1.0")
    next_action: str


class DiagnoseRequest(BaseModel):
    """Incoming request payload for /api/v1/diagnose."""
    service_name: Optional[str] = Field(default="app", description="Name of the service or container")
    logs: Optional[str] = Field(default=None, description="Application or container console logs")
    docker_inspect: Optional[Dict[str, Any]] = Field(default=None, description="Docker inspect JSON output")
    configuration_files: Optional[Dict[str, str]] = Field(default=None, description="Key-value mapping of filenames to file content")
    environment_variables: Optional[Dict[str, str]] = Field(default=None, description="Sanitized environment variables")
    model: Optional[str] = Field(default=None, description="Optional override for Nebius model ID")

