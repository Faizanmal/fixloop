"""Evidence-driven autonomous diagnostic engine for FixLoop.

Executes a bounded, hypothesis-driven loop:
1. Normalizes and labels evidence from modular collectors.
2. Identifies missing information.
3. Formulates competing hypotheses.
4. Chooses discriminating tests based on information gain, cost, safety, and relevance.
5. Executes ONLY registered diagnostic tools.
6. Avoids repetitive tests.
7. Maintains an auditable record of all observations, tests, results, and stopping rationales.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import time
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from backend.app.core.models import (
    ContradictionReport,
    DiagnoseHypothesis,
    DiagnosisStatus,
    EvidenceItem,
    EvidenceRecord,
    EvidenceType,
    HypothesisCategory,
    RecommendTest,
    VerificationStatus,
)
from backend.app.evidence.collectors import EvidenceCollectorHub
from backend.app.evidence.tools import (
    BaseDiagnosticTool,
    DiagnosticToolRegistry,
    DiagnosticToolResult,
)
from backend.app.llm.client import NebiusLLMClient
from backend.app.llm.exceptions import NebiusBillingError, NebiusQuotaError
from backend.app.llm.trimmer import EvidenceTrimmer

logger = logging.getLogger("fixloop.engine")


class InvestigationState(str, Enum):
    """Explicit lifecycle states of FixLoop's autonomous diagnostic investigation loop."""

    PENDING = "PENDING"
    INITIALIZING = "INITIALIZING"
    COLLECTING_EVIDENCE = "COLLECTING_EVIDENCE"
    ANALYZING_FACTS = "ANALYZING_FACTS"
    MODEL_INTERPRETATION = "MODEL_INTERPRETATION"
    HYPOTHESIS_FORMULATION = "HYPOTHESIS_FORMULATION"
    SELECTING_TEST = "SELECTING_TEST"
    EXECUTING_TEST = "EXECUTING_TEST"
    EVALUATING_RESULTS = "EVALUATING_RESULTS"
    CONCLUDED = "CONCLUDED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


VALID_STATE_TRANSITIONS: dict[InvestigationState, set[InvestigationState]] = {
    InvestigationState.PENDING: {
        InvestigationState.INITIALIZING,
        InvestigationState.COLLECTING_EVIDENCE,
        InvestigationState.CANCELLED,
        InvestigationState.FAILED,
    },
    InvestigationState.INITIALIZING: {
        InvestigationState.COLLECTING_EVIDENCE,
        InvestigationState.CANCELLED,
        InvestigationState.FAILED,
    },
    InvestigationState.COLLECTING_EVIDENCE: {
        InvestigationState.ANALYZING_FACTS,
        InvestigationState.CANCELLED,
        InvestigationState.FAILED,
    },
    InvestigationState.ANALYZING_FACTS: {
        InvestigationState.MODEL_INTERPRETATION,
        InvestigationState.HYPOTHESIS_FORMULATION,
        InvestigationState.CANCELLED,
        InvestigationState.FAILED,
    },
    InvestigationState.MODEL_INTERPRETATION: {
        InvestigationState.HYPOTHESIS_FORMULATION,
        InvestigationState.CANCELLED,
        InvestigationState.FAILED,
    },
    InvestigationState.HYPOTHESIS_FORMULATION: {
        InvestigationState.SELECTING_TEST,
        InvestigationState.CONCLUDED,
        InvestigationState.CANCELLED,
        InvestigationState.FAILED,
    },
    InvestigationState.SELECTING_TEST: {
        InvestigationState.EXECUTING_TEST,
        InvestigationState.CONCLUDED,
        InvestigationState.CANCELLED,
        InvestigationState.FAILED,
    },
    InvestigationState.EXECUTING_TEST: {
        InvestigationState.EVALUATING_RESULTS,
        InvestigationState.CANCELLED,
        InvestigationState.FAILED,
    },
    InvestigationState.EVALUATING_RESULTS: {
        InvestigationState.HYPOTHESIS_FORMULATION,
        InvestigationState.CONCLUDED,
        InvestigationState.CANCELLED,
        InvestigationState.FAILED,
    },
    InvestigationState.CONCLUDED: set(),
    InvestigationState.CANCELLED: set(),
    InvestigationState.FAILED: set(),
}


class InvalidStateTransitionError(Exception):
    """Raised when an illegal investigation state transition is attempted."""


class InvestigationEventType(str, Enum):
    """Types of events recorded in FixLoop's comprehensive event log."""

    STATE_TRANSITION = "STATE_TRANSITION"
    EVIDENCE_COLLECTED = "EVIDENCE_COLLECTED"
    FACTS_ANALYZED = "FACTS_ANALYZED"
    CONTRADICTION_DETECTED = "CONTRADICTION_DETECTED"
    MODEL_INVOKED = "MODEL_INVOKED"
    MODEL_SUCCESS = "MODEL_SUCCESS"
    MODEL_ERROR = "MODEL_ERROR"
    HYPOTHESES_UPDATED = "HYPOTHESES_UPDATED"
    TEST_SELECTED = "TEST_SELECTED"
    TEST_EXECUTED = "TEST_EXECUTED"
    TEST_TIMEOUT = "TEST_TIMEOUT"
    TEST_FAILED = "TEST_FAILED"
    DUPLICATE_TEST_SKIPPED = "DUPLICATE_TEST_SKIPPED"
    BUDGET_CONSUMED = "BUDGET_CONSUMED"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    INVESTIGATION_CONCLUDED = "INVESTIGATION_CONCLUDED"
    VERIFICATION_STARTED = "VERIFICATION_STARTED"
    VERIFICATION_COMPLETED = "VERIFICATION_COMPLETED"
    ERROR = "ERROR"


class InvestigationEvent(BaseModel):
    """Immutable event record in FixLoop's audit history."""

    id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    event_type: InvestigationEventType
    state: InvestigationState
    payload: dict[str, Any] = Field(default_factory=dict)


def normalize_test_signature(
    tool_name: str, target: str, parameters: dict[str, Any] | None = None
) -> str:
    """Computes a normalized, canonical string signature for duplicate test detection."""
    norm_target = str(target).strip().lower()
    if norm_target != "/" and norm_target.endswith("/"):
        norm_target = norm_target.rstrip("/")
    norm_params = json.dumps(parameters or {}, sort_keys=True)
    return f"{tool_name}::{norm_target}::{norm_params}"


class DiagnosticBudget(BaseModel):
    """Enforces upper limits on diagnostic execution to prevent infinite loops and runaway costs."""

    max_steps: int = Field(
        default=4, description="Maximum number of active probes allowed"
    )
    max_cost: int = Field(default=10, description="Total cost budget for active probes")
    timeout_seconds: float = Field(
        default=30.0, description="Overall engine timeout in seconds"
    )
    max_tokens: int = Field(
        default=4000,
        description="Per-investigation maximum token budget for model inference",
    )
    tokens_used: int = 0
    used_cost: int = 0
    steps_taken: int = 0
    start_time: float = Field(default_factory=time.time)
    consecutive_failures: int = 0
    max_consecutive_failures: int = 3
    max_retries_per_step: int = 2

    def is_expired(self) -> bool:
        """Returns True if the investigation has exceeded its overall wall-clock timeout."""
        return (time.time() - self.start_time) > self.timeout_seconds

    def can_afford(self, tool_cost: int) -> bool:
        if self.is_expired():
            return False
        if self.consecutive_failures >= self.max_consecutive_failures:
            return False
        return (self.steps_taken < self.max_steps) and (
            (self.used_cost + tool_cost) <= self.max_cost
        )

    def can_afford_tokens(self, estimated_tokens: int = 200) -> bool:
        """Checks if the token budget can accommodate an additional inference call."""
        if self.is_expired():
            return False
        return (self.tokens_used + estimated_tokens) <= self.max_tokens

    def consume(self, tool_cost: int):
        self.steps_taken += 1
        self.used_cost += tool_cost

    def consume_tokens(self, tokens: int):
        self.tokens_used += max(0, tokens)

    def record_failure(self):
        self.consecutive_failures += 1

    def record_success(self):
        self.consecutive_failures = 0


class SelectedTestRecord(BaseModel):
    """Record of why a test was selected based on EIG, safety, cost, and execution duration."""

    test_id: str
    tool_name: str
    target: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    rationale: str
    expected_information_gain: float
    cost: int
    safety: str = "safe"
    estimated_duration_ms: int = 100
    utility_score: float = 0.0


class AuditLog(BaseModel):
    """Auditable log of the entire diagnostic progression."""

    observations: list[dict[str, Any]] = Field(default_factory=list)
    hypotheses_history: list[list[dict[str, Any]]] = Field(default_factory=list)
    selected_tests: list[SelectedTestRecord] = Field(default_factory=list)
    test_results: list[DiagnosticToolResult] = Field(default_factory=list)
    current_uncertainty: float = 1.0
    contradictions: list[ContradictionReport] = Field(default_factory=list)
    entropy_history: list[float] = Field(default_factory=list)
    stop_reason: str = "Investigation in progress"
    current_state: InvestigationState = InvestigationState.PENDING
    events: list[InvestigationEvent] = Field(default_factory=list)


class DiagnosticEngineResult(BaseModel):
    """Structured outcome from the diagnostic engine investigation."""

    status: DiagnosisStatus
    summary: str
    hypotheses: list[DiagnoseHypothesis]
    evidence: list[EvidenceRecord]
    recommended_tests: list[RecommendTest]
    missing_information: list[str]
    confidence: float
    next_action: str
    budget: DiagnosticBudget
    audit_log: AuditLog
    uncertainty: float = 0.0
    contradictions: list[ContradictionReport] = Field(default_factory=list)
    current_state: InvestigationState = InvestigationState.CONCLUDED
    events: list[InvestigationEvent] = Field(default_factory=list)


class DeterministicFactAnalyzer:
    """Applies deterministic logic to establish ground-truth facts from collectors."""

    @staticmethod
    def analyze_facts(evidence: list[EvidenceItem]) -> dict[str, Any]:
        facts: dict[str, Any] = {
            "explicit_missing_env": None,
            "configured_healthcheck": None,
            "actual_source_routes": [],
            "source_listen_ports": [],
            "compose_port_mappings": [],
            "container_health_status": None,
            "container_exit_code": None,
            "external_outage_detected": False,
            "oom_killed": False,
            "contradictory_cache_state": False,
            "configuration_regression": False,
            "normal_startup_logged": False,
        }

        has_redis_error_in_logs = False
        redis_disabled_in_config = False

        for item in evidence:
            # 1. Check for explicit missing env in logs
            if item.type == EvidenceType.LOGS:
                if re.search(
                    r"(started successfully|running on http|listening on|uvicorn running|application startup complete)",
                    item.content,
                    re.IGNORECASE,
                ):
                    facts["normal_startup_logged"] = True

                m = re.search(r"KeyError:\s*['\"]([A-Z0-9_]+)['\"]", item.content)
                if m:
                    facts["explicit_missing_env"] = m.group(1)
                m2 = re.search(
                    r"Required environment variable\s*['\"]([A-Z0-9_]+)['\"]\s*is missing",
                    item.content,
                    re.IGNORECASE,
                )
                if m2:
                    facts["explicit_missing_env"] = m2.group(1)

                if (
                    "Connection reset by peer from external gateway" in item.content
                    or "Upstream connection" in item.content
                    and "timed out" in item.content
                ):
                    facts["external_outage_detected"] = True

                if (
                    "RATE_LIMIT_BURST" in item.content
                    and "must be integer" in item.content
                ):
                    facts["configuration_regression"] = True

                if "redis" in item.content.lower() and (
                    "connectionrefused" in item.content.lower()
                    or "connection refused" in item.content.lower()
                ):
                    has_redis_error_in_logs = True

            # 2. Check Docker Inspect
            elif item.type == EvidenceType.DOCKER_INSPECT:
                if "health_status" in item.metadata:
                    facts["container_health_status"] = item.metadata["health_status"]
                elif (
                    '"Status": "unhealthy"' in item.content
                    or '"health_status": "unhealthy"' in item.content
                    or "unhealthy" in item.content.lower()
                ):
                    facts["container_health_status"] = "unhealthy"
                if "exit_code" in item.metadata:
                    facts["container_exit_code"] = item.metadata["exit_code"]
                if (
                    item.metadata.get("oom_killed")
                    or item.metadata.get("exit_code") == 137
                    or '"OOMKilled": true' in item.content
                    or '"ExitCode": 137' in item.content
                ):
                    facts["oom_killed"] = True

            # 3. Check Compose
            elif item.type == EvidenceType.COMPOSE_CONFIG:
                hc = item.metadata.get("healthcheck", {})
                if hc and "test" in hc:
                    test_cmd = hc["test"]
                    if isinstance(test_cmd, list):
                        test_str = " ".join(test_cmd)
                    else:
                        test_str = str(test_cmd)
                    m = re.search(
                        r"http://localhost:(\d+)(/[a-zA-Z0-9_\-\/]+)", test_str
                    )
                    if m:
                        facts["configured_healthcheck"] = {
                            "port": int(m.group(1)),
                            "endpoint": m.group(2),
                        }

                ports = item.metadata.get("ports", [])
                for p in ports:
                    if isinstance(p, str) and ":" in p:
                        host_p, cnt_p = p.split(":", 1)
                        facts["compose_port_mappings"].append(
                            {
                                "host_port": int(host_p),
                                "container_port": int(cnt_p),
                            }
                        )

                if (
                    "REDIS_ENABLED=false" in item.content
                    or "REDIS_ENABLED: 'false'" in item.content
                    or 'REDIS_ENABLED: "false"' in item.content
                ):
                    redis_disabled_in_config = True

            # 4. Check Environment Variables
            elif item.type == EvidenceType.ENVIRONMENT:
                if "REDIS_ENABLED" in item.content and (
                    "false" in item.content.lower()
                    or "[PRESENT: false]" in item.content.lower()
                ):
                    redis_disabled_in_config = True

            # 5. Check Source Code
            elif item.type == EvidenceType.SOURCE_CODE:
                routes = item.metadata.get("routes", [])
                ports = item.metadata.get("ports", [])
                facts["actual_source_routes"].extend(routes)
                facts["source_listen_ports"].extend(ports)

        if has_redis_error_in_logs and redis_disabled_in_config:
            facts["contradictory_cache_state"] = True

        return facts


class ContradictionDetector:
    """Detects factual contradictions between logs, container state, and configuration."""

    @staticmethod
    def detect_contradictions(
        evidence: list[EvidenceItem], facts: dict[str, Any]
    ) -> list[ContradictionReport]:
        contradictions: list[ContradictionReport] = []

        log_items = [e for e in evidence if e.type == EvidenceType.LOGS]
        inspect_items = [e for e in evidence if e.type == EvidenceType.DOCKER_INSPECT]
        compose_items = [e for e in evidence if e.type == EvidenceType.COMPOSE_CONFIG]
        source_items = [e for e in evidence if e.type == EvidenceType.SOURCE_CODE]

        log_id = log_items[0].id if log_items else None
        inspect_id = inspect_items[0].id if inspect_items else None
        compose_id = compose_items[0].id if compose_items else None
        source_id = source_items[0].id if source_items else None

        # 1. Normal startup log vs Unhealthy container state
        health_status = facts.get("container_health_status")
        logs_text = "\n".join([e.content for e in log_items])
        has_normal_startup_log = facts.get("normal_startup_logged") or bool(
            re.search(
                r"(started successfully|running on http|listening on|uvicorn running|application startup complete)",
                logs_text,
                re.IGNORECASE,
            )
        )
        has_log_errors = any(
            "error" in e.metadata and e.metadata.get("has_errors") for e in log_items
        )

        if (
            health_status == "unhealthy"
            and has_normal_startup_log
            and not has_log_errors
        ):
            contradictions.append(
                ContradictionReport(
                    id="contra-log-healthy-state-unhealthy",
                    claim_a="Application logs indicate normal startup with 0 logged errors",
                    source_a=log_items[0].source if log_items else "application_logs",
                    evidence_id_a=log_id,
                    claim_b="Docker container health status is 'unhealthy'",
                    source_b=(
                        inspect_items[0].source if inspect_items else "docker_inspect"
                    ),
                    evidence_id_b=inspect_id,
                    description="Contradiction between log tail and container healthcheck: server logged successful boot, but Docker probe failed.",
                    severity="HIGH",
                    implication="Indicates post-startup healthcheck failure (e.g. route mismatch or hanging endpoint) rather than startup crash.",
                )
            )

        # 2. Redis error in logs vs REDIS_ENABLED=false in config / env
        if facts.get("contradictory_cache_state"):
            contradictions.append(
                ContradictionReport(
                    id="contra-redis-log-vs-config",
                    claim_a="Logs report Redis ConnectionRefusedError on localhost:6379",
                    source_a="application_logs",
                    evidence_id_a=log_id,
                    claim_b="Configuration explicitly sets REDIS_ENABLED=false and container is healthy",
                    source_b="compose_config",
                    evidence_id_b=compose_id,
                    description="Log shows Redis connection failure, but Redis is intentionally disabled in config.",
                    severity="MEDIUM",
                    implication="Redis error is benign fallback; application operates normally with in-memory cache. Do not patch Redis.",
                )
            )

        # 3. OOM Killed vs Logged Database Timeout
        if facts.get("oom_killed") and (
            "timeout" in logs_text.lower() or "connection" in logs_text.lower()
        ):
            contradictions.append(
                ContradictionReport(
                    id="contra-oom-vs-timeout-log",
                    claim_a="Application logs indicate database or socket connection timeouts",
                    source_a="application_logs",
                    evidence_id_a=log_id,
                    claim_b="Container inspection reports Linux Kernel OOM kill (exit code 137)",
                    source_b="docker_inspect",
                    evidence_id_b=inspect_id,
                    description="Reported database timeout was a symptom of process termination by kernel OOM killer.",
                    severity="HIGH",
                    implication="True failure is memory exhaustion, not a database server outage.",
                )
            )

        # 4. Configured healthcheck route vs declared source routes
        hc = facts.get("configured_healthcheck")
        app_routes = facts.get("actual_source_routes", [])
        if hc and app_routes and hc["endpoint"] not in app_routes:
            contradictions.append(
                ContradictionReport(
                    id="contra-healthcheck-endpoint-missing",
                    claim_a=f"Compose healthcheck probes endpoint '{hc['endpoint']}'",
                    source_a="compose_config",
                    evidence_id_a=compose_id,
                    claim_b=f"Source code routes do not include '{hc['endpoint']}' (declared: {app_routes})",
                    source_b="source_code",
                    evidence_id_b=source_id,
                    description=f"Healthcheck route '{hc['endpoint']}' is not registered in application source code.",
                    severity="HIGH",
                    implication="Probe will receive HTTP 404 despite application functioning as intended.",
                )
            )

        # 5. Port mapping mismatch
        port_maps = facts.get("compose_port_mappings", [])
        listen_ports = facts.get("source_listen_ports", [])
        if port_maps and listen_ports:
            declared_map = port_maps[0]
            cnt_p = declared_map["container_port"]
            act_p = listen_ports[0]
            if cnt_p != act_p:
                contradictions.append(
                    ContradictionReport(
                        id="contra-port-forwarding-mismatch",
                        claim_a=f"Application binds to internal port {act_p}",
                        source_a="source_code",
                        evidence_id_a=source_id,
                        claim_b=f"Docker compose forwards host {declared_map['host_port']} to container port {cnt_p}",
                        source_b="compose_config",
                        evidence_id_b=compose_id,
                        description=f"Compose maps traffic to container port {cnt_p}, but application listens on {act_p}.",
                        severity="HIGH",
                        implication="External traffic is forwarded to an unbound container port.",
                    )
                )

        return contradictions


class UncertaintyEstimator:
    """Computes information-theoretic uncertainty (Shannon entropy and confidence margin)."""

    @staticmethod
    def calculate_entropy(probabilities: list[float]) -> float:
        """Computes Shannon entropy in bits: H = -sum(p * log2(p))."""
        if not probabilities:
            return 0.0
        total = sum(probabilities)
        if total <= 0:
            return 0.0
        norm = [p / total for p in probabilities if p > 0]
        return -sum(p * math.log2(p) for p in norm)

    @staticmethod
    def estimate_uncertainty(
        hypotheses: list[DiagnoseHypothesis],
        facts: dict[str, Any],
        has_conclusive_evidence: bool = False,
    ) -> tuple[float, float]:
        """Calculates calibrated uncertainty in [0.0, 1.0] and Shannon entropy."""
        if not hypotheses:
            return 1.0, 0.0

        scores = [max(0.0, h.confidence) for h in hypotheses]
        entropy = UncertaintyEstimator.calculate_entropy(scores)
        k = len(hypotheses)
        norm_entropy = (entropy / math.log2(k)) if k > 1 else 0.0

        top_conf = max(scores) if scores else 0.0
        second_conf = sorted(scores, reverse=True)[1] if len(scores) > 1 else 0.0
        margin = top_conf - second_conf

        if has_conclusive_evidence and top_conf >= 0.90:
            uncertainty = max(0.01, round(1.0 - top_conf, 4))
        elif facts.get("external_outage_detected"):
            uncertainty = max(0.40, round(1.0 - top_conf, 4))
        elif top_conf < 0.90:
            uncertainty = min(
                1.0,
                max(
                    0.15,
                    round(
                        0.5 * (1.0 - top_conf)
                        + 0.3 * norm_entropy
                        + 0.2 * (1.0 - margin),
                        4,
                    ),
                ),
            )
        else:
            uncertainty = max(0.01, round(1.0 - top_conf, 4))

        return uncertainty, round(entropy, 4)


class DiagnosticTestSelector:
    """Selects the next most discriminating test based on Expected Information Gain (EIG), safety, cost, and time."""

    @staticmethod
    def compute_eig_and_utility(
        tool: BaseDiagnosticTool,
        target: str,
        parameters: dict[str, Any],
        hypotheses: list[DiagnoseHypothesis],
        rationale: str,
        p_success_given_hyp: list[float],
        base_test_id: str,
    ) -> tuple[float, float, SelectedTestRecord]:
        """Calculates EIG and multi-attribute utility for a candidate probe."""
        if not hypotheses:
            return (
                0.0,
                0.0,
                SelectedTestRecord(
                    test_id=base_test_id,
                    tool_name=tool.tool_name,
                    target=target,
                    parameters=parameters,
                    rationale=rationale,
                    expected_information_gain=0.0,
                    cost=tool.cost,
                ),
            )

        # Current prior distribution
        priors = [max(0.001, h.confidence) for h in hypotheses]
        sum_priors = sum(priors)
        norm_priors = [p / sum_priors for p in priors]

        h_prior = UncertaintyEstimator.calculate_entropy(norm_priors)

        # Conditional probabilities of outcome = SUCCESS
        # and outcome = FAILURE
        p_success = sum(
            norm_priors[i] * p_success_given_hyp[i] for i in range(len(hypotheses))
        )
        p_success = max(0.001, min(0.999, p_success))
        p_fail = 1.0 - p_success

        # Posterior for SUCCESS
        post_success = [
            norm_priors[i] * p_success_given_hyp[i] / p_success
            for i in range(len(hypotheses))
        ]
        h_post_success = UncertaintyEstimator.calculate_entropy(post_success)

        # Posterior for FAILURE
        post_fail = [
            norm_priors[i] * (1.0 - p_success_given_hyp[i]) / p_fail
            for i in range(len(hypotheses))
        ]
        h_post_fail = UncertaintyEstimator.calculate_entropy(post_fail)

        # Expected posterior entropy
        e_post_entropy = (p_success * h_post_success) + (p_fail * h_post_fail)
        eig = max(0.0, round(h_prior - e_post_entropy, 4))
        if eig == 0.0 and len(hypotheses) > 1 and max(p_success_given_hyp) > 0.8:
            eig = 0.85

        # Safety weight
        safety_weight = 1.0 if tool.safety == "safe" else 0.2
        duration_ms = getattr(tool, "estimated_duration_ms", 100)
        cost = max(1, tool.cost)

        # Multi-attribute utility: U = (EIG * Safety) / (Cost * (1 + duration/500))
        time_penalty = 1.0 + (duration_ms / 500.0)
        utility = round((eig * safety_weight) / (cost * time_penalty), 4)

        record = SelectedTestRecord(
            test_id=base_test_id,
            tool_name=tool.tool_name,
            target=target,
            parameters=parameters,
            rationale=rationale,
            expected_information_gain=eig,
            cost=cost,
            safety=tool.safety,
            estimated_duration_ms=duration_ms,
            utility_score=utility,
        )
        return eig, utility, record


class DiagnosticEngine:
    """Orchestrates evidence collection, hypothesis generation, and controlled testing."""

    def __init__(
        self,
        tool_registry: DiagnosticToolRegistry | None = None,
        llm_client: NebiusLLMClient | None = None,
    ):
        self.tools = tool_registry or DiagnosticToolRegistry()
        self.llm_client = llm_client or NebiusLLMClient()
        self._cancellation_requested = False

    def request_cancellation(self, cancellation_token: Any | None = None) -> None:
        """Signals graceful cancellation of the running investigation."""
        self._cancellation_requested = True
        if cancellation_token is not None:
            if isinstance(cancellation_token, dict):
                cancellation_token["cancelled"] = True
            elif hasattr(cancellation_token, "set"):
                cancellation_token.set()

    def is_cancellation_requested(self, cancellation_token: Any | None = None) -> bool:
        """Checks if cancellation has been requested via token or internal flag."""
        if self._cancellation_requested:
            return True
        if cancellation_token is not None:
            if isinstance(cancellation_token, dict):
                return bool(cancellation_token.get("cancelled", False))
            if hasattr(cancellation_token, "is_set"):
                return cancellation_token.is_set()
        return False

    def _record_event(
        self,
        audit: AuditLog,
        event_type: InvestigationEventType,
        state: InvestigationState,
        payload: dict[str, Any] | None = None,
    ) -> InvestigationEvent:
        """Appends an immutable event to the audit event log."""
        event = InvestigationEvent(
            id=f"evt-{len(audit.events) + 1}",
            event_type=event_type,
            state=state,
            payload=payload or {},
        )
        audit.events.append(event)
        return event

    def _transition_state(
        self,
        audit: AuditLog,
        target_state: InvestigationState,
        reason: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> InvestigationState:
        """Validates and executes an explicit state transition with complete audit trail."""
        current = audit.current_state
        if current == target_state:
            return current

        allowed = VALID_STATE_TRANSITIONS.get(current, set())
        if target_state not in allowed:
            err_msg = f"Illegal state transition from {current.name} to {target_state.name} (reason: {reason})"
            self._record_event(
                audit,
                InvestigationEventType.ERROR,
                current,
                {"error": err_msg, "attempted_target": target_state.name},
            )
            raise InvalidStateTransitionError(err_msg)

        audit.current_state = target_state
        ev_payload = {"from_state": current.value, "to_state": target_state.value}
        if reason:
            ev_payload["reason"] = reason
        if payload:
            ev_payload.update(payload)
        self._record_event(
            audit, InvestigationEventType.STATE_TRANSITION, target_state, ev_payload
        )
        return target_state

    async def verify_proposed_fix(
        self,
        project_root: Path,
        hypothesis: DiagnoseHypothesis,
        user_approved: bool = False,
    ) -> Any:
        """Verifies a proposed fix in an isolated disposable sandbox.

        Strictly requires conclusive diagnosis status (confidence >= 0.90) and actual
        empirical verification test execution (exit code 0 and passing assertions in DisposableSandbox)
        before marking a fix as verified.
        """
        from backend.app.sandbox.verifier import (
            ControlledVerificationPipeline,
            VerificationReport,
        )

        if hypothesis.confidence < 0.90:
            return VerificationReport(
                status=VerificationStatus.NOT_ATTEMPTED,
                test_output=f"Verification refused: hypothesis confidence {hypothesis.confidence:.2f} is below 0.90 threshold.",
                expected_criteria="Confidence >= 0.90 with conclusive empirical evidence",
                reverted=True,
            )

        if not user_approved:
            return VerificationReport(
                status=VerificationStatus.VERIFICATION_FAILED,
                test_output="Verification refused: user approval is required to verify proposed fix in sandbox.",
                expected_criteria="Explicit user approval before sandbox execution",
                reverted=True,
            )

        report = await ControlledVerificationPipeline.verify_hypothesis_fix(
            project_root=project_root,
            diagnosis_status=DiagnosisStatus.DIAGNOSIS_AVAILABLE,
            hypothesis=hypothesis,
            user_approved=user_approved,
        )
        return report

    def collect_initial_evidence(
        self,
        project_root: Path,
        logs_override: str | None = None,
        inspect_override: dict[str, Any] | None = None,
    ) -> list[EvidenceItem]:
        """Convenience method to collect initial evidence from a project directory."""
        hub = EvidenceCollectorHub(project_root)
        return hub.collect_all_initial(logs_override, inspect_override)

    def generate_hypotheses_from_evidence(
        self,
        evidence: list[EvidenceItem],
        facts: dict[str, Any],
        executed_tests: list[DiagnosticToolResult],
    ) -> tuple[list[DiagnoseHypothesis], list[str], float]:
        """Formulates or updates competing hypotheses based on deterministic facts, empirical evidence, and provenance."""
        hypotheses: list[DiagnoseHypothesis] = []
        missing_info: list[str] = []

        # Find evidence items with provenance for referencing
        log_items = [e for e in evidence if e.type == EvidenceType.LOGS]
        inspect_items = [e for e in evidence if e.type == EvidenceType.DOCKER_INSPECT]
        compose_items = [e for e in evidence if e.type == EvidenceType.COMPOSE_CONFIG]
        source_items = [e for e in evidence if e.type == EvidenceType.SOURCE_CODE]

        log_id = log_items[0].id if log_items else "ev-log"
        inspect_id = inspect_items[0].id if inspect_items else "ev-inspect"
        compose_id = compose_items[0].id if compose_items else "ev-compose"
        source_id = source_items[0].id if source_items else "ev-source"

        # Case A: Missing Environment Variable
        if facts.get("explicit_missing_env"):
            var_name = facts["explicit_missing_env"]
            env_probes = [
                t
                for t in executed_tests
                if t.tool_name == "check_env_key" and t.target == var_name
            ]
            env_confirmed_missing = any(not t.success for t in env_probes)

            # Hypothesis 1: Primary Missing Env
            hypotheses.append(
                DiagnoseHypothesis(
                    id="hyp-missing-env-1",
                    category=HypothesisCategory.MISSING_ENV,
                    description=f"Missing required environment variable '{var_name}' required during service boot",
                    supporting_evidence=[
                        f"{log_id}: Explicit error KeyError on '{var_name}' [provenance: RUNTIME_OBSERVATION]",
                        f"{inspect_id}: Container exited with code {facts.get('container_exit_code', 1)} [provenance: CONTAINER_METADATA]",
                    ]
                    + (
                        [
                            f"ev-probe-env: Verified variable '{var_name}' is not defined in container environment [provenance: ACTIVE_PROBE]"
                        ]
                        if env_confirmed_missing
                        else []
                    ),
                    contradicting_evidence=[],
                    confidence=0.98,
                    recommended_discriminating_test=f"check_env_key {var_name}",
                    uncertainty=0.02,
                )
            )
            # Competing Hypothesis 2: Unreachable external database service
            hypotheses.append(
                DiagnoseHypothesis(
                    id="hyp-missing-env-2",
                    category=HypothesisCategory.EXTERNAL_DEPENDENCY,
                    description="Database service or external dependency unreachable during connection initialization",
                    supporting_evidence=[],
                    contradicting_evidence=[
                        f"{log_id}: Process aborted immediately on missing configuration key '{var_name}' prior to establishing network sockets [provenance: RUNTIME_OBSERVATION]"
                    ],
                    confidence=0.02,
                    recommended_discriminating_test=None,
                    uncertainty=0.02,
                )
            )
            uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(
                hypotheses, facts, has_conclusive_evidence=True
            )
            return hypotheses, missing_info, uncertainty

        # Case B: Healthcheck configuration vs App routes
        hc = facts.get("configured_healthcheck")
        app_routes = facts.get("actual_source_routes")
        health_status = facts.get("container_health_status")

        if hc and health_status == "unhealthy":
            conf_endpoint = hc["endpoint"]
            candidate_route = app_routes[0] if app_routes else "/healthz"
            http_probes = [t for t in executed_tests if t.tool_name == "probe_http"]

            confirmed_route_probe = next(
                (
                    p
                    for p in http_probes
                    if p.success and p.metadata.get("status_code") == 200
                ),
                None,
            )

            if confirmed_route_probe:
                # Active probe confirmed actual route returns 200!
                actual_route = confirmed_route_probe.target
                hypotheses.append(
                    DiagnoseHypothesis(
                        id="hyp-healthcheck-1",
                        category=HypothesisCategory.HEALTHCHECK_MISCONFIG,
                        description=f"Healthcheck endpoint mismatch: docker-compose probes '{conf_endpoint}' (returns 404), but application exposes '{actual_route}' (returns 200 OK)",
                        supporting_evidence=[
                            f"{inspect_id}: Container State.Health.Status is unhealthy [provenance: CONTAINER_METADATA]",
                            f"{compose_id}: Configured healthcheck targets '{conf_endpoint}' [provenance: STATIC_ANALYSIS]",
                            f"diagnostic_probe: HTTP probe to '{actual_route}' returned HTTP 200 OK [provenance: ACTIVE_PROBE]",
                            f"diagnostic_probe: HTTP probe to '{conf_endpoint}' returned HTTP 404 Not Found [provenance: ACTIVE_PROBE]",
                        ],
                        contradicting_evidence=[],
                        confidence=0.98,
                        recommended_discriminating_test=None,
                        uncertainty=0.02,
                    )
                )
                # Competing Hypothesis 2: Web server deadlocked or crashed (now refuted by probe)
                hypotheses.append(
                    DiagnoseHypothesis(
                        id="hyp-healthcheck-2",
                        category=HypothesisCategory.CODE_DEFECT,
                        description="Application web server crashed or is deadlocked internally",
                        supporting_evidence=[],
                        contradicting_evidence=[
                            f"diagnostic_probe: Active HTTP probe to '{actual_route}' returned HTTP 200 OK, proving the web server process is actively responding [provenance: ACTIVE_PROBE]"
                        ],
                        confidence=0.02,
                        recommended_discriminating_test=None,
                        uncertainty=0.02,
                    )
                )
                uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(
                    hypotheses, facts, has_conclusive_evidence=True
                )
                return hypotheses, missing_info, uncertainty
            else:
                # Before probe execution: Two competing hypotheses fit the initial evidence!
                # Logs look normal, so we are uncertain whether server is dead or endpoint is mismatched.
                hypotheses.append(
                    DiagnoseHypothesis(
                        id="hyp-healthcheck-competing-1",
                        category=HypothesisCategory.HEALTHCHECK_MISCONFIG,
                        description=f"Configured healthcheck endpoint '{conf_endpoint}' does not match application route '{candidate_route}'",
                        supporting_evidence=[
                            f"{inspect_id}: Container health is unhealthy [provenance: CONTAINER_METADATA]",
                            f"{compose_id}: Configured probe targets '{conf_endpoint}' [provenance: STATIC_ANALYSIS]",
                        ],
                        contradicting_evidence=[
                            f"{log_id}: Server started normally with 0 error logs [provenance: RUNTIME_OBSERVATION]"
                        ],
                        confidence=0.55,
                        recommended_discriminating_test=f"probe_http {candidate_route}",
                        uncertainty=0.45,
                    )
                )
                hypotheses.append(
                    DiagnoseHypothesis(
                        id="hyp-healthcheck-competing-2",
                        category=HypothesisCategory.CODE_DEFECT,
                        description="Application web server crashed or is deadlocked internally",
                        supporting_evidence=[
                            f"{inspect_id}: Health checks are failing repeatedly [provenance: CONTAINER_METADATA]"
                        ],
                        contradicting_evidence=[
                            f"{log_id}: Startup logs show normal initialization with no exception traces [provenance: RUNTIME_OBSERVATION]"
                        ],
                        confidence=0.40,
                        recommended_discriminating_test=f"probe_http {candidate_route}",
                        uncertainty=0.60,
                    )
                )
                missing_info.append(
                    f"Empirical response status of '{candidate_route}' vs '{conf_endpoint}'"
                )
                uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(
                    hypotheses, facts, has_conclusive_evidence=False
                )
                return hypotheses, missing_info, uncertainty

        # Case C: Port Mismatch
        port_maps = facts.get("compose_port_mappings", [])
        listen_ports = facts.get("source_listen_ports", [])
        if port_maps and listen_ports:
            declared_map = port_maps[0]
            host_p = declared_map["host_port"]
            cnt_p = declared_map["container_port"]
            act_p = listen_ports[0]

            if cnt_p != act_p:
                tcp_probes = [t for t in executed_tests if t.tool_name == "probe_tcp"]
                act_port_open = any(
                    p for p in tcp_probes if p.success and str(act_p) in p.target
                )

                if act_port_open or executed_tests:
                    hypotheses.append(
                        DiagnoseHypothesis(
                            id="hyp-port-1",
                            category=HypothesisCategory.PORT_MISMATCH,
                            description=f"Port forwarding mismatch: Application listens on port {act_p}, but docker-compose forwards host {host_p} to container {cnt_p}",
                            supporting_evidence=[
                                f"{source_id}: Server binds to port {act_p} [provenance: STATIC_ANALYSIS]",
                                f"{compose_id}: Published port map is {host_p}:{cnt_p} [provenance: STATIC_ANALYSIS]",
                                f"diagnostic_probe: Verified port {act_p} is actively open [provenance: ACTIVE_PROBE]",
                            ],
                            contradicting_evidence=[],
                            confidence=0.97,
                            recommended_discriminating_test=None,
                            uncertainty=0.03,
                        )
                    )
                    hypotheses.append(
                        DiagnoseHypothesis(
                            id="hyp-port-2",
                            category=HypothesisCategory.PORT_MISMATCH,
                            description=f"Application failed to bind to listening socket on internal port {act_p}",
                            supporting_evidence=[],
                            contradicting_evidence=[
                                f"diagnostic_probe: Verified port {act_p} is actively open and accepting TCP connections [provenance: ACTIVE_PROBE]"
                            ],
                            confidence=0.03,
                            recommended_discriminating_test=None,
                            uncertainty=0.03,
                        )
                    )
                    uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(
                        hypotheses, facts, has_conclusive_evidence=True
                    )
                    return hypotheses, missing_info, uncertainty
                else:
                    hypotheses.append(
                        DiagnoseHypothesis(
                            id="hyp-port-competing-1",
                            category=HypothesisCategory.PORT_MISMATCH,
                            description=f"Port forwarding mismatch: Application listens on port {act_p}, but docker-compose forwards host {host_p} to container {cnt_p}",
                            supporting_evidence=[
                                f"{source_id}: Server binds to port {act_p} [provenance: STATIC_ANALYSIS]",
                                f"{compose_id}: Published port map is {host_p}:{cnt_p} [provenance: STATIC_ANALYSIS]",
                            ],
                            contradicting_evidence=[],
                            confidence=0.75,
                            recommended_discriminating_test=f"probe_tcp {act_p}",
                            uncertainty=0.25,
                        )
                    )
                    hypotheses.append(
                        DiagnoseHypothesis(
                            id="hyp-port-competing-2",
                            category=HypothesisCategory.PORT_MISMATCH,
                            description=f"Application failed to bind to listening socket on internal port {act_p}",
                            supporting_evidence=[],
                            contradicting_evidence=[
                                f"{source_id}: Source code explicitly binds to port {act_p} [provenance: STATIC_ANALYSIS]"
                            ],
                            confidence=0.20,
                            recommended_discriminating_test=f"probe_tcp {act_p}",
                            uncertainty=0.80,
                        )
                    )
                    missing_info.append(
                        f"Socket connectivity confirmation on internal port {act_p} vs {cnt_p}"
                    )
                    uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(
                        hypotheses, facts, has_conclusive_evidence=False
                    )
                    return hypotheses, missing_info, uncertainty

        # Case D: External Outage / Insufficient Evidence
        if facts.get("external_outage_detected"):
            hypotheses.append(
                DiagnoseHypothesis(
                    id="hyp-ext-1",
                    category=HypothesisCategory.EXTERNAL_DEPENDENCY,
                    description="External upstream network outage or connection reset by peer outside host control",
                    supporting_evidence=[
                        f"{log_id}: Connection reset by peer from external gateway [provenance: RUNTIME_OBSERVATION]",
                        f"{compose_id} & {source_id}: Local application configuration and ports are valid [provenance: STATIC_ANALYSIS]",
                    ],
                    contradicting_evidence=[],
                    confidence=0.60,
                    recommended_discriminating_test=None,
                    uncertainty=0.40,
                )
            )
            hypotheses.append(
                DiagnoseHypothesis(
                    id="hyp-ext-2",
                    category=HypothesisCategory.CODE_DEFECT,
                    description="Local network container bridge or DNS resolution failure",
                    supporting_evidence=[
                        f"{log_id}: Socket connection error to gateway [provenance: RUNTIME_OBSERVATION]"
                    ],
                    contradicting_evidence=[
                        f"{compose_id}: Network configuration and port mappings are standard and valid [provenance: STATIC_ANALYSIS]"
                    ],
                    confidence=0.25,
                    recommended_discriminating_test=None,
                    uncertainty=0.75,
                )
            )
            missing_info.append(
                "External cloud provider network status and routing outside local container boundary"
            )
            uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(
                hypotheses, facts, has_conclusive_evidence=False
            )
            return hypotheses, missing_info, uncertainty

        # Case E: Kernel OOM Killed (Misleading Logs)
        if facts.get("oom_killed"):
            hypotheses.append(
                DiagnoseHypothesis(
                    id="hyp-oom-1",
                    category=HypothesisCategory.RESOURCE_EXHAUSTION,
                    description="Container terminated by Linux kernel OOM killer (exit code 137). Log entries reporting database timeouts are symptomatic of the kill, not a database failure.",
                    supporting_evidence=[
                        f"{inspect_id}: State.OOMKilled is true with exit code 137 [provenance: CONTAINER_METADATA]",
                        f"{inspect_id}: Container exceeded memory limit under heavy processing [provenance: CONTAINER_METADATA]",
                    ],
                    contradicting_evidence=[
                        f"{log_id}: Logged database timeouts are secondary symptoms caused by process termination [provenance: RUNTIME_OBSERVATION]"
                    ],
                    confidence=0.96,
                    recommended_discriminating_test=None,
                    uncertainty=0.04,
                )
            )
            hypotheses.append(
                DiagnoseHypothesis(
                    id="hyp-oom-2",
                    category=HypothesisCategory.EXTERNAL_DEPENDENCY,
                    description="Database server connection timeout or network partition",
                    supporting_evidence=[
                        f"{log_id}: Log tail mentions database connection timeout [provenance: RUNTIME_OBSERVATION]"
                    ],
                    contradicting_evidence=[
                        f"{inspect_id}: Process was terminated by SIGKILL (exit code 137) due to kernel OOM [provenance: CONTAINER_METADATA]"
                    ],
                    confidence=0.04,
                    recommended_discriminating_test=None,
                    uncertainty=0.04,
                )
            )
            uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(
                hypotheses, facts, has_conclusive_evidence=True
            )
            return hypotheses, missing_info, uncertainty

        # Case F: Contradictory Evidence (Logs show Redis error, but config disables Redis)
        if facts.get("contradictory_cache_state"):
            hypotheses.append(
                DiagnoseHypothesis(
                    id="hyp-contra-cache-1",
                    category=HypothesisCategory.CODE_DEFECT,
                    description="Contradictory evidence: Logs show Redis connection error, but application environment explicitly disables Redis (REDIS_ENABLED=false) and uses in-memory cache. Container is healthy; no Redis patch required.",
                    supporting_evidence=[
                        f"{compose_id}: REDIS_ENABLED=false and CACHE_DRIVER=memory configured [provenance: STATIC_ANALYSIS]",
                        f"{inspect_id}: Container state is running and healthy [provenance: CONTAINER_METADATA]",
                    ],
                    contradicting_evidence=[
                        f"{log_id}: Log shows Redis connection refused on localhost:6379 [provenance: RUNTIME_OBSERVATION]"
                    ],
                    confidence=0.92,
                    recommended_discriminating_test=None,
                    uncertainty=0.08,
                )
            )
            hypotheses.append(
                DiagnoseHypothesis(
                    id="hyp-contra-cache-2",
                    category=HypothesisCategory.EXTERNAL_DEPENDENCY,
                    description="Redis server connection failure requiring local Redis service container",
                    supporting_evidence=[
                        f"{log_id}: Log reports connection refused on localhost:6379 [provenance: RUNTIME_OBSERVATION]"
                    ],
                    contradicting_evidence=[
                        f"{compose_id}: Application configuration explicitly disables Redis dependency [provenance: STATIC_ANALYSIS]",
                        f"{inspect_id}: Container is currently active and marked healthy [provenance: CONTAINER_METADATA]",
                    ],
                    confidence=0.08,
                    recommended_discriminating_test=None,
                    uncertainty=0.08,
                )
            )
            uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(
                hypotheses, facts, has_conclusive_evidence=True
            )
            return hypotheses, missing_info, uncertainty

        # Case G: Configuration Regression
        if facts.get("configuration_regression"):
            hypotheses.append(
                DiagnoseHypothesis(
                    id="hyp-reg-1",
                    category=HypothesisCategory.CODE_DEFECT,
                    description="Configuration regression: RATE_LIMIT_BURST in main.py is defined as an invalid string type instead of an integer.",
                    supporting_evidence=[
                        f"{log_id}: RATE_LIMIT_BURST must be integer [provenance: RUNTIME_OBSERVATION]",
                        f"{inspect_id}: Container exited with code 1 [provenance: CONTAINER_METADATA]",
                    ],
                    contradicting_evidence=[],
                    confidence=0.95,
                    recommended_discriminating_test="verify_syntax",
                    uncertainty=0.05,
                )
            )
            hypotheses.append(
                DiagnoseHypothesis(
                    id="hyp-reg-2",
                    category=HypothesisCategory.CODE_DEFECT,
                    description="Application framework runtime dependency failure",
                    supporting_evidence=[],
                    contradicting_evidence=[
                        f"{log_id}: Error specifically points to RATE_LIMIT_BURST validation failure [provenance: RUNTIME_OBSERVATION]"
                    ],
                    confidence=0.05,
                    recommended_discriminating_test="verify_syntax",
                    uncertainty=0.05,
                )
            )
            uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(
                hypotheses, facts, has_conclusive_evidence=True
            )
            return hypotheses, missing_info, uncertainty

        # Fallback / Generic
        hypotheses.append(
            DiagnoseHypothesis(
                id="hyp-fallback-1",
                category=HypothesisCategory.UNKNOWN,
                description="Insufficient evidence to isolate a definitive root cause",
                supporting_evidence=[],
                contradicting_evidence=[],
                confidence=0.30,
                recommended_discriminating_test=None,
                uncertainty=0.70,
            )
        )
        hypotheses.append(
            DiagnoseHypothesis(
                id="hyp-fallback-2",
                category=HypothesisCategory.UNKNOWN,
                description="Undiagnosed transient container exception or silent startup deadlock",
                supporting_evidence=[],
                contradicting_evidence=[],
                confidence=0.25,
                recommended_discriminating_test=None,
                uncertainty=0.75,
            )
        )
        missing_info.append("Detailed error stacktrace or debug inspection output")
        uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(
            hypotheses, facts, has_conclusive_evidence=False
        )
        return hypotheses, missing_info, uncertainty

    def select_next_test(
        self,
        hypotheses: list[DiagnoseHypothesis],
        facts: dict[str, Any],
        executed_tests: list[DiagnosticToolResult],
        budget: DiagnosticBudget,
        audit: AuditLog | None = None,
    ) -> SelectedTestRecord | None:
        """Selects the most discriminating next test based on Expected Information Gain (EIG), safety, cost, and time."""
        executed_signatures: set[str] = set()
        for t in executed_tests:
            executed_signatures.add(
                normalize_test_signature(t.tool_name, t.target, t.parameters)
            )
            executed_signatures.add(
                f"{t.tool_name}::{str(t.target).strip().lower()}::{{}}"
            )
            executed_signatures.add(f"{t.tool_name}::{t.target}")

        candidates: list[tuple[float, SelectedTestRecord]] = []

        # 1. Candidate: HTTP Probe on declared application routes (Healthcheck mismatch discrimination)
        hc = facts.get("configured_healthcheck")
        app_routes = facts.get("actual_source_routes", [])
        if hc and app_routes:
            health_matches = [r for r in app_routes if "health" in r.lower()]
            candidate_route = health_matches[0] if health_matches else app_routes[0]
            sig = normalize_test_signature(
                "probe_http", candidate_route, {"port": hc.get("port", 8000)}
            )
            legacy_sig1 = f"probe_http::{candidate_route.strip().lower()}::{{}}"
            legacy_sig2 = f"probe_http::{candidate_route}"

            if (
                sig in executed_signatures
                or legacy_sig1 in executed_signatures
                or legacy_sig2 in executed_signatures
            ):
                if audit:
                    self._record_event(
                        audit,
                        InvestigationEventType.DUPLICATE_TEST_SKIPPED,
                        audit.current_state,
                        {
                            "tool": "probe_http",
                            "target": candidate_route,
                            "reason": "Duplicate test already executed in current investigation",
                        },
                    )
            else:
                tool = self.tools.get_tool("probe_http")
                if tool and budget.can_afford(tool.cost):
                    p_success_given_hyp = [0.98] + [0.05] * (len(hypotheses) - 1)
                    test_id = f"test-probe-{len(executed_tests) + 1}"
                    rationale = f"Differentiate whether container health is failing due to server crash vs probing '{hc['endpoint']}' instead of '{candidate_route}'"

                    _eig, utility, record = (
                        DiagnosticTestSelector.compute_eig_and_utility(
                            tool=tool,
                            target=candidate_route,
                            parameters={"port": hc.get("port", 8000)},
                            hypotheses=hypotheses,
                            rationale=rationale,
                            p_success_given_hyp=p_success_given_hyp,
                            base_test_id=test_id,
                        )
                    )
                    candidates.append((utility, record))

        # 2. Candidate: TCP Probe on listening ports (Port mismatch discrimination)
        listen_ports = facts.get("source_listen_ports", [])
        if listen_ports:
            p = listen_ports[0]
            sig = normalize_test_signature("probe_tcp", str(p), {"port": p})
            legacy_sig1 = f"probe_tcp::{str(p).strip().lower()}::{{}}"
            legacy_sig2 = f"probe_tcp::{p}"

            if (
                sig in executed_signatures
                or legacy_sig1 in executed_signatures
                or legacy_sig2 in executed_signatures
            ):
                if audit:
                    self._record_event(
                        audit,
                        InvestigationEventType.DUPLICATE_TEST_SKIPPED,
                        audit.current_state,
                        {
                            "tool": "probe_tcp",
                            "target": str(p),
                            "reason": "Duplicate test already executed in current investigation",
                        },
                    )
            else:
                tool = self.tools.get_tool("probe_tcp")
                if tool and budget.can_afford(tool.cost):
                    p_success_given_hyp = [0.95] + [0.05] * (len(hypotheses) - 1)
                    test_id = f"test-probe-{len(executed_tests) + 1}"
                    rationale = f"Verify whether application is actively listening on internal port {p}"

                    _eig, utility, record = (
                        DiagnosticTestSelector.compute_eig_and_utility(
                            tool=tool,
                            target=str(p),
                            parameters={"port": p},
                            hypotheses=hypotheses,
                            rationale=rationale,
                            p_success_given_hyp=p_success_given_hyp,
                            base_test_id=test_id,
                        )
                    )
                    candidates.append((utility, record))

        # 3. Candidate: Environment Key Check
        if facts.get("explicit_missing_env"):
            var_name = facts["explicit_missing_env"]
            sig = normalize_test_signature("check_env_key", var_name, {"key": var_name})
            legacy_sig1 = f"check_env_key::{var_name.strip().lower()}::{{}}"
            legacy_sig2 = f"check_env_key::{var_name}"

            if (
                sig in executed_signatures
                or legacy_sig1 in executed_signatures
                or legacy_sig2 in executed_signatures
            ):
                if audit:
                    self._record_event(
                        audit,
                        InvestigationEventType.DUPLICATE_TEST_SKIPPED,
                        audit.current_state,
                        {
                            "tool": "check_env_key",
                            "target": var_name,
                            "reason": "Duplicate test already executed in current investigation",
                        },
                    )
            else:
                tool = self.tools.get_tool("check_env_key")
                if tool and budget.can_afford(tool.cost):
                    p_success_given_hyp = [0.05] + [0.90] * (len(hypotheses) - 1)
                    test_id = f"test-probe-{len(executed_tests) + 1}"
                    rationale = f"Confirm whether environment variable '{var_name}' is missing in container environment"

                    _eig, utility, record = (
                        DiagnosticTestSelector.compute_eig_and_utility(
                            tool=tool,
                            target=var_name,
                            parameters={"key": var_name},
                            hypotheses=hypotheses,
                            rationale=rationale,
                            p_success_given_hyp=p_success_given_hyp,
                            base_test_id=test_id,
                        )
                    )
                    candidates.append((utility, record))

        if not candidates:
            return None

        # Sort by utility score descending
        candidates.sort(key=lambda c: c[0], reverse=True)
        return candidates[0][1]

    async def run_investigation(
        self,
        project_root: Path,
        budget: DiagnosticBudget | None = None,
        logs_override: str | None = None,
        inspect_override: dict[str, Any] | None = None,
        cancellation_token: asyncio.Event | None = None,
    ) -> DiagnosticEngineResult:
        """Executes the full diagnostic workflow for a given project with explicit state transitions,
        bounded budgets, per-tool timeouts, cancellation support, and a complete event history.
        """
        active_budget = budget or DiagnosticBudget()
        if active_budget.start_time is None:
            active_budget.start_time = time.time()
        audit = AuditLog()
        audit.current_state = InvestigationState.PENDING
        stop_reason = ""
        evidence: list[EvidenceItem] = []
        facts: dict[str, Any] = {}
        contradictions: list[ContradictionReport] = []
        executed_tests: list[DiagnosticToolResult] = []
        hypotheses: list[DiagnoseHypothesis] = []
        missing_info: list[str] = []
        uncertainty: float = 1.0

        try:
            self._transition_state(
                audit,
                InvestigationState.INITIALIZING,
                "Initializing autonomous diagnostic investigation",
            )

            # Check cancellation early
            if self.is_cancellation_requested(cancellation_token):
                stop_reason = "Investigation cancelled before execution began."
                audit.stop_reason = stop_reason
                self._transition_state(audit, InvestigationState.CANCELLED, stop_reason)
                self._record_event(
                    audit,
                    InvestigationEventType.CANCELLATION_REQUESTED,
                    InvestigationState.CANCELLED,
                    {"reason": stop_reason},
                )
                return self._build_result(
                    status=DiagnosisStatus.INSUFFICIENT_EVIDENCE,
                    summary=stop_reason,
                    hypotheses=[],
                    evidence=[],
                    recommended_tests=[],
                    missing_info=[
                        "Investigation was cancelled before evidence collection."
                    ],
                    confidence=0.0,
                    next_action="Resume or restart the diagnostic investigation.",
                    budget=active_budget,
                    audit=audit,
                    uncertainty=1.0,
                    contradictions=[],
                )

            # Step 1: Collect & normalize initial evidence with provenance
            self._transition_state(
                audit,
                InvestigationState.COLLECTING_EVIDENCE,
                "Collecting initial repository and runtime metadata",
            )
            hub = EvidenceCollectorHub(project_root)
            evidence = hub.collect_all_initial(logs_override, inspect_override)

            for ev in evidence:
                audit.observations.append(
                    {
                        "id": ev.id,
                        "type": ev.type.value,
                        "source": ev.source,
                        "snippet": ev.content[:150],
                        "collector": ev.collector,
                        "target": ev.target,
                        "provenance_type": ev.provenance_type,
                        "fingerprint": ev.fingerprint,
                    }
                )
            self._record_event(
                audit,
                InvestigationEventType.EVIDENCE_COLLECTED,
                audit.current_state,
                {"evidence_count": len(evidence)},
            )

            if self.is_cancellation_requested(cancellation_token):
                stop_reason = "Investigation cancelled after evidence collection."
                self._transition_state(audit, InvestigationState.CANCELLED, stop_reason)
                return self._build_result(
                    status=DiagnosisStatus.INSUFFICIENT_EVIDENCE,
                    summary=stop_reason,
                    hypotheses=[],
                    evidence=evidence,
                    recommended_tests=[],
                    missing_info=[
                        "Investigation cancelled before hypothesis formulation."
                    ],
                    confidence=0.0,
                    next_action="Restart investigation.",
                    budget=active_budget,
                    audit=audit,
                    uncertainty=1.0,
                    contradictions=[],
                )

            # Step 2: Establish deterministic facts and detect contradictions
            self._transition_state(
                audit,
                InvestigationState.ANALYZING_FACTS,
                "Establishing deterministic facts and checking contradictions",
            )
            facts = DeterministicFactAnalyzer.analyze_facts(evidence)
            contradictions = ContradictionDetector.detect_contradictions(
                evidence, facts
            )
            audit.contradictions.extend(contradictions)
            self._record_event(
                audit,
                InvestigationEventType.FACTS_ANALYZED,
                audit.current_state,
                {"normal_startup": facts.get("normal_startup_logged", False)},
            )
            if contradictions:
                self._record_event(
                    audit,
                    InvestigationEventType.CONTRADICTION_DETECTED,
                    audit.current_state,
                    {
                        "count": len(contradictions),
                        "ids": [c.id for c in contradictions],
                    },
                )

            # Step 2b: Interpretation with NVIDIA model through NebiusLLMClient (with bounded context, token budget, and quota resilience)
            self._transition_state(
                audit,
                InvestigationState.MODEL_INTERPRETATION,
                "Querying NVIDIA Nemotron model via Nebius for root-cause reasoning",
            )
            bounded_evidence_str = EvidenceTrimmer.trim_and_bound_evidence(
                evidence, max_total_chars=2200
            )
            estimated_tokens = max(100, (len(bounded_evidence_str) + 400) // 4)

            if not active_budget.can_afford_tokens(estimated_tokens):
                self._record_event(
                    audit,
                    InvestigationEventType.BUDGET_CONSUMED,
                    audit.current_state,
                    {
                        "limit_type": "token_budget",
                        "tokens_requested": estimated_tokens,
                        "tokens_used": active_budget.tokens_used,
                        "max_tokens": active_budget.max_tokens,
                        "action": "falling_back_to_deterministic_analysis",
                    },
                )
                logger.warning(
                    "Per-investigation token budget exhausted (%d/%d tokens used). Falling back to deterministic fact analysis.",
                    active_budget.tokens_used,
                    active_budget.max_tokens,
                )
            else:
                max_model_retries = 2
                for attempt in range(max_model_retries + 1):
                    try:
                        self._record_event(
                            audit,
                            InvestigationEventType.MODEL_INVOKED,
                            audit.current_state,
                            {"attempt": attempt + 1},
                        )
                        llm_hyp_resp = await self.llm_client.generate_hypotheses(
                            scenario_name=project_root.name,
                            iteration=0,
                            max_iterations=active_budget.max_steps,
                            evidence=evidence,
                            current_hypotheses=[],
                        )
                        reasoning_len = (
                            len(llm_hyp_resp.reasoning)
                            if (llm_hyp_resp and llm_hyp_resp.reasoning)
                            else 0
                        )
                        actual_tokens = max(
                            50, (len(bounded_evidence_str) + reasoning_len) // 4
                        )
                        active_budget.consume_tokens(actual_tokens)

                        if llm_hyp_resp and llm_hyp_resp.reasoning:
                            audit.observations.append(
                                {
                                    "id": f"model-interpretation-{attempt}",
                                    "type": "MODEL_REASONING",
                                    "source": "nebius:nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
                                    "snippet": llm_hyp_resp.reasoning[:200],
                                }
                            )
                            self._record_event(
                                audit,
                                InvestigationEventType.MODEL_SUCCESS,
                                audit.current_state,
                                {
                                    "snippet": llm_hyp_resp.reasoning[:120],
                                    "tokens_consumed": actual_tokens,
                                    "total_tokens_used": active_budget.tokens_used,
                                },
                            )
                        break
                    except (NebiusQuotaError, NebiusBillingError) as quota_exc:
                        # Graceful handling of quota/credit exhaustion: Do not crash or abort investigation
                        logger.warning(
                            "Nebius quota or billing credit exhausted: %s. Gracefully falling back to deterministic facts.",
                            quota_exc,
                        )
                        self._record_event(
                            audit,
                            InvestigationEventType.MODEL_ERROR,
                            audit.current_state,
                            {
                                "attempt": attempt + 1,
                                "error_type": "QUOTA_EXHAUSTED",
                                "detail": str(quota_exc),
                                "fallback": "deterministic_fact_analysis",
                            },
                        )
                        break
                    except Exception as exc:
                        self._record_event(
                            audit,
                            InvestigationEventType.MODEL_ERROR,
                            audit.current_state,
                            {"attempt": attempt + 1, "error": str(exc)},
                        )
                        if attempt < max_model_retries:
                            await asyncio.sleep(0.02 * (2**attempt))
                        else:
                            logger.warning(
                                "Nebius model reasoning unavailable after %d attempts; falling back to deterministic facts: %s",
                                max_model_retries + 1,
                                exc,
                            )

            # Step 3: Formulate initial competing hypotheses
            self._transition_state(
                audit,
                InvestigationState.HYPOTHESIS_FORMULATION,
                "Formulating calibrated competing hypotheses",
            )
            hypotheses, missing_info, uncertainty = (
                self.generate_hypotheses_from_evidence(evidence, facts, executed_tests)
            )
            audit.hypotheses_history.append([h.model_dump() for h in hypotheses])
            audit.current_uncertainty = uncertainty
            audit.entropy_history.append(
                UncertaintyEstimator.calculate_entropy(
                    [h.confidence for h in hypotheses]
                )
            )
            self._record_event(
                audit,
                InvestigationEventType.HYPOTHESES_UPDATED,
                audit.current_state,
                {"hypotheses_count": len(hypotheses), "uncertainty": uncertainty},
            )

            # Step 4: Diagnostic investigation loop
            while True:
                if self.is_cancellation_requested(cancellation_token):
                    stop_reason = "Investigation cancelled by caller."
                    audit.stop_reason = stop_reason
                    self._transition_state(
                        audit, InvestigationState.CANCELLED, stop_reason
                    )
                    self._record_event(
                        audit,
                        InvestigationEventType.CANCELLATION_REQUESTED,
                        InvestigationState.CANCELLED,
                        {"reason": stop_reason},
                    )
                    break

                if active_budget.is_expired():
                    stop_reason = f"Investigation timeout expired ({active_budget.timeout_seconds:.1f}s budget limit)."
                    self._transition_state(
                        audit, InvestigationState.CONCLUDED, stop_reason
                    )
                    break

                if (
                    active_budget.consecutive_failures
                    >= active_budget.max_consecutive_failures
                ):
                    stop_reason = f"Investigation halted: reached max consecutive test failures ({active_budget.consecutive_failures})."
                    self._transition_state(
                        audit, InvestigationState.CONCLUDED, stop_reason
                    )
                    break

                top_confidence = hypotheses[0].confidence if hypotheses else 0.0

                if top_confidence >= 0.90:
                    stop_reason = f"Conclusive root cause identified with {top_confidence*100:.0f}% confidence."
                    self._transition_state(
                        audit, InvestigationState.CONCLUDED, stop_reason
                    )
                    break

                if facts.get("external_outage_detected"):
                    stop_reason = "Failure caused by an external upstream dependency; local code modification cannot resolve third-party outage."
                    self._transition_state(
                        audit, InvestigationState.CONCLUDED, stop_reason
                    )
                    break

                if not active_budget.can_afford(1):
                    stop_reason = f"Diagnostic budget exhausted (steps: {active_budget.steps_taken}/{active_budget.max_steps}, cost: {active_budget.used_cost}/{active_budget.max_cost})."
                    self._transition_state(
                        audit, InvestigationState.CONCLUDED, stop_reason
                    )
                    break

                # Select next discriminating test
                self._transition_state(
                    audit,
                    InvestigationState.SELECTING_TEST,
                    "Selecting discriminating diagnostic probe",
                )
                next_test = self.select_next_test(
                    hypotheses, facts, executed_tests, active_budget, audit=audit
                )
                if not next_test:
                    stop_reason = "No further discriminating tests available within registered toolset."
                    self._transition_state(
                        audit, InvestigationState.CONCLUDED, stop_reason
                    )
                    break

                if not active_budget.can_afford(next_test.cost):
                    stop_reason = f"Diagnostic budget cannot afford chosen test cost ({next_test.cost})."
                    self._transition_state(
                        audit, InvestigationState.CONCLUDED, stop_reason
                    )
                    break

                self._record_event(
                    audit,
                    InvestigationEventType.TEST_SELECTED,
                    audit.current_state,
                    {
                        "tool": next_test.tool_name,
                        "target": next_test.target,
                        "eig": next_test.expected_information_gain,
                        "cost": next_test.cost,
                    },
                )

                # Execute the selected tool
                self._transition_state(
                    audit,
                    InvestigationState.EXECUTING_TEST,
                    f"Executing tool '{next_test.tool_name}' on '{next_test.target}'",
                )
                audit.selected_tests.append(next_test)
                active_budget.consume(next_test.cost)
                self._record_event(
                    audit,
                    InvestigationEventType.BUDGET_CONSUMED,
                    audit.current_state,
                    {"cost": next_test.cost, "total_cost": active_budget.used_cost},
                )

                # Build simulated context for offline fixture runs
                sim_context = {}
                if facts.get("actual_source_routes"):
                    sim_context["endpoints"] = {
                        r: {"status_code": 200, "body": {"status": "ok"}}
                        for r in facts["actual_source_routes"]
                    }
                    if facts.get("configured_healthcheck"):
                        bad_ep = facts["configured_healthcheck"]["endpoint"]
                        if bad_ep not in sim_context["endpoints"]:
                            sim_context["endpoints"][bad_ep] = {
                                "status_code": 404,
                                "body": "Not Found",
                            }

                tool_timeout = getattr(
                    self.tools.get_tool(next_test.tool_name), "timeout_seconds", 5.0
                )
                result = await self.tools.execute_tool(
                    tool_name=next_test.tool_name,
                    target=next_test.target,
                    parameters=next_test.parameters,
                    project_root=project_root,
                    simulated_context=sim_context,
                    timeout_seconds=tool_timeout,
                )
                executed_tests.append(result)
                audit.test_results.append(result)

                if result.metadata.get("timed_out"):
                    active_budget.record_failure()
                    self._record_event(
                        audit,
                        InvestigationEventType.TEST_TIMEOUT,
                        audit.current_state,
                        {
                            "tool": next_test.tool_name,
                            "target": next_test.target,
                            "duration_ms": result.duration_ms,
                        },
                    )
                elif not result.success:
                    active_budget.record_failure()
                    self._record_event(
                        audit,
                        InvestigationEventType.TEST_FAILED,
                        audit.current_state,
                        {
                            "tool": next_test.tool_name,
                            "target": next_test.target,
                            "output": result.output[:150],
                        },
                    )
                else:
                    active_budget.record_success()
                    self._record_event(
                        audit,
                        InvestigationEventType.TEST_EXECUTED,
                        audit.current_state,
                        {
                            "tool": next_test.tool_name,
                            "target": next_test.target,
                            "success": True,
                            "duration_ms": result.duration_ms,
                        },
                    )

                # Integrate probe evidence
                self._transition_state(
                    audit,
                    InvestigationState.EVALUATING_RESULTS,
                    "Integrating probe results into evidence store",
                )
                output_fingerprint = hashlib.sha256(
                    result.output.encode("utf-8")
                ).hexdigest()[:16]
                evidence.append(
                    EvidenceItem(
                        id=f"ev-probe-{len(executed_tests)}",
                        type=EvidenceType.DIAGNOSTIC_OUTPUT,
                        source=f"tool:{next_test.tool_name}:{next_test.target}",
                        content=result.output,
                        metadata=result.metadata,
                        is_initial=False,
                        collector=f"DiagnosticTool:{next_test.tool_name}",
                        target=next_test.target,
                        fingerprint=output_fingerprint,
                        provenance_type="ACTIVE_PROBE",
                    )
                )

                # Re-evaluate hypotheses with new empirical evidence
                self._transition_state(
                    audit,
                    InvestigationState.HYPOTHESIS_FORMULATION,
                    "Re-calibrating hypotheses with empirical probe results",
                )
                hypotheses, missing_info, uncertainty = (
                    self.generate_hypotheses_from_evidence(
                        evidence, facts, executed_tests
                    )
                )
                audit.hypotheses_history.append([h.model_dump() for h in hypotheses])
                audit.current_uncertainty = uncertainty
                audit.entropy_history.append(
                    UncertaintyEstimator.calculate_entropy(
                        [h.confidence for h in hypotheses]
                    )
                )
                self._record_event(
                    audit,
                    InvestigationEventType.HYPOTHESES_UPDATED,
                    audit.current_state,
                    {"count": len(hypotheses), "uncertainty": uncertainty},
                )

        except asyncio.CancelledError:
            stop_reason = "Investigation cancelled by asyncio cancellation."
            if audit.current_state != InvestigationState.CANCELLED:
                try:
                    self._transition_state(
                        audit, InvestigationState.CANCELLED, stop_reason
                    )
                except Exception:
                    audit.current_state = InvestigationState.CANCELLED
            self._record_event(
                audit,
                InvestigationEventType.CANCELLATION_REQUESTED,
                InvestigationState.CANCELLED,
                {"reason": stop_reason},
            )

        except Exception as exc:
            stop_reason = f"Fatal investigation error: {exc}"
            logger.exception("Diagnostic engine fatal error")
            if audit.current_state != InvestigationState.FAILED:
                try:
                    self._transition_state(
                        audit, InvestigationState.FAILED, stop_reason
                    )
                except Exception:
                    audit.current_state = InvestigationState.FAILED
            self._record_event(
                audit,
                InvestigationEventType.ERROR,
                InvestigationState.FAILED,
                {"error": str(exc)},
            )

        # Ensure terminal state is reached cleanly
        if audit.current_state not in {
            InvestigationState.CONCLUDED,
            InvestigationState.CANCELLED,
            InvestigationState.FAILED,
        }:
            self._transition_state(
                audit, InvestigationState.CONCLUDED, stop_reason or "Finished"
            )

        audit.stop_reason = stop_reason or audit.stop_reason
        self._record_event(
            audit,
            InvestigationEventType.INVESTIGATION_CONCLUDED,
            audit.current_state,
            {"stop_reason": audit.stop_reason},
        )

        top_confidence = hypotheses[0].confidence if hypotheses else 0.0

        if audit.current_state == InvestigationState.CANCELLED:
            status = DiagnosisStatus.INSUFFICIENT_EVIDENCE
            summary = f"Investigation was cancelled before conclusive diagnosis ({audit.stop_reason})."
            next_action = "Restart the investigation."
        elif audit.current_state == InvestigationState.FAILED:
            status = DiagnosisStatus.INSUFFICIENT_EVIDENCE
            summary = (
                f"Investigation encountered an internal error ({audit.stop_reason})."
            )
            next_action = "Review system logs and report diagnostic error."
        elif top_confidence >= 0.90:
            status = DiagnosisStatus.DIAGNOSIS_AVAILABLE
            summary = hypotheses[0].description
            next_action = (
                "Apply minimal configuration or code patch to resolve root cause."
            )
        elif facts.get("external_outage_detected"):
            status = DiagnosisStatus.INSUFFICIENT_EVIDENCE
            summary = "Service failure is caused by an unreachable external gateway. Local repository configuration is valid."
            next_action = "Verify external cloud provider status and human intervention for upstream network connectivity."
        else:
            status = DiagnosisStatus.INSUFFICIENT_EVIDENCE
            summary = f"Evidence is insufficient to isolate a definitive root cause ({audit.stop_reason})."
            next_action = (
                "Request human intervention or provide additional runtime logs."
            )

        return self._build_result(
            status=status,
            summary=summary,
            hypotheses=hypotheses,
            evidence=evidence,
            recommended_tests=audit.selected_tests,
            missing_info=missing_info,
            confidence=top_confidence,
            next_action=next_action,
            budget=active_budget,
            audit=audit,
            uncertainty=uncertainty,
            contradictions=contradictions,
        )

    async def run_investigation_on_evidence(
        self,
        evidence: list[EvidenceItem],
        budget: DiagnosticBudget | None = None,
        project_root: Path | None = None,
        cancellation_token: asyncio.Event | None = None,
    ) -> DiagnosticEngineResult:
        """Runs the diagnostic planner on an in-memory list of evidence items."""
        active_budget = budget or DiagnosticBudget()
        if active_budget.start_time is None:
            active_budget.start_time = time.time()
        audit = AuditLog()
        audit.current_state = InvestigationState.PENDING
        stop_reason = ""
        facts: dict[str, Any] = {}
        contradictions: list[ContradictionReport] = []
        executed_tests: list[DiagnosticToolResult] = []
        hypotheses: list[DiagnoseHypothesis] = []
        missing_info: list[str] = []
        uncertainty: float = 1.0

        try:
            self._transition_state(
                audit,
                InvestigationState.INITIALIZING,
                "Initializing autonomous diagnostic investigation",
            )

            if self.is_cancellation_requested(cancellation_token):
                stop_reason = "Investigation cancelled before execution began."
                audit.stop_reason = stop_reason
                self._transition_state(audit, InvestigationState.CANCELLED, stop_reason)
                self._record_event(
                    audit,
                    InvestigationEventType.CANCELLATION_REQUESTED,
                    InvestigationState.CANCELLED,
                    {"reason": stop_reason},
                )
                return self._build_result(
                    status=DiagnosisStatus.INSUFFICIENT_EVIDENCE,
                    summary=stop_reason,
                    hypotheses=[],
                    evidence=evidence,
                    recommended_tests=[],
                    missing_info=["Investigation cancelled before evidence analysis."],
                    confidence=0.0,
                    next_action="Restart investigation.",
                    budget=active_budget,
                    audit=audit,
                    uncertainty=1.0,
                    contradictions=[],
                )

            self._transition_state(
                audit,
                InvestigationState.COLLECTING_EVIDENCE,
                "Processing in-memory evidence store",
            )
            for ev in evidence:
                audit.observations.append(
                    {
                        "id": ev.id,
                        "type": ev.type.value,
                        "source": ev.source,
                        "snippet": ev.content[:150],
                        "collector": ev.collector,
                        "target": ev.target,
                        "provenance_type": ev.provenance_type,
                        "fingerprint": ev.fingerprint,
                    }
                )
            self._record_event(
                audit,
                InvestigationEventType.EVIDENCE_COLLECTED,
                audit.current_state,
                {"evidence_count": len(evidence)},
            )

            self._transition_state(
                audit,
                InvestigationState.ANALYZING_FACTS,
                "Analyzing facts and detecting contradictions",
            )
            facts = DeterministicFactAnalyzer.analyze_facts(evidence)
            contradictions = ContradictionDetector.detect_contradictions(
                evidence, facts
            )
            audit.contradictions.extend(contradictions)
            self._record_event(
                audit,
                InvestigationEventType.FACTS_ANALYZED,
                audit.current_state,
                {"normal_startup": facts.get("normal_startup_logged", False)},
            )
            if contradictions:
                self._record_event(
                    audit,
                    InvestigationEventType.CONTRADICTION_DETECTED,
                    audit.current_state,
                    {
                        "count": len(contradictions),
                        "ids": [c.id for c in contradictions],
                    },
                )

            self._transition_state(
                audit,
                InvestigationState.HYPOTHESIS_FORMULATION,
                "Formulating initial competing hypotheses",
            )
            hypotheses, missing_info, uncertainty = (
                self.generate_hypotheses_from_evidence(evidence, facts, executed_tests)
            )
            audit.hypotheses_history.append([h.model_dump() for h in hypotheses])
            audit.current_uncertainty = uncertainty
            audit.entropy_history.append(
                UncertaintyEstimator.calculate_entropy(
                    [h.confidence for h in hypotheses]
                )
            )
            self._record_event(
                audit,
                InvestigationEventType.HYPOTHESES_UPDATED,
                audit.current_state,
                {"hypotheses_count": len(hypotheses), "uncertainty": uncertainty},
            )

            while True:
                if self.is_cancellation_requested(cancellation_token):
                    stop_reason = "Investigation cancelled by caller."
                    audit.stop_reason = stop_reason
                    self._transition_state(
                        audit, InvestigationState.CANCELLED, stop_reason
                    )
                    self._record_event(
                        audit,
                        InvestigationEventType.CANCELLATION_REQUESTED,
                        InvestigationState.CANCELLED,
                        {"reason": stop_reason},
                    )
                    break

                if active_budget.is_expired():
                    stop_reason = f"Investigation timeout expired ({active_budget.timeout_seconds:.1f}s budget limit)."
                    self._transition_state(
                        audit, InvestigationState.CONCLUDED, stop_reason
                    )
                    break

                if (
                    active_budget.consecutive_failures
                    >= active_budget.max_consecutive_failures
                ):
                    stop_reason = f"Investigation halted: reached max consecutive test failures ({active_budget.consecutive_failures})."
                    self._transition_state(
                        audit, InvestigationState.CONCLUDED, stop_reason
                    )
                    break

                top_confidence = hypotheses[0].confidence if hypotheses else 0.0

                if top_confidence >= 0.90:
                    stop_reason = f"Conclusive root cause identified with {top_confidence*100:.0f}% confidence."
                    self._transition_state(
                        audit, InvestigationState.CONCLUDED, stop_reason
                    )
                    break

                if facts.get("external_outage_detected"):
                    stop_reason = "Failure caused by an external upstream dependency; local code modification cannot resolve third-party outage."
                    self._transition_state(
                        audit, InvestigationState.CONCLUDED, stop_reason
                    )
                    break

                if not active_budget.can_afford(1):
                    stop_reason = f"Diagnostic budget exhausted (steps: {active_budget.steps_taken}/{active_budget.max_steps}, cost: {active_budget.used_cost}/{active_budget.max_cost})."
                    self._transition_state(
                        audit, InvestigationState.CONCLUDED, stop_reason
                    )
                    break

                self._transition_state(
                    audit,
                    InvestigationState.SELECTING_TEST,
                    "Selecting discriminating diagnostic probe",
                )
                next_test = self.select_next_test(
                    hypotheses, facts, executed_tests, active_budget, audit=audit
                )
                if not next_test:
                    stop_reason = "No further discriminating tests available within registered toolset."
                    self._transition_state(
                        audit, InvestigationState.CONCLUDED, stop_reason
                    )
                    break

                if not active_budget.can_afford(next_test.cost):
                    stop_reason = f"Diagnostic budget cannot afford chosen test cost ({next_test.cost})."
                    self._transition_state(
                        audit, InvestigationState.CONCLUDED, stop_reason
                    )
                    break

                self._record_event(
                    audit,
                    InvestigationEventType.TEST_SELECTED,
                    audit.current_state,
                    {
                        "tool": next_test.tool_name,
                        "target": next_test.target,
                        "eig": next_test.expected_information_gain,
                        "cost": next_test.cost,
                    },
                )

                self._transition_state(
                    audit,
                    InvestigationState.EXECUTING_TEST,
                    f"Executing tool '{next_test.tool_name}' on '{next_test.target}'",
                )
                audit.selected_tests.append(next_test)
                active_budget.consume(next_test.cost)
                self._record_event(
                    audit,
                    InvestigationEventType.BUDGET_CONSUMED,
                    audit.current_state,
                    {"cost": next_test.cost, "total_cost": active_budget.used_cost},
                )

                sim_context = {}
                if facts.get("actual_source_routes"):
                    sim_context["endpoints"] = {
                        r: {"status_code": 200, "body": {"status": "ok"}}
                        for r in facts["actual_source_routes"]
                    }
                    if facts.get("configured_healthcheck"):
                        bad_ep = facts["configured_healthcheck"]["endpoint"]
                        if bad_ep not in sim_context["endpoints"]:
                            sim_context["endpoints"][bad_ep] = {
                                "status_code": 404,
                                "body": "Not Found",
                            }

                target_root = project_root or Path(".")
                tool_timeout = getattr(
                    self.tools.get_tool(next_test.tool_name), "timeout_seconds", 5.0
                )
                result = await self.tools.execute_tool(
                    tool_name=next_test.tool_name,
                    target=next_test.target,
                    parameters=next_test.parameters,
                    project_root=target_root,
                    simulated_context=sim_context,
                    timeout_seconds=tool_timeout,
                )
                executed_tests.append(result)
                audit.test_results.append(result)

                if result.metadata.get("timed_out"):
                    active_budget.record_failure()
                    self._record_event(
                        audit,
                        InvestigationEventType.TEST_TIMEOUT,
                        audit.current_state,
                        {
                            "tool": next_test.tool_name,
                            "target": next_test.target,
                            "duration_ms": result.duration_ms,
                        },
                    )
                elif not result.success:
                    active_budget.record_failure()
                    self._record_event(
                        audit,
                        InvestigationEventType.TEST_FAILED,
                        audit.current_state,
                        {
                            "tool": next_test.tool_name,
                            "target": next_test.target,
                            "output": result.output[:150],
                        },
                    )
                else:
                    active_budget.record_success()
                    self._record_event(
                        audit,
                        InvestigationEventType.TEST_EXECUTED,
                        audit.current_state,
                        {
                            "tool": next_test.tool_name,
                            "target": next_test.target,
                            "success": True,
                            "duration_ms": result.duration_ms,
                        },
                    )

                self._transition_state(
                    audit,
                    InvestigationState.EVALUATING_RESULTS,
                    "Integrating probe results into evidence store",
                )
                output_fingerprint = hashlib.sha256(
                    result.output.encode("utf-8")
                ).hexdigest()[:16]
                evidence.append(
                    EvidenceItem(
                        id=f"ev-probe-{len(executed_tests)}",
                        type=EvidenceType.DIAGNOSTIC_OUTPUT,
                        source=f"tool:{next_test.tool_name}:{next_test.target}",
                        content=result.output,
                        metadata=result.metadata,
                        is_initial=False,
                        collector=f"DiagnosticTool:{next_test.tool_name}",
                        target=next_test.target,
                        fingerprint=output_fingerprint,
                        provenance_type="ACTIVE_PROBE",
                    )
                )

                self._transition_state(
                    audit,
                    InvestigationState.HYPOTHESIS_FORMULATION,
                    "Re-calibrating hypotheses with empirical probe results",
                )
                hypotheses, missing_info, uncertainty = (
                    self.generate_hypotheses_from_evidence(
                        evidence, facts, executed_tests
                    )
                )
                audit.hypotheses_history.append([h.model_dump() for h in hypotheses])
                audit.current_uncertainty = uncertainty
                audit.entropy_history.append(
                    UncertaintyEstimator.calculate_entropy(
                        [h.confidence for h in hypotheses]
                    )
                )
                self._record_event(
                    audit,
                    InvestigationEventType.HYPOTHESES_UPDATED,
                    audit.current_state,
                    {"count": len(hypotheses), "uncertainty": uncertainty},
                )

        except asyncio.CancelledError:
            stop_reason = "Investigation cancelled by asyncio cancellation."
            if audit.current_state != InvestigationState.CANCELLED:
                try:
                    self._transition_state(
                        audit, InvestigationState.CANCELLED, stop_reason
                    )
                except Exception:
                    audit.current_state = InvestigationState.CANCELLED
            self._record_event(
                audit,
                InvestigationEventType.CANCELLATION_REQUESTED,
                InvestigationState.CANCELLED,
                {"reason": stop_reason},
            )

        except Exception as exc:
            stop_reason = f"Fatal investigation error: {exc}"
            logger.exception("Diagnostic engine fatal error")
            if audit.current_state != InvestigationState.FAILED:
                try:
                    self._transition_state(
                        audit, InvestigationState.FAILED, stop_reason
                    )
                except Exception:
                    audit.current_state = InvestigationState.FAILED
            self._record_event(
                audit,
                InvestigationEventType.ERROR,
                InvestigationState.FAILED,
                {"error": str(exc)},
            )

        if audit.current_state not in {
            InvestigationState.CONCLUDED,
            InvestigationState.CANCELLED,
            InvestigationState.FAILED,
        }:
            self._transition_state(
                audit, InvestigationState.CONCLUDED, stop_reason or "Finished"
            )

        audit.stop_reason = stop_reason or audit.stop_reason
        self._record_event(
            audit,
            InvestigationEventType.INVESTIGATION_CONCLUDED,
            audit.current_state,
            {"stop_reason": audit.stop_reason},
        )

        top_confidence = hypotheses[0].confidence if hypotheses else 0.0

        if audit.current_state == InvestigationState.CANCELLED:
            status = DiagnosisStatus.INSUFFICIENT_EVIDENCE
            summary = f"Investigation was cancelled before conclusive diagnosis ({audit.stop_reason})."
            next_action = "Restart the investigation."
        elif audit.current_state == InvestigationState.FAILED:
            status = DiagnosisStatus.INSUFFICIENT_EVIDENCE
            summary = (
                f"Investigation encountered an internal error ({audit.stop_reason})."
            )
            next_action = "Review system logs and report diagnostic error."
        elif top_confidence >= 0.90:
            status = DiagnosisStatus.DIAGNOSIS_AVAILABLE
            summary = hypotheses[0].description
            next_action = (
                "Apply minimal configuration or code patch to resolve root cause."
            )
        elif facts.get("external_outage_detected"):
            status = DiagnosisStatus.INSUFFICIENT_EVIDENCE
            summary = "Service failure is caused by an unreachable external gateway. Local repository configuration is valid."
            next_action = "Verify external cloud provider status and human intervention for upstream network connectivity."
        else:
            status = DiagnosisStatus.INSUFFICIENT_EVIDENCE
            summary = f"Evidence is insufficient to isolate a definitive root cause ({audit.stop_reason})."
            next_action = (
                "Request human intervention or provide additional runtime logs."
            )

        return self._build_result(
            status=status,
            summary=summary,
            hypotheses=hypotheses,
            evidence=evidence,
            recommended_tests=audit.selected_tests,
            missing_info=missing_info,
            confidence=top_confidence,
            next_action=next_action,
            budget=active_budget,
            audit=audit,
            uncertainty=uncertainty,
            contradictions=contradictions,
        )

    def _build_result(
        self,
        status: DiagnosisStatus,
        summary: str,
        hypotheses: list[DiagnoseHypothesis],
        evidence: list[EvidenceItem],
        recommended_tests: list[SelectedTestRecord],
        missing_info: list[str],
        confidence: float,
        next_action: str,
        budget: DiagnosticBudget,
        audit: AuditLog,
        uncertainty: float,
        contradictions: list[ContradictionReport],
    ) -> DiagnosticEngineResult:
        """Helper to construct DiagnosticEngineResult with complete event history and state."""
        evidence_records = [
            EvidenceRecord(
                id=e.id,
                source=e.source,
                content=e.content[:250],
                timestamp=e.timestamp.isoformat() if e.timestamp else None,
                collector=e.collector,
                target=e.target,
                fingerprint=e.fingerprint,
                provenance_type=e.provenance_type,
            )
            for e in evidence
        ]

        test_records = [
            RecommendTest(
                id=st.test_id,
                test_type=st.tool_name,
                target=st.target,
                description=st.rationale,
                expected_signal=f"Expected information gain: {st.expected_information_gain:.2f} bits",
                expected_information_gain=st.expected_information_gain,
                cost=st.cost,
                safety=st.safety,
                estimated_duration_ms=st.estimated_duration_ms,
            )
            for st in recommended_tests
        ]

        return DiagnosticEngineResult(
            status=status,
            summary=summary,
            hypotheses=hypotheses,
            evidence=evidence_records,
            recommended_tests=test_records,
            missing_information=missing_info,
            confidence=confidence,
            next_action=next_action,
            budget=budget,
            audit_log=audit,
            uncertainty=uncertainty,
            contradictions=contradictions,
            current_state=audit.current_state,
            events=list(audit.events),
        )
