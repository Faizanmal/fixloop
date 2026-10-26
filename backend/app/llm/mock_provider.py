"""Mock LLM Provider for offline testing, CI suites, and fallback development.

Returns deterministic, evidence-aligned diagnostic hypotheses and patches
for the 4 benchmark scenarios when live Nebius Token Factory inference is not active.
"""

from typing import Dict, Any, List
from backend.app.core.models import (
    Hypothesis,
    HypothesisCategory,
    DiagnosticAction,
    DiagnosticProbeType,
    LLMHypothesisResponse,
    LLMPatchResponse
)


class MockLLMProvider:
    """Provides deterministic responses for offline verification of the agent loop."""

    @classmethod
    def get_hypotheses_for_scenario(cls, scenario_name: str, iteration: int, collected_evidence: List[Any]) -> LLMHypothesisResponse:
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
                            suggested_probe_rationale="Probe the server directly via HTTP GET on /healthz vs /health"
                        ),
                        Hypothesis(
                            id="hyp-2",
                            title="Server failed to bind to 0.0.0.0",
                            description="Server might be listening on 127.0.0.1 inside container or wrong port",
                            category=HypothesisCategory.PORT_MISMATCH,
                            confidence_score=0.35,
                            suggested_probe_rationale="Check container port bindings and TCP connectivity"
                        )
                    ],
                    needs_diagnostic_probe=True,
                    recommended_probe=DiagnosticAction(
                        id="probe-1",
                        probe_type=DiagnosticProbeType.HTTP_GET,
                        target="/healthz",
                        parameters={"port": 8000},
                        rationale="Distinguish whether server is responsive at /healthz vs /health"
                    ),
                    is_evidence_sufficient=False
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
                            supporting_evidence_ids=["probe-1"]
                        )
                    ],
                    needs_diagnostic_probe=False,
                    is_evidence_sufficient=True
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
                            confidence_score=0.70
                        )
                    ],
                    needs_diagnostic_probe=True,
                    recommended_probe=DiagnosticAction(
                        id="probe-port-1",
                        probe_type=DiagnosticProbeType.TCP_CONNECT,
                        target="127.0.0.1",
                        parameters={"port": 8000},
                        rationale="Verify which port is actively open inside the container"
                    ),
                    is_evidence_sufficient=False
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
                            confidence_score=0.99
                        )
                    ],
                    needs_diagnostic_probe=False,
                    is_evidence_sufficient=True
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
                            confidence_score=0.65
                        )
                    ],
                    needs_diagnostic_probe=True,
                    recommended_probe=DiagnosticAction(
                        id="probe-env-1",
                        probe_type=DiagnosticProbeType.READ_TARGET_FILE,
                        target="docker-compose.yml",
                        parameters={},
                        rationale="Compare expected environment configuration against defined variables"
                    ),
                    is_evidence_sufficient=False
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
                            confidence_score=0.97
                        )
                    ],
                    needs_diagnostic_probe=False,
                    is_evidence_sufficient=True
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
                        confidence_score=0.50
                    )
                ],
                needs_diagnostic_probe=False,
                is_evidence_sufficient=False,
                refusal_reason="Insufficient evidence to generate a safe local patch. Failure is caused by an external dependency outage. Refusing to invent an unverified fix."
            )

    @classmethod
    def get_patch_for_scenario(cls, scenario_name: str) -> LLMPatchResponse:
        scenario = scenario_name.lower()
        if "healthcheck" in scenario:
            return LLMPatchResponse(
                target_file="docker-compose.yml",
                diff_unified="--- a/docker-compose.yml\n+++ b/docker-compose.yml\n@@ -8,3 +8,3 @@\n     healthcheck:\n-      test: [\"CMD\", \"curl\", \"-f\", \"http://localhost:8000/health\"]\n+      test: [\"CMD\", \"curl\", \"-f\", \"http://localhost:8000/healthz\"]\n",
                explanation="Updated healthcheck endpoint URL from '/health' to match the actual route '/healthz'.",
                verification_command="docker inspect --format='{{json .State.Health.Status}}' scenario1_app"
            )
        elif "port" in scenario:
            return LLMPatchResponse(
                target_file="docker-compose.yml",
                diff_unified="--- a/docker-compose.yml\n+++ b/docker-compose.yml\n@@ -6,3 +6,3 @@\n     ports:\n-      - \"8000:5000\"\n+      - \"8000:8000\"\n",
                explanation="Aligned container target port in compose from 5000 to 8000.",
                verification_command="curl -f http://localhost:8000/api/ping"
            )
        elif "env" in scenario:
            return LLMPatchResponse(
                target_file="docker-compose.yml",
                diff_unified="--- a/docker-compose.yml\n+++ b/docker-compose.yml\n@@ -6,2 +6,4 @@\n     environment:\n+      - DATABASE_URL=sqlite:///./data.db\n",
                explanation="Added missing DATABASE_URL environment variable to docker-compose.yml.",
                verification_command="docker logs scenario3_app"
            )
        else:
            raise ValueError("Cannot generate patch for ambiguous / unverified scenario")
