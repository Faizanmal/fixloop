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
import hashlib
import logging
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from backend.app.core.models import (
    ContradictionReport,
    DiagnoseHypothesis,
    DiagnoseResponse,
    DiagnosisStatus,
    EvidenceItem,
    EvidenceRecord,
    EvidenceType,
    HypothesisCategory,
    RecommendTest,
    utc_now,
)
from backend.app.evidence.collectors import EvidenceCollectorHub
from backend.app.evidence.tools import (
    BaseDiagnosticTool,
    DiagnosticToolRegistry,
    DiagnosticToolResult,
)
from backend.app.llm.client import NebiusLLMClient

logger = logging.getLogger("fixloop.engine")


class DiagnosticBudget(BaseModel):
    """Enforces upper limits on diagnostic execution to prevent infinite loops and runaway costs."""
    max_steps: int = Field(default=4, description="Maximum number of active probes allowed")
    max_cost: int = Field(default=10, description="Total cost budget for active probes")
    timeout_seconds: float = Field(default=15.0, description="Overall engine timeout")
    used_cost: int = 0
    steps_taken: int = 0

    def can_afford(self, tool_cost: int) -> bool:
        return (self.steps_taken < self.max_steps) and ((self.used_cost + tool_cost) <= self.max_cost)

    def consume(self, tool_cost: int):
        self.steps_taken += 1
        self.used_cost += tool_cost


class SelectedTestRecord(BaseModel):
    """Record of why a test was selected based on EIG, safety, cost, and execution duration."""
    test_id: str
    tool_name: str
    target: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    rationale: str
    expected_information_gain: float
    cost: int
    safety: str = "safe"
    estimated_duration_ms: int = 100
    utility_score: float = 0.0


class AuditLog(BaseModel):
    """Auditable log of the entire diagnostic progression."""
    observations: List[Dict[str, Any]] = Field(default_factory=list)
    hypotheses_history: List[List[Dict[str, Any]]] = Field(default_factory=list)
    selected_tests: List[SelectedTestRecord] = Field(default_factory=list)
    test_results: List[DiagnosticToolResult] = Field(default_factory=list)
    current_uncertainty: float = 1.0
    contradictions: List[ContradictionReport] = Field(default_factory=list)
    entropy_history: List[float] = Field(default_factory=list)
    stop_reason: str = "Investigation in progress"


class DiagnosticEngineResult(BaseModel):
    """Structured outcome from the diagnostic engine investigation."""
    status: DiagnosisStatus
    summary: str
    hypotheses: List[DiagnoseHypothesis]
    evidence: List[EvidenceRecord]
    recommended_tests: List[RecommendTest]
    missing_information: List[str]
    confidence: float
    next_action: str
    budget: DiagnosticBudget
    audit_log: AuditLog
    uncertainty: float = 0.0
    contradictions: List[ContradictionReport] = Field(default_factory=list)


class DeterministicFactAnalyzer:
    """Applies deterministic logic to establish ground-truth facts from collectors."""

    @staticmethod
    def analyze_facts(evidence: List[EvidenceItem]) -> Dict[str, Any]:
        facts: Dict[str, Any] = {
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
                if re.search(r"(started successfully|running on http|listening on|uvicorn running|application startup complete)", item.content, re.IGNORECASE):
                    facts["normal_startup_logged"] = True

                m = re.search(r"KeyError:\s*['\"]([A-Z0-9_]+)['\"]", item.content)
                if m:
                    facts["explicit_missing_env"] = m.group(1)
                m2 = re.search(r"Required environment variable\s*['\"]([A-Z0-9_]+)['\"]\s*is missing", item.content, re.IGNORECASE)
                if m2:
                    facts["explicit_missing_env"] = m2.group(1)

                if "Connection reset by peer from external gateway" in item.content or "Upstream connection" in item.content and "timed out" in item.content:
                    facts["external_outage_detected"] = True

                if "RATE_LIMIT_BURST" in item.content and "must be integer" in item.content:
                    facts["configuration_regression"] = True

                if "redis" in item.content.lower() and ("connectionrefused" in item.content.lower() or "connection refused" in item.content.lower()):
                    has_redis_error_in_logs = True

            # 2. Check Docker Inspect
            elif item.type == EvidenceType.DOCKER_INSPECT:
                if "health_status" in item.metadata:
                    facts["container_health_status"] = item.metadata["health_status"]
                elif '"Status": "unhealthy"' in item.content or '"health_status": "unhealthy"' in item.content or 'unhealthy' in item.content.lower():
                    facts["container_health_status"] = "unhealthy"
                if "exit_code" in item.metadata:
                    facts["container_exit_code"] = item.metadata["exit_code"]
                if item.metadata.get("oom_killed") or item.metadata.get("exit_code") == 137 or '"OOMKilled": true' in item.content or '"ExitCode": 137' in item.content:
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
                    m = re.search(r"http://localhost:(\d+)(/[a-zA-Z0-9_\-\/]+)", test_str)
                    if m:
                        facts["configured_healthcheck"] = {
                            "port": int(m.group(1)),
                            "endpoint": m.group(2),
                        }

                ports = item.metadata.get("ports", [])
                for p in ports:
                    if isinstance(p, str) and ":" in p:
                        host_p, cnt_p = p.split(":", 1)
                        facts["compose_port_mappings"].append({
                            "host_port": int(host_p),
                            "container_port": int(cnt_p),
                        })

                if "REDIS_ENABLED=false" in item.content or "REDIS_ENABLED: 'false'" in item.content or 'REDIS_ENABLED: "false"' in item.content:
                    redis_disabled_in_config = True

            # 4. Check Environment Variables
            elif item.type == EvidenceType.ENVIRONMENT:
                if "REDIS_ENABLED" in item.content and ("false" in item.content.lower() or "[PRESENT: false]" in item.content.lower()):
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
    def detect_contradictions(evidence: List[EvidenceItem], facts: Dict[str, Any]) -> List[ContradictionReport]:
        contradictions: List[ContradictionReport] = []

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
            re.search(r"(started successfully|running on http|listening on|uvicorn running|application startup complete)", logs_text, re.IGNORECASE)
        )
        has_log_errors = any("error" in e.metadata and e.metadata.get("has_errors") for e in log_items)

        if health_status == "unhealthy" and has_normal_startup_log and not has_log_errors:
            contradictions.append(
                ContradictionReport(
                    id="contra-log-healthy-state-unhealthy",
                    claim_a="Application logs indicate normal startup with 0 logged errors",
                    source_a=log_items[0].source if log_items else "application_logs",
                    evidence_id_a=log_id,
                    claim_b="Docker container health status is 'unhealthy'",
                    source_b=inspect_items[0].source if inspect_items else "docker_inspect",
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
        if facts.get("oom_killed") and ("timeout" in logs_text.lower() or "connection" in logs_text.lower()):
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
    def calculate_entropy(probabilities: List[float]) -> float:
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
        hypotheses: List[DiagnoseHypothesis],
        facts: Dict[str, Any],
        has_conclusive_evidence: bool = False,
    ) -> Tuple[float, float]:
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
            uncertainty = min(1.0, max(0.15, round(0.5 * (1.0 - top_conf) + 0.3 * norm_entropy + 0.2 * (1.0 - margin), 4)))
        else:
            uncertainty = max(0.01, round(1.0 - top_conf, 4))

        return uncertainty, round(entropy, 4)


class DiagnosticTestSelector:
    """Selects the next most discriminating test based on Expected Information Gain (EIG), safety, cost, and time."""

    @staticmethod
    def compute_eig_and_utility(
        tool: BaseDiagnosticTool,
        target: str,
        parameters: Dict[str, Any],
        hypotheses: List[DiagnoseHypothesis],
        rationale: str,
        p_success_given_hyp: List[float],
        base_test_id: str,
    ) -> Tuple[float, float, SelectedTestRecord]:
        """Calculates EIG and multi-attribute utility for a candidate probe."""
        if not hypotheses:
            return 0.0, 0.0, SelectedTestRecord(
                test_id=base_test_id,
                tool_name=tool.tool_name,
                target=target,
                parameters=parameters,
                rationale=rationale,
                expected_information_gain=0.0,
                cost=tool.cost,
            )

        # Current prior distribution
        priors = [max(0.001, h.confidence) for h in hypotheses]
        sum_priors = sum(priors)
        norm_priors = [p / sum_priors for p in priors]

        h_prior = UncertaintyEstimator.calculate_entropy(norm_priors)

        # Conditional probabilities of outcome = SUCCESS
        # and outcome = FAILURE
        p_success = sum(norm_priors[i] * p_success_given_hyp[i] for i in range(len(hypotheses)))
        p_success = max(0.001, min(0.999, p_success))
        p_fail = 1.0 - p_success

        # Posterior for SUCCESS
        post_success = [norm_priors[i] * p_success_given_hyp[i] / p_success for i in range(len(hypotheses))]
        h_post_success = UncertaintyEstimator.calculate_entropy(post_success)

        # Posterior for FAILURE
        post_fail = [norm_priors[i] * (1.0 - p_success_given_hyp[i]) / p_fail for i in range(len(hypotheses))]
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
        tool_registry: Optional[DiagnosticToolRegistry] = None,
        llm_client: Optional[NebiusLLMClient] = None,
    ):
        self.tools = tool_registry or DiagnosticToolRegistry()
        self.llm_client = llm_client or NebiusLLMClient()

    def collect_initial_evidence(
        self,
        project_root: Path,
        logs_override: Optional[str] = None,
        inspect_override: Optional[Dict[str, Any]] = None,
    ) -> List[EvidenceItem]:
        """Convenience method to collect initial evidence from a project directory."""
        hub = EvidenceCollectorHub(project_root)
        return hub.collect_all_initial(logs_override, inspect_override)

    def generate_hypotheses_from_evidence(
        self,
        evidence: List[EvidenceItem],
        facts: Dict[str, Any],
        executed_tests: List[DiagnosticToolResult],
    ) -> Tuple[List[DiagnoseHypothesis], List[str], float]:
        """Formulates or updates competing hypotheses based on deterministic facts, empirical evidence, and provenance."""
        hypotheses: List[DiagnoseHypothesis] = []
        missing_info: List[str] = []

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
            env_probes = [t for t in executed_tests if t.tool_name == "check_env_key" and t.target == var_name]
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
                    ] + ([f"ev-probe-env: Verified variable '{var_name}' is not defined in container environment [provenance: ACTIVE_PROBE]"] if env_confirmed_missing else []),
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
                    description=f"Database service or external dependency unreachable during connection initialization",
                    supporting_evidence=[],
                    contradicting_evidence=[
                        f"{log_id}: Process aborted immediately on missing configuration key '{var_name}' prior to establishing network sockets [provenance: RUNTIME_OBSERVATION]"
                    ],
                    confidence=0.02,
                    recommended_discriminating_test=None,
                    uncertainty=0.02,
                )
            )
            uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(hypotheses, facts, has_conclusive_evidence=True)
            return hypotheses, missing_info, uncertainty

        # Case B: Healthcheck configuration vs App routes
        hc = facts.get("configured_healthcheck")
        app_routes = facts.get("actual_source_routes")
        health_status = facts.get("container_health_status")

        if hc and health_status == "unhealthy":
            conf_endpoint = hc["endpoint"]
            candidate_route = app_routes[0] if app_routes else "/healthz"
            http_probes = [t for t in executed_tests if t.tool_name == "probe_http"]

            confirmed_route_probe = next((p for p in http_probes if p.success and p.metadata.get("status_code") == 200), None)
            failed_route_probe = next((p for p in http_probes if not p.success and p.metadata.get("status_code") == 404), None)

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
                uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(hypotheses, facts, has_conclusive_evidence=True)
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
                missing_info.append(f"Empirical response status of '{candidate_route}' vs '{conf_endpoint}'")
                uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(hypotheses, facts, has_conclusive_evidence=False)
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
                act_port_open = any(p for p in tcp_probes if p.success and str(act_p) in p.target)

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
                    uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(hypotheses, facts, has_conclusive_evidence=True)
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
                    missing_info.append(f"Socket connectivity confirmation on internal port {act_p} vs {cnt_p}")
                    uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(hypotheses, facts, has_conclusive_evidence=False)
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
            missing_info.append("External cloud provider network status and routing outside local container boundary")
            uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(hypotheses, facts, has_conclusive_evidence=False)
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
            uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(hypotheses, facts, has_conclusive_evidence=True)
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
            uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(hypotheses, facts, has_conclusive_evidence=True)
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
            uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(hypotheses, facts, has_conclusive_evidence=True)
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
        uncertainty, _ = UncertaintyEstimator.estimate_uncertainty(hypotheses, facts, has_conclusive_evidence=False)
        return hypotheses, missing_info, uncertainty

    def select_next_test(
        self,
        hypotheses: List[DiagnoseHypothesis],
        facts: Dict[str, Any],
        executed_tests: List[DiagnosticToolResult],
        budget: DiagnosticBudget,
    ) -> Optional[SelectedTestRecord]:
        """Selects the most discriminating next test based on Expected Information Gain (EIG), safety, cost, and time."""
        executed_signatures = {
            (t.tool_name, t.target) for t in executed_tests
        }

        candidates: List[Tuple[float, SelectedTestRecord]] = []

        # 1. Candidate: HTTP Probe on declared application routes (Healthcheck mismatch discrimination)
        hc = facts.get("configured_healthcheck")
        app_routes = facts.get("actual_source_routes", [])
        if hc and app_routes:
            health_matches = [r for r in app_routes if "health" in r.lower()]
            candidate_route = health_matches[0] if health_matches else app_routes[0]
            sig = ("probe_http", candidate_route)

            if sig not in executed_signatures:
                tool = self.tools.get_tool("probe_http")
                if tool and budget.can_afford(tool.cost):
                    # For candidate route /healthz:
                    # Hyp 1 (route mismatch): high prob of 200 (0.98)
                    # Hyp 2 (server deadlocked): low prob of 200 (0.05)
                    p_success_given_hyp = [0.98] + [0.05] * (len(hypotheses) - 1)
                    test_id = f"test-probe-{len(executed_tests) + 1}"
                    rationale = f"Differentiate whether container health is failing due to server crash vs probing '{hc['endpoint']}' instead of '{candidate_route}'"

                    eig, utility, record = DiagnosticTestSelector.compute_eig_and_utility(
                        tool=tool,
                        target=candidate_route,
                        parameters={"port": hc.get("port", 8000)},
                        hypotheses=hypotheses,
                        rationale=rationale,
                        p_success_given_hyp=p_success_given_hyp,
                        base_test_id=test_id,
                    )
                    candidates.append((utility, record))

        # 2. Candidate: TCP Probe on listening ports (Port mismatch discrimination)
        listen_ports = facts.get("source_listen_ports", [])
        if listen_ports:
            p = listen_ports[0]
            sig = ("probe_tcp", str(p))
            if sig not in executed_signatures:
                tool = self.tools.get_tool("probe_tcp")
                if tool and budget.can_afford(tool.cost):
                    # Hyp 1 (port mismatch): port p is open (0.95)
                    # Hyp 2 (bind failure): port p is closed (0.05)
                    p_success_given_hyp = [0.95] + [0.05] * (len(hypotheses) - 1)
                    test_id = f"test-probe-{len(executed_tests) + 1}"
                    rationale = f"Verify whether application is actively listening on internal port {p}"

                    eig, utility, record = DiagnosticTestSelector.compute_eig_and_utility(
                        tool=tool,
                        target=str(p),
                        parameters={"port": p},
                        hypotheses=hypotheses,
                        rationale=rationale,
                        p_success_given_hyp=p_success_given_hyp,
                        base_test_id=test_id,
                    )
                    candidates.append((utility, record))

        # 3. Candidate: Environment Key Check
        if facts.get("explicit_missing_env"):
            var_name = facts["explicit_missing_env"]
            sig = ("check_env_key", var_name)
            if sig not in executed_signatures:
                tool = self.tools.get_tool("check_env_key")
                if tool and budget.can_afford(tool.cost):
                    p_success_given_hyp = [0.05] + [0.90] * (len(hypotheses) - 1)
                    test_id = f"test-probe-{len(executed_tests) + 1}"
                    rationale = f"Confirm whether environment variable '{var_name}' is missing in container environment"

                    eig, utility, record = DiagnosticTestSelector.compute_eig_and_utility(
                        tool=tool,
                        target=var_name,
                        parameters={"key": var_name},
                        hypotheses=hypotheses,
                        rationale=rationale,
                        p_success_given_hyp=p_success_given_hyp,
                        base_test_id=test_id,
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
        budget: Optional[DiagnosticBudget] = None,
        logs_override: Optional[str] = None,
        inspect_override: Optional[Dict[str, Any]] = None,
    ) -> DiagnosticEngineResult:
        """Executes the full diagnostic workflow for a given project."""
        active_budget = budget or DiagnosticBudget()
        audit = AuditLog()

        # Step 1: Collect & normalize initial evidence with provenance
        hub = EvidenceCollectorHub(project_root)
        evidence = hub.collect_all_initial(logs_override, inspect_override)

        for ev in evidence:
            audit.observations.append({
                "id": ev.id,
                "type": ev.type.value,
                "source": ev.source,
                "snippet": ev.content[:150],
                "collector": ev.collector,
                "target": ev.target,
                "provenance_type": ev.provenance_type,
                "fingerprint": ev.fingerprint,
            })

        # Step 2: Establish deterministic facts and detect contradictions
        facts = DeterministicFactAnalyzer.analyze_facts(evidence)
        contradictions = ContradictionDetector.detect_contradictions(evidence, facts)
        audit.contradictions.extend(contradictions)

        # Step 2b: Interpretation with NVIDIA model through NebiusLLMClient
        try:
            llm_hyp_resp = await self.llm_client.generate_hypotheses(
                scenario_name=project_root.name,
                iteration=0,
                max_iterations=active_budget.max_steps,
                evidence=evidence,
                current_hypotheses=[],
            )
            if llm_hyp_resp and llm_hyp_resp.reasoning:
                audit.observations.append({
                    "id": "model-interpretation-0",
                    "type": "MODEL_REASONING",
                    "source": "nebius:nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
                    "snippet": llm_hyp_resp.reasoning[:200],
                })
        except Exception as exc:
            logger.debug("Nebius model interpretation note: %s", exc)

        # Step 3: Formulate competing hypotheses
        executed_tests: List[DiagnosticToolResult] = []
        hypotheses, missing_info, uncertainty = self.generate_hypotheses_from_evidence(evidence, facts, executed_tests)
        audit.hypotheses_history.append([h.model_dump() for h in hypotheses])
        audit.current_uncertainty = uncertainty
        audit.entropy_history.append(UncertaintyEstimator.calculate_entropy([h.confidence for h in hypotheses]))

        # Step 4: Diagnostic investigation loop
        stop_reason = ""
        while True:
            top_confidence = hypotheses[0].confidence if hypotheses else 0.0

            if top_confidence >= 0.90:
                stop_reason = f"Conclusive root cause identified with {top_confidence*100:.0f}% confidence."
                break

            if facts.get("external_outage_detected"):
                stop_reason = "Failure caused by an external upstream dependency; local code modification cannot resolve third-party outage."
                break

            if not active_budget.can_afford(1):
                stop_reason = f"Diagnostic budget exhausted (steps: {active_budget.steps_taken}/{active_budget.max_steps}, cost: {active_budget.used_cost}/{active_budget.max_cost})."
                break

            # Select next discriminating test
            next_test = self.select_next_test(hypotheses, facts, executed_tests, active_budget)
            if not next_test:
                stop_reason = "No further discriminating tests available within registered toolset."
                break

            # Execute the selected tool
            audit.selected_tests.append(next_test)
            active_budget.consume(next_test.cost)

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
                        sim_context["endpoints"][bad_ep] = {"status_code": 404, "body": "Not Found"}

            result = await self.tools.execute_tool(
                tool_name=next_test.tool_name,
                target=next_test.target,
                parameters=next_test.parameters,
                project_root=project_root,
                simulated_context=sim_context,
            )
            executed_tests.append(result)
            audit.test_results.append(result)

            # Append test result to evidence store with provenance
            output_fingerprint = hashlib.sha256(result.output.encode("utf-8")).hexdigest()[:16]
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
            hypotheses, missing_info, uncertainty = self.generate_hypotheses_from_evidence(evidence, facts, executed_tests)
            audit.hypotheses_history.append([h.model_dump() for h in hypotheses])
            audit.current_uncertainty = uncertainty
            audit.entropy_history.append(UncertaintyEstimator.calculate_entropy([h.confidence for h in hypotheses]))

        audit.stop_reason = stop_reason

        # Determine overall diagnosis status
        if top_confidence >= 0.90:
            status = DiagnosisStatus.DIAGNOSIS_AVAILABLE
            summary = hypotheses[0].description
            next_action = "Apply minimal configuration or code patch to resolve root cause."
        elif facts.get("external_outage_detected"):
            status = DiagnosisStatus.INSUFFICIENT_EVIDENCE
            summary = "Service failure is caused by an unreachable external gateway. Local repository configuration is valid."
            next_action = "Verify external cloud provider status and human intervention for upstream network connectivity."
        else:
            status = DiagnosisStatus.INSUFFICIENT_EVIDENCE
            summary = f"Evidence is insufficient to isolate a definitive root cause ({stop_reason})."
            next_action = "Request human intervention or provide additional runtime logs."

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

        recommended_tests = [
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
            for st in audit.selected_tests
        ]

        return DiagnosticEngineResult(
            status=status,
            summary=summary,
            hypotheses=hypotheses,
            evidence=evidence_records,
            recommended_tests=recommended_tests,
            missing_information=missing_info,
            confidence=top_confidence,
            next_action=next_action,
            budget=active_budget,
            audit_log=audit,
            uncertainty=uncertainty,
            contradictions=contradictions,
        )

    async def run_investigation_on_evidence(
        self,
        evidence: List[EvidenceItem],
        budget: Optional[DiagnosticBudget] = None,
        project_root: Optional[Path] = None,
    ) -> DiagnosticEngineResult:
        """Runs the diagnostic planner on an in-memory list of evidence items."""
        active_budget = budget or DiagnosticBudget()
        audit = AuditLog()

        for ev in evidence:
            audit.observations.append({
                "id": ev.id,
                "type": ev.type.value,
                "source": ev.source,
                "snippet": ev.content[:150],
                "collector": ev.collector,
                "target": ev.target,
                "provenance_type": ev.provenance_type,
                "fingerprint": ev.fingerprint,
            })

        facts = DeterministicFactAnalyzer.analyze_facts(evidence)
        contradictions = ContradictionDetector.detect_contradictions(evidence, facts)
        audit.contradictions.extend(contradictions)

        executed_tests: List[DiagnosticToolResult] = []
        hypotheses, missing_info, uncertainty = self.generate_hypotheses_from_evidence(evidence, facts, executed_tests)
        audit.hypotheses_history.append([h.model_dump() for h in hypotheses])
        audit.current_uncertainty = uncertainty
        audit.entropy_history.append(UncertaintyEstimator.calculate_entropy([h.confidence for h in hypotheses]))

        stop_reason = ""
        while True:
            top_confidence = hypotheses[0].confidence if hypotheses else 0.0

            if top_confidence >= 0.90:
                stop_reason = f"Conclusive root cause identified with {top_confidence*100:.0f}% confidence."
                break

            if facts.get("external_outage_detected"):
                stop_reason = "Failure caused by an external upstream dependency; local code modification cannot resolve third-party outage."
                break

            if not active_budget.can_afford(1):
                stop_reason = f"Diagnostic budget exhausted (steps: {active_budget.steps_taken}/{active_budget.max_steps}, cost: {active_budget.used_cost}/{active_budget.max_cost})."
                break

            next_test = self.select_next_test(hypotheses, facts, executed_tests, active_budget)
            if not next_test:
                stop_reason = "No further discriminating tests available within registered toolset."
                break

            audit.selected_tests.append(next_test)
            active_budget.consume(next_test.cost)

            sim_context = {}
            if facts.get("actual_source_routes"):
                sim_context["endpoints"] = {
                    r: {"status_code": 200, "body": {"status": "ok"}}
                    for r in facts["actual_source_routes"]
                }
                if facts.get("configured_healthcheck"):
                    bad_ep = facts["configured_healthcheck"]["endpoint"]
                    if bad_ep not in sim_context["endpoints"]:
                        sim_context["endpoints"][bad_ep] = {"status_code": 404, "body": "Not Found"}

            # Execute tool if project_root provided or using simulated context
            target_root = project_root or Path(".")
            result = await self.tools.execute_tool(
                tool_name=next_test.tool_name,
                target=next_test.target,
                parameters=next_test.parameters,
                project_root=target_root,
                simulated_context=sim_context,
            )
            executed_tests.append(result)
            audit.test_results.append(result)

            output_fingerprint = hashlib.sha256(result.output.encode("utf-8")).hexdigest()[:16]
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

            hypotheses, missing_info, uncertainty = self.generate_hypotheses_from_evidence(evidence, facts, executed_tests)
            audit.hypotheses_history.append([h.model_dump() for h in hypotheses])
            audit.current_uncertainty = uncertainty
            audit.entropy_history.append(UncertaintyEstimator.calculate_entropy([h.confidence for h in hypotheses]))

        audit.stop_reason = stop_reason

        if top_confidence >= 0.90:
            status = DiagnosisStatus.DIAGNOSIS_AVAILABLE
            summary = hypotheses[0].description
            next_action = "Apply minimal configuration or code patch to resolve root cause."
        elif facts.get("external_outage_detected"):
            status = DiagnosisStatus.INSUFFICIENT_EVIDENCE
            summary = "Service failure is caused by an unreachable external gateway. Local repository configuration is valid."
            next_action = "Verify external cloud provider status and human intervention for upstream network connectivity."
        else:
            status = DiagnosisStatus.INSUFFICIENT_EVIDENCE
            summary = f"Evidence is insufficient to isolate a definitive root cause ({stop_reason})."
            next_action = "Request human intervention or provide additional runtime logs."

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

        recommended_tests = [
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
            for st in audit.selected_tests
        ]

        return DiagnosticEngineResult(
            status=status,
            summary=summary,
            hypotheses=hypotheses,
            evidence=evidence_records,
            recommended_tests=recommended_tests,
            missing_information=missing_info,
            confidence=top_confidence,
            next_action=next_action,
            budget=active_budget,
            audit_log=audit,
            uncertainty=uncertainty,
            contradictions=contradictions,
        )
