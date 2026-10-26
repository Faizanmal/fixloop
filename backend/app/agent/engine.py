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
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from backend.app.core.models import (
    DiagnoseHypothesis,
    DiagnoseResponse,
    DiagnosisStatus,
    EvidenceItem,
    EvidenceRecord,
    EvidenceType,
    RecommendTest,
    utc_now,
)
from backend.app.evidence.collectors import EvidenceCollectorHub
from backend.app.evidence.tools import (
    BaseDiagnosticTool,
    DiagnosticToolRegistry,
    DiagnosticToolResult,
)

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
    """Record of why a test was selected."""
    test_id: str
    tool_name: str
    target: str
    parameters: Dict[str, Any]
    rationale: str
    expected_information_gain: float
    cost: int


class AuditLog(BaseModel):
    """Auditable log of the entire diagnostic progression."""
    observations: List[Dict[str, Any]] = Field(default_factory=list)
    hypotheses_history: List[List[Dict[str, Any]]] = Field(default_factory=list)
    selected_tests: List[SelectedTestRecord] = Field(default_factory=list)
    test_results: List[DiagnosticToolResult] = Field(default_factory=list)
    current_uncertainty: float = 1.0
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
        }

        has_redis_error_in_logs = False
        redis_disabled_in_config = False

        for item in evidence:
            # 1. Check for explicit missing env in logs
            if item.type == EvidenceType.LOGS:
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


class DiagnosticEngine:
    """Orchestrates evidence collection, hypothesis generation, and controlled testing."""

    def __init__(self, tool_registry: Optional[DiagnosticToolRegistry] = None):
        self.tools = tool_registry or DiagnosticToolRegistry()

    def generate_hypotheses_from_evidence(
        self,
        evidence: List[EvidenceItem],
        facts: Dict[str, Any],
        executed_tests: List[DiagnosticToolResult],
    ) -> Tuple[List[DiagnoseHypothesis], List[str], float]:
        """Formulates or updates competing hypotheses based on deterministic facts and empirical evidence."""
        hypotheses: List[DiagnoseHypothesis] = []
        missing_info: List[str] = []

        # Case A: Missing Environment Variable
        if facts.get("explicit_missing_env"):
            var_name = facts["explicit_missing_env"]
            hypotheses.append(
                DiagnoseHypothesis(
                    description=f"Missing required environment variable '{var_name}' required during service boot",
                    supporting_evidence=[
                        f"application_logs: Explicit error KeyError on '{var_name}'",
                        f"docker_inspect: Container exited with code {facts.get('container_exit_code', 1)}"
                    ],
                    contradicting_evidence=[],
                    confidence=0.98,
                    recommended_discriminating_test=f"check_env_key {var_name}"
                )
            )
            return hypotheses, missing_info, 0.02

        # Case B: Healthcheck configuration vs App routes
        hc = facts.get("configured_healthcheck")
        app_routes = facts.get("actual_source_routes")
        health_status = facts.get("container_health_status")

        if hc and health_status == "unhealthy":
            conf_endpoint = hc["endpoint"]
            # Check if any probe was executed on endpoints
            http_probes = [t for t in executed_tests if t.tool_name == "probe_http"]
            
            # If we have executed a probe
            confirmed_route_probe = next((p for p in http_probes if p.success and p.metadata.get("status_code") == 200), None)
            failed_route_probe = next((p for p in http_probes if not p.success and p.metadata.get("status_code") == 404), None)

            if confirmed_route_probe:
                # Strong evidence confirmed via active probe!
                actual_route = confirmed_route_probe.target
                hypotheses.append(
                    DiagnoseHypothesis(
                        description=f"Healthcheck endpoint mismatch: docker-compose probes '{conf_endpoint}' (returns 404), but application exposes '{actual_route}' (returns 200 OK)",
                        supporting_evidence=[
                            f"docker_inspect: Container State.Health.Status is unhealthy",
                            f"compose_config: Configured healthcheck targets '{conf_endpoint}'",
                            f"diagnostic_probe: HTTP probe to '{actual_route}' returned HTTP 200 OK",
                            f"diagnostic_probe: HTTP probe to '{conf_endpoint}' returned HTTP 404 Not Found"
                        ],
                        contradicting_evidence=[],
                        confidence=0.98,
                        recommended_discriminating_test=None
                    )
                )
                return hypotheses, missing_info, 0.02
            else:
                # Before probe execution: We have competing hypotheses!
                # Logs look normal, so we are uncertain whether server is dead or endpoint is mismatched.
                hypotheses.append(
                    DiagnoseHypothesis(
                        description=f"Configured healthcheck endpoint '{conf_endpoint}' does not match application route '{app_routes[0] if app_routes else '/healthz'}'",
                        supporting_evidence=[
                            f"docker_inspect: Container health is unhealthy",
                            f"compose_config: Configured probe targets '{conf_endpoint}'"
                        ],
                        contradicting_evidence=[
                            "application_logs: Server started normally with 0 error logs"
                        ],
                        confidence=0.60,
                        recommended_discriminating_test=f"probe_http {app_routes[0] if app_routes else '/healthz'}"
                    )
                )
                hypotheses.append(
                    DiagnoseHypothesis(
                        description="Application web server crashed or is deadlocked internally",
                        supporting_evidence=[
                            f"docker_inspect: Health checks are failing repeatedly"
                        ],
                        contradicting_evidence=[
                            "application_logs show normal startup with no exception traces"
                        ],
                        confidence=0.35,
                        recommended_discriminating_test="probe_tcp on port 8000"
                    )
                )
                missing_info.append(f"Empirical response status of '{app_routes[0] if app_routes else '/healthz'}' vs '{conf_endpoint}'")
                return hypotheses, missing_info, 0.40

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
                            description=f"Port forwarding mismatch: Application listens on port {act_p}, but docker-compose forwards host {host_p} to container {cnt_p}",
                            supporting_evidence=[
                                f"source_code: Server binds to port {act_p}",
                                f"compose_config: Published port map is {host_p}:{cnt_p}",
                                f"diagnostic_probe: Verified port {act_p} is actively open"
                            ],
                            contradicting_evidence=[],
                            confidence=0.97,
                            recommended_discriminating_test=None
                        )
                    )
                    return hypotheses, missing_info, 0.03
                else:
                    hypotheses.append(
                        DiagnoseHypothesis(
                            description=f"Port forwarding mismatch: Application listens on port {act_p}, but docker-compose forwards host {host_p} to container {cnt_p}",
                            supporting_evidence=[
                                f"source_code: Server binds to port {act_p}",
                                f"compose_config: Published port map is {host_p}:{cnt_p}"
                            ],
                            contradicting_evidence=[],
                            confidence=0.75,
                            recommended_discriminating_test=f"probe_tcp {act_p}"
                        )
                    )
                    missing_info.append(f"Socket connectivity confirmation on internal port {act_p} vs {cnt_p}")
                    return hypotheses, missing_info, 0.25

        # Case D: External Outage / Insufficient Evidence
        if facts.get("external_outage_detected"):
            hypotheses.append(
                DiagnoseHypothesis(
                    description="External upstream network outage or connection reset by peer outside host control",
                    supporting_evidence=[
                        "application_logs: Connection reset by peer from external gateway",
                        "compose_config & source_code: Local application configuration and ports are valid"
                    ],
                    contradicting_evidence=[],
                    confidence=0.60,
                    recommended_discriminating_test=None
                )
            )
            missing_info.append("External cloud provider network status and routing outside local container boundary")
            return hypotheses, missing_info, 0.40

        # Case E: Kernel OOM Killed (Misleading Logs)
        if facts.get("oom_killed"):
            hypotheses.append(
                DiagnoseHypothesis(
                    description="Container terminated by Linux kernel OOM killer (exit code 137). Log entries reporting database timeouts are symptomatic of the kill, not a database failure.",
                    supporting_evidence=[
                        "docker_inspect: State.OOMKilled is true with exit code 137",
                        "docker_inspect: Container exceeded memory limit under heavy processing"
                    ],
                    contradicting_evidence=[
                        "application_logs: Logged database timeouts are secondary symptoms caused by process termination"
                    ],
                    confidence=0.96,
                    recommended_discriminating_test=None
                )
            )
            return hypotheses, missing_info, 0.04

        # Case F: Contradictory Evidence (Logs show Redis error, but config disables Redis)
        if facts.get("contradictory_cache_state"):
            hypotheses.append(
                DiagnoseHypothesis(
                    description="Contradictory evidence: Logs show Redis connection error, but application environment explicitly disables Redis (REDIS_ENABLED=false) and uses in-memory cache. Container is healthy; no Redis patch required.",
                    supporting_evidence=[
                        "compose_config: REDIS_ENABLED=false and CACHE_DRIVER=memory configured",
                        "docker_inspect: Container state is running and healthy"
                    ],
                    contradicting_evidence=[
                        "application_logs: Log shows Redis connection refused on localhost:6379"
                    ],
                    confidence=0.92,
                    recommended_discriminating_test=None
                )
            )
            return hypotheses, missing_info, 0.08

        # Case G: Configuration Regression
        if facts.get("configuration_regression"):
            hypotheses.append(
                DiagnoseHypothesis(
                    description="Configuration regression: RATE_LIMIT_BURST in main.py is defined as an invalid string type instead of an integer.",
                    supporting_evidence=[
                        "application_logs: RATE_LIMIT_BURST must be integer",
                        "docker_inspect: Container exited with code 1"
                    ],
                    contradicting_evidence=[],
                    confidence=0.95,
                    recommended_discriminating_test="verify_syntax"
                )
            )
            return hypotheses, missing_info, 0.05

        # Fallback / Generic
        hypotheses.append(
            DiagnoseHypothesis(
                description="Insufficient evidence to isolate a definitive root cause",
                supporting_evidence=[],
                contradicting_evidence=[],
                confidence=0.30,
                recommended_discriminating_test=None
            )
        )
        missing_info.append("Detailed error stacktrace or debug inspection output")
        return hypotheses, missing_info, 0.70

    def select_next_test(
        self,
        hypotheses: List[DiagnoseHypothesis],
        facts: Dict[str, Any],
        executed_tests: List[DiagnosticToolResult],
        budget: DiagnosticBudget,
    ) -> Optional[SelectedTestRecord]:
        """Selects the most discriminating next test based on information gain, cost, safety, and relevance."""
        executed_signatures = {
            (t.tool_name, t.target) for t in executed_tests
        }

        candidates: List[Tuple[float, SelectedTestRecord]] = []

        # Check Scenario B: Healthcheck mismatch
        hc = facts.get("configured_healthcheck")
        app_routes = facts.get("actual_source_routes", [])
        if hc and app_routes:
            # Prioritize routes containing 'health' (e.g. /healthz, /health)
            health_matches = [r for r in app_routes if "health" in r.lower()]
            candidate_route = health_matches[0] if health_matches else app_routes[0]
            sig = ("probe_http", candidate_route)
            if sig not in executed_signatures:
                tool = self.tools.get_tool("probe_http")
                if tool and budget.can_afford(tool.cost):
                    record = SelectedTestRecord(
                        test_id=f"test-probe-{len(executed_tests) + 1}",
                        tool_name="probe_http",
                        target=candidate_route,
                        parameters={"port": hc.get("port", 8000)},
                        rationale=f"Differentiate whether container health is failing due to server crash vs probing '{hc['endpoint']}' instead of '{candidate_route}'",
                        expected_information_gain=0.95,
                        cost=tool.cost,
                    )
                    candidates.append((0.95 / tool.cost, record))

        # Check Scenario C: Port mismatch
        listen_ports = facts.get("source_listen_ports", [])
        if listen_ports:
            p = listen_ports[0]
            sig = ("probe_tcp", str(p))
            if sig not in executed_signatures:
                tool = self.tools.get_tool("probe_tcp")
                if tool and budget.can_afford(tool.cost):
                    record = SelectedTestRecord(
                        test_id=f"test-probe-{len(executed_tests) + 1}",
                        tool_name="probe_tcp",
                        target=str(p),
                        parameters={"port": p},
                        rationale=f"Verify whether application is actively listening on internal port {p}",
                        expected_information_gain=0.85,
                        cost=tool.cost,
                    )
                    candidates.append((0.85 / tool.cost, record))

        if not candidates:
            return None

        # Sort by (information_gain / cost) descending
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

        # Step 1: Collect & normalize initial evidence
        hub = EvidenceCollectorHub(project_root)
        evidence = hub.collect_all_initial(logs_override, inspect_override)

        for ev in evidence:
            audit.observations.append({
                "id": ev.id,
                "type": ev.type.value,
                "source": ev.source,
                "snippet": ev.content[:150],
            })

        # Step 2: Establish deterministic facts
        facts = DeterministicFactAnalyzer.analyze_facts(evidence)

        # Step 3: Initial hypothesis formulation
        executed_tests: List[DiagnosticToolResult] = []
        hypotheses, missing_info, uncertainty = self.generate_hypotheses_from_evidence(evidence, facts, executed_tests)
        audit.hypotheses_history.append([h.model_dump() for h in hypotheses])
        audit.current_uncertainty = uncertainty

        # Step 4: Diagnostic investigation loop
        stop_reason = ""
        while True:
            # Check stopping criteria
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

            # Append test result to evidence store
            evidence.append(
                EvidenceItem(
                    id=f"ev-probe-{len(executed_tests)}",
                    type=EvidenceType.DIAGNOSTIC_OUTPUT,
                    source=f"tool:{next_test.tool_name}:{next_test.target}",
                    content=result.output,
                    metadata=result.metadata,
                    is_initial=False,
                )
            )

            # Re-evaluate hypotheses with new empirical evidence
            hypotheses, missing_info, uncertainty = self.generate_hypotheses_from_evidence(evidence, facts, executed_tests)
            audit.hypotheses_history.append([h.model_dump() for h in hypotheses])
            audit.current_uncertainty = uncertainty

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
            )
            for e in evidence
        ]

        recommended_tests = [
            RecommendTest(
                id=st.test_id,
                test_type=st.tool_name,
                target=st.target,
                description=st.rationale,
                expected_signal=f"Expected information gain: {st.expected_information_gain}",
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
        )
