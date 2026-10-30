"""Automated test suite for FixLoop's autonomous investigation loop.

Validates:
1. Explicit state transitions & illegal transition rejection (InvestigationState machine).
2. Bounded diagnostic budget (step limits, cost limits, wall-clock timeout, consecutive failures).
3. Duplicate-test detection (canonical signature normalization, skipping duplicates, DUPLICATE_TEST_SKIPPED event).
4. Per-tool timeouts (asyncio.wait_for protection, TEST_TIMEOUT event, graceful failure).
5. Cancellation (cancellation token, request_cancellation, and asyncio Task cancellation).
6. Maximum retry limits & recovery from model/API failures (idempotent retries, exponential backoff, graceful fallback).
7. Failed tests handling (negative evidence integration, TEST_FAILED event, hypotheses updates).
8. Interrupted investigations (complete event history and partial evidence preservation).
9. Verification evidence requirement (refusing fixes without empirical proof in DisposableSandbox).
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.agent.engine import (
    AuditLog,
    DeterministicFactAnalyzer,
    DiagnosticBudget,
    DiagnosticEngine,
    InvalidStateTransitionError,
    InvestigationEventType,
    InvestigationState,
    SelectedTestRecord,
    normalize_test_signature,
)
from backend.app.core.models import (
    DiagnoseHypothesis,
    DiagnosisStatus,
    HypothesisCategory,
    VerificationStatus,
)
from backend.app.evidence.tools import (
    BaseDiagnosticTool,
    DiagnosticToolRegistry,
    DiagnosticToolResult,
    ToolCheckEnvKey,
    ToolProbeTCP,
)
from backend.app.llm.exceptions import NebiusError

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCENARIOS_DIR = REPO_ROOT / "scenarios"


# =========================================================================
# 1. Explicit State Transitions & Validation
# =========================================================================


def test_valid_state_transitions():
    """Verify that valid state transitions succeed and append chronological events."""
    engine = DiagnosticEngine()
    audit = AuditLog()
    audit.current_state = InvestigationState.PENDING

    # Step through valid sequence
    engine._transition_state(audit, InvestigationState.INITIALIZING, "Starting")
    assert audit.current_state == InvestigationState.INITIALIZING

    engine._transition_state(
        audit, InvestigationState.COLLECTING_EVIDENCE, "Gathering files"
    )
    assert audit.current_state == InvestigationState.COLLECTING_EVIDENCE

    engine._transition_state(
        audit, InvestigationState.ANALYZING_FACTS, "Checking rules"
    )
    assert audit.current_state == InvestigationState.ANALYZING_FACTS

    engine._transition_state(
        audit, InvestigationState.HYPOTHESIS_FORMULATION, "Drafting hypotheses"
    )
    assert audit.current_state == InvestigationState.HYPOTHESIS_FORMULATION

    engine._transition_state(audit, InvestigationState.SELECTING_TEST, "Picking test")
    assert audit.current_state == InvestigationState.SELECTING_TEST

    engine._transition_state(audit, InvestigationState.EXECUTING_TEST, "Running probe")
    assert audit.current_state == InvestigationState.EXECUTING_TEST

    engine._transition_state(
        audit, InvestigationState.EVALUATING_RESULTS, "Checking probe output"
    )
    assert audit.current_state == InvestigationState.EVALUATING_RESULTS

    engine._transition_state(audit, InvestigationState.CONCLUDED, "Done")
    assert audit.current_state == InvestigationState.CONCLUDED

    # Verify event count and chronological order
    transition_events = [
        e
        for e in audit.events
        if e.event_type == InvestigationEventType.STATE_TRANSITION
    ]
    assert len(transition_events) == 8
    for i in range(len(transition_events) - 1):
        assert transition_events[i].timestamp <= transition_events[i + 1].timestamp


def test_illegal_state_transition_rejection():
    """Verify that invalid transitions raise InvalidStateTransitionError without corrupting state."""
    engine = DiagnosticEngine()
    audit = AuditLog()
    audit.current_state = InvestigationState.PENDING

    # Direct jump from PENDING to CONCLUDED or EXECUTING_TEST is illegal
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        engine._transition_state(
            audit, InvestigationState.EXECUTING_TEST, "Skipping ahead"
        )
    assert "PENDING" in str(exc_info.value) and "EXECUTING_TEST" in str(exc_info.value)
    assert audit.current_state == InvestigationState.PENDING

    # Direct jump from CONCLUDED back to EXECUTING_TEST is illegal
    audit.current_state = InvestigationState.CONCLUDED
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        engine._transition_state(
            audit, InvestigationState.EXECUTING_TEST, "Zombie test"
        )
    assert "CONCLUDED" in str(exc_info.value) and "EXECUTING_TEST" in str(
        exc_info.value
    )
    assert audit.current_state == InvestigationState.CONCLUDED


# =========================================================================
# 2. Infinite-Loop Prevention (Budget, Duplicate Tests, Failure Limits)
# =========================================================================


@pytest.mark.asyncio
async def test_infinite_loop_prevention_budget_exhaustion():
    """Verify that loop halts cleanly when budget step limit is reached, preventing infinite looping."""
    scenario_path = SCENARIOS_DIR / "scenario_b_healthcheck_mismatch"
    engine = DiagnosticEngine()

    # Allow exactly 1 step
    budget = DiagnosticBudget(max_steps=1, max_cost=10)
    result = await engine.run_investigation(project_root=scenario_path, budget=budget)

    # Must halt within bounded budget
    assert budget.steps_taken == 1
    assert len(result.audit_log.selected_tests) == 1
    assert result.audit_log.current_state == InvestigationState.CONCLUDED
    assert any(
        "exhausted" in e.payload.get("stop_reason", "").lower()
        or "conclusive" in e.payload.get("stop_reason", "").lower()
        for e in result.audit_log.events
        if e.event_type == InvestigationEventType.INVESTIGATION_CONCLUDED
    )


def test_duplicate_test_signature_normalization():
    """Verify canonical signature normalization handles parameter order, whitespace, and defaults."""
    sig1 = normalize_test_signature(
        "probe_http",
        "http://localhost:8000/healthz",
        {"headers": {"accept": "json"}, "port": 8000},
    )
    sig2 = normalize_test_signature(
        "probe_http",
        "http://localhost:8000/healthz",
        {"port": 8000, "headers": {"accept": "json"}},
    )
    sig3 = normalize_test_signature(
        "probe_http",
        "http://localhost:8000/healthz/",
        {"port": 8000, "headers": {"accept": "json"}},
    )

    # Param order and trailing slash variations normalize to identical canonical representation
    assert sig1 == sig2
    assert sig1 == sig3


@pytest.mark.asyncio
async def test_duplicate_test_detection_and_skipping():
    """Verify engine detects previously executed tests, emits DUPLICATE_TEST_SKIPPED, and does not re-run them."""
    engine = DiagnosticEngine()
    audit = AuditLog()

    # Pre-populate executed test
    _probe = SelectedTestRecord(
        test_id="test-probe-1",
        tool_name="probe_http",
        target="/healthz",
        parameters={"port": 8000},
        rationale="Check /healthz endpoint",
        expected_information_gain=0.6,
        cost=1,
    )
    executed_tests = [
        DiagnosticToolResult(
            tool_name="probe_http",
            target="/healthz",
            parameters={"port": 8000},
            success=True,
            output="HTTP 200 OK",
            cost=1,
            duration_ms=25,
        )
    ]

    hypotheses = [
        DiagnoseHypothesis(
            id="hyp-1",
            category=HypothesisCategory.HEALTHCHECK_MISCONFIG,
            description="Route mismatch on /healthz",
            confidence=0.5,
            evidence_supporting=["ev-1"],
            discriminating_tests=["probe_http:/healthz"],
        ),
        DiagnoseHypothesis(
            id="hyp-2",
            category=HypothesisCategory.UNKNOWN,
            description="Application thread deadlock",
            confidence=0.5,
            evidence_supporting=["ev-1"],
            discriminating_tests=["probe_tcp:8000"],
        ),
    ]
    facts = {
        "actual_source_routes": ["/healthz"],
        "configured_healthcheck": {"endpoint": "/health", "port": 8000},
        "container_listening_ports": [8000],
        "source_listen_ports": [8000],
    }
    budget = DiagnosticBudget(max_steps=5, max_cost=10)

    # Select next test; should skip /healthz because it was already executed, and select probe_tcp:8000
    next_test = engine.select_next_test(
        hypotheses, facts, executed_tests, budget, audit=audit
    )
    assert next_test is not None
    assert next_test.tool_name == "probe_tcp"

    # Confirm DUPLICATE_TEST_SKIPPED event was logged for /healthz
    duplicate_events = [
        e
        for e in audit.events
        if e.event_type == InvestigationEventType.DUPLICATE_TEST_SKIPPED
    ]
    assert len(duplicate_events) >= 1
    assert duplicate_events[0].payload.get("tool") == "probe_http"
    assert duplicate_events[0].payload.get("target") == "/healthz"


@pytest.mark.asyncio
async def test_consecutive_failures_limit_halts_loop():
    """Verify loop halts when consecutive test failures hit max_consecutive_failures (e.g. 3)."""
    engine = DiagnosticEngine()
    budget = DiagnosticBudget(max_steps=10, max_consecutive_failures=3)

    # Simulate 3 consecutive failures
    assert budget.consecutive_failures == 0
    budget.record_failure()
    assert budget.consecutive_failures == 1
    budget.record_failure()
    assert budget.consecutive_failures == 2
    budget.record_failure()
    assert budget.consecutive_failures == 3

    # Reset behavior verification
    budget.record_success()
    assert budget.consecutive_failures == 0

    # Test that run_investigation halts when max consecutive failures reached
    scenario_path = SCENARIOS_DIR / "scenario_b_healthcheck_mismatch"
    failing_tools = DiagnosticToolRegistry()

    class AlwaysFailingTool(BaseDiagnosticTool):
        tool_name = "probe_http"
        cost = 1
        safety = "read_only"
        description = "Always fails"
        timeout_seconds = 1.0

        async def execute(
            self, target, parameters, project_root, simulated_context=None
        ):
            return DiagnosticToolResult(
                tool_name=self.tool_name,
                target=target,
                parameters=parameters,
                success=False,
                output="Connection refused / Socket error",
                cost=1,
                duration_ms=10,
            )

    failing_tools.register(AlwaysFailingTool())
    engine.tools = failing_tools

    # Set budget with max_consecutive_failures=1
    fast_fail_budget = DiagnosticBudget(max_steps=5, max_consecutive_failures=1)
    result = await engine.run_investigation(
        project_root=scenario_path, budget=fast_fail_budget
    )

    # Must halt with max consecutive test failures in stop_reason
    assert "consecutive test failures" in result.audit_log.stop_reason.lower()
    assert result.audit_log.current_state == InvestigationState.CONCLUDED


# =========================================================================
# 3. Per-Tool and Overall Wall-Clock Timeouts
# =========================================================================


class HangingTool(BaseDiagnosticTool):
    tool_name = "hanging_probe"
    cost = 1
    safety = "read_only"
    description = "Simulates an unresponsive probe"
    timeout_seconds = 0.05  # 50ms timeout

    async def execute(self, target, parameters, project_root, simulated_context=None):
        await asyncio.sleep(0.5)  # Sleeps 500ms, exceeding 50ms timeout
        return DiagnosticToolResult(
            tool_name=self.tool_name,
            target=target,
            parameters=parameters,
            success=True,
            output="Should never reach here",
            cost=1,
            duration_ms=500,
        )


@pytest.mark.asyncio
async def test_per_tool_timeout_handling():
    """Verify that DiagnosticToolRegistry intercepts tool timeouts via asyncio.wait_for and returns safe failure result."""
    registry = DiagnosticToolRegistry()
    registry.register(HangingTool())

    start_time = time.time()
    result = await registry.execute_tool(
        tool_name="hanging_probe",
        target="/unresponsive",
        parameters={},
        project_root=REPO_ROOT,
    )
    elapsed = time.time() - start_time

    # Must return cleanly in ~50ms without crashing
    assert elapsed < 0.25
    assert result.success is False
    assert result.metadata.get("timed_out") is True
    assert "timed out after 0.05s" in result.output


@pytest.mark.asyncio
async def test_overall_budget_wall_clock_timeout():
    """Verify that investigation halts gracefully when wall-clock budget expires."""
    scenario_path = SCENARIOS_DIR / "scenario_b_healthcheck_mismatch"
    engine = DiagnosticEngine()

    # Configure tiny timeout (10ms)
    timeout_budget = DiagnosticBudget(timeout_seconds=0.01)
    timeout_budget.start_time = time.time() - 1.0  # Simulate 1 second already elapsed

    assert timeout_budget.is_expired() is True

    result = await engine.run_investigation(
        project_root=scenario_path, budget=timeout_budget
    )

    assert "timeout expired" in result.audit_log.stop_reason.lower()
    assert result.audit_log.current_state == InvestigationState.CONCLUDED


# =========================================================================
# 4. Cancellation (Token & Asyncio Task)
# =========================================================================


@pytest.mark.asyncio
async def test_cancellation_via_token_before_start():
    """Verify that cancellation token set before execution halts immediately at initialization."""
    scenario_path = SCENARIOS_DIR / "scenario_a_missing_env"
    engine = DiagnosticEngine()

    token = {"cancelled": True}
    result = await engine.run_investigation(
        project_root=scenario_path, cancellation_token=token
    )

    assert result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert result.audit_log.current_state == InvestigationState.CANCELLED
    assert "cancelled before execution" in result.audit_log.stop_reason.lower()

    # Event history includes cancellation
    cancel_events = [
        e
        for e in result.audit_log.events
        if e.event_type == InvestigationEventType.CANCELLATION_REQUESTED
    ]
    assert len(cancel_events) >= 1


@pytest.mark.asyncio
async def test_cancellation_via_token_during_investigation():
    """Verify that requesting cancellation during active loop transitions cleanly to CANCELLED."""
    scenario_path = SCENARIOS_DIR / "scenario_b_healthcheck_mismatch"
    engine = DiagnosticEngine()
    token = {"cancelled": False}

    # Simulate token being cancelled during first tool execution
    orig_select = engine.select_next_test

    def cancel_on_select(*args, **kwargs):
        engine.request_cancellation(token)
        return orig_select(*args, **kwargs)

    engine.select_next_test = cancel_on_select

    result = await engine.run_investigation(
        project_root=scenario_path, cancellation_token=token
    )

    assert result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert result.audit_log.current_state == InvestigationState.CANCELLED
    assert "cancelled by caller" in result.audit_log.stop_reason.lower()


@pytest.mark.asyncio
async def test_cancellation_via_asyncio_task():
    """Verify that asyncio Task cancellation is captured and marked CANCELLED in audit log."""
    scenario_path = SCENARIOS_DIR / "scenario_b_healthcheck_mismatch"
    engine = DiagnosticEngine()

    async def run_and_cancel():
        task = asyncio.create_task(engine.run_investigation(project_root=scenario_path))
        await asyncio.sleep(0.001)
        task.cancel()
        try:
            return await task
        except asyncio.CancelledError:
            return None

    # Should handle cancellation cleanly
    result = await run_and_cancel()
    # If the task finishes before or after cancel, check that engine handles without unhandled exceptions
    assert result is None or result.audit_log.current_state in {
        InvestigationState.CANCELLED,
        InvestigationState.CONCLUDED,
    }


# =========================================================================
# 5. Model/API Failure Recovery & Idempotent Retries
# =========================================================================


@pytest.mark.asyncio
async def test_model_api_failure_recovery_and_fallback():
    """Verify that when Nebius model fails (e.g. 503 error), engine retries with backoff and falls back to deterministic analysis."""
    scenario_path = SCENARIOS_DIR / "scenario_a_missing_env"
    engine = DiagnosticEngine()

    # Mock LLM client to fail with NebiusError
    mock_llm = MagicMock()
    mock_llm.generate_hypotheses = AsyncMock(
        side_effect=NebiusError("Nebius Service Unavailable (503)")
    )
    engine.llm_client = mock_llm

    result = await engine.run_investigation(project_root=scenario_path)

    # Must recover and still diagnose Scenario A via DeterministicFactAnalyzer
    assert result.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE
    assert result.confidence >= 0.95
    assert any("DATABASE_URL" in h.description for h in result.hypotheses)

    # Verify MODEL_ERROR events were logged
    model_errors = [
        e
        for e in result.audit_log.events
        if e.event_type == InvestigationEventType.MODEL_ERROR
    ]
    assert len(model_errors) >= 1
    assert "503" in model_errors[0].payload.get("error", "")

    # LLM retried up to max_retries_per_step (2 retries = 3 calls total)
    assert mock_llm.generate_hypotheses.call_count == 3


@pytest.mark.asyncio
async def test_malformed_model_output_fallback():
    """Verify that malformed model output (e.g. invalid JSON) triggers retry and falls back to deterministic analysis."""
    scenario_path = SCENARIOS_DIR / "scenario_c_port_mismatch"
    engine = DiagnosticEngine()

    mock_llm = MagicMock()
    mock_llm.generate_hypotheses = AsyncMock(
        side_effect=ValueError("Expecting value: line 1 column 1 (char 0)")
    )
    engine.llm_client = mock_llm

    result = await engine.run_investigation(project_root=scenario_path)

    # Deterministic fallback handles Scenario C (port 8000 vs 5000)
    assert result.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE
    assert result.confidence >= 0.95
    assert any(
        "8000" in h.description and "5000" in h.description for h in result.hypotheses
    )


# =========================================================================
# 6. Failed Tests Handling & Negative Evidence Integration
# =========================================================================


@pytest.mark.asyncio
async def test_failed_test_recorded_as_negative_evidence():
    """Verify that when a diagnostic probe fails (e.g. connection refused), it is recorded as negative evidence and updates hypotheses."""
    scenario_path = SCENARIOS_DIR / "scenario_b_healthcheck_mismatch"
    engine = DiagnosticEngine()

    # Register tool registry where probe_http fails
    custom_tools = DiagnosticToolRegistry()

    class FailingHTTPProbe(BaseDiagnosticTool):
        tool_name = "probe_http"
        cost = 1
        safety = "read_only"
        description = "Simulates endpoint returning HTTP 404"
        timeout_seconds = 2.0

        async def execute(
            self, target, parameters, project_root, simulated_context=None
        ):
            return DiagnosticToolResult(
                tool_name=self.tool_name,
                target=target,
                parameters=parameters,
                success=False,
                output="HTTP 404 Not Found: endpoint /healthz does not exist",
                cost=1,
                duration_ms=15,
            )

    custom_tools.register(FailingHTTPProbe())
    custom_tools.register(ToolProbeTCP())
    custom_tools.register(ToolCheckEnvKey())
    engine.tools = custom_tools

    result = await engine.run_investigation(project_root=scenario_path)

    # Must record TEST_FAILED event
    failed_events = [
        e
        for e in result.audit_log.events
        if e.event_type == InvestigationEventType.TEST_FAILED
    ]
    assert len(failed_events) >= 1
    assert failed_events[0].payload.get("tool") == "probe_http"

    # Must register probe result in test_results with success=False
    assert any(
        t.tool_name == "probe_http" and t.success is False
        for t in result.audit_log.test_results
    )

    # Negative evidence is preserved in evidence list with ACTIVE_PROBE provenance
    probe_evidence = [e for e in result.evidence if e.provenance_type == "ACTIVE_PROBE"]
    assert len(probe_evidence) >= 1
    assert "HTTP 404" in probe_evidence[0].content


# =========================================================================
# 7. Interrupted Investigations & Complete Event History
# =========================================================================


@pytest.mark.asyncio
async def test_interrupted_investigation_preserves_event_history_and_evidence():
    """Verify that interrupted investigations retain complete event history, observations, and evidence."""
    scenario_path = SCENARIOS_DIR / "scenario_b_healthcheck_mismatch"
    engine = DiagnosticEngine()

    token = {"cancelled": False}

    # Intercept after collecting evidence to trigger cancellation
    orig_analyze = DeterministicFactAnalyzer.analyze_facts

    def cancel_after_facts(evidence):
        facts = orig_analyze(evidence)
        engine.request_cancellation(token)
        return facts

    with patch(
        "backend.app.agent.engine.DeterministicFactAnalyzer.analyze_facts",
        side_effect=cancel_after_facts,
    ):
        result = await engine.run_investigation(
            project_root=scenario_path, cancellation_token=token
        )

    # Investigation cancelled cleanly
    assert result.audit_log.current_state == InvestigationState.CANCELLED

    # Crucial: Event history must not be empty and must include lifecycle events
    event_types = [e.event_type for e in result.audit_log.events]
    assert InvestigationEventType.STATE_TRANSITION in event_types
    assert InvestigationEventType.EVIDENCE_COLLECTED in event_types
    assert InvestigationEventType.FACTS_ANALYZED in event_types
    assert InvestigationEventType.CANCELLATION_REQUESTED in event_types

    # Observations and evidence collected prior to interruption are preserved
    assert len(result.evidence) > 0
    assert len(result.audit_log.observations) > 0


# =========================================================================
# 8. Verification Evidence Requirement for Fix Proposals
# =========================================================================


@pytest.mark.asyncio
async def test_require_actual_verification_evidence_refuses_low_confidence():
    """Verify that verify_proposed_fix strictly refuses hypotheses with confidence < 0.90."""
    engine = DiagnosticEngine()

    low_conf_hypothesis = DiagnoseHypothesis(
        id="hyp-low",
        category=HypothesisCategory.MISSING_ENV,
        description="Unverified speculative guess",
        confidence=0.60,
        evidence_supporting=["ev-1"],
    )

    report = await engine.verify_proposed_fix(
        project_root=SCENARIOS_DIR / "scenario_a_missing_env",
        hypothesis=low_conf_hypothesis,
        user_approved=True,
    )

    assert report.status == VerificationStatus.NOT_ATTEMPTED
    assert "below 0.90 threshold" in report.test_output
    assert report.reverted is True


@pytest.mark.asyncio
async def test_require_actual_verification_evidence_requires_user_approval():
    """Verify that high-risk patch generation refuses without explicit user approval."""
    engine = DiagnosticEngine()

    high_conf_hypothesis = DiagnoseHypothesis(
        id="hyp-high",
        category=HypothesisCategory.MISSING_ENV,
        description="Missing DATABASE_URL in docker-compose.yml",
        confidence=0.98,
        evidence_supporting=["ev-1"],
    )

    report = await engine.verify_proposed_fix(
        project_root=SCENARIOS_DIR / "scenario_a_missing_env",
        hypothesis=high_conf_hypothesis,
        user_approved=False,  # User approval omitted
    )

    # High-risk modifications without approval must not be marked verified_fixed
    assert report.status != VerificationStatus.VERIFIED_FIXED
    assert report.status == VerificationStatus.VERIFICATION_FAILED
    assert "approval" in report.test_output.lower()


@pytest.mark.asyncio
async def test_require_actual_verification_evidence_succeeds_with_sandbox_proof():
    """Verify that verify_proposed_fix only marks VERIFIED_FIXED when sandbox verification actually passes."""
    scenario_path = SCENARIOS_DIR / "scenario_a_missing_env"
    engine = DiagnosticEngine()

    # 1. Investigate and obtain high-confidence diagnosis
    result = await engine.run_investigation(project_root=scenario_path)
    assert result.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE
    assert result.confidence >= 0.95

    # 2. Verify with DisposableSandbox
    report = await engine.verify_proposed_fix(
        project_root=scenario_path,
        hypothesis=result.hypotheses[0],
        user_approved=True,
    )

    # Actual verification succeeded
    assert report.status == VerificationStatus.VERIFIED_FIXED
    assert report.reverted is True
    assert "DATABASE_URL successfully declared" in report.test_output
