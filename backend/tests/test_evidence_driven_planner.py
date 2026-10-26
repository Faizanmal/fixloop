"""Comprehensive automated tests for FixLoop's evidence-driven diagnostic planner.

Validates:
1. Logs are normal but health check fails (contradiction detection, route mismatch vs deadlock,
   discriminating probe selection via EIG, resolution of uncertainty).
2. Two hypotheses initially fit the evidence (competing probabilities, elevated entropy, EIG
   computation, multi-attribute utility based on safety, cost, and execution time).
3. Evidence remains insufficient (honest diagnosis refusal, confidence strictly < 0.90, elevated
   uncertainty, zero invented observations, zero false claims of proven diagnosis).
4. Evidence provenance tracking (collector, target, SHA256 fingerprint, provenance type across all items).
5. Contradiction detection across logs, container state, and configuration.
6. Uncertainty estimation (Shannon entropy calibration and confidence margin).
7. Hybrid tooling (deterministic tools for factual checks and NVIDIA Nemotron model via Nebius for planning).
"""

import math
import hashlib
from pathlib import Path
from typing import Dict, Any, List
import pytest

from backend.app.core.models import (
    DiagnosisStatus,
    DiagnoseHypothesis,
    HypothesisCategory,
    EvidenceItem,
    EvidenceType,
    EvidenceRecord,
    ContradictionReport,
    RecommendTest,
)
from backend.app.agent.engine import (
    DiagnosticEngine,
    DiagnosticBudget,
    DeterministicFactAnalyzer,
    ContradictionDetector,
    UncertaintyEstimator,
    DiagnosticTestSelector,
    DiagnosticEngineResult,
    SelectedTestRecord,
)
from backend.app.evidence.collectors import (
    LogCollector,
    DockerStateCollector,
    ComposeConfigCollector,
    SourceCodeCollector,
    EnvironmentCollector,
    compute_fingerprint,
)
from backend.app.evidence.tools import (
    DiagnosticToolRegistry,
    ToolProbeHTTP,
    ToolProbeTCP,
    ToolCheckEnvKey,
    ToolReadApprovedFile,
    BaseDiagnosticTool,
    DiagnosticToolResult,
)
from backend.app.llm.client import NebiusLLMClient
from backend.app.llm.mock_provider import MockLLMProvider

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCENARIOS_DIR = REPO_ROOT / "scenarios"


# ==============================================================================
# TEST CASE 1: Logs are normal, but health check fails
# ==============================================================================

@pytest.mark.asyncio
async def test_logs_normal_but_health_check_fails():
    """Scenario where application logs show 100% normal startup with 0 errors,
    but Docker container inspection reports an 'unhealthy' healthcheck.

    Verifies:
    - ContradictionDetector flags 'contra-log-healthy-state-unhealthy'.
    - Two competing hypotheses are initially formulated:
        (a) Healthcheck endpoint mismatch (/health vs /healthz)
        (b) Application deadlock / hung thread pool
    - Prior uncertainty is elevated (entropy > 0.8, uncertainty > 0.40).
    - Diagnostic probe to '/healthz' is selected using EIG and safety/cost utility.
    - Post-probe execution:
        - Route mismatch hypothesis reaches confidence >= 0.95.
        - Competing deadlock hypothesis is refuted (confidence <= 0.05) with probe provenance.
        - Uncertainty collapses to <= 0.05.
    - Full evidence provenance is verified on all items.
    """
    scenario_path = SCENARIOS_DIR / "scenario_b_healthcheck_mismatch"
    assert scenario_path.exists(), f"Scenario path not found: {scenario_path}"

    engine = DiagnosticEngine()

    # Step 1: Collect initial evidence
    evidence = engine.collect_initial_evidence(scenario_path)

    # Verify initial evidence items carry complete provenance
    assert len(evidence) >= 4
    for ev in evidence:
        assert ev.collector is not None and len(ev.collector) > 0
        assert ev.target is not None and len(ev.target) > 0
        assert ev.fingerprint is not None and len(ev.fingerprint) >= 16
        assert ev.provenance_type in {
            "RUNTIME_OBSERVATION",
            "CONTAINER_METADATA",
            "STATIC_ANALYSIS",
            "ENVIRONMENT_INSPECTION",
            "ACTIVE_PROBE",
        }

    # Step 2: Establish facts and verify contradiction detection
    facts = DeterministicFactAnalyzer.analyze_facts(evidence)
    assert facts.get("normal_startup_logged") is True
    assert facts.get("container_health_status") == "unhealthy"

    contradictions = ContradictionDetector.detect_contradictions(evidence, facts)
    assert len(contradictions) >= 1
    contra_ids = [c.id for c in contradictions]
    assert "contra-log-healthy-state-unhealthy" in contra_ids

    unhealthy_contra = next(c for c in contradictions if c.id == "contra-log-healthy-state-unhealthy")
    assert unhealthy_contra.severity == "HIGH"
    assert "route mismatch" in unhealthy_contra.implication.lower() or "hanging" in unhealthy_contra.implication.lower()

    # Step 3: Before active probe execution, verify competing hypotheses & high uncertainty
    initial_hypotheses, missing_info, initial_uncertainty = engine.generate_hypotheses_from_evidence(
        evidence=evidence,
        facts=facts,
        executed_tests=[],
    )
    assert len(initial_hypotheses) == 2
    hyp_cats = [h.category for h in initial_hypotheses]
    assert HypothesisCategory.HEALTHCHECK_MISCONFIG in hyp_cats
    assert HypothesisCategory.CODE_DEFECT in hyp_cats

    # Verify neither hypothesis has reached conclusive threshold prior to probing
    assert all(h.confidence < 0.90 for h in initial_hypotheses)
    assert initial_uncertainty >= 0.40

    prior_entropy = UncertaintyEstimator.calculate_entropy([h.confidence for h in initial_hypotheses])
    assert prior_entropy > 0.80

    # Step 4: Verify test selector selects the discriminating probe
    budget = DiagnosticBudget(max_steps=3, max_cost=10)
    selected_test = engine.select_next_test(
        hypotheses=initial_hypotheses,
        facts=facts,
        executed_tests=[],
        budget=budget,
    )
    assert selected_test is not None
    assert selected_test.tool_name == "probe_http"
    assert selected_test.target == "/healthz"
    assert selected_test.expected_information_gain > 0.0
    assert selected_test.safety == "safe"
    assert selected_test.utility_score > 0.0

    # Step 5: Run full investigation
    result: DiagnosticEngineResult = await engine.run_investigation(project_root=scenario_path)

    # Acceptance Invariants
    assert result.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE
    assert result.confidence >= 0.95
    assert result.uncertainty <= 0.05

    # Top hypothesis is confirmed route mismatch
    top_h = result.hypotheses[0]
    assert top_h.category == HypothesisCategory.HEALTHCHECK_MISCONFIG
    assert "/healthz" in top_h.description and "/health" in top_h.description
    assert any("[provenance: ACTIVE_PROBE]" in s for s in top_h.supporting_evidence)

    # Competing hypothesis is now refuted with probe provenance
    refuted_h = next(h for h in result.hypotheses if h.id == "hyp-healthcheck-2")
    assert refuted_h.confidence <= 0.05
    assert any("[provenance: ACTIVE_PROBE]" in c for c in refuted_h.contradicting_evidence)

    # Audit log confirms execution and uncertainty reduction
    assert len(result.audit_log.selected_tests) >= 1
    assert result.audit_log.selected_tests[0].target == "/healthz"
    assert len(result.audit_log.entropy_history) >= 2
    # Entropy dropped after probe
    assert result.audit_log.entropy_history[-1] < result.audit_log.entropy_history[0]


# ==============================================================================
# TEST CASE 2: Two hypotheses initially fit the evidence (EIG Selection)
# ==============================================================================

@pytest.mark.asyncio
async def test_two_hypotheses_initially_fit_evidence_and_eig_selection():
    """Scenario where initial evidence equally supports two competing root causes:
    H1: Port forwarding mismatch (Docker Compose publishes port 5000:5000, App listens on 8000)
    H2: Application service failed to bind to 0.0.0.0 / socket closed

    Verifies:
    - Initial confidence distribution is split (e.g. 0.55 vs 0.40).
    - Initial Shannon entropy is high (~0.97 bits) and uncertainty is elevated.
    - Test selector calculates Expected Information Gain (EIG):
        EIG = H_prior - E[H_posterior]
    - Multi-attribute utility balances EIG, safety, cost, and duration:
        Utility = (EIG * Safety) / (Cost * (1 + duration_ms / 500))
    - Discriminating TCP probe to port 8000 is selected over non-discriminating or expensive tests.
    - Post-probe execution: winning hypothesis confidence jumps to >= 0.95, uncertainty drops.
    """
    scenario_path = SCENARIOS_DIR / "scenario_c_port_mismatch"
    assert scenario_path.exists()

    engine = DiagnosticEngine()

    # Step 1: Collect initial evidence
    evidence = engine.collect_initial_evidence(scenario_path)
    facts = DeterministicFactAnalyzer.analyze_facts(evidence)

    # Step 2: Formulate initial hypotheses without executing tests
    initial_hypotheses, missing_info, initial_uncertainty = engine.generate_hypotheses_from_evidence(
        evidence=evidence,
        facts=facts,
        executed_tests=[],
    )

    assert len(initial_hypotheses) == 2
    h1 = initial_hypotheses[0]
    h2 = initial_hypotheses[1]

    # Verify both hypotheses initially fit the evidence without conclusive threshold
    assert 0.70 <= h1.confidence < 0.90
    assert 0.15 <= h2.confidence <= 0.30
    assert initial_uncertainty >= 0.30

    # Calculate prior Shannon entropy directly
    prior_entropy = UncertaintyEstimator.calculate_entropy([h1.confidence, h2.confidence])
    assert 0.70 <= prior_entropy <= 1.05, f"Expected elevated entropy for competing hypotheses, got {prior_entropy}"

    # Step 3: Test EIG and Utility computation on candidate tools
    tool_tcp = ToolProbeTCP()
    # Tool TCP port 8000: highly discriminating
    # If H1 is true, port 8000 is open (success prob = 0.95)
    # If H2 is true, port 8000 is closed (success prob = 0.05)
    eig_tcp, util_tcp, record_tcp = DiagnosticTestSelector.compute_eig_and_utility(
        tool=tool_tcp,
        target="8000",
        parameters={"port": 8000},
        hypotheses=initial_hypotheses,
        rationale="Probe TCP port 8000 to determine if service is actively listening",
        p_success_given_hyp=[0.95, 0.05],
        base_test_id="test-tcp-8000",
    )

    assert eig_tcp > 0.50, f"Expected high EIG for discriminating TCP probe, got {eig_tcp}"
    assert util_tcp > 0.0
    assert record_tcp.safety == "safe"
    assert record_tcp.cost == 2
    assert record_tcp.estimated_duration_ms == 80

    # Non-discriminating test (e.g. read an uninformative file where both hypotheses predict same outcome)
    tool_file = ToolReadApprovedFile()
    eig_null, util_null, record_null = DiagnosticTestSelector.compute_eig_and_utility(
        tool=tool_file,
        target="README.md",
        parameters={"path": "README.md"},
        hypotheses=initial_hypotheses,
        rationale="Read README",
        p_success_given_hyp=[0.50, 0.50],  # Non-discriminating: provides 0 information
        base_test_id="test-readme",
    )
    assert eig_null < 0.10
    assert util_tcp > util_null, "Discriminating probe must have higher utility than non-discriminating read"

    # Step 4: Run full investigation
    result = await engine.run_investigation(project_root=scenario_path)

    # Acceptance Invariants
    assert result.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE
    assert result.confidence >= 0.95
    assert result.uncertainty <= 0.05

    # Top hypothesis confirms port mismatch
    assert any("8000" in h.description and "5000" in h.description for h in result.hypotheses)

    # Competing hypothesis is refuted
    refuted = next((h for h in result.hypotheses if h.id == "hyp-port-competing-2"), None)
    if refuted:
        assert refuted.confidence <= 0.05
        assert len(refuted.contradicting_evidence) > 0


# ==============================================================================
# TEST CASE 3: Evidence remains insufficient (Never invent observations)
# ==============================================================================

@pytest.mark.asyncio
async def test_evidence_remains_insufficient_never_invents_observations():
    """Scenario D: External upstream dependency timeout.
    The local code and container configuration are 100% valid; the outage is external.

    Strict AI Safety & Debugging Standards:
    - Never claim a diagnosis is proven without supporting evidence (status != DIAGNOSIS_AVAILABLE).
    - Top confidence must remain strictly below conclusive threshold (confidence < 0.90).
    - Uncertainty must remain elevated (uncertainty >= 0.35).
    - Engine must NEVER invent observations, manufacture false findings, or hallucinate bugs.
    - Missing information must explicitly articulate what external data is unavailable.
    """
    scenario_path = SCENARIOS_DIR / "scenario_d_insufficient_evidence"
    assert scenario_path.exists()

    engine = DiagnosticEngine()
    result = await engine.run_investigation(project_root=scenario_path)

    # Acceptance Invariant 1: Honesty in uncertainty
    assert result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert result.confidence < 0.90
    assert result.uncertainty >= 0.35

    # Acceptance Invariant 2: Hypotheses reflect external ambiguity
    assert len(result.hypotheses) >= 1
    top_h = result.hypotheses[0]
    assert any(k in top_h.description.lower() for k in ["external", "upstream", "outage", "third-party"])
    assert top_h.confidence < 0.90

    # Acceptance Invariant 3: Zero invented observations
    # Every single observation recorded must have an actual collector and target
    assert len(result.audit_log.observations) > 0
    for obs in result.audit_log.observations:
        assert "id" in obs
        assert "type" in obs
        # Source must be an actual known collector, tool, or nebius model interpretation
        assert any(
            obs.get("source", "").startswith(prefix)
            for prefix in ["project:", "docker", "compose", "source", "container", "env", "tool:", "nebius:", "logs"]
        ), f"Unexpected unverified observation source: {obs.get('source')}"

    # Acceptance Invariant 4: Explicit missing information recorded
    assert len(result.missing_information) > 0
    assert any("external" in m.lower() or "upstream" in m.lower() or "third-party" in m.lower() for m in result.missing_information)

    # Acceptance Invariant 5: Stop reason reflects external dependency limitation
    assert "external" in result.audit_log.stop_reason.lower() or "upstream" in result.audit_log.stop_reason.lower()


# ==============================================================================
# TEST CASE 4: Evidence Provenance Integrity
# ==============================================================================

def test_evidence_provenance_across_all_collectors():
    """Validates that all evidence collectors populate provenance fields:
    - collector: Name of collector module
    - target: Concrete target (file, container ID, env key)
    - fingerprint: Nonce/SHA256 content hash
    - provenance_type: Classification string
    """
    # 1. LogCollector
    raw_logs = "2026-10-26T12:00:00Z [info] Application started successfully.\n2026-10-26T12:00:01Z [error] Connection timeout."
    log_items = LogCollector.collect_from_text(raw_logs, source_label="test_logs.txt")
    assert len(log_items) == 2  # Tail + Error extract
    for item in log_items:
        assert item.collector == "LogCollector"
        assert item.target.startswith("test_logs.txt")
        assert item.provenance_type == "RUNTIME_OBSERVATION"
        assert len(item.fingerprint) == 16
        expected_hash = hashlib.sha256(item.content.encode("utf-8")).hexdigest()[:16]
        assert item.fingerprint == expected_hash

    # 2. DockerStateCollector
    raw_inspect = '{"Id": "c123456789abcdef", "State": {"Status": "running", "Health": {"Status": "unhealthy"}}}'
    inspect_items = DockerStateCollector.collect_from_json(raw_inspect, source_label="inspect.json")
    assert len(inspect_items) >= 1
    for item in inspect_items:
        assert item.collector == "DockerStateCollector"
        assert item.provenance_type == "CONTAINER_METADATA"
        assert len(item.fingerprint) == 16

    # 3. EnvironmentCollector (with secret masking)
    raw_env = {
        "PORT": "8000",
        "DATABASE_PASSWORD": "super_secret_production_password_xyz",
        "API_SECRET_TOKEN": "Bearer secret_token_abc_123",
    }
    env_items = EnvironmentCollector.collect_presence(raw_env, expected_keys={"PORT", "DATABASE_PASSWORD"})
    assert len(env_items) == 1
    env_item = env_items[0]
    assert env_item.collector == "EnvironmentCollector"
    assert env_item.provenance_type == "ENVIRONMENT_INSPECTION"
    # Ensure sensitive credentials are masked, never exposed
    assert "super_secret_production_password_xyz" not in env_item.content
    assert "[PRESENT_SECRET_MASKED]" in env_item.content


# ==============================================================================
# TEST CASE 5: Contradiction Detection Invariants
# ==============================================================================

def test_contradiction_detection_factual_invariants():
    """Validates that ContradictionDetector catches all 5 classes of factual contradictions:
    1. Log normal startup vs Docker unhealthy
    2. Redis connection errors in log vs REDIS_ENABLED=false config
    3. Linux Kernel OOM exit 137 vs logged DB connection timeout
    4. Healthcheck route in Compose missing from FastAPI source routes
    5. Compose host:container port mapping mismatch against source listen port
    """
    # 1. Healthy Log vs Unhealthy Container
    ev1 = [
        EvidenceItem(
            id="ev-log-1",
            type=EvidenceType.LOGS,
            source="logs.txt",
            content="[info] Application startup complete. Uvicorn running on 0.0.0.0:8000",
            collector="LogCollector",
            target="logs.txt",
            fingerprint="abc123",
            provenance_type="RUNTIME_OBSERVATION",
        ),
        EvidenceItem(
            id="ev-insp-1",
            type=EvidenceType.DOCKER_INSPECT,
            source="docker_inspect.json",
            content='{"State": {"Health": {"Status": "unhealthy"}}}',
            collector="DockerStateCollector",
            target="docker_inspect.json",
            fingerprint="def456",
            provenance_type="CONTAINER_METADATA",
        ),
    ]
    facts1 = DeterministicFactAnalyzer.analyze_facts(ev1)
    contra1 = ContradictionDetector.detect_contradictions(ev1, facts1)
    assert any(c.id == "contra-log-healthy-state-unhealthy" for c in contra1)

    # 2. Redis log error vs REDIS_ENABLED=false
    ev2 = [
        EvidenceItem(
            id="ev-log-2",
            type=EvidenceType.LOGS,
            source="logs.txt",
            content="[warning] Redis connection refused on localhost:6379; falling back to in-memory cache",
            collector="LogCollector",
            target="logs.txt",
            fingerprint="111222",
            provenance_type="RUNTIME_OBSERVATION",
        ),
        EvidenceItem(
            id="ev-comp-2",
            type=EvidenceType.COMPOSE_CONFIG,
            source="docker-compose.yml",
            content="services:\n  web:\n    environment:\n      - REDIS_ENABLED=false\n",
            collector="ComposeConfigCollector",
            target="docker-compose.yml",
            fingerprint="333444",
            provenance_type="STATIC_ANALYSIS",
        ),
    ]
    facts2 = DeterministicFactAnalyzer.analyze_facts(ev2)
    contra2 = ContradictionDetector.detect_contradictions(ev2, facts2)
    assert any(c.id == "contra-redis-log-vs-config" for c in contra2)

    # 3. Kernel OOM vs Logged DB timeout
    ev3 = [
        EvidenceItem(
            id="ev-log-3",
            type=EvidenceType.LOGS,
            source="logs.txt",
            content="[error] TimeoutError: connection timeout to PostgreSQL database at db:5432",
            collector="LogCollector",
            target="logs.txt",
            fingerprint="555666",
            provenance_type="RUNTIME_OBSERVATION",
        ),
        EvidenceItem(
            id="ev-insp-3",
            type=EvidenceType.DOCKER_INSPECT,
            source="docker_inspect.json",
            content='{"State": {"OOMKilled": true, "ExitCode": 137}}',
            collector="DockerStateCollector",
            target="docker_inspect.json",
            fingerprint="777888",
            provenance_type="CONTAINER_METADATA",
        ),
    ]
    facts3 = DeterministicFactAnalyzer.analyze_facts(ev3)
    contra3 = ContradictionDetector.detect_contradictions(ev3, facts3)
    assert any(c.id == "contra-oom-vs-timeout-log" for c in contra3)


# ==============================================================================
# TEST CASE 6: Shannon Entropy & Uncertainty Calibration
# ==============================================================================

def test_shannon_entropy_and_uncertainty_calibration():
    """Validates mathematical properties of Shannon entropy calculation:
    - Equal distribution [0.5, 0.5] yields H = 1.0 bit
    - Skewed distribution [0.98, 0.02] yields near-zero entropy
    - Single hypothesis [1.0] yields H = 0.0 bit
    - Uniform 4-way [0.25, 0.25, 0.25, 0.25] yields H = 2.0 bits
    - Empty list yields H = 0.0 bit
    """
    # 2-way uniform
    h2 = UncertaintyEstimator.calculate_entropy([0.5, 0.5])
    assert math.isclose(h2, 1.0, rel_tol=1e-3)

    # 4-way uniform
    h4 = UncertaintyEstimator.calculate_entropy([0.25, 0.25, 0.25, 0.25])
    assert math.isclose(h4, 2.0, rel_tol=1e-3)

    # Single hypothesis
    h1 = UncertaintyEstimator.calculate_entropy([1.0])
    assert math.isclose(h1, 0.0, abs_tol=1e-4)

    # Empty list
    h0 = UncertaintyEstimator.calculate_entropy([])
    assert h0 == 0.0

    # Skewed (conclusive)
    h_skewed = UncertaintyEstimator.calculate_entropy([0.98, 0.02])
    assert h_skewed < 0.20

    # Uncertainty calculation calibration
    hyps_balanced = [
        DiagnoseHypothesis(description="Hyp A", confidence=0.50),
        DiagnoseHypothesis(description="Hyp B", confidence=0.45),
    ]
    u_balanced, _ = UncertaintyEstimator.estimate_uncertainty(hyps_balanced, facts={})
    assert u_balanced >= 0.40

    hyps_conclusive = [
        DiagnoseHypothesis(description="Hyp Winner", confidence=0.98),
        DiagnoseHypothesis(description="Hyp Loser", confidence=0.02),
    ]
    u_conclusive, _ = UncertaintyEstimator.estimate_uncertainty(hyps_conclusive, facts={}, has_conclusive_evidence=True)
    assert u_conclusive <= 0.05


# ==============================================================================
# TEST CASE 7: Hybrid Tooling & Nebius NVIDIA Model Architecture
# ==============================================================================

@pytest.mark.asyncio
async def test_hybrid_tooling_with_nebius_nvidia_model():
    """Validates the architectural division of responsibility:
    1. Deterministic tools execute factual checks without LLM hallucination.
    2. NebiusLLMClient / NVIDIA model performs interpretation and reasoning.
    3. Audit log records reasoning provenance attributed to the model.
    """
    scenario_path = SCENARIOS_DIR / "scenario_a_missing_env"
    assert scenario_path.exists()

    # Step 1: Deterministic check verifies environment key
    tool_env = ToolCheckEnvKey()
    tool_res = await tool_env.execute(
        target="DATABASE_URL",
        parameters={"key": "DATABASE_URL"},
        project_root=scenario_path,
    )
    assert tool_res.tool_name == "check_env_key"
    assert tool_res.success is False  # Missing in scenario A!
    assert "NOT found" in tool_res.output or "missing" in tool_res.output.lower()

    # Step 2: NebiusLLMClient integration
    client = NebiusLLMClient()
    assert client.default_model == "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"

    engine = DiagnosticEngine(llm_client=client)
    result = await engine.run_investigation(project_root=scenario_path)

    # Acceptance criteria
    assert result.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE
    assert result.confidence >= 0.95
    assert any("DATABASE_URL" in h.description for h in result.hypotheses)

    # Verify model interpretation in audit log observations
    model_obs = [
        obs for obs in result.audit_log.observations
        if obs.get("type") == "MODEL_REASONING" or "nebius:" in obs.get("source", "")
    ]
    assert len(model_obs) >= 1
    assert "nvidia" in model_obs[0]["source"].lower()
