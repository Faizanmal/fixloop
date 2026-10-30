"""Mock LLM Provider for offline testing, CI suites, and fallback development.

Returns deterministic, evidence-aligned diagnostic hypotheses and patches
for the 4 benchmark scenarios when live Nebius Token Factory inference is not active.
"""

from typing import Any

from backend.app.core.models import (
    DiagnoseHypothesis,
    DiagnoseRequest,
    DiagnoseResponse,
    DiagnosisStatus,
    DiagnosticAction,
    DiagnosticProbeType,
    EvidenceRecord,
    Hypothesis,
    HypothesisCategory,
    LLMHypothesisResponse,
    LLMPatchResponse,
    RecommendTest,
)
from backend.app.data.sample_reports import MOCK_NEBIUS_HEALTHCHECK_RESPONSE


class MockLLMProvider:
    """Provides deterministic responses for offline verification of the agent loop."""

    @classmethod
    def get_hypotheses_for_scenario(
        cls, scenario_name: str, iteration: int, collected_evidence: list[Any]
    ) -> LLMHypothesisResponse:
        scenario = scenario_name.lower()

        if "healthcheck" in scenario:
            if iteration == 0:
                # Initial logs are vague (container unhealthy)
                return LLMHypothesisResponse(
                    reasoning="Container exited or marked unhealthy. Initial logs show server started, but Docker healthcheck failed.",
                    hypotheses=[
                        Hypothesis(
                            id="hyp-1",
                            title="Mismatched healthcheck endpoint path",
                            description="The web server exposes '/healthz' but Dockerfile/compose probes '/health'",
                            category=HypothesisCategory.HEALTHCHECK_MISCONFIG,
                            confidence_score=0.60,
                            suggested_probe_rationale="Probe the server directly via HTTP GET on /healthz vs /health",
                        ),
                        Hypothesis(
                            id="hyp-2",
                            title="Server failed to bind to 0.0.0.0",
                            description="Server might be listening on 127.0.0.1 inside container or wrong port",
                            category=HypothesisCategory.PORT_MISMATCH,
                            confidence_score=0.35,
                            suggested_probe_rationale="Check container port bindings and TCP connectivity",
                        ),
                    ],
                    needs_diagnostic_probe=True,
                    recommended_probe=DiagnosticAction(
                        id="probe-1",
                        probe_type=DiagnosticProbeType.HTTP_GET,
                        target="/healthz",
                        parameters={"port": 8000},
                        rationale="Distinguish whether server is responsive at /healthz vs /health",
                    ),
                    is_evidence_sufficient=False,
                )
            else:
                # Diagnostic probe confirmed /healthz returns 200, /health returned 404
                return LLMHypothesisResponse(
                    reasoning="Diagnostic test confirmed HTTP 200 on /healthz and 404 on /health. Root cause confirmed.",
                    hypotheses=[
                        Hypothesis(
                            id="hyp-1",
                            title="Mismatched healthcheck endpoint path",
                            description="Application exposes /healthz; docker-compose.yml mistakenly probes /health",
                            category=HypothesisCategory.HEALTHCHECK_MISCONFIG,
                            confidence_score=0.98,
                            supporting_evidence_ids=["probe-1"],
                        )
                    ],
                    needs_diagnostic_probe=False,
                    is_evidence_sufficient=True,
                )

        elif "port" in scenario:
            if iteration == 0:
                return LLMHypothesisResponse(
                    reasoning="Port mismatch suspected between compose host:container port mapping and actual app listen port.",
                    hypotheses=[
                        Hypothesis(
                            id="hyp-port-1",
                            title="Internal port mismatch in docker-compose",
                            description="App listens on port 8000, but compose mapped host:5000",
                            category=HypothesisCategory.PORT_MISMATCH,
                            confidence_score=0.70,
                        )
                    ],
                    needs_diagnostic_probe=True,
                    recommended_probe=DiagnosticAction(
                        id="probe-port-1",
                        probe_type=DiagnosticProbeType.TCP_CONNECT,
                        target="127.0.0.1",
                        parameters={"port": 8000},
                        rationale="Verify which port is actively open inside the container",
                    ),
                    is_evidence_sufficient=False,
                )
            else:
                return LLMHypothesisResponse(
                    reasoning="Probe confirmed port 8000 is open, whereas 5000 is closed.",
                    hypotheses=[
                        Hypothesis(
                            id="hyp-port-1",
                            title="Internal port mismatch in docker-compose",
                            description="Application listens on port 8000, but container port was mapped to 5000",
                            category=HypothesisCategory.PORT_MISMATCH,
                            confidence_score=0.99,
                        )
                    ],
                    needs_diagnostic_probe=False,
                    is_evidence_sufficient=True,
                )

        elif "env" in scenario:
            if iteration == 0:
                return LLMHypothesisResponse(
                    reasoning="App crashed during boot with ambiguous error. Missing environment variable suspected.",
                    hypotheses=[
                        Hypothesis(
                            id="hyp-env-1",
                            title="Missing critical environment variable",
                            description="Required env var (e.g. DATABASE_URL or API_KEY) is missing in docker-compose.yml",
                            category=HypothesisCategory.MISSING_ENV,
                            confidence_score=0.65,
                        )
                    ],
                    needs_diagnostic_probe=True,
                    recommended_probe=DiagnosticAction(
                        id="probe-env-1",
                        probe_type=DiagnosticProbeType.READ_TARGET_FILE,
                        target="docker-compose.yml",
                        parameters={},
                        rationale="Compare expected environment configuration against defined variables",
                    ),
                    is_evidence_sufficient=False,
                )
            else:
                return LLMHypothesisResponse(
                    reasoning="Read docker-compose.yml and confirmed DATABASE_URL is not set.",
                    hypotheses=[
                        Hypothesis(
                            id="hyp-env-1",
                            title="Missing DATABASE_URL in docker-compose.yml",
                            description="App requires DATABASE_URL to connect, but environment block omitted it.",
                            category=HypothesisCategory.MISSING_ENV,
                            confidence_score=0.97,
                        )
                    ],
                    needs_diagnostic_probe=False,
                    is_evidence_sufficient=True,
                )

        else:
            # Ambiguous failure / Insufficient Evidence scenario
            return LLMHypothesisResponse(
                reasoning="Evidence shows network timeout connecting to external cloud gateway. Application code and Docker config are valid. External outage cannot be resolved with local code changes.",
                hypotheses=[
                    Hypothesis(
                        id="hyp-ext-1",
                        title="External upstream dependency failure",
                        description="External API endpoint is unreachable or returning 503. Local patch cannot resolve third-party outage.",
                        category=HypothesisCategory.EXTERNAL_DEPENDENCY,
                        confidence_score=0.50,
                    )
                ],
                needs_diagnostic_probe=False,
                is_evidence_sufficient=False,
                refusal_reason="Insufficient evidence to generate a safe local patch. Failure is caused by an external dependency outage. Refusing to invent an unverified fix.",
            )

    @classmethod
    def get_patch_for_scenario(cls, scenario_name: str) -> LLMPatchResponse:
        scenario = scenario_name.lower()
        if "healthcheck" in scenario:
            return LLMPatchResponse(
                target_file="docker-compose.yml",
                diff_unified='--- a/docker-compose.yml\n+++ b/docker-compose.yml\n@@ -8,3 +8,3 @@\n     healthcheck:\n-      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]\n+      test: ["CMD", "curl", "-f", "http://localhost:8000/healthz"]\n',
                explanation="Updated healthcheck endpoint URL from '/health' to match the actual route '/healthz'.",
                verification_command="docker inspect --format='{{json .State.Health.Status}}' scenario1_app",
            )
        elif "port" in scenario:
            return LLMPatchResponse(
                target_file="docker-compose.yml",
                diff_unified='--- a/docker-compose.yml\n+++ b/docker-compose.yml\n@@ -6,3 +6,3 @@\n     ports:\n-      - "8000:5000"\n+      - "8000:8000"\n',
                explanation="Aligned container target port in compose from 5000 to 8000.",
                verification_command="curl -f http://localhost:8000/api/ping",
            )
        elif "env" in scenario:
            return LLMPatchResponse(
                target_file="docker-compose.yml",
                diff_unified="--- a/docker-compose.yml\n+++ b/docker-compose.yml\n@@ -6,2 +6,4 @@\n     environment:\n+      - DATABASE_URL=sqlite:///./data.db\n",
                explanation="Added missing DATABASE_URL environment variable to docker-compose.yml.",
                verification_command="docker logs scenario3_app",
            )
        else:
            raise ValueError(
                "Cannot generate patch for ambiguous / unverified scenario"
            )

    @classmethod
    def diagnose(cls, request: DiagnoseRequest) -> DiagnoseResponse:
        """Produces a deterministic diagnosis response matching DiagnoseResponse schema."""
        import re

        logs = request.logs or ""
        service_name = request.service_name or "service"
        context_str = (
            service_name
            + " "
            + logs
            + " "
            + str(request.docker_inspect or "")
            + " "
            + str(request.configuration_files or "")
        ).lower()

        # 1. Missing Environment Variable Check (e.g. KeyError 'DATABASE_URL' or missing env)
        env_match = (
            re.search(r"KeyError:\s*['\"]([A-Z0-9_]+)['\"]", logs)
            or re.search(r"KeyError\s+['\"]([A-Z0-9_]+)['\"]", logs)
            or re.search(
                r"Required environment variable\s*['\"]([A-Z0-9_]+)['\"]",
                logs,
                re.IGNORECASE,
            )
            or re.search(
                r"missing\s+['\"]?([A-Z0-9_]+)['\"]?\s+(?:env|environment variable)",
                logs,
                re.IGNORECASE,
            )
        )

        if env_match or (
            (
                "keyerror" in logs.lower()
                or "missing env" in logs.lower()
                or "environment variable" in logs.lower()
                or "variable missing" in logs.lower()
                or "missing variable" in logs.lower()
            )
            and "database" in context_str
        ):
            var_name = (
                env_match.group(1)
                if env_match
                else ("DATABASE_URL" if "database" in context_str else "CONFIG_VAR")
            )
            evidence_snippet = next(
                (
                    line.strip()
                    for line in logs.splitlines()
                    if var_name in line or "KeyError" in line
                ),
                f"KeyError: '{var_name}'",
            )
            return DiagnoseResponse(
                status=DiagnosisStatus.DIAGNOSIS_AVAILABLE,
                summary=f"Service '{service_name}' failed to start because the {var_name} environment variable is missing from the container configuration.",
                hypotheses=[
                    DiagnoseHypothesis(
                        description=f"Missing {var_name} configuration required for service initialization",
                        supporting_evidence=[
                            f"application_logs: {evidence_snippet}",
                            f"environment: {var_name} is not set in container environment",
                        ],
                        contradicting_evidence=[],
                        confidence=0.96,
                        recommended_discriminating_test=f"CHECK_ENV_KEY_EXISTS {var_name}",
                    )
                ],
                evidence=[
                    EvidenceRecord(
                        id="ev-1", source="application_logs", content=evidence_snippet
                    ),
                    EvidenceRecord(
                        id="ev-2",
                        source="environment_variables",
                        content=f"Container environment inspection confirms {var_name} is undefined.",
                    ),
                ],
                recommended_tests=[
                    RecommendTest(
                        id="test-env-1",
                        test_type="CHECK_ENV",
                        target=var_name,
                        description=f"Verify whether {var_name} is defined in the container environment",
                        expected_signal="Variable is missing / undefined",
                    )
                ],
                missing_information=[],
                confidence=0.96,
                next_action=f"Define {var_name} in docker-compose.yml or container environment block",
                has_safe_patch=True,
            )

        # 2. Healthcheck Probe Mismatch Check
        has_healthcheck_clue = any(
            k in context_str
            for k in ["healthcheck", "health check", "/health", "/healthz", "unhealthy"]
        )
        if has_healthcheck_clue and (
            "404" in context_str
            or "mismatch" in context_str
            or "unhealthy" in context_str
            or "refused" in context_str
        ):
            evidence_snippet = next(
                (
                    line.strip()
                    for line in logs.splitlines()
                    if any(k in line.lower() for k in ["health", "404", "unhealthy"])
                ),
                "Health check probe returned HTTP 404",
            )
            return DiagnoseResponse(
                status=DiagnosisStatus.DIAGNOSIS_AVAILABLE,
                summary=f"Container healthcheck failure for '{service_name}': probe endpoint does not match application route configuration.",
                hypotheses=[
                    DiagnoseHypothesis(
                        description="Healthcheck probe requests an unmapped or incorrect route on the container",
                        supporting_evidence=[
                            f"application_logs: {evidence_snippet}",
                            "docker_inspect: container marked unhealthy due to failing probe",
                        ],
                        contradicting_evidence=[],
                        confidence=0.94,
                        recommended_discriminating_test="HTTP_GET /health vs /healthz",
                    )
                ],
                evidence=[
                    EvidenceRecord(
                        id="ev-hc-1",
                        source="application_logs",
                        content=evidence_snippet,
                    )
                ],
                recommended_tests=[
                    RecommendTest(
                        id="test-hc-1",
                        test_type="HTTP_GET",
                        target="/healthz",
                        description="Probe alternative health endpoint to confirm route availability",
                        expected_signal="HTTP 200 OK",
                    )
                ],
                missing_information=[],
                confidence=0.94,
                next_action="Align healthcheck probe test endpoint in docker-compose.yml with application route",
                has_safe_patch=True,
            )

        # 2.5. Database / Local Service ECONNREFUSED Check (e.g., orders-api ECONNREFUSED 127.0.0.1:5432)
        if (
            "econnrefused" in context_str or "connection refused" in context_str
        ) and not has_healthcheck_clue:
            evidence_snippet = next(
                (
                    line.strip()
                    for line in logs.splitlines()
                    if any(
                        k in line.lower()
                        for k in [
                            "econnrefused",
                            "refused",
                            "5432",
                            "postgres",
                            "redis",
                        ]
                    )
                ),
                "connect ECONNREFUSED 127.0.0.1:5432",
            )
            is_pg = (
                "5432" in context_str
                or "postgres" in context_str
                or "pg" in context_str
            )
            db_label = "PostgreSQL database" if is_pg else "Downstream service"
            target_ep = "127.0.0.1:5432" if "5432" in context_str else "target endpoint"
            return DiagnoseResponse(
                status=DiagnosisStatus.DIAGNOSIS_AVAILABLE,
                summary=f"Connection refused for '{service_name}': {db_label} at {target_ep} is not running or not reachable from the container network.",
                hypotheses=[
                    DiagnoseHypothesis(
                        description=f"{db_label} is not running or not reachable at {target_ep} (ECONNREFUSED)",
                        supporting_evidence=[
                            f"application_logs: {evidence_snippet}",
                        ],
                        contradicting_evidence=[],
                        confidence=0.96,
                        recommended_discriminating_test=f"TCP_CONNECT {target_ep}",
                    )
                ],
                evidence=[
                    EvidenceRecord(
                        id="ev-conn-1",
                        source="application_logs",
                        content=evidence_snippet,
                    )
                ],
                recommended_tests=[
                    RecommendTest(
                        id="test-conn-1",
                        test_type="TCP_CONNECT",
                        target=target_ep,
                        description=f"Verify whether {db_label} is listening and reachable on {target_ep}",
                        expected_signal="TCP connection established",
                    )
                ],
                missing_information=[],
                confidence=0.96,
                next_action=f"Ensure {db_label} container is running and configure host/network connectivity instead of loopback 127.0.0.1",
                has_safe_patch=False,
            )

        # 3. External Outage / Upstream Timeout Check
        if (
            "external" in context_str
            or "upstream" in context_str
            or (
                "timeout" in context_str
                and "health" not in context_str
                and "port" not in context_str
            )
        ):
            evidence_snippet = next(
                (
                    line.strip()
                    for line in logs.splitlines()
                    if any(
                        k in line.lower()
                        for k in ["timeout", "gateway", "reset", "upstream"]
                    )
                ),
                "Connection timeout to external gateway",
            )
            return DiagnoseResponse(
                status=DiagnosisStatus.INSUFFICIENT_EVIDENCE,
                summary=f"Service failure for '{service_name}' is caused by an external upstream dependency timeout. Local container and code configuration are valid.",
                hypotheses=[
                    DiagnoseHypothesis(
                        description="Upstream third-party gateway is unreachable or experiencing outage",
                        supporting_evidence=[f"application_logs: {evidence_snippet}"],
                        contradicting_evidence=[],
                        confidence=0.65,
                        recommended_discriminating_test="TCP_CONNECT to upstream gateway IP",
                    )
                ],
                evidence=[
                    EvidenceRecord(
                        id="ev-ext-1",
                        source="application_logs",
                        content=evidence_snippet,
                    )
                ],
                recommended_tests=[],
                missing_information=[
                    "Status of external cloud provider service",
                    "Upstream network route accessibility",
                ],
                confidence=0.50,
                next_action="Check upstream provider status page and verify network routing",
                has_safe_patch=None,
            )

        # 4. Preset Scenario B Explicit Request (without custom logs override)
        if (
            request.service_name == "scenario_b_healthcheck_mismatch"
            and not request.logs
        ):
            return DiagnoseResponse.model_validate(MOCK_NEBIUS_HEALTHCHECK_RESPONSE)

        # 5. Default Fallback for Unrelated Noise or Unrecognized Logs:
        # Never return an unrelated preset diagnosis!
        lines = [l.strip() for l in logs.splitlines() if l.strip()]
        first_few_lines = lines[:3]
        log_sample = (
            "; ".join(first_few_lines)
            if first_few_lines
            else "No error traceback found"
        )
        return DiagnoseResponse(
            status=DiagnosisStatus.INSUFFICIENT_EVIDENCE,
            summary=f"Insufficient evidence in provided logs to establish a deterministic root cause for '{service_name}'. No known crash signature, exception traceback, or fatal error detected.",
            hypotheses=[],
            evidence=(
                [
                    EvidenceRecord(
                        id="ev-adhoc-1",
                        source="application_logs",
                        content=f"Analyzed logs ({len(lines)} line(s)): {log_sample[:200]}",
                    )
                ]
                if logs
                else []
            ),
            recommended_tests=[],
            missing_information=[
                "Container fatal crash traceback or panic log",
                "Docker inspect exit code and status",
                "Target container environment and configuration files",
            ],
            confidence=0.15,
            next_action="Provide container crash traceback, inspect json, or compose configuration.",
            has_safe_patch=None,
        )
