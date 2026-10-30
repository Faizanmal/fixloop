"""Automated tests for FixLoop evidence-driven diagnostic engine.

Validates:
- All four benchmark scenarios (A, B, C, D).
- Scenario B requires an additional diagnostic probe to identify the cause.
- Scenario D ends with 'insufficient_evidence' honestly.
- Bounded diagnostic budget and timeout policy.
- Repetitive test avoidance.
- Strict security boundary validation preventing arbitrary filesystem inspection.
- Environment variable masking (zero secret disclosure).
"""

from pathlib import Path

import pytest

from backend.app.agent.engine import (
    DiagnosticBudget,
    DiagnosticEngine,
)
from backend.app.core.models import DiagnosisStatus
from backend.app.evidence.collectors import (
    ApprovedPathValidator,
    EnvironmentCollector,
    SecurityBoundaryError,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCENARIOS_DIR = REPO_ROOT / "scenarios"


@pytest.mark.asyncio
async def test_scenario_a_missing_env():
    """Scenario A: Logs explicitly identify a missing environment variable (DATABASE_URL)."""
    scenario_path = SCENARIOS_DIR / "scenario_a_missing_env"
    assert scenario_path.exists()

    engine = DiagnosticEngine()
    result = await engine.run_investigation(project_root=scenario_path)

    assert result.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE
    assert result.confidence >= 0.95
    assert any("DATABASE_URL" in h.description for h in result.hypotheses)
    assert len(result.audit_log.observations) > 0
    assert "conclusive" in result.audit_log.stop_reason.lower()


@pytest.mark.asyncio
async def test_scenario_b_healthcheck_mismatch_requires_additional_diagnostic():
    """Scenario B: Logs look normal, but container is unhealthy. Requires an additional probe to identify cause."""
    scenario_path = SCENARIOS_DIR / "scenario_b_healthcheck_mismatch"
    assert scenario_path.exists()

    engine = DiagnosticEngine()
    result = await engine.run_investigation(project_root=scenario_path)

    # Acceptance Criterion: Scenario B requires an additional diagnostic probe
    assert len(result.audit_log.selected_tests) >= 1
    selected_test = result.audit_log.selected_tests[0]
    assert selected_test.tool_name == "probe_http"
    assert selected_test.target == "/healthz"

    # Verify probe execution
    assert len(result.audit_log.test_results) >= 1
    probe_result = result.audit_log.test_results[0]
    assert probe_result.success is True

    # Final outcome is diagnosis_available with high confidence
    assert result.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE
    assert result.confidence >= 0.95
    assert any(
        "/healthz" in h.description and "/health" in h.description
        for h in result.hypotheses
    )


@pytest.mark.asyncio
async def test_scenario_c_port_mismatch():
    """Scenario C: The application listens on port 8000 while compose publishes port 5000."""
    scenario_path = SCENARIOS_DIR / "scenario_c_port_mismatch"
    assert scenario_path.exists()

    engine = DiagnosticEngine()
    result = await engine.run_investigation(project_root=scenario_path)

    assert result.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE
    assert result.confidence >= 0.95
    assert any(
        "8000" in h.description and "5000" in h.description for h in result.hypotheses
    )


@pytest.mark.asyncio
async def test_scenario_d_insufficient_evidence():
    """Scenario D: External upstream outage; evidence is insufficient to fix locally. Refuses to invent fix."""
    scenario_path = SCENARIOS_DIR / "scenario_d_insufficient_evidence"
    assert scenario_path.exists()

    engine = DiagnosticEngine()
    result = await engine.run_investigation(project_root=scenario_path)

    # Acceptance Criterion: Scenario D ends with insufficient_evidence
    assert result.status == DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert any(
        "external" in h.description.lower() or "upstream" in h.description.lower()
        for h in result.hypotheses
    )
    assert "external" in result.audit_log.stop_reason.lower()


@pytest.mark.asyncio
async def test_bounded_budget_enforcement():
    """Verify that DiagnosticEngine strictly obeys max_steps and budget constraints."""
    scenario_path = SCENARIOS_DIR / "scenario_b_healthcheck_mismatch"

    # Restrict budget to 0 steps allowed
    starved_budget = DiagnosticBudget(max_steps=0, max_cost=0)
    engine = DiagnosticEngine()
    result = await engine.run_investigation(
        project_root=scenario_path, budget=starved_budget
    )

    # Must halt without executing unbudgeted tests
    assert len(result.audit_log.selected_tests) == 0
    assert starved_budget.steps_taken == 0
    assert "exhausted" in result.audit_log.stop_reason.lower()


@pytest.mark.asyncio
async def test_repetition_avoidance():
    """Verify that test selector never executes repetitive identical tests."""
    scenario_path = SCENARIOS_DIR / "scenario_b_healthcheck_mismatch"
    engine = DiagnosticEngine()
    budget = DiagnosticBudget(max_steps=4, max_cost=10)

    result = await engine.run_investigation(project_root=scenario_path, budget=budget)

    executed_keys = [(t.tool_name, t.target) for t in result.audit_log.test_results]
    # Ensure no duplicates in executed tests
    assert len(executed_keys) == len(set(executed_keys))


def test_security_boundary_validator_blocks_path_traversal():
    """Verify that ApprovedPathValidator prevents directory traversal and inspecting outside project root."""
    approved_root = SCENARIOS_DIR / "scenario_a_missing_env"

    # Direct traversal attempt
    with pytest.raises(SecurityBoundaryError):
        ApprovedPathValidator.validate_and_resolve(approved_root, "../../etc/passwd")

    with pytest.raises(SecurityBoundaryError):
        ApprovedPathValidator.validate_and_resolve(
            approved_root, "../scenario_b_healthcheck_mismatch/main.py"
        )

    with pytest.raises(SecurityBoundaryError):
        ApprovedPathValidator.validate_and_resolve(
            approved_root, "/Windows/System32/drivers"
        )


def test_environment_collector_masks_sensitive_values():
    """Verify EnvironmentCollector tracks variable presence without exposing secrets."""
    raw_env = {
        "PORT": "8080",
        "DATABASE_PASSWORD": "super_secret_db_password_12345",
        "AUTH_BEARER_TOKEN": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "APP_ENV": "production",
    }
    evidence = EnvironmentCollector.collect_presence(
        raw_env, expected_keys={"PORT", "DATABASE_PASSWORD"}
    )
    assert len(evidence) == 1

    content = evidence[0].content
    # Presence is reported
    assert "DATABASE_PASSWORD" in content
    assert "AUTH_BEARER_TOKEN" in content

    # CRITICAL: Secret values are completely masked
    assert "super_secret_db_password_12345" not in content
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in content
    assert "[PRESENT_SECRET_MASKED]" in content
