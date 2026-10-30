"""Unit tests for Pydantic domain models in FixLoop."""

import pytest
from pydantic import ValidationError

from backend.app.core.models import (
    DiagnoseHypothesis,
    DiagnoseResponse,
    DiagnosisStatus,
    DiagnosticAction,
    DiagnosticActionStatus,
    DiagnosticProbeType,
    EvidenceItem,
    EvidenceRecord,
    EvidenceType,
    Hypothesis,
    HypothesisCategory,
    InvestigationState,
    InvestigationStatus,
    RecommendTest,
)


def test_evidence_item_creation():
    ev = EvidenceItem(
        id="ev-1",
        type=EvidenceType.LOGS,
        source="docker.logs",
        content="2026-10-26 Error: connection refused",
        is_initial=True,
    )
    assert ev.id == "ev-1"
    assert ev.type == EvidenceType.LOGS
    assert ev.is_initial is True
    assert ev.metadata == {}


def test_hypothesis_confidence_bounds():
    # Valid confidence
    h = Hypothesis(
        id="hyp-1",
        title="Misconfigured port",
        description="Port 8000 does not match compose",
        category=HypothesisCategory.PORT_MISMATCH,
        confidence_score=0.85,
    )
    assert h.confidence_score == 0.85

    # Invalid confidence > 1.0
    with pytest.raises(ValidationError):
        Hypothesis(
            id="hyp-2",
            title="Invalid",
            description="Invalid",
            category=HypothesisCategory.UNKNOWN,
            confidence_score=1.5,
        )

    # Invalid confidence < 0.0
    with pytest.raises(ValidationError):
        Hypothesis(
            id="hyp-3",
            title="Invalid",
            description="Invalid",
            category=HypothesisCategory.UNKNOWN,
            confidence_score=-0.1,
        )


def test_diagnose_hypothesis_bounds():
    # Valid
    dh = DiagnoseHypothesis(
        description="Healthcheck path mismatch",
        supporting_evidence=["ev-1"],
        contradicting_evidence=[],
        confidence=0.92,
        recommended_discriminating_test="HTTP_GET /healthz",
    )
    assert dh.confidence == 0.92

    # Invalid > 1.0
    with pytest.raises(ValidationError):
        DiagnoseHypothesis(description="Invalid", confidence=1.1)


def test_diagnose_response_serialization():
    resp = DiagnoseResponse(
        status=DiagnosisStatus.DIAGNOSIS_AVAILABLE,
        summary="Clear healthcheck failure identified",
        hypotheses=[
            DiagnoseHypothesis(
                description="Probe mismatch",
                supporting_evidence=["ev-1"],
                contradicting_evidence=[],
                confidence=0.95,
                recommended_discriminating_test="HTTP_GET /healthz",
            )
        ],
        evidence=[
            EvidenceRecord(
                id="ev-1", source="docker_inspect", content="unhealthy status"
            )
        ],
        recommended_tests=[
            RecommendTest(
                id="test-1",
                test_type="HTTP_GET",
                target="/healthz",
                description="Verify route",
                expected_signal="200 OK",
            )
        ],
        missing_information=[],
        confidence=0.95,
        next_action="Patch compose",
    )
    json_bytes = resp.model_dump_json()
    reconstructed = DiagnoseResponse.model_validate_json(json_bytes)
    assert reconstructed.status == DiagnosisStatus.DIAGNOSIS_AVAILABLE
    assert reconstructed.hypotheses[0].confidence == 0.95


def test_diagnostic_action_lifecycle():
    act = DiagnosticAction(
        id="act-1",
        probe_type=DiagnosticProbeType.HTTP_GET,
        target="/healthz",
        parameters={"port": 8000},
        rationale="Verify whether endpoint responds with 200 OK",
    )
    assert act.status == DiagnosticActionStatus.PENDING
    assert act.requires_human_approval is False
    assert act.output is None


def test_investigation_state_serialization():
    state = InvestigationState(
        id="inv-test-1",
        scenario_name="scenario_1_healthcheck",
        project_path="/tmp/scenarios/scenario_1",
        status=InvestigationStatus.INITIALIZING,
    )
    assert state.status == InvestigationStatus.INITIALIZING
    assert state.iteration == 0
    assert len(state.evidence_store) == 0

    # Add evidence
    state.evidence_store.append(
        EvidenceItem(
            id="ev-1",
            type=EvidenceType.DOCKER_INSPECT,
            source="docker.inspect",
            content='{"Health": {"Status": "unhealthy"}}',
        )
    )
    assert len(state.evidence_store) == 1

    # Serialize to JSON and deserialize back
    data_json = state.model_dump_json()
    reconstructed = InvestigationState.model_validate_json(data_json)
    assert reconstructed.id == "inv-test-1"
    assert (
        reconstructed.evidence_store[0].content == '{"Health": {"Status": "unhealthy"}}'
    )
