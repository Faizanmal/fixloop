"""Core domain models and schema definitions for FixLoop.

All models adhere to strict Pydantic v2 validation.
Separates observations, hypotheses, diagnostic actions, patches, and verification results.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


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
    source: str = Field(
        ..., description="Origin of evidence: e.g. docker.logs, probe.http_get"
    )
    timestamp: datetime = Field(default_factory=utc_now)
    content: str = Field(
        ..., description="Raw text or structured JSON string of the evidence"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_initial: bool = Field(
        default=False, description="True if collected before hypothesis generation"
    )
    collector: str | None = Field(
        default=None,
        description="Collector module or probe runner that gathered this evidence",
    )
    target: str | None = Field(default=None, description="Resource or file target")
    fingerprint: str | None = Field(
        default=None, description="SHA256 fingerprint of evidence content"
    )
    provenance_type: str | None = Field(
        default=None,
        description="STATIC_ANALYSIS, RUNTIME_OBSERVATION, ACTIVE_PROBE, etc.",
    )


class HypothesisCategory(str, Enum):
    HEALTHCHECK_MISCONFIG = "HEALTHCHECK_MISCONFIG"
    PORT_MISMATCH = "PORT_MISMATCH"
    MISSING_ENV = "MISSING_ENV"
    CODE_DEFECT = "CODE_DEFECT"
    CODE_BUG = "CODE_BUG"
    EXTERNAL_DEPENDENCY = "EXTERNAL_DEPENDENCY"
    RESOURCE_EXHAUSTION = "RESOURCE_EXHAUSTION"
    CONFIG_ERROR = "CONFIG_ERROR"
    UNKNOWN = "UNKNOWN"


class Hypothesis(BaseModel):
    """A plausible root-cause explanation for the observed system failure."""

    id: str = Field(..., description="Hypothesis identifier, e.g. hyp-1")
    title: str = Field(..., max_length=150)
    description: str
    category: HypothesisCategory
    confidence_score: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence between 0.0 and 1.0"
    )
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    suggested_probe_rationale: str | None = None


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
    target: str = Field(
        ..., description="Target identifier (container name, URL path, file path)"
    )
    parameters: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(
        ..., description="Why this probe distinguishes competing hypotheses"
    )
    tested_hypothesis_id: str | None = None
    requires_human_approval: bool = Field(default=False)
    status: DiagnosticActionStatus = Field(default=DiagnosticActionStatus.PENDING)
    output: str | None = None
    executed_at: datetime | None = None


class Patch(BaseModel):
    """A minimal unified diff proposed to resolve the identified root cause."""

    id: str = Field(..., description="Patch identifier, e.g. patch-1")
    hypothesis_id: str
    target_file: str = Field(
        ..., description="Relative path of file to patch, e.g. docker-compose.yml"
    )
    diff_unified: str = Field(..., description="Unified diff format patch")
    explanation: str
    is_minimal: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now)


class VerificationStatus(str, Enum):
    VERIFIED_FIXED = "verified_fixed"
    VERIFICATION_FAILED = "verification_failed"
    PATCH_REJECTED = "patch_rejected"
    VERIFICATION_INCONCLUSIVE = "verification_inconclusive"
    NOT_ATTEMPTED = "not_attempted"


class VerificationResult(BaseModel):
    """Honest test execution results validating whether the proposed patch resolves the issue."""

    status: VerificationStatus
    exit_code: int | None = None
    test_output: str
    duration_ms: int = 0
    verified_at: datetime | None = None


class InvestigationOutcome(str, Enum):
    VERIFIED_FIX = "VERIFIED_FIX"
    FAILED_FIX = "FAILED_FIX"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    HUMAN_INTERVENTION_REQUIRED = "HUMAN_INTERVENTION_REQUIRED"
    DIAGNOSIS_AVAILABLE = "DIAGNOSIS_AVAILABLE"
    DIAGNOSIS_NO_PATCH = "DIAGNOSIS_NO_PATCH"


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
    evidence_store: list[EvidenceItem] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    diagnostic_history: list[DiagnosticAction] = Field(default_factory=list)
    candidate_patch: Patch | None = None
    verification_result: VerificationResult | None = None
    outcome: InvestigationOutcome | None = None
    outcome_summary: str | None = None
    confidence: float | None = None
    duration_ms: int | None = None
    diagnosis_duration_ms: int | None = None
    verification_duration_ms: int | None = None
    lookup_duration_ms: int | None = None
    is_sample: bool = False
    diagnosis: Any | None = None
    patch_proposal: Any | None = None
    verification_report: Any | None = None
    started_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    idempotency_key: str | None = None
    is_cached: bool = False
    original_duration_ms: int | None = None
    has_safe_patch: bool | None = None


# Request & Response Contracts for REST API


class StartInvestigationRequest(BaseModel):
    scenario_name: str | None = Field(
        default=None, description="Preset scenario name, or custom repo path"
    )
    custom_repo_path: str | None = Field(default=None)
    max_iterations: int = Field(default=5, ge=1, le=10)
    idempotency_key: str | None = Field(
        default=None, description="Client idempotency key to prevent duplicate runs"
    )


class HumanApprovalRequest(BaseModel):
    action_id: str
    approved: bool
    comments: str | None = None


class LLMHypothesisResponse(BaseModel):
    """Structured format expected from Nebius / Nemotron model when reasoning over evidence."""

    reasoning: str
    hypotheses: list[Hypothesis]
    needs_diagnostic_probe: bool
    recommended_probe: DiagnosticAction | None = None
    is_evidence_sufficient: bool = False
    refusal_reason: str | None = None


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


class ContradictionReport(BaseModel):
    """Contradiction detected between two pieces of evidence or observations."""

    id: str = Field(..., description="Unique contradiction identifier, e.g. contra-1")
    claim_a: str = Field(..., description="First claim or observation")
    source_a: str = Field(..., description="Source of first observation")
    evidence_id_a: str | None = Field(
        default=None, description="Optional ID of first evidence item"
    )
    claim_b: str = Field(..., description="Second conflicting claim or observation")
    source_b: str = Field(..., description="Source of second observation")
    evidence_id_b: str | None = Field(
        default=None, description="Optional ID of second evidence item"
    )
    description: str = Field(..., description="Nature of the contradiction")
    severity: str = Field(default="HIGH", description="Severity: HIGH, MEDIUM, LOW")
    implication: str = Field(
        default="", description="Diagnostic implication of this contradiction"
    )


class DiagnoseHypothesis(BaseModel):
    """Individual root-cause hypothesis with evidence references and confidence."""

    description: str = Field(
        ..., description="Description of the proposed root cause hypothesis"
    )
    supporting_evidence: list[str] = Field(
        default_factory=list, description="References to supporting evidence"
    )
    contradicting_evidence: list[str] = Field(
        default_factory=list, description="References to contradicting evidence"
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence level between 0.0 and 1.0"
    )
    recommended_discriminating_test: str | None = Field(
        default=None, description="Recommended discriminating test"
    )
    id: str | None = Field(
        default=None, description="Hypothesis identifier, e.g. hyp-1"
    )
    category: HypothesisCategory | None = Field(
        default=None, description="Category classification"
    )
    uncertainty: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Uncertainty metric for this hypothesis",
    )


class EvidenceRecord(BaseModel):
    """Record of observed system evidence with full provenance."""

    id: str = Field(..., description="Unique ID for this evidence record, e.g. ev-1")
    source: str = Field(
        ..., description="Source of evidence: logs, inspect, env, config, etc."
    )
    content: str = Field(..., description="Content or summary of observed evidence")
    timestamp: str | None = Field(
        default=None, description="ISO timestamp if available"
    )
    collector: str | None = Field(
        default=None, description="Collector that gathered this evidence"
    )
    target: str | None = Field(default=None, description="Target resource or file")
    fingerprint: str | None = Field(
        default=None, description="SHA256 fingerprint of evidence content"
    )
    provenance_type: str | None = Field(
        default=None, description="Provenance category: STATIC, RUNTIME, ACTIVE_PROBE"
    )


class RecommendTest(BaseModel):
    """Controlled discriminating test recommended to isolate competing hypotheses."""

    id: str = Field(
        ..., description="Identifier for recommended test probe, e.g. test-1"
    )
    test_type: str = Field(
        ..., description="Type of probe: HTTP_GET, TCP_CONNECT, CHECK_ENV, READ_FILE"
    )
    target: str = Field(..., description="Target endpoint, port, variable, or file")
    description: str = Field(..., description="Explanation of what this test verifies")
    expected_signal: str = Field(
        ..., description="Signal indicating positive or negative outcome"
    )
    expected_information_gain: float | None = Field(
        default=None, description="Expected Information Gain (EIG)"
    )
    cost: int | None = Field(
        default=None, description="Resource cost of executing this test"
    )
    safety: str | None = Field(
        default="safe", description="Safety tier: safe or disruptive"
    )
    estimated_duration_ms: int | None = Field(
        default=None, description="Estimated execution time in milliseconds"
    )


class DiagnoseResponse(BaseModel):
    """Complete structured diagnosis response matching FixLoop API specification."""

    status: DiagnosisStatus
    summary: str
    hypotheses: list[DiagnoseHypothesis] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    recommended_tests: list[RecommendTest] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Overall confidence level between 0.0 and 1.0"
    )
    next_action: str
    uncertainty: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Estimated diagnostic uncertainty (entropy/margin)",
    )
    contradictions: list[ContradictionReport] = Field(
        default_factory=list, description="Contradictions detected across evidence"
    )
    investigation_id: str | None = Field(
        default=None, description="Assigned investigation identifier if recorded"
    )
    idempotency_key: str | None = Field(
        default=None, description="Idempotency key for request deduplication"
    )
    is_cached: bool = Field(
        default=False, description="True if response was served from cache"
    )
    original_duration_ms: int | None = Field(
        default=None, description="Original execution duration if served from cache"
    )
    lookup_duration_ms: int | None = Field(
        default=None, description="Cache lookup duration in milliseconds"
    )
    duration_ms: int | None = Field(
        default=None,
        description="Authoritative server execution duration in milliseconds",
    )
    started_at_iso: str | None = Field(
        default=None, description="Server creation ISO timestamp"
    )
    has_safe_patch: bool | None = Field(
        default=None,
        description="True if a safe patch procedure exists for this diagnosis",
    )


class DiagnoseRequest(BaseModel):
    """Incoming request payload for /api/v1/diagnose."""

    service_name: str | None = Field(
        default="app", description="Name of the service or container"
    )
    logs: str | None = Field(
        default=None, description="Application or container console logs"
    )
    docker_inspect: dict[str, Any] | None = Field(
        default=None, description="Docker inspect JSON output"
    )
    configuration_files: dict[str, str] | None = Field(
        default=None, description="Key-value mapping of filenames to file content"
    )
    environment_variables: dict[str, str] | None = Field(
        default=None, description="Sanitized environment variables"
    )
    model: str | None = Field(
        default=None, description="Optional override for Nebius model ID"
    )
    idempotency_key: str | None = Field(
        default=None, description="Client idempotency key to prevent duplicate runs"
    )
    investigation_id: str | None = Field(
        default=None, description="Reattach to or reuse existing run ID"
    )
    client_last_id: str | None = Field(
        default=None, description="Highest run ID currently stored in client history"
    )
    async_mode: bool | None = Field(
        default=False,
        description="Run diagnosis as an asynchronous background task and return run ID immediately",
    )


class VerifyPatchRequest(BaseModel):
    """Request payload for /api/v1/verify."""

    scenario_name: str = Field(
        ..., description="Target scenario identifier (e.g. scenario_a_missing_env)"
    )
    user_approved: bool = Field(
        default=True, description="Human approval flag for high-risk operations"
    )
    investigation_id: str | None = Field(
        default=None,
        description="Optional investigation ID to update upon verification",
    )
